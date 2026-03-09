"""Temporal awareness layer for the synthesis engine.

Wraps the existing synthesis pipeline to inject temporal context:
  - Before synthesis: loads previous themes and trends
  - After synthesis: computes trends, detects relationships, runs comparison

This is what turns atomic synthesis into an evolving intelligence layer.
The key insight: every synthesis output should be temporally aware, telling
the user not just "here's what your feedback says" but "here's what changed
since last time and why it matters."
"""

import json
from datetime import datetime, timezone

from backend.db.supabase_client import get_supabase
from backend.services.signal_correlation import detect_theme_relationships
from backend.services.synthesis_comparison import compare_with_previous
from backend.services.trend_detection import compute_trends_for_synthesis


def build_temporal_context(project_id: str) -> dict:
    """Build temporal context to inject into the synthesis pipeline.

    Loads:
      - Previous themes with their trend directions
      - Active signal correlations
      - Recent changes from last comparison

    Returns a dict that can be injected into synthesis prompts.
    """
    db = get_supabase()

    # Get most recent synthesis
    latest = (
        db.table("syntheses")
        .select("id, created_at")
        .eq("project_id", project_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
    )

    if not latest:
        return {
            "has_history": False,
            "previous_themes": [],
            "trends": [],
            "correlations": [],
            "context_note": "This is the first synthesis for this project.",
        }

    latest_id = latest[0]["id"]
    latest_date = latest[0]["created_at"]

    # Load previous themes
    themes = (
        db.table("themes")
        .select("id, title, description, chunk_ids")
        .eq("synthesis_id", latest_id)
        .execute()
        .data or []
    )

    # Load trends for those themes
    trends = (
        db.table("theme_trends")
        .select("theme_title, trend_direction, velocity, mention_count, segment_spread")
        .eq("synthesis_id", latest_id)
        .execute()
        .data or []
    )
    trend_map = {t["theme_title"]: t for t in trends}

    # Build annotated theme list
    annotated_themes = []
    for theme in themes:
        trend = trend_map.get(theme["title"], {})
        annotated_themes.append({
            "title": theme["title"],
            "description": theme.get("description", ""),
            "evidence_count": len(theme.get("chunk_ids") or []),
            "trend": trend.get("trend_direction", "unknown"),
            "velocity": trend.get("velocity", 0),
            "segment_spread": trend.get("segment_spread", 0),
        })

    # Load recent correlations
    correlations = (
        db.table("signal_correlations")
        .select("correlation_type, signal_a, signal_b, explanation")
        .eq("project_id", project_id)
        .order("detected_at", desc=True)
        .limit(10)
        .execute()
        .data or []
    )

    # Build a context note for synthesis prompts
    emerging = [t for t in annotated_themes if t["trend"] == "emerging"]
    accelerating = [t for t in annotated_themes if t["trend"] == "accelerating"]
    declining = [t for t in annotated_themes if t["trend"] == "declining"]

    context_parts = [
        f"Previous synthesis ({latest_date}) found {len(themes)} themes.",
    ]
    if emerging:
        context_parts.append(
            f"Emerging themes: {', '.join(t['title'] for t in emerging)}"
        )
    if accelerating:
        context_parts.append(
            f"Accelerating themes: {', '.join(t['title'] for t in accelerating)}"
        )
    if declining:
        context_parts.append(
            f"Declining themes: {', '.join(t['title'] for t in declining)}"
        )

    return {
        "has_history": True,
        "previous_synthesis_id": latest_id,
        "previous_synthesis_date": latest_date,
        "previous_themes": annotated_themes,
        "trends": trends,
        "correlations": correlations,
        "context_note": " ".join(context_parts),
    }


def run_temporal_synthesis_postprocess(
    project_id: str,
    synthesis_id: str,
) -> dict:
    """Run all post-synthesis intelligence passes.

    Called after the core synthesis pipeline completes:
      1. Compute trend data for the new themes
      2. Detect theme relationships and signal correlations
      3. Compare with previous synthesis to generate "what changed"

    Returns a summary of all post-processing results.
    """
    results = {}

    # 1. Trend detection
    trends = compute_trends_for_synthesis(project_id, synthesis_id)
    results["trends"] = {
        "total": len(trends),
        "emerging": len([t for t in trends if t["trend_direction"] == "emerging"]),
        "accelerating": len([t for t in trends if t["trend_direction"] == "accelerating"]),
        "stable": len([t for t in trends if t["trend_direction"] == "stable"]),
        "declining": len([t for t in trends if t["trend_direction"] == "declining"]),
        "resurgent": len([t for t in trends if t["trend_direction"] == "resurgent"]),
    }

    # 2. Theme relationship detection
    relationships = detect_theme_relationships(project_id, synthesis_id)
    results["relationships"] = {
        "theme_relationships": len(relationships.get("relationships", [])),
        "signal_correlations": len(relationships.get("correlations", [])),
        "segment_divergences": len(relationships.get("segment_divergences", [])),
    }

    # 3. Cross-synthesis comparison
    comparison = compare_with_previous(project_id, synthesis_id)
    if comparison:
        results["comparison"] = {
            "summary": comparison.get("summary", ""),
            "new_themes": len(comparison.get("new_themes") or []),
            "removed_themes": len(comparison.get("removed_themes") or []),
            "accelerating": len(comparison.get("accelerating_themes") or []),
            "declining": len(comparison.get("declining_themes") or []),
        }
    else:
        results["comparison"] = None  # First synthesis, nothing to compare

    return results


def generate_temporal_report(project_id: str, synthesis_id: str) -> str:
    """Generate a human-readable temporal intelligence report.

    This is the "demo output" — the thing that makes people say
    "nothing else does this."

    Example output:
      "Theme 'Onboarding Friction' first appeared 8 weeks ago from 2 enterprise
       accounts, has grown to 14 mentions across 3 segments, and correlates with
       a support ticket spike you saw in week 5."
    """
    db = get_supabase()

    # Load themes for this synthesis
    themes = (
        db.table("themes")
        .select("id, title, description, chunk_ids")
        .eq("synthesis_id", synthesis_id)
        .execute()
        .data or []
    )

    # Load all trend history for this project
    all_trends = (
        db.table("theme_trends")
        .select("theme_title, synthesis_id, measured_at, mention_count, "
                "segment_spread, source_count, trend_direction, velocity")
        .eq("project_id", project_id)
        .order("measured_at")
        .execute()
        .data or []
    )

    # Group trends by theme title
    trend_history: dict[str, list[dict]] = {}
    for t in all_trends:
        trend_history.setdefault(t["theme_title"], []).append(t)

    # Load relationships
    relationships = (
        db.table("theme_relationships")
        .select("source_theme_id, target_theme_id, relationship, strength, evidence")
        .eq("project_id", project_id)
        .order("strength", desc=True)
        .limit(20)
        .execute()
        .data or []
    )
    theme_id_to_title = {t["id"]: t["title"] for t in themes}

    # Load correlations
    correlations = (
        db.table("signal_correlations")
        .select("correlation_type, signal_a, signal_b, explanation")
        .eq("project_id", project_id)
        .order("detected_at", desc=True)
        .limit(10)
        .execute()
        .data or []
    )

    # Build report
    report_lines = ["# Temporal Intelligence Report", ""]

    for theme in themes:
        title = theme["title"]
        history = trend_history.get(title, [])

        if not history:
            report_lines.append(f"## {title}")
            report_lines.append("*New theme — no prior history.*")
            report_lines.append("")
            continue

        latest = history[-1]
        first = history[0]

        # Compute weeks since first seen
        first_date = first.get("measured_at", "")
        mention_total = sum(h.get("mention_count", 0) for h in history)
        max_segments = max(h.get("segment_spread", 0) for h in history)

        report_lines.append(f"## {title}")
        report_lines.append(
            f"- **Trend**: {latest['trend_direction']} "
            f"(velocity: {latest['velocity']:+.2f})"
        )
        report_lines.append(
            f"- **History**: First appeared {first_date[:10]}, "
            f"tracked across {len(history)} synthesis runs"
        )
        report_lines.append(
            f"- **Total mentions**: {mention_total} across up to {max_segments} segments"
        )

        if len(history) > 1:
            mention_trajectory = [h["mention_count"] for h in history]
            report_lines.append(
                f"- **Mention trajectory**: {' → '.join(str(m) for m in mention_trajectory)}"
            )

        # Add relationship context
        for rel in relationships:
            if rel["source_theme_id"] == theme["id"]:
                target_title = theme_id_to_title.get(rel["target_theme_id"], "unknown")
                evidence = rel.get("evidence", {})
                explanation = evidence.get("explanation", "") if isinstance(evidence, dict) else ""
                report_lines.append(
                    f"- **{rel['relationship']}** → {target_title} "
                    f"(strength: {rel['strength']:.2f}) — {explanation}"
                )

        report_lines.append("")

    # Correlations section
    if correlations:
        report_lines.append("## Signal Correlations")
        for corr in correlations:
            signal_a = corr.get("signal_a", {})
            signal_b = corr.get("signal_b", {})
            label_a = signal_a.get("label", "?") if isinstance(signal_a, dict) else "?"
            label_b = signal_b.get("label", "?") if isinstance(signal_b, dict) else "?"
            report_lines.append(
                f"- **{corr['correlation_type']}**: {label_a} ↔ {label_b} — "
                f"{corr.get('explanation', '')}"
            )
        report_lines.append("")

    return "\n".join(report_lines)
