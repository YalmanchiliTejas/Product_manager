"""pgvector semantic search wrapper.

Calls the `semantic_search_chunks` Postgres function defined in
db/migrations/0001_pgvector_semantic_search.sql via Supabase RPC.

Pipeline: query string → OpenAI embedding → pgvector cosine similarity search.
"""

from backend.db.supabase_client import get_supabase
from backend.services.embeddings import create_embedding, to_pgvector_literal


def semantic_search(
    project_id: str,
    query: str,
    match_count: int = 8,
    source_types: list[str] | None = None,
    segment_tags: list[str] | None = None,
) -> list[dict]:
    """Embed *query* and retrieve the top-k matching chunks for *project_id*.

    Args:
        project_id:   UUID of the project to search within.
        query:        Natural-language query string.
        match_count:  Max number of chunks to return (clamped 1–50).
        source_types: Optional allowlist of source_type values.
        segment_tags: Optional allowlist of segment tags (array overlap filter).

    Returns:
        List of dicts with keys:
            chunk_id, source_id, content, metadata, similarity (0–1 float).
    """
    if not query.strip():
        raise ValueError("query must not be empty.")
    if not project_id.strip():
        raise ValueError("project_id must not be empty.")

    match_count = max(1, min(match_count, 50))

    # Embed the query
    embedding = create_embedding(query)

    # Call pgvector RPC
    db = get_supabase()
    result = db.rpc(
        "semantic_search_chunks",
        {
            "input_project_id": project_id,
            "query_embedding": to_pgvector_literal(embedding),
            "match_count": match_count,
            "filter_source_types": source_types if source_types else None,
            "filter_segment_tags": segment_tags if segment_tags else None,
        },
    ).execute()

    return result.data or []
