"""Knowledge Graph router — entities, trends, correlations, comparisons, temporal synthesis.

This is the core intelligence API. Every endpoint either builds the knowledge graph
or reads from it. The temporal synthesis endpoint is the primary entry point that
runs the full pipeline: synthesis → trends → correlations → comparison → report.

API overview:
    # Entity extraction & graph
    POST   /api/knowledge-graph/entities/extract     — Extract entities from sources
    GET    /api/knowledge-graph/entities/{project_id} — List entities
    GET    /api/knowledge-graph/entities/{entity_id}/connections — Entity connections

    # Snapshot comparison
    GET    /api/knowledge-graph/snapshots/{project_id} — List snapshots
    POST   /api/knowledge-graph/snapshots/compare      — Compare two snapshots
    POST   /api/knowledge-graph/snapshots/compare-latest — Auto-compare latest two

    # Trend detection
    GET    /api/knowledge-graph/trends/{project_id}          — Trend history
    POST   /api/knowledge-graph/trends/trending              — Get trending themes

    # Signal correlation
    POST   /api/knowledge-graph/correlations/detect          — Detect correlations
    GET    /api/knowledge-graph/correlations/{project_id}    — List correlations
    GET    /api/knowledge-graph/relationships/{project_id}   — List theme relationships

    # Synthesis comparison
    POST   /api/knowledge-graph/synthesis/compare            — Compare two syntheses
    GET    /api/knowledge-graph/synthesis/timeline/{project_id} — Synthesis timeline

    # Temporal synthesis (full pipeline)
    POST   /api/knowledge-graph/synthesis/temporal           — Full temporal synthesis
    GET    /api/knowledge-graph/synthesis/report/{project_id}/{synthesis_id} — Get report
"""

from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.db.supabase_client import get_supabase
from backend.schemas.models import (
    EntityConnectionsResponse,
    EntityExtractionRequest,
    EntityExtractionResponse,
    EntityResponse,
    SignalCorrelationRequest,
    SignalCorrelationResponse,
    SnapshotComparisonRequest,
    SnapshotComparisonResponse,
    SnapshotListResponse,
    SynthesisComparisonRequest,
    SynthesisComparisonResponse,
    SynthesisTimelineResponse,
    TemporalSynthesisRequest,
    TemporalSynthesisResponse,
    TrendingThemesRequest,
    TrendResponse,
)
from backend.services.entity_extraction import (
    extract_entities_for_project,
    extract_entities_for_source,
    get_entity_connections,
    get_entity_graph,
)
from backend.services.signal_correlation import (
    detect_theme_relationships,
    get_signal_correlations,
    get_theme_relationships,
)
from backend.services.snapshot_comparison import (
    compare_latest_snapshots,
    compare_snapshots,
    get_latest_snapshots,
)
from backend.services.synthesis_comparison import (
    compare_syntheses,
    compare_with_previous,
    get_synthesis_timeline,
)
from backend.services.synthesis_graph import run_synthesis_graph
from backend.services.temporal_synthesis import (
    build_temporal_context,
    generate_temporal_report,
    run_temporal_synthesis_postprocess,
)
from backend.services.trend_detection import (
    get_trend_history,
    get_trending_themes,
    compute_trends_for_synthesis,
)

router = APIRouter(prefix="/api/knowledge-graph", tags=["knowledge-graph"])


# ---------------------------------------------------------------------------
# Entity extraction & graph
# ---------------------------------------------------------------------------

@router.post(
    "/entities/extract",
    response_model=EntityExtractionResponse,
    summary="Extract entities from project sources into the knowledge graph",
)
def extract_entities(body: EntityExtractionRequest) -> EntityExtractionResponse:
    try:
        if body.source_id:
            result = extract_entities_for_source(body.project_id, body.source_id)
            return EntityExtractionResponse(
                sources_processed=1,
                entities_found=result["entities_found"],
                mentions_created=result["mentions_created"],
            )
        else:
            result = extract_entities_for_project(body.project_id)
            return EntityExtractionResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/entities/{project_id}",
    response_model=list[EntityResponse],
    summary="List all entities in the knowledge graph",
)
def list_entities(project_id: str, entity_type: str | None = None) -> list[EntityResponse]:
    try:
        entities = get_entity_graph(project_id, entity_type)
        return [EntityResponse(**e) for e in entities]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/entities/{entity_id}/connections",
    response_model=EntityConnectionsResponse,
    summary="Get all connections (chunks, sources) for an entity",
)
def entity_connections(entity_id: str) -> EntityConnectionsResponse:
    try:
        result = get_entity_connections(entity_id)
        return EntityConnectionsResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Snapshot comparison
# ---------------------------------------------------------------------------

@router.get(
    "/snapshots/{project_id}",
    response_model=SnapshotListResponse,
    summary="List recent memory snapshots",
)
def list_snapshots(project_id: str, limit: int = 10) -> SnapshotListResponse:
    snapshots = get_latest_snapshots(project_id, limit)
    return SnapshotListResponse(snapshots=snapshots)


@router.post(
    "/snapshots/compare",
    response_model=SnapshotComparisonResponse,
    summary="Compare two memory snapshots",
)
def snapshot_compare(body: SnapshotComparisonRequest) -> SnapshotComparisonResponse:
    try:
        result = compare_snapshots(
            body.project_id, body.baseline_snapshot_id, body.current_snapshot_id
        )
        return SnapshotComparisonResponse(
            new_items=result.get("new_items", []),
            removed_items=result.get("removed_items", []),
            changed_items=result.get("changed_items", []),
            summary=result.get("summary", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/snapshots/compare-latest",
    response_model=SnapshotComparisonResponse,
    summary="Auto-compare the two most recent snapshots",
)
def snapshot_compare_latest(project_id: str) -> SnapshotComparisonResponse:
    result = compare_latest_snapshots(project_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Fewer than 2 snapshots available.")
    return SnapshotComparisonResponse(
        new_items=result.get("new_items", []),
        removed_items=result.get("removed_items", []),
        changed_items=result.get("changed_items", []),
        summary=result.get("summary", ""),
    )


# ---------------------------------------------------------------------------
# Trend detection
# ---------------------------------------------------------------------------

@router.get(
    "/trends/{project_id}",
    response_model=TrendResponse,
    summary="Get trend history for a project",
)
def trend_history(
    project_id: str,
    theme_title: str | None = None,
    limit: int = 50,
) -> TrendResponse:
    trends = get_trend_history(project_id, theme_title, limit)
    return TrendResponse(trends=trends)


@router.post(
    "/trends/trending",
    response_model=TrendResponse,
    summary="Get currently trending themes with direction filters",
)
def trending_themes(body: TrendingThemesRequest) -> TrendResponse:
    trends = get_trending_themes(body.project_id, body.direction)
    return TrendResponse(trends=trends)


# ---------------------------------------------------------------------------
# Signal correlation
# ---------------------------------------------------------------------------

@router.post(
    "/correlations/detect",
    response_model=SignalCorrelationResponse,
    summary="Detect theme relationships and signal correlations for a synthesis",
)
def detect_correlations(body: SignalCorrelationRequest) -> SignalCorrelationResponse:
    try:
        result = detect_theme_relationships(body.project_id, body.synthesis_id)
        return SignalCorrelationResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/correlations/{project_id}",
    summary="List signal correlations",
)
def list_correlations(
    project_id: str,
    correlation_type: str | None = None,
) -> list[dict]:
    return get_signal_correlations(project_id, correlation_type)


@router.get(
    "/relationships/{project_id}",
    summary="List theme relationships",
)
def list_relationships(project_id: str) -> list[dict]:
    return get_theme_relationships(project_id)


# ---------------------------------------------------------------------------
# Synthesis comparison
# ---------------------------------------------------------------------------

@router.post(
    "/synthesis/compare",
    response_model=SynthesisComparisonResponse,
    summary="Compare two synthesis runs — what changed?",
)
def synthesis_compare(body: SynthesisComparisonRequest) -> SynthesisComparisonResponse:
    try:
        result = compare_syntheses(
            body.project_id, body.baseline_synthesis_id, body.current_synthesis_id
        )
        return SynthesisComparisonResponse(
            new_themes=result.get("new_themes", []),
            removed_themes=result.get("removed_themes", []),
            accelerating_themes=result.get("accelerating_themes", []),
            declining_themes=result.get("declining_themes", []),
            stable_themes=result.get("stable_themes", []),
            contradictions=result.get("contradictions", []),
            summary=result.get("summary", ""),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/synthesis/timeline/{project_id}",
    response_model=SynthesisTimelineResponse,
    summary="Get synthesis timeline with comparison annotations",
)
def synthesis_timeline(project_id: str, limit: int = 10) -> SynthesisTimelineResponse:
    syntheses = get_synthesis_timeline(project_id, limit)
    return SynthesisTimelineResponse(syntheses=syntheses)


# ---------------------------------------------------------------------------
# Temporal Synthesis — the main event
# ---------------------------------------------------------------------------

def _create_synthesis_record(
    project_id: str,
    source_ids: list[str] | None,
    model_used: str,
) -> str:
    """Insert a synthesis record and return its UUID."""
    db = get_supabase()
    result = (
        db.table("syntheses")
        .insert({
            "project_id": project_id,
            "trigger_type": "temporal",
            "source_ids": source_ids or [],
            "model_used": model_used,
        })
        .execute()
    )
    return result.data[0]["id"]


@router.post(
    "/synthesis/temporal",
    response_model=TemporalSynthesisResponse,
    summary=(
        "Full temporal synthesis: core pipeline + trends + correlations + comparison + report"
    ),
)
def temporal_synthesis(body: TemporalSynthesisRequest) -> TemporalSynthesisResponse:
    """Run the complete temporally-aware synthesis pipeline.

    This is the primary entry point for the knowledge graph. It:
    1. Loads temporal context (previous themes, trends, correlations)
    2. Runs the core synthesis pipeline (themes + opportunities + evidence drilling)
    3. Computes trend data (emerging, accelerating, declining themes)
    4. Detects theme relationships and signal correlations
    5. Compares with previous synthesis to generate "what changed"
    6. Generates a temporal intelligence report

    The output tells the user not just "here's what your feedback says"
    but "here's what changed since last time and why it matters."
    """
    model_label = body.model_used or settings.fast_model

    try:
        # 1. Build temporal context
        temporal_context = build_temporal_context(body.project_id)

        # 2. Run core synthesis
        synthesis_id = _create_synthesis_record(
            body.project_id, body.source_ids, model_label
        )
        core_result = run_synthesis_graph(
            project_id=body.project_id,
            synthesis_id=synthesis_id,
            source_ids=body.source_ids,
            max_iterations=body.max_drill_down_iterations,
        )

        # 3. Run entity extraction if requested
        if body.extract_entities:
            from backend.services.entity_extraction import extract_entities_for_project
            extract_entities_for_project(body.project_id)

        # 4. Post-process: trends + correlations + comparison
        postprocess = run_temporal_synthesis_postprocess(
            body.project_id, synthesis_id
        )

        # 5. Generate temporal report
        report = generate_temporal_report(body.project_id, synthesis_id)

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return TemporalSynthesisResponse(
        synthesis_id=synthesis_id,
        themes=core_result["themes"],
        opportunities=core_result["opportunities"],
        iterations=core_result["iterations"],
        theme_count=len(core_result["themes"]),
        opportunity_count=len(core_result["opportunities"]),
        temporal_context=temporal_context,
        postprocess=postprocess,
        report=report,
    )


@router.get(
    "/synthesis/report/{project_id}/{synthesis_id}",
    summary="Get the temporal intelligence report for a synthesis",
)
def get_report(project_id: str, synthesis_id: str) -> dict:
    try:
        report = generate_temporal_report(project_id, synthesis_id)
        return {"report": report}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
