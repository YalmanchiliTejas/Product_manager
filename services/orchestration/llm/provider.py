"""
LLM-agnostic provider built on LiteLLM.

All model calls go through this module. Swapping providers is a config change,
not a code change — just set the relevant env vars in config.py:

    LLM_FAST_MODEL=gpt-4o-mini        # was claude-haiku
    LLM_BALANCED_MODEL=gpt-4o         # was claude-sonnet
    EMBEDDING_MODEL=voyage/voyage-3   # was text-embedding-3-small

LiteLLM normalises the request/response format across 100+ providers.
"""

import json
import re
from typing import AsyncIterator

import litellm

from services.orchestration.config import settings

# Suppress litellm's noisy logging in production
litellm.suppress_debug_info = True


def _strip_fences(raw: str) -> str:
    """Remove ```json ... ``` markdown fences if the model wrapped its JSON."""
    stripped = raw.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```\s*$", "", stripped)
    return stripped.strip()


def _model_for(tier: str) -> str:
    return {
        "fast": settings.LLM_FAST,
        "balanced": settings.LLM_BALANCED,
        "deep": settings.LLM_DEEP,
    }[tier]


# ── Synchronous (used in CPU-bound or simple contexts) ──────────────────────

def complete(tier: str, system: str, user: str, max_tokens: int = 4096) -> str:
    """Blocking text completion."""
    response = litellm.completion(
        model=_model_for(tier),
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content or ""  # type: ignore[union-attr]


def complete_json(tier: str, system: str, user: str, max_tokens: int = 4096) -> dict:
    """Blocking JSON completion. Strips markdown fences and parses."""
    raw = complete(tier, system, user, max_tokens)
    try:
        return json.loads(_strip_fences(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned invalid JSON:\n{raw[:500]}") from exc


def embed(text: str) -> list[float]:
    """Blocking single-string embedding."""
    response = litellm.embedding(model=settings.EMBEDDING_MODEL, input=[text])
    return response.data[0]["embedding"]  # type: ignore[index]


def to_pgvector_literal(vector: list[float]) -> str:
    return "[" + ",".join(str(v) for v in vector) + "]"


# ── Async (used in FastAPI route handlers) ──────────────────────────────────

async def acomplete(tier: str, system: str, user: str, max_tokens: int = 4096) -> str:
    """Async text completion."""
    response = await litellm.acompletion(
        model=_model_for(tier),
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content or ""  # type: ignore[union-attr]


async def acomplete_json(
    tier: str, system: str, user: str, max_tokens: int = 4096
) -> dict:
    """Async JSON completion."""
    raw = await acomplete(tier, system, user, max_tokens)
    try:
        return json.loads(_strip_fences(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned invalid JSON:\n{raw[:500]}") from exc


async def aembed(text: str) -> list[float]:
    """Async single-string embedding."""
    response = await litellm.aembedding(model=settings.EMBEDDING_MODEL, input=[text])
    return response.data[0]["embedding"]  # type: ignore[index]


async def astream(
    tier: str,
    messages: list[dict],
    system: str,
    max_tokens: int = 2048,
) -> AsyncIterator[str]:
    """
    Async streaming completion. Yields text delta strings.

    Usage:
        async for chunk in astream("balanced", messages, system):
            yield chunk
    """
    full_messages = [{"role": "system", "content": system}] + messages

    stream = await litellm.acompletion(
        model=_model_for(tier),
        max_tokens=max_tokens,
        messages=full_messages,
        stream=True,
    )

    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content
