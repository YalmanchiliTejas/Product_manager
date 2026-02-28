"""Memory router — persistent PM memory endpoints (backed by mem0)."""

from fastapi import APIRouter, HTTPException

from backend.schemas.models import (
    ContextPackRequest,
    ContextPackResponse,
    MemoryAddRequest,
    MemoryItem,
    MemoryResponse,
    MemorySearchRequest,
)
from backend.services.context_pack import get_context_pack
from backend.services.memory import (
    add_memories,
    delete_memory,
    get_all_memories,
    search_memories,
)

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.post(
    "/add",
    response_model=MemoryResponse,
    summary="Extract and store memories from a conversation exchange",
)
def add_memory_from_conversation(body: MemoryAddRequest) -> MemoryResponse:
    """Feed a conversation to mem0.

    mem0 uses an LLM to decide what's worth remembering (facts, decisions,
    open questions, preferences) and stores them with deduplication.
    """
    try:
        records = add_memories(
            messages=[m.model_dump() for m in body.messages],
            project_id=body.project_id,
            user_id=body.user_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return MemoryResponse(
        memories=[
            MemoryItem(
                id=r.get("id", ""),
                memory=r.get("memory", ""),
                created_at=r.get("created_at"),
                metadata=r.get("metadata"),
            )
            for r in records
        ]
    )


@router.post(
    "/search",
    response_model=MemoryResponse,
    summary="Search memories semantically relevant to a query",
)
def search_memory(body: MemorySearchRequest) -> MemoryResponse:
    """Return the top-k memories most relevant to the query.

    Used automatically by the RAG pipeline when user_id is provided — but
    exposed here for debugging and direct PM use.
    """
    try:
        records = search_memories(
            query=body.query,
            project_id=body.project_id,
            user_id=body.user_id,
            limit=body.limit,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return MemoryResponse(
        memories=[
            MemoryItem(
                id=r.get("id", ""),
                memory=r.get("memory", ""),
                score=r.get("score"),
                created_at=r.get("created_at"),
                metadata=r.get("metadata"),
            )
            for r in records
        ]
    )


@router.get(
    "/{project_id}/{user_id}",
    response_model=MemoryResponse,
    summary="Get all memories for a project/user",
)
def list_memories(project_id: str, user_id: str) -> MemoryResponse:
    """Return the full memory store for a project/user pair."""
    try:
        records = get_all_memories(project_id=project_id, user_id=user_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return MemoryResponse(
        memories=[
            MemoryItem(
                id=r.get("id", ""),
                memory=r.get("memory", ""),
                created_at=r.get("created_at"),
                metadata=r.get("metadata"),
            )
            for r in records
        ]
    )


@router.delete(
    "/{memory_id}",
    status_code=204,
    summary="Delete a specific memory by ID",
)
def remove_memory(memory_id: str) -> None:
    """Permanently delete a memory. Useful for correcting incorrect extractions."""
    try:
        delete_memory(memory_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/context-pack",
    response_model=ContextPackResponse,
    summary="Build compact context pack for a task",
)
def build_context_pack(body: ContextPackRequest) -> ContextPackResponse:
    """Build and persist a compact context pack with citations."""
    try:
        pack = get_context_pack(
            project_id=body.project_id,
            task_type=body.task_type,
            query=body.query,
            budget_tokens=body.budget_tokens,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ContextPackResponse(**pack)
