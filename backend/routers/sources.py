"""Sources router — file ingestion pipeline endpoint."""

from fastapi import APIRouter, HTTPException

from backend.schemas.models import ProcessSourceRequest, ProcessSourceResponse
from backend.services.ingestion import run_ingestion_pipeline

router = APIRouter(prefix="/api/sources", tags=["sources"])


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
