"""Theme trend detection service.

Tracks how themes evolve across synthesis runs:
  - emerging: theme appeared for the first time in this synthesis
  - accelerating: mention count or segment spread is growing
  - stable: roughly same strength as before
  - declining: mention count or segment spread is shrinking
  - resurgent: theme was declining but has bounced back

Computes velocity (rate of change) and stores trend records for time-series analysis.
"""

import json
from datetime import datetime, timezone

from backend.db.supabase_client import get_supabase


def _compute_theme_metrics(theme: dict, chunks: list[dict], sources: list[dict]) -> dict:
    """Compute quantitative metrics for a theme based on its evidence."""
    chunk_ids = theme.get("chunk_ids") or []
    mention_count = len(chunk_ids)

    # Find which sources these chunks belong to
    chunk_source_map = {c["id"]: c.get("source_id") for c in chunks}
    theme_source_ids = set()
    theme_segment_tags = set()

    for cid in chunk_ids:
        sid = chunk_source_map.get(cid)
        if sid:
            theme_source_ids.add(sid)

    source_map = {s["id"]: s for s in sources}
    for sid in theme_source_ids:
        src = source_map.get(sid, {})
        for tag in (src.get("segment_tags") or []):
            theme_segment_tags.add(tag)

    return {
        "mention_count": mention_count,
        "source_count": len(theme_source_ids),
        "segment_spread": len(theme_segment_tags),
    }


def _classify_trend(
    current_mentions: int,
    previous_mentions: int | None,
    current_segments: int,
    previous_segments: int | None,
    was_declining: bool = False,
) -> tuple[str, float]:
    """Classify trend direction and compute velocity.

    Returns: (trend_direction, velocity)
      velocity > 0 means growing, < 0 means shrinking, 0 means stable
    """
    if previous_mentions is None:
        # First time seeing this theme
        return "emerging", 1.0

    if previous_mentions == 0:
        if current_mentions > 0:
            return "emerging", 1.0
        return "stable", 0.0

    # Compute velocity as percentage change
    mention_velocity = (current_mentions - previous_mentions) / max(previous_mentions, 1)
    segment_velocity = 0.0
    if previous_segments is not None and previous_segments > 0:
        segment_velocity = (current_segments - (previous_segments or 0)) / max(previous_segments, 1)

    # Weighted velocity: mentions matter more, but segment spread is a strong signal
    velocity = 0.7 * mention_velocity + 0.3 * segment_velocity

    if velocity > 0.3:
        if was_declining:
            return "resurgent", velocity
        return "accelerating", velocity
    elif velocity < -0.3:
        return "declining", velocity
    else:
        return "stable", velocity


def compute_trends_for_synthesis(
    project_id: str,
    synthesis_id: str,
) -> list[dict]:
    """Compute and store trend data for all themes in a synthesis run.

    Compares against the most recent previous synthesis to determine
    trend direction and velocity.

    Returns: list of theme_trends records created.
    """
    db = get_supabase()

    # Fetch themes for this synthesis
    themes_resp = (
        db.table("themes")
        .select("id, title, description, chunk_ids, synthesis_id")
        .eq("synthesis_id", synthesis_id)
        .execute()
    )
    current_themes = themes_resp.data or []
    if not current_themes:
        return []

    # Fetch all chunks and sources for metric computation
    all_chunk_ids = []
    for t in current_themes:
        all_chunk_ids.extend(t.get("chunk_ids") or [])
    all_chunk_ids = list(set(all_chunk_ids))

    chunks = []
    if all_chunk_ids:
        chunks_resp = (
            db.table("chunks")
            .select("id, source_id")
            .in_("id", all_chunk_ids)
            .execute()
        )
        chunks = chunks_resp.data or []

    source_ids = list(set(c.get("source_id") for c in chunks if c.get("source_id")))
    sources = []
    if source_ids:
        sources_resp = (
            db.table("sources")
            .select("id, segment_tags")
            .in_("id", source_ids)
            .execute()
        )
        sources = sources_resp.data or []

    # Find the previous synthesis for comparison
    synth_resp = (
        db.table("syntheses")
        .select("id, created_at")
        .eq("project_id", project_id)
        .neq("id", synthesis_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    previous_synthesis = synth_resp.data[0] if synth_resp.data else None

    # Load previous trends for comparison
    previous_trends: dict[str, dict] = {}
    if previous_synthesis:
        prev_trends_resp = (
            db.table("theme_trends")
            .select("theme_title, mention_count, segment_spread, source_count, trend_direction")
            .eq("synthesis_id", previous_synthesis["id"])
            .execute()
        )
        for pt in (prev_trends_resp.data or []):
            previous_trends[pt["theme_title"].lower().strip()] = pt

    # Compute trends for each current theme
    trend_records = []
    for theme in current_themes:
        metrics = _compute_theme_metrics(theme, chunks, sources)
        title_key = theme["title"].lower().strip()
        prev = previous_trends.get(title_key)

        prev_mentions = prev["mention_count"] if prev else None
        prev_segments = prev["segment_spread"] if prev else None
        was_declining = prev["trend_direction"] == "declining" if prev else False

        trend_direction, velocity = _classify_trend(
            current_mentions=metrics["mention_count"],
            previous_mentions=prev_mentions,
            current_segments=metrics["segment_spread"],
            previous_segments=prev_segments,
            was_declining=was_declining,
        )

        trend_records.append({
            "project_id": project_id,
            "theme_title": theme["title"],
            "synthesis_id": synthesis_id,
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "mention_count": metrics["mention_count"],
            "segment_spread": metrics["segment_spread"],
            "source_count": metrics["source_count"],
            "trend_direction": trend_direction,
            "velocity": round(velocity, 3),
            "metadata": {
                "theme_id": theme["id"],
                "previous_synthesis_id": previous_synthesis["id"] if previous_synthesis else None,
            },
        })

    if trend_records:
        db.table("theme_trends").insert(trend_records).execute()

    return trend_records


def get_trend_history(
    project_id: str,
    theme_title: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Fetch trend history for a project, optionally filtered by theme title."""
    db = get_supabase()
    query = (
        db.table("theme_trends")
        .select("*")
        .eq("project_id", project_id)
        .order("measured_at", desc=True)
        .limit(limit)
    )
    if theme_title:
        query = query.ilike("theme_title", theme_title)

    return query.execute().data or []


def get_trending_themes(
    project_id: str,
    direction: str | None = None,
) -> list[dict]:
    """Get the latest trend snapshot for each theme.

    Args:
        project_id: Project UUID.
        direction: Optional filter — 'emerging', 'accelerating', 'declining', etc.

    Returns list of the most recent trend record per theme, sorted by velocity.
    """
    db = get_supabase()

    # Get the latest synthesis
    synth_resp = (
        db.table("syntheses")
        .select("id")
        .eq("project_id", project_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not synth_resp.data:
        return []

    latest_synthesis_id = synth_resp.data[0]["id"]

    query = (
        db.table("theme_trends")
        .select("*")
        .eq("synthesis_id", latest_synthesis_id)
        .order("velocity", desc=True)
    )
    if direction:
        query = query.eq("trend_direction", direction)

    return query.execute().data or []
