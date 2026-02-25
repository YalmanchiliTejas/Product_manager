"""Persistent memory layer for PM agents using mem0.

mem0 handles:
  - Extracting key facts, decisions, and insights from conversations using an LLM
  - Deduplicating and updating memories intelligently over time
  - Semantic retrieval of the most relevant memories for a given query

Storage backends:
  - If DATABASE_URL is set → pgvector in Supabase (persistent across restarts)
  - Otherwise             → local in-memory vector store (lost on restart)

Usage in the RAG pipeline:
  1. Before generating an answer: search_memories(query, project_id, user_id)
     → inject relevant past PM knowledge into context
  2. After generating an answer: add_memories(messages, project_id, user_id)
     → distil key takeaways for future sessions
"""

import urllib.parse
from functools import lru_cache

from mem0 import Memory

from backend.config import settings

_COLLECTION_NAME = "pm_agent_memories"


def _parse_db_url(url: str) -> dict:
    """Parse a PostgreSQL connection string into mem0 pgvector config dict."""
    p = urllib.parse.urlparse(url)
    return {
        "host": p.hostname or "localhost",
        "port": p.port or 5432,
        "user": p.username or "postgres",
        "password": p.password or "",
        "dbname": (p.path or "/postgres").lstrip("/") or "postgres",
    }


@lru_cache(maxsize=1)
def _get_mem0_client() -> Memory:
    """Build and cache the mem0 Memory client.

    Configured with:
    - Anthropic claude-haiku for memory extraction (fast + cheap)
    - OpenAI text-embedding-3-small for semantic retrieval (same as RAG chunks)
    - pgvector (Supabase) if DATABASE_URL is set, else in-memory
    """
    config: dict = {
        "llm": {
            "provider": "anthropic",
            "config": {
                "model": settings.fast_model,
                "api_key": settings.anthropic_api_key,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": settings.embedding_model,
                "api_key": settings.openai_api_key,
            },
        },
    }

    if settings.database_url:
        db_params = _parse_db_url(settings.database_url)
        config["vector_store"] = {
            "provider": "pgvector",
            "config": {
                **db_params,
                "collection_name": _COLLECTION_NAME,
                "embedding_model_dims": 1536,
            },
        }
        config["history_db_url"] = settings.database_url

    return Memory.from_config(config)


def add_memories(
    messages: list[dict],
    project_id: str,
    user_id: str,
) -> list[dict]:
    """Extract and store memories from a conversation exchange.

    mem0 uses the LLM to decide what's worth remembering (facts, decisions,
    preferences, open questions) and handles deduplication/updates automatically.

    Args:
        messages:   Conversation turns: [{"role": "user"|"assistant", "content": str}]
        project_id: Used as agent_id to scope memories to this project.
        user_id:    The PM's user ID.

    Returns:
        List of memory records that were added or updated (id, memory, event).
    """
    m = _get_mem0_client()
    result = m.add(
        messages,
        user_id=user_id,
        agent_id=project_id,
        metadata={"project_id": project_id},
    )
    records = result.get("results", []) if isinstance(result, dict) else result
    return [r for r in records if r.get("event") in ("ADD", "UPDATE")]


def search_memories(
    query: str,
    project_id: str,
    user_id: str,
    limit: int = 5,
) -> list[dict]:
    """Retrieve memories semantically relevant to a query.

    Args:
        query:      Natural language query (e.g. the user's current question).
        project_id: Scopes search to this project.
        user_id:    Scopes search to this user.
        limit:      Max memories to return.

    Returns:
        List of memory records sorted by relevance: [{id, memory, score}, ...]
    """
    m = _get_mem0_client()
    result = m.search(
        query,
        user_id=user_id,
        agent_id=project_id,
        limit=limit,
    )
    return result.get("results", []) if isinstance(result, dict) else result


def get_all_memories(project_id: str, user_id: str) -> list[dict]:
    """Fetch all stored memories for a project/user combination.

    Returns:
        List of memory records: [{id, memory, created_at, metadata}, ...]
    """
    m = _get_mem0_client()
    result = m.get_all(user_id=user_id, agent_id=project_id)
    return result.get("results", []) if isinstance(result, dict) else result


def delete_memory(memory_id: str) -> None:
    """Delete a specific memory by its ID."""
    m = _get_mem0_client()
    m.delete(memory_id)
