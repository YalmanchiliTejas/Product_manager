"""Search router — semantic search and RAG query endpoints."""

from fastapi import APIRouter, HTTPException

from backend.schemas.models import (
    RAGQueryRequest,
    RAGQueryResponse,
    SemanticSearchRequest,
    SemanticSearchResponse,
)
from backend.services.rag import run_rag_pipeline
from backend.services.semantic_search import semantic_search

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post(
    "/semantic",
    response_model=SemanticSearchResponse,
    summary="Semantic chunk search via pgvector",
)
def search_semantic(body: SemanticSearchRequest) -> SemanticSearchResponse:
    """Embed the query and return the top-k matching chunks using cosine similarity.

    Calls the `semantic_search_chunks` Postgres function via Supabase RPC.
    """
    try:
        matches = semantic_search(
            project_id=body.project_id,
            query=body.query,
            match_count=body.match_count,
            source_types=body.source_types,
            segment_tags=body.segment_tags,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return SemanticSearchResponse(matches=matches)


@router.post(
    "/rag",
    response_model=RAGQueryResponse,
    summary="RAG query: retrieve relevant chunks, then generate a grounded answer",
)
def rag_query(body: RAGQueryRequest) -> RAGQueryResponse:
    """Full RAG pipeline: embed query → retrieve chunks → augment → generate with Anthropic.

    Every claim in the answer cites a chunk_id from the retrieved evidence.
    Returns the answer, cited chunk IDs, retrieved chunk metadata, and token usage.
    """
    history = (
        [msg.model_dump() for msg in body.conversation_history]
        if body.conversation_history
        else None
    )
    try:
        result = run_rag_pipeline(
            project_id=body.project_id,
            query=body.query,
            conversation_history=history,
            match_count=body.match_count,
            source_types=body.source_types,
            segment_tags=body.segment_tags,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RAGQueryResponse(**result)
