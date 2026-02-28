"""LangGraph workflow for incremental memory refresh."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.graph import END, StateGraph

from backend.db.supabase_client import get_supabase
from backend.services.ingestion import run_ingestion_pipeline
from backend.services.memory_index import rebuild_index_memory


class MemoryState(TypedDict, total=False):
    project_id: str
    run_type: str
    changed_sources: list[dict]
    changed_sources_count: int
    memory_items_created: int
    conflicts_found: int
    snapshot_id: str
    status: str


def _normalized_hash(text: str | None) -> str:
    normalized = (text or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def detect_changed_sources(state: MemoryState) -> MemoryState:
    db = get_supabase()
    project_id = state["project_id"]
    sources = (
        db.table("sources")
        .select("id, raw_content, content_hash, updated_at")
        .eq("project_id", project_id)
        .execute()
        .data
        or []
    )
    changed = []
    for src in sources:
        new_hash = _normalized_hash(src.get("raw_content"))
        if new_hash != (src.get("content_hash") or ""):
            changed.append({"id": src["id"], "content_hash": new_hash})
    state["changed_sources"] = changed
    state["changed_sources_count"] = len(changed)
    return state


def rechunk_reembed(state: MemoryState) -> MemoryState:
    db = get_supabase()
    for src in state.get("changed_sources", []):
        run_ingestion_pipeline(src["id"])
        db.table("sources").update(
            {"content_hash": src["content_hash"], "last_ingested_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", src["id"]).execute()
    return state


def extract_memory_items(state: MemoryState) -> MemoryState:
    db = get_supabase()
    project_id = state["project_id"]
    created = 0
    for src in state.get("changed_sources", []):
        chunks = (
            db.table("chunks")
            .select("id, content")
            .eq("source_id", src["id"])
            .limit(20)
            .execute()
            .data
            or []
        )
        for chunk in chunks:
            content = chunk.get("content", "")
            lower = content.lower()
            inferred_type = None
            if "must" in lower or "constraint" in lower:
                inferred_type = "constraint"
            elif "decide" in lower or "decision" in lower:
                inferred_type = "decision"
            elif "metric" in lower or "kpi" in lower:
                inferred_type = "metric"
            elif "persona" in lower:
                inferred_type = "persona"
            if not inferred_type:
                continue
            title = content.split(".")[0][:120] or f"{inferred_type} from {src['id']}"
            db.table("memory_items").insert(
                {
                    "project_id": project_id,
                    "type": inferred_type,
                    "title": title,
                    "content": content[:2000],
                    "authority": 1,
                    "evidence_chunk_ids": [chunk["id"]],
                    "metadata": {"source_id": src["id"], "extracted_by": "memory_update_graph"},
                }
            ).execute()
            created += 1
    state["memory_items_created"] = created
    return state


def consolidate_and_supersede(state: MemoryState) -> MemoryState:
    db = get_supabase()
    project_id = state["project_id"]
    rows = (
        db.table("memory_items")
        .select("id, type, title, content, supersedes_id")
        .eq("project_id", project_id)
        .is_("effective_to", "null")
        .in_("type", ["decision", "constraint"])
        .order("created_at", desc=False)
        .execute()
        .data
        or []
    )

    seen: dict[tuple[str, str], dict] = {}
    conflicts = 0
    for row in rows:
        key = (row["type"], row["title"].strip().lower())
        if key not in seen:
            seen[key] = row
            continue
        prior = seen[key]
        if prior["content"].strip() == row["content"].strip():
            db.table("memory_items").update(
                {"effective_to": datetime.now(timezone.utc).isoformat(), "supersedes_id": prior["id"]}
            ).eq("id", row["id"]).execute()
        elif not row.get("supersedes_id") and not prior.get("supersedes_id"):
            conflicts += 1
    state["conflicts_found"] = conflicts
    return state


def write_weekly_snapshot(state: MemoryState) -> MemoryState:
    db = get_supabase()
    project_id = state["project_id"]
    active = (
        db.table("memory_items")
        .select("id, type, title")
        .eq("project_id", project_id)
        .is_("effective_to", "null")
        .in_("type", ["constraint", "decision", "metric", "persona"])
        .limit(100)
        .execute()
        .data
        or []
    )
    snapshot_body = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "constraint": len([r for r in active if r["type"] == "constraint"]),
            "decision": len([r for r in active if r["type"] == "decision"]),
            "metric": len([r for r in active if r["type"] == "metric"]),
            "persona": len([r for r in active if r["type"] == "persona"]),
        },
        "items": active[:25],
    }
    ins = (
        db.table("memory_items")
        .insert(
            {
                "project_id": project_id,
                "type": "snapshot",
                "title": f"Weekly snapshot {datetime.now(timezone.utc).date().isoformat()}",
                "content": json.dumps(snapshot_body),
                "authority": 5,
                "metadata": {"run_type": state.get("run_type", "weekly_snapshot")},
            }
        )
        .execute()
    )
    state["snapshot_id"] = ins.data[0]["id"]
    return state


def rebuild_index(state: MemoryState) -> MemoryState:
    rebuild_index_memory(state["project_id"])
    return state


def validations(state: MemoryState) -> MemoryState:
    state["status"] = "ok" if state.get("conflicts_found", 0) == 0 else "warning"
    return state


def build_graph():
    graph = StateGraph(MemoryState)
    graph.add_node("detect_changed_sources", detect_changed_sources)
    graph.add_node("rechunk_reembed", rechunk_reembed)
    graph.add_node("extract_memory_items", extract_memory_items)
    graph.add_node("consolidate_and_supersede", consolidate_and_supersede)
    graph.add_node("write_weekly_snapshot", write_weekly_snapshot)
    graph.add_node("rebuild_index_memory", rebuild_index)
    graph.add_node("validations", validations)

    graph.set_entry_point("detect_changed_sources")
    graph.add_edge("detect_changed_sources", "rechunk_reembed")
    graph.add_edge("rechunk_reembed", "extract_memory_items")
    graph.add_edge("extract_memory_items", "consolidate_and_supersede")
    graph.add_edge("consolidate_and_supersede", "write_weekly_snapshot")
    graph.add_edge("write_weekly_snapshot", "rebuild_index_memory")
    graph.add_edge("rebuild_index_memory", "validations")
    graph.add_edge("validations", END)
    return graph.compile()


def run_memory_update(project_id: str, run_type: str = "manual_rebuild") -> dict:
    app = build_graph()
    result = app.invoke({"project_id": project_id, "run_type": run_type})

    db = get_supabase()
    db.table("memory_runs").insert(
        {
            "project_id": project_id,
            "run_type": run_type,
            "stats": {
                "changed_sources_count": result.get("changed_sources_count", 0),
                "memory_items_created": result.get("memory_items_created", 0),
                "conflicts_found": result.get("conflicts_found", 0),
                "snapshot_id": result.get("snapshot_id"),
            },
            "status": result.get("status", "ok"),
        }
    ).execute()

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run memory update graph")
    parser.add_argument("project_id")
    parser.add_argument("--run-type", default="manual_rebuild")
    args = parser.parse_args()
    print(json.dumps(run_memory_update(args.project_id, args.run_type), indent=2))
