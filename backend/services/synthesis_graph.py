"""LangGraph synthesis pipeline — stateful, recursive theme extraction + opportunity scoring.

Improvements over the original linear two-pass pipeline:

  Recursive evidence drilling
    After theme extraction, weak themes (< 2 supporting chunks) trigger a
    targeted semantic search for additional evidence. The graph loops back
    through extraction with the expanded chunk set — up to max_iterations times.

  Stateful graph
    LangGraph tracks the full state across nodes, making intermediate results
    inspectable and the pipeline resumable.

  Structured node separation
    Each concern (fetch, extract, evaluate, drill-down, persist, score) is an
    isolated node, making the pipeline easy to extend (e.g. add a "validate
    opportunities" node, or swap in a different model per node).

Graph topology:

    fetch_chunks
         │
    extract_themes ◄────────────────────┐
         │                              │
    evaluate_themes                 drill_down
         │                              │
    [weak themes AND iterations left?]──┘
         │ [no more weak themes OR max iterations reached]
    persist_themes
         │
    score_opportunities
         │
        END
"""

import json
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from backend.db.supabase_client import get_supabase
from backend.services.llm import get_fast_llm, get_strong_llm
from backend.services.semantic_search import semantic_search
from backend.services.synthesis import (
    _OPPORTUNITY_SYSTEM_PROMPT,
    _THEME_CONSOLIDATION_PROMPT,
    _THEME_SYSTEM_PROMPT,
    _batch_chunks,
    _build_chunk_block,
    _fetch_chunks_for_sources,
    _fetch_project_source_ids,
    _parse_json_response,
)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class SynthesisState(TypedDict):
    project_id: str
    synthesis_id: str
    source_ids: list[str] | None
    # Chunk pool — grows during drill-down passes
    chunks: list[dict]
    chunk_id_set: list[str]          # parallel list of IDs (avoids set serialisation issues)
    # Pipeline outputs
    themes: list[dict]               # raw themes during extraction; DB-persisted after persist_themes
    opportunities: list[dict]        # DB-persisted after score_opportunities
    # Control flow
    iteration: int
    max_iterations: int
    weak_theme_titles: list[str]     # titles of themes that need more evidence


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def fetch_chunks_node(state: SynthesisState) -> dict:
    """Load all chunks for the project from Supabase."""
    valid_source_ids = _fetch_project_source_ids(state["project_id"], state["source_ids"])
    chunks = _fetch_chunks_for_sources(valid_source_ids)
    if not chunks:
        raise ValueError(
            "No chunks found. Process at least one source document before running synthesis."
        )
    return {
        "chunks": chunks,
        "chunk_id_set": [c["id"] for c in chunks],
    }


def extract_themes_node(state: SynthesisState) -> dict:
    """Run batched theme extraction on the current chunk pool (fast model).

    On drill-down iterations (iteration > 0), existing theme titles are passed
    as context so the model extends rather than duplicates known themes.
    """
    llm = get_fast_llm()
    chunks = state["chunks"]
    batches = _batch_chunks(chunks)
    all_raw_themes: list[dict] = []

    for batch_idx, batch in enumerate(batches):
        chunk_block = _build_chunk_block(batch)

        # On subsequent iterations, tell the model what we already found
        context_note = ""
        if state["themes"] and state["iteration"] > 0:
            existing_titles = [t.get("title", "") for t in state["themes"]]
            context_note = (
                f"\nAlready-identified themes (extend or refine; do not duplicate):\n"
                f"{json.dumps(existing_titles, indent=2)}\n\n"
            )

        user_message = (
            f"Research chunks (batch {batch_idx + 1}/{len(batches)}, "
            f"{len(batch)} chunks) for project {state['project_id']}:{context_note}\n\n"
            f"{chunk_block}\n\n"
            f"Extract the key themes from this research."
        )
        response = llm.invoke([
            SystemMessage(content=_THEME_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ])
        parsed = _parse_json_response(response.content)
        all_raw_themes.extend(parsed.get("themes", []))

    # Consolidation pass when multiple batches produced themes
    if len(batches) > 1 and all_raw_themes:
        consolidation_message = (
            f"Consolidate the following {len(all_raw_themes)} themes from "
            f"{len(batches)} batches of the same project. Merge duplicates.\n\n"
            f"Themes:\n{json.dumps(all_raw_themes, indent=2)}"
        )
        response = llm.invoke([
            SystemMessage(content=_THEME_CONSOLIDATION_PROMPT),
            HumanMessage(content=consolidation_message),
        ])
        parsed = _parse_json_response(response.content)
        all_raw_themes = parsed.get("themes", [])

    return {"themes": all_raw_themes}


def evaluate_themes_node(state: SynthesisState) -> dict:
    """Identify themes with weak evidence (fewer than 2 supporting chunks).

    These will trigger a drill-down pass to find additional supporting evidence
    before moving on to opportunity scoring.
    """
    weak_titles = [
        t.get("title", "")
        for t in state["themes"]
        if len(t.get("chunk_ids", [])) < 2
    ]
    return {"weak_theme_titles": weak_titles}


def drill_down_node(state: SynthesisState) -> dict:
    """For each weak theme, semantically search for additional supporting chunks.

    Uses the theme title + description as a semantic query against all project
    chunks already stored in pgvector.  New (unseen) chunks are added to the
    pool; the graph then loops back to extract_themes with the richer corpus.
    """
    new_chunks = list(state["chunks"])
    existing_ids = set(state["chunk_id_set"])

    for theme in state["themes"]:
        title = theme.get("title", "")
        if title not in state["weak_theme_titles"]:
            continue

        # Build a focused query from the theme title + description
        description = theme.get("description", "")
        query = f"{title}: {description}".strip(": ")

        candidates = semantic_search(
            project_id=state["project_id"],
            query=query,
            match_count=10,
        )

        for match in candidates:
            chunk_id = match["chunk_id"]
            if chunk_id not in existing_ids:
                new_chunks.append(
                    {
                        "id": chunk_id,
                        "source_id": match["source_id"],
                        "content": match["content"],
                        "chunk_index": 0,
                    }
                )
                existing_ids.add(chunk_id)

    return {
        "chunks": new_chunks,
        "chunk_id_set": list(existing_ids),
        "iteration": state["iteration"] + 1,
    }


def persist_themes_node(state: SynthesisState) -> dict:
    """Write finalised themes to Supabase and return them with DB-assigned IDs."""
    if not state["themes"]:
        return {"themes": []}

    db = get_supabase()
    theme_rows = [
        {
            "project_id": state["project_id"],
            "synthesis_id": state["synthesis_id"],
            "title": t.get("title", "Untitled Theme"),
            "description": t.get("description", ""),
            "chunk_ids": t.get("chunk_ids", []),
            "quotes": t.get("quotes", []),
            "metadata": {"drill_down_iterations": state["iteration"]},
        }
        for t in state["themes"]
    ]
    result = db.table("themes").insert(theme_rows).execute()
    return {"themes": result.data or []}


def score_opportunities_node(state: SynthesisState) -> dict:
    """Generate and rank product opportunities from persisted themes (strong model).

    Mirrors the original Pass 2 logic but operates on the LangGraph state so
    it inherits any extra chunks found during drill-down.
    """
    themes = state["themes"]
    if not themes:
        return {"opportunities": []}

    # Collect chunk IDs referenced by all themes
    all_chunk_ids = list(
        dict.fromkeys(cid for t in themes for cid in (t.get("chunk_ids") or []))
    )

    chunks_by_id: dict[str, dict] = {}
    if all_chunk_ids:
        db = get_supabase()
        resp = (
            db.table("chunks")
            .select("id, source_id, content")
            .in_("id", all_chunk_ids)
            .execute()
        )
        chunks_by_id = {c["id"]: c for c in (resp.data or [])}

    themes_block = json.dumps(
        [
            {
                "theme_id": t.get("id", t.get("title")),
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
        f"Project: {state['project_id']}\n\n"
        f"Themes from user research:\n{themes_block}\n\n"
        f"Supporting evidence chunks:\n\n{chunk_block}\n\n"
        f"Generate a prioritized list of product opportunities based on this research."
    )

    response = get_strong_llm().invoke([
        SystemMessage(content=_OPPORTUNITY_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ])
    parsed = _parse_json_response(response.content)
    opportunities_raw = parsed.get("opportunities", [])

    if not opportunities_raw:
        return {"opportunities": []}

    db = get_supabase()
    opp_rows = [
        {
            "project_id": state["project_id"],
            "synthesis_id": state["synthesis_id"],
            "title": opp.get("title", "Untitled Opportunity"),
            "description": opp.get("description", ""),
            "score": int(opp.get("score", 5)),
            "reasoning": opp.get("reasoning", ""),
            "contradictions": opp.get("contradictions") or None,
            "theme_ids": opp.get("theme_ids") or [],
            "chunk_ids": opp.get("chunk_ids") or [],
            "metadata": {"graph_iterations": state["iteration"]},
        }
        for opp in opportunities_raw
    ]
    result = db.table("opportunities").insert(opp_rows).execute()
    return {"opportunities": result.data or []}


# ---------------------------------------------------------------------------
# Conditional routing
# ---------------------------------------------------------------------------

def _route_after_evaluation(state: SynthesisState) -> str:
    """Drill down if there are weak themes and we haven't hit the iteration cap."""
    if state["weak_theme_titles"] and state["iteration"] < state["max_iterations"]:
        return "drill_down"
    return "persist_themes"


# ---------------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------------

def _build_graph() -> object:
    workflow = StateGraph(SynthesisState)

    workflow.add_node("fetch_chunks", fetch_chunks_node)
    workflow.add_node("extract_themes", extract_themes_node)
    workflow.add_node("evaluate_themes", evaluate_themes_node)
    workflow.add_node("drill_down", drill_down_node)
    workflow.add_node("persist_themes", persist_themes_node)
    workflow.add_node("score_opportunities", score_opportunities_node)

    workflow.set_entry_point("fetch_chunks")
    workflow.add_edge("fetch_chunks", "extract_themes")
    workflow.add_edge("extract_themes", "evaluate_themes")
    workflow.add_conditional_edges(
        "evaluate_themes",
        _route_after_evaluation,
        {
            "drill_down": "drill_down",
            "persist_themes": "persist_themes",
        },
    )
    workflow.add_edge("drill_down", "extract_themes")   # ← recursive loop
    workflow.add_edge("persist_themes", "score_opportunities")
    workflow.add_edge("score_opportunities", END)

    return workflow.compile()


_graph = _build_graph()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_synthesis_graph(
    project_id: str,
    synthesis_id: str,
    source_ids: list[str] | None = None,
    max_iterations: int = 2,
) -> dict:
    """Run the full LangGraph synthesis pipeline.

    Args:
        project_id:      Project UUID.
        synthesis_id:    Pre-created synthesis record UUID.
        source_ids:      Optional subset of source UUIDs.
        max_iterations:  Max recursive drill-down passes for weak themes.

    Returns:
        {
          "themes": [...],          # DB-persisted theme records
          "opportunities": [...],   # DB-persisted opportunity records
          "iterations": int,        # actual drill-down iterations performed
        }
    """
    initial_state: SynthesisState = {
        "project_id": project_id,
        "synthesis_id": synthesis_id,
        "source_ids": source_ids,
        "chunks": [],
        "chunk_id_set": [],
        "themes": [],
        "opportunities": [],
        "iteration": 0,
        "max_iterations": max_iterations,
        "weak_theme_titles": [],
    }

    final_state = _graph.invoke(initial_state)

    return {
        "themes": final_state["themes"],
        "opportunities": final_state["opportunities"],
        "iterations": final_state["iteration"],
    }
