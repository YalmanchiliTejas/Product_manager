"""Sources router — full CRUD + ingestion pipeline endpoint."""

from fastapi import APIRouter, HTTPException

from backend.db.supabase_client import get_supabase
from backend.schemas.models import (
    ProcessSourceRequest,
    ProcessSourceResponse,
    SourceCreate,
    SourceResponse,
    SourceUpdate,
)
from backend.services.ingestion import run_ingestion_pipeline

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get(
    "",
    response_model=list[SourceResponse],
    summary="List all sources for a project",
)
def list_sources(project_id: str) -> list[SourceResponse]:
    db = get_supabase()
    result = (
        db.table("sources")
        .select("*")
        .eq("project_id", project_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


@router.post(
    "",
    response_model=SourceResponse,
    status_code=201,
    summary="Create a new source document",
)
def create_source(body: SourceCreate) -> SourceResponse:
    db = get_supabase()
    try:
        result = (
            db.table("sources")
            .insert(
                {
                    "project_id": body.project_id,
                    "name": body.name,
                    "source_type": body.source_type,
                    "segment_tags": body.segment_tags or [],
                    "raw_content": body.raw_content,
                    "file_path": body.file_path,
                    "metadata": body.metadata or {},
                }
            )
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result.data[0]


@router.get(
    "/{source_id}",
    response_model=SourceResponse,
    summary="Get a single source by ID",
)
def get_source(source_id: str) -> SourceResponse:
    db = get_supabase()
    result = db.table("sources").select("*").eq("id", source_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Source not found")
    return result.data[0]


@router.patch(
    "/{source_id}",
    response_model=SourceResponse,
    summary="Update a source's type or segment tags",
)
def update_source(source_id: str, body: SourceUpdate) -> SourceResponse:
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")
    db = get_supabase()
    result = db.table("sources").update(updates).eq("id", source_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Source not found")
    return result.data[0]


@router.delete(
    "/{source_id}",
    status_code=204,
    summary="Delete a source and its chunks",
)
def delete_source(source_id: str) -> None:
    db = get_supabase()
    db.table("sources").delete().eq("id", source_id).execute()


@router.post(
    "/process",
    response_model=ProcessSourceResponse,
    summary="Process a source: extract → chunk → embed → store",
)
def process_source(body: ProcessSourceRequest) -> ProcessSourceResponse:
    """Run the full ingestion pipeline for a source record.

    Fetches the source from Supabase, extracts text, chunks it, embeds each
    chunk via OpenAI, and upserts the chunk rows (with pgvector embeddings).
    """
    try:
        result = run_ingestion_pipeline(body.source_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ProcessSourceResponse(**result)
