"""Context pack assembly with compact always-on index + on-demand evidence."""

from backend.db.supabase_client import get_supabase
from backend.services.hybrid_search import hybrid_search_chunks, hybrid_search_memory_items


def _estimate_tokens(payload: dict) -> int:
    return max(1, len(str(payload)) // 4)


def get_context_pack(project_id: str, task_type: str, query: str, budget_tokens: int = 2500) -> dict:
    db = get_supabase()

    index_rows = (
        db.table("memory_items")
        .select("id, content")
        .eq("project_id", project_id)
        .eq("type", "index")
        .is_("effective_to", "null")
        .order("updated_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    index_text = index_rows[0]["content"] if index_rows else ""

    memory_candidates = hybrid_search_memory_items(project_id=project_id, query=query, match_count=24)
    filtered_memory = [
        m
        for m in memory_candidates
        if m.get("type") in {"constraint", "decision", "metric", "persona", "glossary", "snapshot", "theme_taxonomy"}
    ][:12]

    chunk_candidates = hybrid_search_chunks(project_id=project_id, query=query, match_count=30)
    seen_sources: set[str] = set()
    evidence_chunks: list[dict] = []
    for row in chunk_candidates:
        src = row.get("source_id")
        if src in seen_sources:
            continue
        evidence_chunks.append(row)
        seen_sources.add(src)
        if len(evidence_chunks) >= 10:
            break

    pack = {
        "index": index_text,
        "memory_items": [
            {
                "id": m["id"],
                "type": m.get("type"),
                "title": m.get("title"),
                "content": m.get("content"),
                "tags": m.get("tags") or [],
                "authority": m.get("authority", 0),
                "evidence_chunk_ids": m.get("evidence_chunk_ids") or [],
            }
            for m in filtered_memory
        ],
        "evidence_chunks": [
            {
                "chunk_id": c.get("chunk_id"),
                "source_id": c.get("source_id"),
                "content": c.get("content"),
                "combined_score": c.get("combined_score"),
                "semantic_score": c.get("semantic_score"),
                "keyword_score": c.get("keyword_score"),
            }
            for c in evidence_chunks
        ],
    }
    pack["citations"] = {
        "memory_item_ids": [m["id"] for m in pack["memory_items"]],
        "chunk_ids": [c["chunk_id"] for c in pack["evidence_chunks"]],
    }

    while _estimate_tokens(pack) > budget_tokens and pack["evidence_chunks"]:
        pack["evidence_chunks"].pop()
        pack["citations"]["chunk_ids"] = [c["chunk_id"] for c in pack["evidence_chunks"]]

    while _estimate_tokens(pack) > budget_tokens and pack["memory_items"]:
        pack["memory_items"].pop()
        pack["citations"]["memory_item_ids"] = [m["id"] for m in pack["memory_items"]]

    token_estimate = _estimate_tokens(pack)

    db.table("context_packs").insert(
        {
            "project_id": project_id,
            "task_type": task_type,
            "query": query,
            "packed_json": pack,
            "token_estimate": token_estimate,
        }
    ).execute()

    return pack
