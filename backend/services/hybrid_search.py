"""Hybrid retrieval over chunks and memory items."""

from backend.db.supabase_client import get_supabase
from backend.services.embeddings import create_embedding, to_pgvector_literal


def keyword_search_chunks(project_id: str, query: str, match_count: int = 8) -> list[dict]:
    db = get_supabase()
    resp = db.rpc(
        "keyword_search_chunks",
        {
            "input_project_id": project_id,
            "query": query,
            "match_count": max(1, min(match_count, 50)),
        },
    ).execute()
    return resp.data or []


def hybrid_search_chunks(project_id: str, query: str, match_count: int = 12) -> list[dict]:
    embedding = create_embedding(query)
    db = get_supabase()
    resp = db.rpc(
        "hybrid_search_chunks",
        {
            "input_project_id": project_id,
            "query": query,
            "query_embedding": to_pgvector_literal(embedding),
            "match_count": max(1, min(match_count, 50)),
        },
    ).execute()
    return resp.data or []


def hybrid_search_memory_items(project_id: str, query: str, match_count: int = 12) -> list[dict]:
    embedding = create_embedding(query)
    db = get_supabase()

    # vector branch
    vec = (
        db.table("memory_items")
        .select("id, type, title, content, tags, authority, effective_from, effective_to, evidence_chunk_ids, metadata")
        .eq("project_id", project_id)
        .is_("effective_to", "null")
        .not_.is_("embedding", "null")
        .order("embedding", desc=False)
        .limit(max(1, min(match_count, 50)))
        .execute()
    )
    vector_candidates = vec.data or []

    # keyword branch
    kw = (
        db.table("memory_items")
        .select("id, type, title, content, tags, authority, effective_from, effective_to, evidence_chunk_ids, metadata")
        .eq("project_id", project_id)
        .is_("effective_to", "null")
        .or_(f"title.ilike.%{query}%,content.ilike.%{query}%")
        .limit(max(1, min(match_count, 50)))
        .execute()
    )
    keyword_candidates = kw.data or []

    by_id: dict[str, dict] = {}
    for row in vector_candidates + keyword_candidates:
        by_id[row["id"]] = row

    # lightweight in-app relevance boost by authority+recency
    def _score(item: dict) -> float:
        authority = float(item.get("authority") or 0)
        recency = float(str(item.get("effective_from") or "").replace("-", "").replace(":", "").replace("T", "").replace("Z", "")[:8] or 0)
        text = f"{item.get('title', '')} {item.get('content', '')}".lower()
        lexical = 1.0 if query.lower() in text else 0.0
        return (authority * 0.3) + (recency * 0.00000001) + lexical

    ranked = sorted(by_id.values(), key=_score, reverse=True)
    return ranked[: max(1, min(match_count, 50))]
