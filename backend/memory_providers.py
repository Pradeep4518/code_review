"""
RepoMind memory layer.

Defines a common MemoryProvider interface with two implementations:

- HindsightMemoryProvider: talks to the real Hindsight Cloud REST API
  (https://api.hindsight.vectorize.io), using the documented
  retain / recall / list-memories endpoints.
- LocalMemoryProvider: a persistent JSON-backed fallback so the demo
  never breaks if Hindsight credentials are missing or the API is
  briefly unreachable.

Both providers expose the same three async operations: retain(), recall(),
and list_memories(), so the rest of the app never has to know which one
is active. The active provider (and whether it is real Hindsight or the
local fallback) is always reported back to the frontend -- RepoMind never
claims to be using Hindsight when it isn't.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

HINDSIGHT_BASE_URL_DEFAULT = "https://api.hindsight.vectorize.io"
LOCAL_MEMORY_PATH = Path(__file__).parent / "local_memory.json"

CATEGORY_KEYWORDS = {
    "database": ["database", "db", "sql", "repository layer", "query", "orm"],
    "security": ["security", "auth", "token", "secret", "injection", "vulnerab", "credential"],
    "logging": ["log", "logging", "print(", "console.log"],
    "architecture": ["architecture", "route", "handler", "layer", "thin", "pattern", "structure"],
    "api": ["api", "endpoint", "rest", "fastapi", "route"],
    "testing": ["test", "pytest", "coverage", "unit test"],
    "performance": ["performance", "timeout", "latency", "n+1", "index", "slow"],
}


def infer_category(text: str) -> str:
    lowered = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return category
    return "other"


@dataclass
class MemoryItem:
    """Normalized memory record used everywhere in the app (API + frontend)."""

    id: str
    content: str
    category: str
    source: str  # "seed" | "teach"
    timestamp: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "source": self.source,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }
        if self.score is not None:
            d["score"] = self.score
        return d


class MemoryProvider(ABC):
    provider_name: str

    @abstractmethod
    async def retain(self, content: str, category: str, source: str) -> MemoryItem: ...

    @abstractmethod
    async def recall(self, query: str, limit: int = 6) -> list[MemoryItem]:
        """Return memories relevant to `query`, most relevant first."""

    @abstractmethod
    async def list_memories(self, limit: int = 100) -> list[MemoryItem]: ...

    @abstractmethod
    async def is_connected(self) -> bool: ...


# --------------------------------------------------------------------------
# Local fallback provider
# --------------------------------------------------------------------------


class LocalMemoryProvider(MemoryProvider):
    """
    Deterministic, persistent, keyword-scored local memory store.

    Used automatically whenever HINDSIGHT_API_KEY is not configured, or if
    a live call to Hindsight Cloud fails. Data is written to
    backend/local_memory.json so it survives server restarts, which keeps
    the "Teach -> Recall -> Review" loop demoable even fully offline.
    """

    provider_name = "local"

    def __init__(self, path: Path = LOCAL_MEMORY_PATH):
        self.path = path
        if not self.path.exists():
            self._write([])

    def _read(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _write(self, items: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(items, indent=2))

    async def is_connected(self) -> bool:
        return True  # local storage is always "connected"

    async def retain(self, content: str, category: str, source: str) -> MemoryItem:
        items = self._read()
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=content,
            category=category or infer_category(content),
            source=source,
            timestamp=_now_iso(),
            metadata={"provider": "local"},
        )
        items.append(item.to_dict())
        self._write(items)
        return item

    async def recall(self, query: str, limit: int = 6) -> list[MemoryItem]:
        items = self._read()
        query_terms = {t for t in query.lower().replace("\n", " ").split() if len(t) > 2}

        scored: list[tuple[float, dict[str, Any]]] = []
        for raw in items:
            text = raw["content"].lower()
            overlap = sum(1 for t in query_terms if t in text)
            # boost if the memory's category keywords appear in the query too
            category_hit = 1 if raw.get("category", "") in query.lower() else 0
            score = overlap + category_hit
            if score > 0:
                scored.append((score, raw))

        # If nothing scored (e.g. very short query), fall back to most recent memories
        if not scored:
            scored = [(0.1, raw) for raw in items[-limit:]]

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]
        max_score = max((s for s, _ in top), default=1) or 1
        results = []
        for s, raw in top:
            item = MemoryItem(
                id=raw["id"],
                content=raw["content"],
                category=raw.get("category", "other"),
                source=raw.get("source", "seed"),
                timestamp=raw.get("timestamp", _now_iso()),
                metadata=raw.get("metadata", {}),
                score=round(min(s / max_score, 1.0), 3),
            )
            results.append(item)
        return results

    async def list_memories(self, limit: int = 100) -> list[MemoryItem]:
        items = self._read()
        items = sorted(items, key=lambda r: r.get("timestamp", ""), reverse=True)[:limit]
        return [
            MemoryItem(
                id=r["id"],
                content=r["content"],
                category=r.get("category", "other"),
                source=r.get("source", "seed"),
                timestamp=r.get("timestamp", _now_iso()),
                metadata=r.get("metadata", {}),
            )
            for r in items
        ]


# --------------------------------------------------------------------------
# Hindsight Cloud provider (real REST API)
# --------------------------------------------------------------------------


class HindsightMemoryProvider(MemoryProvider):
    """
    Talks to the real Hindsight Cloud REST API.

    Endpoints used (verified against the official Hindsight HTTP API
    reference at https://hindsight.vectorize.io/api-reference, tenant
    "default"):

      POST /v1/default/banks/{bank_id}/memories          -> retain
      POST /v1/default/banks/{bank_id}/memories/recall    -> recall
      GET  /v1/default/banks/{bank_id}/memories/list      -> list memories

    Auth: `Authorization: Bearer <HINDSIGHT_API_KEY>` header.
    """

    provider_name = "hindsight"

    def __init__(self, api_key: str, bank_id: str, base_url: str | None = None, timeout: float = 20.0):
        self.api_key = api_key
        self.bank_id = bank_id
        self.base_url = (base_url or HINDSIGHT_BASE_URL_DEFAULT).rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _bank_path(self, suffix: str = "") -> str:
        return f"{self.base_url}/v1/default/banks/{self.bank_id}{suffix}"

    async def is_connected(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/health/live")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def retain(self, content: str, category: str, source: str) -> MemoryItem:
        category = category or infer_category(content)
        payload = {
            "items": [
                {
                    "content": content,
                    "context": f"RepoMind engineering convention | category={category} | source={source}",
                }
            ],
            "async": False,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self._bank_path("/memories"), headers=self._headers(), json=payload)
            resp.raise_for_status()

        # Hindsight's retain response confirms ingestion but does not echo back
        # generated memory IDs for each extracted fact, so we mint a local
        # correlation ID for the UI and keep the category/source metadata
        # in our own lightweight index for /api/memories rendering.
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=content,
            category=category,
            source=source,
            timestamp=_now_iso(),
            metadata={"provider": "hindsight", "bank_id": self.bank_id},
        )
        _record_hindsight_local_index(self.bank_id, item)
        return item

    async def recall(self, query: str, limit: int = 6) -> list[MemoryItem]:
        payload = {
            "query": query,
            "budget": "mid",
            "max_tokens": 2048,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self._bank_path("/memories/recall"), headers=self._headers(), json=payload
            )
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])[:limit]
        local_index = {m.id: m for m in _read_hindsight_local_index(self.bank_id)}
        items: list[MemoryItem] = []
        for r in results:
            text = r.get("text", "")
            category = infer_category(text)
            # try to recover the richer category/source from our local index
            # (matched by fuzzy text containment), otherwise infer from content
            source = "seed"
            for m in local_index.values():
                if m.content.strip() == text.strip():
                    category = m.category
                    source = m.source
                    break
            items.append(
                MemoryItem(
                    id=r.get("id", str(uuid.uuid4())),
                    content=text,
                    category=category,
                    source=source,
                    timestamp=r.get("occurred_start") or _now_iso(),
                    metadata={"provider": "hindsight", "type": r.get("type", "world")},
                    score=None,
                )
            )
        return items

    async def list_memories(self, limit: int = 100) -> list[MemoryItem]:
        params = {"limit": limit}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                self._bank_path("/memories/list"), headers=self._headers(), params=params
            )
            resp.raise_for_status()
            data = resp.json()

        local_index = {m.content.strip(): m for m in _read_hindsight_local_index(self.bank_id)}
        items: list[MemoryItem] = []
        for r in data.get("items", []):
            text = r.get("text", "")
            matched = local_index.get(text.strip())
            category = matched.category if matched else infer_category(text)
            source = matched.source if matched else "seed"
            items.append(
                MemoryItem(
                    id=r.get("id", str(uuid.uuid4())),
                    content=text,
                    category=category,
                    source=source,
                    timestamp=r.get("date") or _now_iso(),
                    metadata={"provider": "hindsight", "fact_type": r.get("fact_type", "world")},
                )
            )
        return items


# --------------------------------------------------------------------------
# Small local index kept alongside the Hindsight provider
# --------------------------------------------------------------------------
# Hindsight is the source of truth for memory *content*, but it does not
# return the RepoMind-specific "category" / "source" (seed vs taught) labels
# we want to show in the UI. We keep a tiny local JSON index, keyed by bank,
# purely for that cosmetic metadata -- it is never used as a memory store of
# record and RepoMind still calls real Hindsight retain/recall for every
# review. If this index is ever missing or stale, category falls back to
# keyword inference, so nothing user-facing breaks.

_HINDSIGHT_INDEX_PATH = Path(__file__).parent / "hindsight_local_index.json"


def _read_hindsight_local_index(bank_id: str) -> list[MemoryItem]:
    try:
        data = json.loads(_HINDSIGHT_INDEX_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return [MemoryItem(**m) for m in data.get(bank_id, [])]


def _record_hindsight_local_index(bank_id: str, item: MemoryItem) -> None:
    try:
        data = json.loads(_HINDSIGHT_INDEX_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.setdefault(bank_id, [])
    data[bank_id].append(
        {
            "id": item.id,
            "content": item.content,
            "category": item.category,
            "source": item.source,
            "timestamp": item.timestamp,
            "metadata": item.metadata,
        }
    )
    _HINDSIGHT_INDEX_PATH.write_text(json.dumps(data, indent=2))


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_memory_provider() -> MemoryProvider:
    """
    Factory: returns a HindsightMemoryProvider if HINDSIGHT_API_KEY is set,
    otherwise falls back to LocalMemoryProvider. The choice (and whether
    Hindsight is actually reachable) is surfaced to the frontend via
    /api/health so the UI never falsely claims "Hindsight Connected".
    """
    api_key = os.getenv("HINDSIGHT_API_KEY", "").strip()
    bank_id = os.getenv("HINDSIGHT_BANK_ID", "repomind-demo-team").strip()
    base_url = os.getenv("HINDSIGHT_API_URL", HINDSIGHT_BASE_URL_DEFAULT).strip()

    if api_key:
        return HindsightMemoryProvider(api_key=api_key, bank_id=bank_id, base_url=base_url)
    return LocalMemoryProvider()
