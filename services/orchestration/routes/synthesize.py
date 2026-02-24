"""
POST /synthesize

Runs the full MapReduce synthesis pipeline for a project and persists the
results (synthesis record + themes + opportunities) to Supabase.

Body:
  project_id   string   (required)
  source_ids   string[] (optional — defaults to ALL sources for the project)
  trigger_type string   (optional — 'manual' | 'chat_query', default 'manual')

Returns:
  { synthesis_id, theme_count, opportunity_count, summary }
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.orchestration.db import get_supabase, run_sync
from services.orchestration.agent.map_reduce import (
    SourceInput,
    run_map_reduce_synthesis,
)

router = APIRouter()


class SynthesizeBody(BaseModel):
    project_id: str
    source_ids: list[str] | None = None
    trigger_type: str = "manual"


@router.post("/synthesize")
async def synthesize(body: SynthesizeBody):
    supabase = get_supabase()
    project_id = body.project_id.strip()

    # ── Fetch sources ─────────────────────────────────────────────────────
    query = (
        supabase.from_("sources")
        .select("id, name, source_type, segment_tags, raw_content")
        .eq("project_id", project_id)
    )
    if body.source_ids:
        query = query.in_("id", body.source_ids)

    result = await run_sync(lambda: query.execute())
    sources_data = result.data or []

    if not sources_data:
        raise HTTPException(
            status_code=400,
            detail="No sources found. Upload and process sources first.",
        )

    # Only sources with extractable text can be synthesised
    sources = [
        SourceInput(
            id=s["id"],
            name=s["name"],
            content=s["raw_content"],
            source_type=s["source_type"],
            segment_tags=s.get("segment_tags") or [],
        )
        for s in sources_data
        if s.get("raw_content") and s["raw_content"].strip()
    ]

    if not sources:
        raise HTTPException(
            status_code=400,
            detail="None of the selected sources have raw_content. Process sources first.",
        )

    # ── Run pipeline ──────────────────────────────────────────────────────
    try:
        result_data = await run_map_reduce_synthesis(sources)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # ── Persist synthesis ─────────────────────────────────────────────────
    model_label = f"{body.trigger_type} / haiku+sonnet+opus (mapreduce)"
    synth_result = await run_sync(
        lambda: supabase.from_("syntheses")
        .insert(
            {
                "project_id": project_id,
                "trigger_type": body.trigger_type,
                "summary": result_data.synthesis_string,
                "source_ids": [s.id for s in sources],
                "model_used": model_label,
            }
        )
        .select("id")
        .single()
        .execute()
    )

    synthesis_id: str = synth_result.data["id"]

    # ── Persist themes ────────────────────────────────────────────────────
    if result_data.themes:
        theme_rows = [
            {
                "project_id": project_id,
                "synthesis_id": synthesis_id,
                "title": t.title,
                "description": t.description,
                "frequency_score": t.frequency_score,
                "severity_score": t.severity_score,
                "segment_distribution": t.segment_distribution,
                "supporting_quotes": [
                    {"quote": q.quote, "source_name": q.source_name}
                    for q in t.supporting_quotes
                ],
            }
            for t in result_data.themes
        ]
        await run_sync(lambda: supabase.from_("themes").insert(theme_rows).execute())

    # ── Persist opportunities ─────────────────────────────────────────────
    if result_data.opportunities:
        opp_rows = [
            {
                "project_id": project_id,
                "synthesis_id": synthesis_id,
                "title": o.title,
                "problem_statement": o.problem_statement,
                "evidence": o.evidence,
                "affected_segments": o.affected_segments,
                "confidence_score": o.confidence_score,
                "why_now": o.why_now,
                "ai_reasoning": o.ai_reasoning,
                "rank": rank + 1,
                "status": "proposed",
            }
            for rank, o in enumerate(result_data.opportunities)
        ]
        await run_sync(lambda: supabase.from_("opportunities").insert(opp_rows).execute())

    return {
        "synthesis_id": synthesis_id,
        "theme_count": len(result_data.themes),
        "opportunity_count": len(result_data.opportunities),
        "summary": result_data.synthesis_string,
    }
