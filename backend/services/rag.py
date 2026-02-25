"""RAG (Retrieval-Augmented Generation) pipeline.

Steps:
  1. Semantic search  — embed query, retrieve top-k chunks via pgvector
  2. Context assembly — format chunks into a grounded evidence block
  3. Generate         — call Anthropic with strict citation instructions
  4. Post-process     — extract cited chunk IDs from the response text

Returns:
    {
      "answer": str,
      "cited_chunk_ids": [str, ...],
      "retrieved_chunks": [{chunk_id, source_id, similarity, content_preview}, ...],
      "usage": {input_tokens, output_tokens}
    }
"""

import re

import anthropic

from backend.config import settings
from backend.services.semantic_search import semantic_search

_RAG_SYSTEM_PROMPT = """\
You are a PM research assistant. Answer questions using ONLY the research chunks provided.

Rules:
- Cite every non-trivial claim with its chunk_id (e.g. "… [chunk_id: <uuid>]").
- Use exact verbatim quotes where the text supports it.
- If the evidence is insufficient or contradictory, say so explicitly and describe \
what additional data would help.
- Do NOT invent information not present in the chunks.
- Keep answers focused and evidence-first."""


def run_rag_pipeline(
    project_id: str,
    query: str,
    conversation_history: list[dict] | None = None,
    match_count: int = 8,
    source_types: list[str] | None = None,
    segment_tags: list[str] | None = None,
) -> dict:
    """Full RAG pipeline: query → embed → retrieve → augment → generate.

    Args:
        project_id:           Project UUID to search within.
        query:                User question.
        conversation_history: Prior turns as [{"role": "user"|"assistant", "content": str}, ...].
        match_count:          Max chunks to retrieve (1–50).
        source_types:         Optional source type filter.
        segment_tags:         Optional segment tag filter.

    Returns:
        Dict with answer, citations, retrieved chunk metadata, and token usage.
    """
    # ------------------------------------------------------------------
    # 1. Retrieve relevant chunks
    # ------------------------------------------------------------------
    chunks = semantic_search(
        project_id=project_id,
        query=query,
        match_count=match_count,
        source_types=source_types,
        segment_tags=segment_tags,
    )

    if not chunks:
        return {
            "answer": (
                "No relevant content found for this project. "
                "Please add and process source documents first."
            ),
            "cited_chunk_ids": [],
            "retrieved_chunks": [],
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }

    # ------------------------------------------------------------------
    # 2. Build the evidence block
    # ------------------------------------------------------------------
    evidence_parts = []
    for i, chunk in enumerate(chunks, start=1):
        evidence_parts.append(
            f"[{i}] chunk_id: {chunk['chunk_id']}\n"
            f"    source_id: {chunk['source_id']}\n"
            f"    similarity: {chunk['similarity']:.3f}\n"
            f"    content:\n{chunk['content']}"
        )
    evidence_block = "\n\n" + ("-" * 60) + "\n\n".join(evidence_parts)

    augmented_user_message = (
        f"Research evidence ({len(chunks)} chunks):\n"
        f"{evidence_block}\n\n"
        f"{'=' * 60}\n\n"
        f"Question: {query}"
    )

    # ------------------------------------------------------------------
    # 3. Build message list (prepend history, append augmented question)
    # ------------------------------------------------------------------
    messages: list[dict] = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": augmented_user_message})

    # ------------------------------------------------------------------
    # 4. Generate with Anthropic
    # ------------------------------------------------------------------
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.strong_model,
        max_tokens=2048,
        system=_RAG_SYSTEM_PROMPT,
        messages=messages,
    )

    answer: str = response.content[0].text

    # ------------------------------------------------------------------
    # 5. Extract cited chunk IDs (UUIDs appearing after "chunk_id:")
    # ------------------------------------------------------------------
    uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    cited_ids = list(
        dict.fromkeys(  # preserves order, deduplicates
            re.findall(
                rf"chunk_id[:\s]+({uuid_pattern})",
                answer,
                re.IGNORECASE,
            )
        )
    )

    return {
        "answer": answer,
        "cited_chunk_ids": cited_ids,
        "retrieved_chunks": [
            {
                "chunk_id": c["chunk_id"],
                "source_id": c["source_id"],
                "similarity": c["similarity"],
                "content_preview": c["content"][:200],
            }
            for c in chunks
        ],
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }
