"""Synthesis router — theme extraction (Pass 1) and opportunity scoring (Pass 2)."""

from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.db.supabase_client import get_supabase
from backend.schemas.models import (
    OpportunityScoringRequest,
    OpportunityScoringResponse,
    ThemeExtractionRequest,
    ThemeExtractionResponse,
)
from backend.services.synthesis import run_opportunity_scoring, run_theme_extraction

router = APIRouter(prefix="/api/synthesis", tags=["synthesis"])


def _create_synthesis_record(
    project_id: str,
    source_ids: list[str] | None,
    model_used: str,
) -> str:
    """Insert a synthesis record and return its UUID."""
    db = get_supabase()
    result = (
        db.table("syntheses")
        .insert(
            {
                "project_id": project_id,
                "trigger_type": "manual",
                "source_ids": source_ids or [],
                "model_used": model_used,
            }
        )
        .execute()
    )
    return result.data[0]["id"]


@router.post(
    "/themes",
    response_model=ThemeExtractionResponse,
    summary="Pass 1 — Extract themes from research chunks (fast model)",
)
def extract_themes(body: ThemeExtractionRequest) -> ThemeExtractionResponse:
    """Run the theme extraction pipeline (Pass 1).

    1. Creates a synthesis record in Supabase.
    2. Fetches chunks for the project (optionally filtered by source_ids).
    3. Batches chunks to fit within the model context window.
    4. Calls the fast model (claude-haiku) to produce themes with chunk citations.
    5. Consolidates across batches if needed.
    6. Persists themes to Supabase and returns them with their database IDs.
    """
    model_label = body.model_used or settings.fast_model
    try:
        synthesis_id = _create_synthesis_record(
            body.project_id, body.source_ids, model_label
        )
        themes = run_theme_extraction(
            project_id=body.project_id,
            synthesis_id=synthesis_id,
            source_ids=body.source_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ThemeExtractionResponse(
        synthesis_id=synthesis_id,
        themes=themes,
        theme_count=len(themes),
    )


@router.post(
    "/opportunities",
    response_model=OpportunityScoringResponse,
    summary="Pass 2 — Score and rank product opportunities (strong model)",
)
def score_opportunities(body: OpportunityScoringRequest) -> OpportunityScoringResponse:
    """Run the opportunity scoring pipeline (Pass 2).

    1. Fetches themes produced in Pass 1 for the given synthesis_id.
    2. Retrieves all supporting chunks referenced by those themes.
    3. Calls the strong model (claude-sonnet) with strict citation requirements.
    4. Persists ranked opportunities to Supabase and returns them.

    Requires a completed Pass 1 (theme extraction) for the same synthesis_id.
    """
    try:
        opportunities = run_opportunity_scoring(
            project_id=body.project_id,
            synthesis_id=body.synthesis_id,
            theme_ids=body.theme_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return OpportunityScoringResponse(
        synthesis_id=body.synthesis_id,
        opportunities=opportunities,
        opportunity_count=len(opportunities),
    )
