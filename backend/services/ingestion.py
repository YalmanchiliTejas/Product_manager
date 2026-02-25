"""File processing ingestion pipeline.

Steps:
  1. Fetch source record from Supabase
  2. Extract plain text (raw_content or file_path on disk)
  3. Chunk text into overlapping segments
  4. Embed each chunk concurrently via OpenAI
  5. Delete old chunks for this source
  6. Insert new chunk rows into Supabase

Returns a summary dict: {source_id, chunk_count}.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.config import settings
from backend.db.supabase_client import get_supabase
from backend.services.embeddings import create_embedding, to_pgvector_literal
from backend.services.file_processing import chunk_text, extract_text


def _embed_chunk(item: tuple[int, str]) -> tuple[int, list[float]]:
    """Embed one chunk; returns (index, embedding)."""
    idx, content = item
    embedding = create_embedding(content)
    return idx, embedding


def run_ingestion_pipeline(source_id: str) -> dict:
    """Full extract → chunk → embed → store pipeline for a source.

    Args:
        source_id: UUID of the source row in Supabase.

    Returns:
        {"source_id": str, "chunk_count": int}

    Raises:
        ValueError: if source not found or no text can be extracted.
    """
    db = get_supabase()

    # ------------------------------------------------------------------
    # 1. Fetch source
    # ------------------------------------------------------------------
    resp = (
        db.table("sources")
        .select("id, project_id, source_type, segment_tags, raw_content, file_path, metadata")
        .eq("id", source_id)
        .maybe_single()
        .execute()
    )
    if resp.data is None:
        raise ValueError(f"Source '{source_id}' not found.")
    source = resp.data

    # ------------------------------------------------------------------
    # 2. Extract text
    # ------------------------------------------------------------------
    raw_text = extract_text(
        raw_content=source.get("raw_content"),
        file_path=source.get("file_path"),
    )

    # ------------------------------------------------------------------
    # 3. Chunk
    # ------------------------------------------------------------------
    chunks = chunk_text(raw_text, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        raise ValueError("No text content found after extraction.")

    # ------------------------------------------------------------------
    # 4. Embed concurrently
    # ------------------------------------------------------------------
    embeddings: list[list[float]] = [[] for _ in chunks]
    with ThreadPoolExecutor(max_workers=settings.embed_concurrency) as pool:
        futures = {
            pool.submit(_embed_chunk, (i, content)): i
            for i, content in enumerate(chunks)
        }
        for future in as_completed(futures):
            idx, emb = future.result()
            embeddings[idx] = emb

    # ------------------------------------------------------------------
    # 5. Delete stale chunks
    # ------------------------------------------------------------------
    db.table("chunks").delete().eq("source_id", source_id).execute()

    # ------------------------------------------------------------------
    # 6. Insert new chunks
    # ------------------------------------------------------------------
    base_metadata = {
        "project_id": source["project_id"],
        "source_type": source.get("source_type", "untyped"),
        "segment_tags": source.get("segment_tags") or [],
        **(source.get("metadata") or {}),
    }

    chunk_rows = [
        {
            "source_id": source_id,
            "content": content,
            "chunk_index": idx,
            "embedding": to_pgvector_literal(embeddings[idx]),
            "metadata": base_metadata,
        }
        for idx, content in enumerate(chunks)
    ]

    db.table("chunks").insert(chunk_rows).execute()

    return {"source_id": source_id, "chunk_count": len(chunks)}
