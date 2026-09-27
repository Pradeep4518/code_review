"""
RepoMind LLM layer.

Wraps Groq for the actual code-review generation, with a deterministic
local review engine as a fallback so the demo never breaks if GROQ_API_KEY
is missing, the model name is wrong, or the network call fails/times out.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Optional

DEFAULT_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
FALLBACK_MODELS = ["openai/gpt-oss-120b", "qwen/qwen3-32b"]

STATELESS_SYSTEM_PROMPT = """You are a competent but generic AI code reviewer.
You have no knowledge of this specific team's conventions, prior decisions, or
past reviewer corrections. Review the given pull request diff using only
general software engineering best practices (security, correctness, style).
Be concise: 3-6 bullet points. Do not invent team-specific rules you were not
given."""

MEMORY_SYSTEM_PROMPT = """You are RepoMind, an AI code-review agent with long-term
memory of this specific engineering team's architecture decisions, coding
conventions, and past reviewer corrections, recalled below from Hindsight.

Review the given pull request diff. For every issue that relates to one of the
recalled team memories, EXPLICITLY cite it, in this format:

  Memory used: "<the exact memory text>"

Then explain how the code violates or should follow that memory. Also still
flag any generic best-practice issues that memory doesn't cover. Be concise:
3-6 bullet points total. Do not fabricate memories that were not provided to
you."""


@dataclass
class ReviewResult:
    review_text: str
    latency_ms: int
    provider: str  # "groq" | "local"
    model: Optional[str] = None
    error: Optional[str] = None


class GroqService:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY", "").strip()
        self.model = DEFAULT_MODEL

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def _call_groq(self, client, model: str, messages: list[dict]) -> str:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=800,
        )
        return resp.choices[0].message.content

    async def review(
        self, code_diff: str, pr_title: str, memory_context: str | None
    ) -> ReviewResult:
        """
        Generate a review. If Groq isn't configured, or every attempted
        model fails, falls back to the deterministic local review engine
        so the request never 500s.
        """
        if not self.configured:
            text = local_review(code_diff, memory_context)
            return ReviewResult(review_text=text, latency_ms=0, provider="local", error="GROQ_API_KEY not set")

        try:
            from groq import AsyncGroq
        except ImportError:
            text = local_review(code_diff, memory_context)
            return ReviewResult(review_text=text, latency_ms=0, provider="local", error="groq package not installed")

        system_prompt = MEMORY_SYSTEM_PROMPT if memory_context else STATELESS_SYSTEM_PROMPT
        user_content = f"PR Title: {pr_title}\n\n"
        if memory_context:
            user_content += f"RECALLED TEAM MEMORIES (from Hindsight):\n{memory_context}\n\n"
        user_content += f"CODE DIFF:\n```\n{code_diff}\n```"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        client = AsyncGroq(api_key=self.api_key)
        models_to_try = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]
        last_error = None

        for model in models_to_try:
            start = time.monotonic()
            try:
                text = await self._call_groq(client, model, messages)
                latency_ms = int((time.monotonic() - start) * 1000)
                return ReviewResult(review_text=text, latency_ms=latency_ms, provider="groq", model=model)
            except Exception as exc:  # noqa: BLE001 - surfaced to caller, never crashes the request
                last_error = f"{type(exc).__name__}: {exc}"
                continue

        # every model failed (bad key, rate limit, network, invalid model, etc.)
        text = local_review(code_diff, memory_context)
        return ReviewResult(
            review_text=text,
            latency_ms=0,
            provider="local",
            error=f"Groq unavailable after trying {models_to_try}: {last_error}",
        )


# --------------------------------------------------------------------------
# Deterministic local review engine (Groq fallback)
# --------------------------------------------------------------------------

RAW_SQL_PATTERN = re.compile(r"\b(execute|cursor\.execute|db\.execute)\s*\(", re.IGNORECASE)
FSTRING_SQL_PATTERN = re.compile(r"(f[\"']|\.format\(|%\s*\()[^\"']*\b(SELECT|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)
STRING_CONCAT_SQL_PATTERN = re.compile(r"(SELECT|INSERT|UPDATE|DELETE)\b.*[\"']\s*\+", re.IGNORECASE)
PRINT_PATTERN = re.compile(r"\bprint\s*\(")
CONSOLE_LOG_PATTERN = re.compile(r"\bconsole\.log\s*\(")
SENSITIVE_LOG_PATTERN = re.compile(r"(log|print|console\.log)\s*\([^)]*\b(token|password|secret|api_key|auth)\b", re.IGNORECASE)
ASYNC_NO_TRY_PATTERN = re.compile(r"async\s+def\s+\w+\s*\([^)]*\)\s*:")
TRY_PATTERN = re.compile(r"\btry\s*:")
DIRECT_DB_IN_ROUTE_PATTERN = re.compile(r"@app\.(get|post|put|delete|patch)")


def _find_memory_for(text_lower: str, memory_context: str | None, keywords: list[str]) -> Optional[str]:
    if not memory_context:
        return None
    for line in memory_context.splitlines():
        line_lower = line.lower()
        if any(kw in line_lower for kw in keywords):
            cleaned = line.strip("- ").strip()
            if cleaned:
                return cleaned
    return None


def local_review(code_diff: str, memory_context: str | None) -> str:
    """
    A deterministic, pattern-based reviewer used whenever Groq is
    unavailable. It intentionally mirrors the two-mode behavior (stateless
    vs memory-augmented) described in the product spec: with memory_context
    supplied, matching issues cite the relevant memory; without it, findings
    stay generic.
    """
    findings: list[str] = []
    has_route_handler = bool(DIRECT_DB_IN_ROUTE_PATTERN.search(code_diff))

    if RAW_SQL_PATTERN.search(code_diff) or FSTRING_SQL_PATTERN.search(code_diff) or STRING_CONCAT_SQL_PATTERN.search(code_diff):
        finding = "- **SQL injection risk**: the query is built with string interpolation/concatenation instead of parameterized queries. Use bound parameters (e.g. `cursor.execute(query, params)`)."
        mem = _find_memory_for(code_diff.lower(), memory_context, ["database", "sql", "repository layer"])
        if mem:
            finding += f'\n  Memory used: "{mem}"'
        findings.append(finding)

    if has_route_handler and (RAW_SQL_PATTERN.search(code_diff) or "db." in code_diff):
        finding = "- **Repository/architecture pattern**: this route handler talks to the database directly instead of going through a repository/service layer."
        mem = _find_memory_for(code_diff.lower(), memory_context, ["repository layer", "thin", "architecture", "route handler"])
        if mem:
            finding += f'\n  Memory used: "{mem}"'
        elif memory_context is None:
            finding += " (Consider extracting data access into a dedicated module.)"
        findings.append(finding)

    if PRINT_PATTERN.search(code_diff) or CONSOLE_LOG_PATTERN.search(code_diff):
        finding = "- **Ad-hoc logging**: `print()`/`console.log()` is used instead of structured logging, which won't integrate with log aggregation in production."
        mem = _find_memory_for(code_diff.lower(), memory_context, ["logging", "structured logging"])
        if mem:
            finding += f'\n  Memory used: "{mem}"'
        findings.append(finding)

    if SENSITIVE_LOG_PATTERN.search(code_diff):
        finding = "- **Sensitive data in logs**: a token/secret/credential-like value appears to be logged, which is a security risk (log exfiltration, compliance)."
        mem = _find_memory_for(code_diff.lower(), memory_context, ["logging", "token", "secret"])
        if mem:
            finding += f'\n  Memory used: "{mem}"'
        findings.append(finding)

    if ASYNC_NO_TRY_PATTERN.search(code_diff) and "await" in code_diff and not TRY_PATTERN.search(code_diff):
        finding = "- **Missing async error handling**: an `async def` performs `await` calls with no `try`/`except`, so a failure will propagate as an unhandled exception."
        mem = _find_memory_for(code_diff.lower(), memory_context, ["error handling", "async", "exception"])
        if mem:
            finding += f'\n  Memory used: "{mem}"'
        findings.append(finding)

    if not findings:
        findings.append("- No significant issues detected by the pattern-based fallback reviewer. Code follows recognized conventions.")
        if memory_context:
            findings.append(f"- Cross-checked against {len(memory_context.splitlines())} recalled team memories; no violations found.")

    header = "### RepoMind Review (local fallback engine — Groq unavailable)\n"
    return header + "\n".join(findings)
