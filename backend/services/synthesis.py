"""Synthesis pipelines: theme extraction (Pass 1) and opportunity scoring (Pass 2).

Pass 1 — Theme Extraction (fast model, claude-haiku):
  - Fetches all chunks for the project (optionally filtered by source_ids)
  - Batches chunks to fit within the model's context window
  - Uses a strict JSON schema prompt to extract recurring themes with citations
  - If multiple batches are needed, consolidates themes in a final pass
  - Persists themes to Supabase `themes` table

Pass 2 — Opportunity Scoring (strong model, claude-sonnet):
  - Fetches themes produced in Pass 1 (by synthesis_id)
  - Fetches all supporting chunks referenced by those themes
  - Uses a strict JSON schema prompt to generate ranked product opportunities
  - Each opportunity must cite theme_ids and chunk_ids
  - Persists opportunities to Supabase `opportunities` table

Both passes require:
  - chunk_ids in citations to be real UUIDs from the provided context
  - Exact verbatim quotes (not paraphrases)
  - Confidence-based gating: if evidence is weak, score lower and explain why
"""

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from backend.config import settings
from backend.db.supabase_client import get_supabase
from backend.services.llm import get_fast_llm, get_strong_llm


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_THEME_SYSTEM_PROMPT = """\
You are a senior product researcher. Given a set of research chunks (interviews, surveys,
support tickets, feedback, etc.), identify the key recurring themes.

For each theme you MUST:
- Write a concise title (< 8 words)
- Write a 2–3 sentence description of the theme and why it matters
- List the chunk_ids that directly support this theme (must be real UUIDs from the input)
- Include 1–2 verbatim quotes copied exactly from those chunks

Output ONLY valid JSON matching this exact schema — no markdown, no extra keys:
{
  "themes": [
    {
      "title": "string",
      "description": "string",
      "chunk_ids": ["uuid", "uuid"],
      "quotes": ["exact verbatim text from chunk", "..."]
    }
  ]
}

Hard rules:
- chunk_ids must appear in the provided evidence — never fabricate IDs
- Quotes must be exact text; no paraphrasing
- Do not invent themes unsupported by the evidence
- Aim for 3–8 distinct themes; merge overlapping themes
- If evidence is too thin for a theme, omit it"""

_THEME_CONSOLIDATION_PROMPT = """\
You are a senior product researcher. You have themes extracted from multiple batches of the same
research corpus. Some themes may be duplicates or highly overlapping.

Merge and deduplicate them into a final canonical theme list. Combine chunk_ids and quotes from
merged themes. Output the same JSON schema as before:
{
  "themes": [
    {
      "title": "string",
      "description": "string",
      "chunk_ids": ["uuid", ...],
      "quotes": ["exact verbatim text", ...]
    }
  ]
}

Hard rules: keep only real chunk_ids that appeared in the input themes."""

_OPPORTUNITY_SYSTEM_PROMPT = """\
You are a senior product strategist. Given themes extracted from user research and supporting
evidence chunks, generate a prioritized list of product opportunities.

For each opportunity you MUST:
- Write a clear, actionable title (e.g. "Build X to solve Y")
- Write a 3–5 sentence description covering the user problem, business impact, and solution direction
- Assign a priority score 1–10 (10 = highest; consider frequency, severity, and strategic fit)
- Explain your scoring reasoning with explicit references to evidence
- Note any contradictions, edge cases, or gaps in the evidence
- List the theme_ids and chunk_ids that support this opportunity (must be real UUIDs from input)

Output ONLY valid JSON matching this exact schema — no markdown, no extra keys:
{
  "opportunities": [
    {
      "title": "string",
      "description": "string",
      "score": 8,
      "reasoning": "string",
      "contradictions": "string or null",
      "theme_ids": ["uuid", ...],
      "chunk_ids": ["uuid", ...]
    }
  ]
}

Hard rules:
- theme_ids and chunk_ids must be real UUIDs from the provided input
- Score must reflect evidence strength; do not over-inflate weak signals
- Opportunities must be ranked in descending score order in the output list
- If the evidence cannot support a well-grounded opportunity, do not include it"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Rough character budget: 4 chars ≈ 1 token; leave room for system + output
_MAX_CHARS_PER_BATCH = 60_000 * 4  # ~60k tokens of context per batch


def _batch_chunks(chunks: list[dict]) -> list[list[dict]]:
    """Split chunks into batches that fit within the context budget."""
    batches: list[list[dict]] = []
    current: list[dict] = []
    current_chars = 0

    for chunk in chunks:
        cost = len(chunk.get("content", "")) + 120  # overhead for id lines
        if current_chars + cost > _MAX_CHARS_PER_BATCH and current:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(chunk)
        current_chars += cost

    if current:
        batches.append(current)

    return batches


def _parse_json_response(text: str) -> dict:
    """Extract a JSON object from a model response, handling markdown fences."""
    # Strip ```json … ``` or ``` … ``` fences
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fence_match:
        return json.loads(fence_match.group(1))

    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Last resort: find the outermost { … }
    brace_match = re.search(r"\{[\s\S]+\}", text)
    if brace_match:
        return json.loads(brace_match.group(0))

    raise ValueError(f"Could not parse JSON from model response:\n{text[:500]}")


def _fetch_project_source_ids(
    project_id: str, source_ids: list[str] | None
) -> list[str]:
    """Return source IDs for a project, optionally intersected with a provided list."""
    db = get_supabase()
    resp = db.table("sources").select("id").eq("project_id", project_id).execute()
    project_source_ids = [r["id"] for r in (resp.data or [])]

    if source_ids:
        allowed = set(source_ids)
        project_source_ids = [sid for sid in project_source_ids if sid in allowed]

    return project_source_ids


def _fetch_chunks_for_sources(source_ids: list[str]) -> list[dict]:
    """Fetch all chunk rows for the given source IDs, ordered for determinism."""
    if not source_ids:
        return []
    db = get_supabase()
    resp = (
        db.table("chunks")
        .select("id, source_id, content, chunk_index")
        .in_("source_id", source_ids)
        .order("source_id")
        .order("chunk_index")
        .execute()
    )
    return resp.data or []


def _build_chunk_block(chunks: list[dict]) -> str:
    """Format a list of chunks into a readable evidence block for prompts."""
    parts = []
    for chunk in chunks:
        parts.append(
            f"chunk_id: {chunk['id']}\n"
            f"source_id: {chunk['source_id']}\n"
            f"content: {chunk['content']}"
        )
    return ("\n\n" + "-" * 60 + "\n\n").join(parts)


# ---------------------------------------------------------------------------
# Pass 1: Theme extraction
# ---------------------------------------------------------------------------

def run_theme_extraction(
    project_id: str,
    synthesis_id: str,
    source_ids: list[str] | None = None,
) -> list[dict]:
    """Extract themes from research chunks using the fast model (Pass 1).

    Args:
        project_id:   Project UUID.
        synthesis_id: Pre-created synthesis record UUID.
        source_ids:   Optional subset of source UUIDs to restrict extraction.

    Returns:
        List of persisted theme dicts (with their new DB-assigned `id`s).

    Raises:
        ValueError: If no chunks are available.
    """
    # -- Fetch chunks --
    valid_source_ids = _fetch_project_source_ids(project_id, source_ids)
    chunks = _fetch_chunks_for_sources(valid_source_ids)
    if not chunks:
        raise ValueError(
            "No chunks found. Process at least one source document before extracting themes."
        )

    llm = get_fast_llm()
    batches = _batch_chunks(chunks)
    all_raw_themes: list[dict] = []

    # -- Per-batch extraction --
    for batch_idx, batch in enumerate(batches):
        chunk_block = _build_chunk_block(batch)
        user_message = (
            f"Research chunks (batch {batch_idx + 1}/{len(batches)}, "
            f"{len(batch)} chunks) for project {project_id}:\n\n"
            f"{chunk_block}\n\n"
            f"Extract the key themes from this research."
        )
        response = llm.invoke([
            SystemMessage(content=_THEME_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ])
        parsed = _parse_json_response(response.content)
        all_raw_themes.extend(parsed.get("themes", []))

    # -- Consolidation pass when multiple batches produced themes --
    if len(batches) > 1 and all_raw_themes:
        consolidation_message = (
            f"Consolidate the following {len(all_raw_themes)} themes extracted from "
            f"{len(batches)} batches of the same project. Merge duplicates.\n\n"
            f"Themes:\n{json.dumps(all_raw_themes, indent=2)}"
        )
        response = llm.invoke([
            SystemMessage(content=_THEME_CONSOLIDATION_PROMPT),
            HumanMessage(content=consolidation_message),
        ])
        parsed = _parse_json_response(response.content)
        all_raw_themes = parsed.get("themes", [])

    if not all_raw_themes:
        return []

    # -- Persist themes --
    db = get_supabase()
    theme_rows = [
        {
            "project_id": project_id,
            "synthesis_id": synthesis_id,
            "title": t.get("title", "Untitled Theme"),
            "description": t.get("description", ""),
            "chunk_ids": t.get("chunk_ids", []),
            "quotes": t.get("quotes", []),
            "metadata": {},
        }
        for t in all_raw_themes
    ]
    result = db.table("themes").insert(theme_rows).execute()
    return result.data or []


# ---------------------------------------------------------------------------
# Pass 2: Opportunity scoring
# ---------------------------------------------------------------------------

def run_opportunity_scoring(
    project_id: str,
    synthesis_id: str,
    theme_ids: list[str] | None = None,
) -> list[dict]:
    """Generate and score product opportunities from themes (Pass 2).

    Args:
        project_id:   Project UUID.
        synthesis_id: Synthesis record UUID (to scope themes).
        theme_ids:    Optional subset of theme UUIDs to include.

    Returns:
        List of persisted opportunity dicts (with their new DB-assigned `id`s).

    Raises:
        ValueError: If no themes are found.
    """
    db = get_supabase()

    # -- Fetch themes --
    themes_q = (
        db.table("themes")
        .select("id, title, description, chunk_ids, quotes")
        .eq("synthesis_id", synthesis_id)
    )
    if theme_ids:
        themes_q = themes_q.in_("id", theme_ids)
    themes_resp = themes_q.execute()
    themes = themes_resp.data or []

    if not themes:
        raise ValueError(
            "No themes found for this synthesis. Run theme extraction (Pass 1) first."
        )

    # -- Collect supporting chunk IDs referenced by all themes --
    all_chunk_ids: list[str] = []
    for theme in themes:
        all_chunk_ids.extend(theme.get("chunk_ids") or [])
    all_chunk_ids = list(dict.fromkeys(all_chunk_ids))  # deduplicate, preserve order

    # -- Fetch supporting chunks --
    chunks_by_id: dict[str, dict] = {}
    if all_chunk_ids:
        chunks_resp = (
            db.table("chunks")
            .select("id, source_id, content")
            .in_("id", all_chunk_ids)
            .execute()
        )
        chunks_by_id = {c["id"]: c for c in (chunks_resp.data or [])}

    # -- Build prompt context --
    themes_block = json.dumps(
        [
            {
                "theme_id": t["id"],
                "title": t["title"],
                "description": t["description"],
                "quotes": t.get("quotes") or [],
            }
            for t in themes
        ],
        indent=2,
    )

    chunk_block = _build_chunk_block(list(chunks_by_id.values()))

    user_message = (
        f"Project: {project_id}\n\n"
        f"Themes from user research:\n{themes_block}\n\n"
        f"Supporting evidence chunks:\n\n{chunk_block}\n\n"
        f"Generate a prioritized list of product opportunities based on this research."
    )

    # -- Generate with strong model --
    response = get_strong_llm().invoke([
        SystemMessage(content=_OPPORTUNITY_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ])

    parsed = _parse_json_response(response.content)
    opportunities = parsed.get("opportunities", [])

    if not opportunities:
        return []

    # -- Persist opportunities --
    opp_rows = [
        {
            "project_id": project_id,
            "synthesis_id": synthesis_id,
            "title": opp.get("title", "Untitled Opportunity"),
            "description": opp.get("description", ""),
            "score": int(opp.get("score", 5)),
            "reasoning": opp.get("reasoning", ""),
            "contradictions": opp.get("contradictions") or None,
            "theme_ids": opp.get("theme_ids") or [],
            "chunk_ids": opp.get("chunk_ids") or [],
            "metadata": {},
        }
        for opp in opportunities
    ]
    result = db.table("opportunities").insert(opp_rows).execute()
    return result.data or []
