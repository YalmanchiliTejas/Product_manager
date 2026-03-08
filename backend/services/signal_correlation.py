"""Signal correlation engine.

Detects cross-theme patterns and relationships:
  - Theme co-occurrence: themes that appear together in the same sources
  - Segment divergence: different segments expressing opposing signals
  - Theme relationships: dependency, contradiction, amplification between themes

Uses both heuristic analysis (chunk overlap, segment comparison) and LLM-based
reasoning for nuanced relationship detection.
"""

import json
from collections import defaultdict

from langchain_core.messages import HumanMessage, SystemMessage

from backend.db.supabase_client import get_supabase
from backend.services.llm import get_strong_llm
from backend.services.synthesis import _parse_json_response


_CORRELATION_ANALYSIS_PROMPT = """\
You are a senior product strategist analyzing relationships between themes
extracted from user research.

Given a set of themes with their supporting evidence, identify:

1. **Co-occurring themes**: themes that appear together suggesting a connected user journey
2. **Dependencies**: theme A can only be solved after theme B (prerequisite)
3. **Contradictions**: themes that present opposing signals from different users/segments
4. **Amplifiers**: theme A makes theme B more urgent or impactful
5. **Evolution**: theme A is an earlier version of / has evolved into theme B

For each relationship found:
- source_title: title of the first theme
- target_title: title of the second theme
- relationship: co_occurs | depends_on | contradicts | evolves_into | amplifies
- strength: 0.0 to 1.0 (how confident)
- explanation: 1-2 sentences explaining why this relationship exists

Output ONLY valid JSON:
{
  "relationships": [
    {
      "source_title": "string",
      "target_title": "string",
      "relationship": "co_occurs|depends_on|contradicts|evolves_into|amplifies",
      "strength": 0.8,
      "explanation": "string"
    }
  ],
  "segment_divergences": [
    {
      "theme_title": "string",
      "segment_a": "string",
      "segment_b": "string",
      "divergence": "string",
      "evidence": "string"
    }
  ]
}

Rules:
- Only report relationships with genuine evidence
- Strength should reflect evidence quality, not just your intuition
- If no relationships are found, return empty arrays"""


def _compute_chunk_overlap(themes: list[dict]) -> list[dict]:
    """Find themes that share supporting chunks (strong co-occurrence signal)."""
    theme_chunks: dict[str, set] = {}
    for theme in themes:
        title = theme.get("title", "")
        chunk_ids = set(theme.get("chunk_ids") or [])
        if chunk_ids:
            theme_chunks[title] = chunk_ids

    overlaps = []
    titles = list(theme_chunks.keys())
    for i in range(len(titles)):
        for j in range(i + 1, len(titles)):
            shared = theme_chunks[titles[i]] & theme_chunks[titles[j]]
            if shared:
                total = len(theme_chunks[titles[i]] | theme_chunks[titles[j]])
                strength = len(shared) / total if total > 0 else 0
                overlaps.append({
                    "source_title": titles[i],
                    "target_title": titles[j],
                    "shared_chunk_count": len(shared),
                    "strength": round(strength, 3),
                    "shared_chunk_ids": list(shared),
                })

    return sorted(overlaps, key=lambda x: x["strength"], reverse=True)


def _compute_segment_distribution(themes: list[dict], chunks: list[dict], sources: list[dict]) -> dict:
    """Map each theme to its segment distribution."""
    chunk_source_map = {c["id"]: c.get("source_id") for c in chunks}
    source_segments = {s["id"]: (s.get("segment_tags") or []) for s in sources}

    result = {}
    for theme in themes:
        title = theme.get("title", "")
        segments = defaultdict(int)
        for cid in (theme.get("chunk_ids") or []):
            sid = chunk_source_map.get(cid)
            if sid:
                for tag in source_segments.get(sid, []):
                    segments[tag] += 1
        result[title] = dict(segments)

    return result


def detect_theme_relationships(
    project_id: str,
    synthesis_id: str,
) -> dict:
    """Detect and store relationships between themes in a synthesis run.

    Uses both heuristic chunk-overlap analysis and LLM-based reasoning.

    Returns: {relationships: [...], correlations: [...], segment_divergences: [...]}
    """
    db = get_supabase()

    # Fetch themes
    themes_resp = (
        db.table("themes")
        .select("id, title, description, chunk_ids, quotes")
        .eq("synthesis_id", synthesis_id)
        .execute()
    )
    themes = themes_resp.data or []
    if len(themes) < 2:
        return {"relationships": [], "correlations": [], "segment_divergences": []}

    # Fetch supporting data
    all_chunk_ids = list(set(
        cid for t in themes for cid in (t.get("chunk_ids") or [])
    ))

    chunks = []
    if all_chunk_ids:
        chunks = (
            db.table("chunks")
            .select("id, source_id, content")
            .in_("id", all_chunk_ids)
            .execute()
            .data or []
        )

    source_ids = list(set(c.get("source_id") for c in chunks if c.get("source_id")))
    sources = []
    if source_ids:
        sources = (
            db.table("sources")
            .select("id, segment_tags, source_type")
            .in_("id", source_ids)
            .execute()
            .data or []
        )

    # 1. Heuristic: chunk overlap analysis
    overlaps = _compute_chunk_overlap(themes)

    # 2. Segment distribution analysis
    seg_dist = _compute_segment_distribution(themes, chunks, sources)

    # 3. LLM-based relationship analysis
    themes_context = json.dumps([
        {
            "title": t["title"],
            "description": t.get("description", ""),
            "quotes": (t.get("quotes") or [])[:3],
            "chunk_count": len(t.get("chunk_ids") or []),
            "segments": seg_dist.get(t["title"], {}),
        }
        for t in themes
    ], indent=2)

    llm = get_strong_llm()
    response = llm.invoke([
        SystemMessage(content=_CORRELATION_ANALYSIS_PROMPT),
        HumanMessage(content=(
            f"Analyze relationships between these {len(themes)} themes from project research:\n\n"
            f"{themes_context}"
        )),
    ])
    parsed = _parse_json_response(response.content)
    llm_relationships = parsed.get("relationships", [])
    llm_divergences = parsed.get("segment_divergences", [])

    # Build theme title → id map
    title_to_id = {t["title"]: t["id"] for t in themes}

    # Store theme_relationships
    relationship_records = []
    for rel in llm_relationships:
        source_id = title_to_id.get(rel.get("source_title"))
        target_id = title_to_id.get(rel.get("target_title"))
        if not source_id or not target_id or source_id == target_id:
            continue

        relationship_type = rel.get("relationship", "co_occurs")
        if relationship_type not in ("co_occurs", "depends_on", "contradicts", "evolves_into", "amplifies"):
            relationship_type = "co_occurs"

        record = {
            "project_id": project_id,
            "source_theme_id": source_id,
            "target_theme_id": target_id,
            "relationship": relationship_type,
            "strength": min(1.0, max(0.0, float(rel.get("strength", 0.5)))),
            "evidence": {
                "explanation": rel.get("explanation", ""),
                "detected_by": "llm",
            },
        }
        relationship_records.append(record)

    # Add heuristic co-occurrence relationships
    for overlap in overlaps:
        source_id = title_to_id.get(overlap["source_title"])
        target_id = title_to_id.get(overlap["target_title"])
        if source_id and target_id:
            relationship_records.append({
                "project_id": project_id,
                "source_theme_id": source_id,
                "target_theme_id": target_id,
                "relationship": "co_occurs",
                "strength": overlap["strength"],
                "evidence": {
                    "shared_chunks": overlap["shared_chunk_count"],
                    "detected_by": "heuristic_chunk_overlap",
                },
            })

    if relationship_records:
        db.table("theme_relationships").insert(relationship_records).execute()

    # Store signal_correlations for segment divergences
    correlation_records = []
    for div in llm_divergences:
        correlation_records.append({
            "project_id": project_id,
            "correlation_type": "segment_divergence",
            "signal_a": {
                "type": "segment",
                "label": div.get("segment_a", ""),
                "theme": div.get("theme_title", ""),
            },
            "signal_b": {
                "type": "segment",
                "label": div.get("segment_b", ""),
                "theme": div.get("theme_title", ""),
            },
            "correlation_score": -0.5,  # divergence = negative correlation
            "explanation": div.get("divergence", ""),
            "evidence_chunk_ids": [],
            "metadata": {"evidence": div.get("evidence", "")},
        })

    # Store co-occurrence correlations
    for overlap in overlaps[:10]:  # top 10 overlaps
        correlation_records.append({
            "project_id": project_id,
            "correlation_type": "theme_cooccurrence",
            "signal_a": {"type": "theme", "label": overlap["source_title"]},
            "signal_b": {"type": "theme", "label": overlap["target_title"]},
            "correlation_score": overlap["strength"],
            "explanation": f"Themes share {overlap['shared_chunk_count']} evidence chunks",
            "evidence_chunk_ids": overlap.get("shared_chunk_ids", [])[:10],
        })

    if correlation_records:
        db.table("signal_correlations").insert(correlation_records).execute()

    return {
        "relationships": relationship_records,
        "correlations": correlation_records,
        "segment_divergences": llm_divergences,
    }


def get_theme_relationships(project_id: str) -> list[dict]:
    """Fetch all theme relationships for a project."""
    db = get_supabase()
    return (
        db.table("theme_relationships")
        .select("id, source_theme_id, target_theme_id, relationship, strength, evidence")
        .eq("project_id", project_id)
        .order("strength", desc=True)
        .execute()
        .data or []
    )


def get_signal_correlations(
    project_id: str,
    correlation_type: str | None = None,
) -> list[dict]:
    """Fetch signal correlations, optionally filtered by type."""
    db = get_supabase()
    query = (
        db.table("signal_correlations")
        .select("*")
        .eq("project_id", project_id)
        .order("correlation_score", desc=True)
    )
    if correlation_type:
        query = query.eq("correlation_type", correlation_type)

    return query.execute().data or []
