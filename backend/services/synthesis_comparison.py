"""Cross-synthesis comparison — "What changed since last time?"

Compares two synthesis runs to produce a structured delta report:
  - New themes: appeared in current but not in baseline
  - Removed themes: in baseline but not in current
  - Accelerating themes: grew in evidence strength
  - Declining themes: lost evidence strength
  - Stable themes: roughly same strength
  - Contradictions: themes where signals conflict across runs

This is the "read layer" that makes the synthesis engine temporally aware.
"""

import json
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from backend.db.supabase_client import get_supabase
from backend.services.llm import get_fast_llm
from backend.services.synthesis import _parse_json_response


_COMPARISON_PROMPT = """\
You are a senior product analyst comparing two rounds of user research synthesis.

Given themes from a BASELINE synthesis and a CURRENT synthesis, produce a change report:

1. **New themes**: themes in CURRENT that have no equivalent in BASELINE
2. **Removed themes**: themes in BASELINE that have no equivalent in CURRENT
3. **Accelerating themes**: themes present in both but stronger in CURRENT (more evidence, broader segments)
4. **Declining themes**: themes present in both but weaker in CURRENT
5. **Stable themes**: themes roughly the same in both
6. **Contradictions**: themes where the signal has reversed or become confused

For matched themes (even if titles differ slightly), compare by meaning not exact title.

Output ONLY valid JSON:
{
  "new_themes": [{"title": "...", "why_new": "..."}],
  "removed_themes": [{"title": "...", "why_gone": "..."}],
  "accelerating": [{"title": "...", "baseline_strength": "weak|moderate|strong", "current_strength": "weak|moderate|strong", "explanation": "..."}],
  "declining": [{"title": "...", "baseline_strength": "weak|moderate|strong", "current_strength": "weak|moderate|strong", "explanation": "..."}],
  "stable": [{"title": "..."}],
  "contradictions": [{"title": "...", "contradiction": "..."}],
  "executive_summary": "2-3 sentence summary of what changed and why it matters"
}"""


def _theme_summary(theme: dict) -> dict:
    """Build a compact summary of a theme for comparison."""
    return {
        "title": theme.get("title", ""),
        "description": theme.get("description", ""),
        "chunk_count": len(theme.get("chunk_ids") or []),
        "quotes": (theme.get("quotes") or [])[:2],
    }


def compare_syntheses(
    project_id: str,
    baseline_synthesis_id: str,
    current_synthesis_id: str,
) -> dict:
    """Compare two synthesis runs and store the diff.

    Args:
        project_id: Project UUID.
        baseline_synthesis_id: The older synthesis run.
        current_synthesis_id: The newer synthesis run.

    Returns:
        The synthesis_comparisons record with categorized theme changes.
    """
    db = get_supabase()

    # Fetch themes for both syntheses
    baseline_themes = (
        db.table("themes")
        .select("id, title, description, chunk_ids, quotes")
        .eq("synthesis_id", baseline_synthesis_id)
        .execute()
        .data or []
    )
    current_themes = (
        db.table("themes")
        .select("id, title, description, chunk_ids, quotes")
        .eq("synthesis_id", current_synthesis_id)
        .execute()
        .data or []
    )

    if not baseline_themes and not current_themes:
        return {"summary": "Both syntheses have no themes."}

    # Use LLM for semantic matching and comparison
    baseline_block = json.dumps([_theme_summary(t) for t in baseline_themes], indent=2)
    current_block = json.dumps([_theme_summary(t) for t in current_themes], indent=2)

    llm = get_fast_llm()
    response = llm.invoke([
        SystemMessage(content=_COMPARISON_PROMPT),
        HumanMessage(content=(
            f"BASELINE synthesis ({len(baseline_themes)} themes):\n{baseline_block}\n\n"
            f"CURRENT synthesis ({len(current_themes)} themes):\n{current_block}\n\n"
            f"Compare these two rounds and identify what changed."
        )),
    ])
    parsed = _parse_json_response(response.content)

    # Store the comparison
    comp_record = {
        "project_id": project_id,
        "baseline_synthesis_id": baseline_synthesis_id,
        "current_synthesis_id": current_synthesis_id,
        "new_themes": parsed.get("new_themes", []),
        "removed_themes": parsed.get("removed_themes", []),
        "accelerating_themes": parsed.get("accelerating", []),
        "declining_themes": parsed.get("declining", []),
        "stable_themes": parsed.get("stable", []),
        "contradictions": parsed.get("contradictions", []),
        "summary": parsed.get("executive_summary", ""),
    }

    resp = db.table("synthesis_comparisons").insert(comp_record).execute()
    result = resp.data[0] if resp.data else comp_record
    return result


def compare_with_previous(
    project_id: str,
    current_synthesis_id: str,
) -> dict | None:
    """Automatically compare a synthesis with the most recent previous one.

    Returns the comparison result or None if no previous synthesis exists.
    """
    db = get_supabase()

    # Find the synthesis just before the current one
    current_resp = (
        db.table("syntheses")
        .select("id, created_at")
        .eq("id", current_synthesis_id)
        .single()
        .execute()
    )
    if not current_resp.data:
        return None

    current_created = current_resp.data["created_at"]

    previous_resp = (
        db.table("syntheses")
        .select("id")
        .eq("project_id", project_id)
        .neq("id", current_synthesis_id)
        .lt("created_at", current_created)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not previous_resp.data:
        return None

    return compare_syntheses(
        project_id=project_id,
        baseline_synthesis_id=previous_resp.data[0]["id"],
        current_synthesis_id=current_synthesis_id,
    )


def get_synthesis_timeline(project_id: str, limit: int = 10) -> list[dict]:
    """Get a timeline of synthesis runs with their comparison summaries.

    Returns syntheses ordered newest-first, each annotated with
    the comparison to its predecessor (if available).
    """
    db = get_supabase()

    syntheses = (
        db.table("syntheses")
        .select("id, created_at, trigger_type, model_used, source_ids")
        .eq("project_id", project_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data or []
    )

    # Load comparisons for these syntheses
    synth_ids = [s["id"] for s in syntheses]
    comparisons = {}
    if synth_ids:
        comp_resp = (
            db.table("synthesis_comparisons")
            .select("current_synthesis_id, summary, new_themes, accelerating_themes, declining_themes")
            .in_("current_synthesis_id", synth_ids)
            .execute()
        )
        for c in (comp_resp.data or []):
            comparisons[c["current_synthesis_id"]] = c

    # Count themes per synthesis
    for synth in syntheses:
        theme_count = (
            db.table("themes")
            .select("id", count="exact")
            .eq("synthesis_id", synth["id"])
            .execute()
        )
        synth["theme_count"] = theme_count.count or 0

        comp = comparisons.get(synth["id"])
        if comp:
            synth["comparison_summary"] = comp.get("summary", "")
            synth["new_theme_count"] = len(comp.get("new_themes") or [])
            synth["accelerating_count"] = len(comp.get("accelerating_themes") or [])
            synth["declining_count"] = len(comp.get("declining_themes") or [])
        else:
            synth["comparison_summary"] = None

    return syntheses
