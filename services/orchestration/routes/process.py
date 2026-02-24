"""
POST /process

Chunks a source document, embeds each chunk, and stores them in Supabase.
This is the ingestion pipeline — must be called after a source is created.

Body: { "source_id": "<uuid>" }
Returns: { "source_id": "...", "chunk_count": N }
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.orchestration.db import get_supabase, run_sync
from services.orchestration.llm.provider import aembed, to_pgvector_literal

router = APIRouter()


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 150) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    chunks: list[str] = []
    cursor = 0
    while cursor < len(normalized):
        end = min(cursor + chunk_size, len(normalized))
        chunks.append(normalized[cursor:end])
        if end >= len(normalized):
            break
        cursor = max(end - overlap, cursor + 1)
    return chunks


class ProcessBody(BaseModel):
    source_id: str


@router.post("/process")
async def process_source(body: ProcessBody):
    supabase = get_supabase()
    source_id = body.source_id.strip()

    # ── Fetch source ──────────────────────────────────────────────────────
    result = await run_sync(
        lambda: supabase.from_("sources")
        .select("id, project_id, raw_content, file_path, metadata")
        .eq("id", source_id)
        .maybe_single()
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Source not found.")

    source = result.data

    # ── Extract text ──────────────────────────────────────────────────────
    raw_content: str | None = source.get("raw_content")
    if not raw_content or not raw_content.strip():
        raise HTTPException(
            status_code=400,
            detail="Source has no raw_content. Provide text when creating the source.",
        )

    # ── Chunk ─────────────────────────────────────────────────────────────
    chunks = chunk_text(raw_content)
    if not chunks:
        raise HTTPException(status_code=400, detail="No text content found after chunking.")

    # ── Delete existing chunks for idempotency ────────────────────────────
    await run_sync(
        lambda: supabase.from_("chunks").delete().eq("source_id", source_id).execute()
    )

    # ── Embed sequentially to respect rate limits ─────────────────────────
    chunk_rows = []
    for idx, content in enumerate(chunks):
        vector = await aembed(content)
        chunk_rows.append(
            {
                "source_id": source["id"],
                "project_id": source["project_id"],
                "content": content,
                "chunk_index": idx,
                "embedding": to_pgvector_literal(vector),
                "metadata": source.get("metadata") or {},
            }
        )

    # ── Insert in batches of 100 ──────────────────────────────────────────
    BATCH = 100
    for i in range(0, len(chunk_rows), BATCH):
        batch = chunk_rows[i : i + BATCH]
        await run_sync(lambda b=batch: supabase.from_("chunks").insert(b).execute())

    return {"source_id": source_id, "chunk_count": len(chunks)}
