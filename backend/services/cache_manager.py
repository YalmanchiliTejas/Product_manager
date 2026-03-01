"""Four-layer cache coordinator for the PM agent.

All methods degrade gracefully — exceptions return None, never crash.

Cache layers
------------
1. Embedding cache    — L1: process-level dict  |  L2: Supabase `agent_embedding_cache`
                        key: sha256(text) → list[float]  (stored as JSONB)
2. Tool result cache  — In-memory dict, session-scoped (never persisted)
                        key: (tool_name, sha256(args), session_id) → str
3. LLM response cache — L1: process-level dict  |  L2: Supabase `agent_llm_cache`
                        key: sha256(prompt_key) → str
4. Anthropic prompt cache — server-side, zero local state needed
                             (enabled via cache_control headers in react_loop.py)

Required Supabase tables (run once in the SQL editor)
------------------------------------------------------
    CREATE TABLE IF NOT EXISTS agent_embedding_cache (
        text_hash   TEXT PRIMARY KEY,
        vector      JSONB  NOT NULL,
        created_at  TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS agent_llm_cache (
        prompt_hash TEXT PRIMARY KEY,
        response    TEXT  NOT NULL,
        created_at  TIMESTAMPTZ DEFAULT NOW()
    );

If SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set, or if the tables
do not yet exist, all operations fall back silently to the in-process L1
dicts (no error is raised, caches just don't persist across restarts).

Stats: get_stats() -> {hits, misses, tokens_saved}
"""

from __future__ import annotations

import hashlib
import json
import threading

# ── Hashing helpers ───────────────────────────────────────────────────────

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _args_hash(args: dict) -> str:
    return _hash(json.dumps(args, sort_keys=True, default=str))


# ── Stats ─────────────────────────────────────────────────────────────────

_stats: dict[str, int] = {"hits": 0, "misses": 0, "tokens_saved": 0}
_stats_lock = threading.Lock()


def _inc_hits(tokens_saved: int = 0) -> None:
    with _stats_lock:
        _stats["hits"] += 1
        _stats["tokens_saved"] += tokens_saved


def _inc_misses() -> None:
    with _stats_lock:
        _stats["misses"] += 1


def get_stats() -> dict:
    """Return a snapshot of cache statistics."""
    with _stats_lock:
        return dict(_stats)


def reset_stats() -> None:
    """Reset all counters to zero."""
    with _stats_lock:
        _stats["hits"] = 0
        _stats["misses"] = 0
        _stats["tokens_saved"] = 0


# ── Supabase client helper ────────────────────────────────────────────────

def _get_db():
    """Return the Supabase client, or None if not configured."""
    try:
        from backend.db.supabase_client import get_supabase
        return get_supabase()
    except Exception:
        return None


# ── 1. Embedding cache (L1: process dict, L2: Supabase) ──────────────────

_emb_l1: dict[str, list[float]] = {}
_emb_lock = threading.Lock()


def get_embedding_cached(text: str) -> list[float] | None:
    """Return a cached embedding vector or None."""
    try:
        h = _hash(text.strip())

        # L1 hit
        with _emb_lock:
            if h in _emb_l1:
                _inc_hits()
                return _emb_l1[h]

        # L2 hit (Supabase)
        db = _get_db()
        if db is not None:
            result = (
                db.table("agent_embedding_cache")
                .select("vector")
                .eq("text_hash", h)
                .execute()
            )
            if result.data:
                vector = result.data[0]["vector"]
                # Supabase returns JSONB as a Python list directly
                if isinstance(vector, list):
                    with _emb_lock:
                        _emb_l1[h] = vector
                    _inc_hits()
                    return vector

        _inc_misses()
        return None
    except Exception:
        return None


def store_embedding(text: str, vector: list[float]) -> None:
    """Persist an embedding vector to L1 and Supabase."""
    try:
        h = _hash(text.strip())
        with _emb_lock:
            _emb_l1[h] = vector
    except Exception:
        pass

    try:
        db = _get_db()
        if db is not None:
            db.table("agent_embedding_cache").upsert(
                {"text_hash": h, "vector": vector}
            ).execute()
    except Exception:
        pass


# ── 2. Tool result cache (in-memory, session-scoped) ─────────────────────

_tool_cache: dict[tuple[str, str, str], str] = {}
_tool_lock = threading.Lock()


def get_tool_result_cached(
    tool_name: str,
    args: dict,
    session_id: str,
) -> str | None:
    """Return a cached tool result or None."""
    try:
        key = (tool_name, _args_hash(args), session_id)
        with _tool_lock:
            result = _tool_cache.get(key)
        if result is not None:
            _inc_hits()
            return result
        _inc_misses()
        return None
    except Exception:
        return None


def store_tool_result(
    tool_name: str,
    args: dict,
    session_id: str,
    result: str,
) -> None:
    """Store a tool result in the session-scoped in-memory cache."""
    try:
        key = (tool_name, _args_hash(args), session_id)
        with _tool_lock:
            _tool_cache[key] = result
    except Exception:
        pass


def clear_tool_cache_for_session(session_id: str) -> None:
    """Evict all entries for the given session."""
    try:
        with _tool_lock:
            stale = [k for k in _tool_cache if k[2] == session_id]
            for k in stale:
                del _tool_cache[k]
    except Exception:
        pass


# ── 3. LLM response cache (L1: process dict, L2: Supabase) ───────────────

_llm_l1: dict[str, str] = {}
_llm_lock = threading.Lock()


def get_llm_response(prompt_key: str) -> str | None:
    """Return a cached LLM response string or None."""
    try:
        h = _hash(prompt_key)

        # L1 hit
        with _llm_lock:
            if h in _llm_l1:
                _inc_hits()
                return _llm_l1[h]

        # L2 hit (Supabase)
        db = _get_db()
        if db is not None:
            result = (
                db.table("agent_llm_cache")
                .select("response")
                .eq("prompt_hash", h)
                .execute()
            )
            if result.data:
                response = result.data[0]["response"]
                with _llm_lock:
                    _llm_l1[h] = response
                _inc_hits()
                return response

        _inc_misses()
        return None
    except Exception:
        return None


def store_llm_response(prompt_key: str, response: str) -> None:
    """Persist an LLM response to L1 and Supabase."""
    try:
        h = _hash(prompt_key)
        with _llm_lock:
            _llm_l1[h] = response
    except Exception:
        pass

    try:
        db = _get_db()
        if db is not None:
            db.table("agent_llm_cache").upsert(
                {"prompt_hash": h, "response": response}
            ).execute()
    except Exception:
        pass
