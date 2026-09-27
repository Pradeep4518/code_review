"""
RepoMind backend — FastAPI app.

Endpoints:
  GET  /api/health    - reports Hindsight/Groq connectivity status
  POST /api/review    - stateless or Hindsight-memory-augmented code review
  POST /api/teach      - persist a new team engineering convention
  GET  /api/memories   - list normalized memories for the UI
  POST /api/seed        - prepopulate Hindsight/local memory with starter conventions

Run with:  uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from llm_service import GroqService
from memory_providers import HindsightMemoryProvider, MemoryItem, build_memory_provider

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("repomind")

app = FastAPI(title="RepoMind API", version="1.0.0")

# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------
# Hackathon/demo configuration: allow every origin so the Vite dev server
# (any port) and any judge's environment can call the API without extra
# setup. Do NOT ship this permissive configuration to a real production
# deployment — restrict allow_origins to your actual frontend's origin(s).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

memory_provider = build_memory_provider()
groq_service = GroqService()

MAX_DIFF_CHARS = 20_000
SEED_MEMORIES = [
    {
        "content": "All database access must go through the repository layer (repository/db.py). API route handlers must never execute raw SQL directly.",
        "category": "database",
    },
    {
        "content": "Production services must use structured logging (structlog/logging with JSON formatter). Never use print(), console.log(), or log authorization tokens, passwords, or API keys.",
        "category": "logging",
    },
    {
        "content": "Database queries must define explicit timeout behavior and must never construct SQL through unsafe string interpolation or concatenation — always use parameterized queries.",
        "category": "database",
    },
    {
        "content": "All FastAPI route handlers must remain thin: validate input, call a service/repository function, and return the result. Business logic and data access do not belong in the route function body.",
        "category": "architecture",
    },
    {
        "content": "Every async function that awaits an I/O call (database, HTTP, queue) must wrap it in try/except and return a typed error response instead of letting the exception propagate unhandled.",
        "category": "architecture",
    },
]


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------


class ReviewRequest(BaseModel):
    code_diff: str = Field(..., min_length=1, max_length=MAX_DIFF_CHARS)
    pr_title: str = Field(default="Untitled PR", max_length=300)
    bypass_memory: bool = Field(default=False)


class TeachRequest(BaseModel):
    rule: str = Field(..., min_length=3, max_length=2000)
    category: str = Field(default="other", max_length=50)


ALLOWED_CATEGORIES = {
    "architecture", "database", "security", "logging",
    "testing", "api", "performance", "other",
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _memory_provider_label() -> str:
    return memory_provider.provider_name


async def _hindsight_reachable() -> bool:
    if isinstance(memory_provider, HindsightMemoryProvider):
        return await memory_provider.is_connected()
    return False


def _build_memory_context(memories: list[MemoryItem]) -> str:
    if not memories:
        return ""
    lines = [f"- [{m.category.upper()}] {m.content}" for m in memories]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@app.get("/api/health")
async def health():
    hindsight_connected = await _hindsight_reachable()
    memory_count = 0
    try:
        memory_count = len(await memory_provider.list_memories(limit=1000))
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory list failed during health check: %s", exc)

    return {
        "status": "ok",
        "memory_provider": _memory_provider_label(),
        "hindsight_connected": hindsight_connected if _memory_provider_label() == "hindsight" else False,
        "memory_mode": "HINDSIGHT CONNECTED" if hindsight_connected and _memory_provider_label() == "hindsight" else "DEMO MEMORY MODE",
        "groq_configured": groq_service.configured,
        "groq_status": "GROQ READY" if groq_service.configured else "GROQ FALLBACK (local engine)",
        "memory_count": memory_count,
        "bank_id": getattr(memory_provider, "bank_id", "local"),
    }


@app.post("/api/review")
async def review(req: ReviewRequest):
    if len(req.code_diff) > MAX_DIFF_CHARS:
        raise HTTPException(status_code=413, detail="code_diff too large")

    memories: list[MemoryItem] = []
    memory_context = None

    if not req.bypass_memory:
        try:
            recall_query = f"{req.pr_title}\n{req.code_diff}"
            memories = await memory_provider.recall(recall_query, limit=6)
            memory_context = _build_memory_context(memories)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Hindsight recall failed, proceeding without memory context: %s", exc)
            memories = []
            memory_context = None

    result = await groq_service.review(
        code_diff=req.code_diff,
        pr_title=req.pr_title,
        memory_context=memory_context if memory_context else None,
    )

    return {
        "review": result.review_text,
        "memories": [m.to_dict() for m in memories],
        "memory_count": len(memories),
        "groq_latency_ms": result.latency_ms,
        "memory_enabled": not req.bypass_memory,
        "memory_provider": _memory_provider_label() if not req.bypass_memory else "none",
        "llm_provider": result.provider,
        "llm_model": result.model,
        "llm_error": result.error,
    }


@app.post("/api/teach")
async def teach(req: TeachRequest):
    category = req.category.lower().strip()
    if category not in ALLOWED_CATEGORIES:
        category = "other"

    try:
        item = await memory_provider.retain(content=req.rule, category=category, source="teach")
    except Exception as exc:  # noqa: BLE001
        logger.error("retain failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Failed to persist memory: {exc}") from exc

    return {
        "success": True,
        "rule": item.content,
        "category": item.category,
        "provider": _memory_provider_label(),
        "memory_id": item.id,
    }


@app.get("/api/memories")
async def get_memories():
    try:
        memories = await memory_provider.list_memories(limit=200)
    except Exception as exc:  # noqa: BLE001
        logger.error("list_memories failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Failed to list memories: {exc}") from exc

    return {
        "memories": [m.to_dict() for m in memories],
        "count": len(memories),
        "provider": _memory_provider_label(),
    }


@app.post("/api/seed")
async def seed():
    """
    Idempotent-ish seeding: retains the starter engineering conventions.
    Safe to call multiple times (Hindsight/local storage both dedupe
    near-identical facts reasonably well; re-running just reinforces them).
    """
    created: list[dict] = []
    errors: list[str] = []

    async def _retain_one(entry: dict) -> None:
        try:
            item = await memory_provider.retain(
                content=entry["content"], category=entry["category"], source="seed"
            )
            created.append(item.to_dict())
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{entry['category']}: {exc}")

    # Retain sequentially — Hindsight's retain does LLM-based fact extraction
    # per call, so keeping this simple and sequential avoids rate-limit
    # surprises during a live demo seed.
    for entry in SEED_MEMORIES:
        await _retain_one(entry)

    return {
        "success": len(errors) == 0,
        "seeded_count": len(created),
        "memories": created,
        "errors": errors,
        "provider": _memory_provider_label(),
    }


@app.get("/")
async def root():
    return {
        "name": "RepoMind API",
        "tagline": "The Self-Evolving Code Review Agent",
        "docs": "/docs",
        "memory_provider": _memory_provider_label(),
    }
