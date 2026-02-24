"""
POST /search

Semantic search over a project's chunks via pgvector.

Body: { "query": "...", "project_id": "...", "match_count": 8 }
Returns: { "matches": [...] }
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.orchestration.db import get_supabase, run_sync
from services.orchestration.llm.provider import aembed, to_pgvector_literal

router = APIRouter()


class SearchBody(BaseModel):
    query: str
    project_id: str
    match_count: int = 8


@router.post("/search")
async def semantic_search(body: SearchBody):
    query = body.query.strip()
    project_id = body.project_id.strip()
    match_count = max(1, min(body.match_count, 50))

    if not query:
        raise HTTPException(status_code=400, detail="query is required.")
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required.")

    supabase = get_supabase()

    embedding = await aembed(query)
    vec_literal = to_pgvector_literal(embedding)

    result = await run_sync(
        lambda: supabase.rpc(
            "semantic_search_chunks",
            {
                "input_project_id": project_id,
                "query_embedding": vec_literal,
                "match_count": match_count,
            },
        ).execute()
    )

    return {"matches": result.data or []}
