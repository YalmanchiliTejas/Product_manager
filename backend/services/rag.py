"""RAG (Retrieval-Augmented Generation) pipeline.

Steps:
  1. Memory recall   — if user_id is provided, retrieve relevant PM memories
                       from past sessions and inject them as context
  2. Semantic search — embed query, retrieve top-k chunks via pgvector
  3. Context assembly— format memory + chunks into a grounded evidence block
  4. Generate        — call the configured strong LLM with strict citation instructions
  5. Post-process    — extract cited chunk IDs from the response text
  6. Memory store    — distil the conversation exchange into persistent memories
                       for future sessions (only when user_id is provided)

The LLM is selected via the LLM_PROVIDER env var — no Anthropic-specific code here.

Returns:
    {
      "answer": str,
      "cited_chunk_ids": [str, ...],
      "retrieved_chunks": [{chunk_id, source_id, similarity, content_preview}, ...],
      "usage": {input_tokens, output_tokens}
    }
"""

import re

from langchain_core.messages import HumanMessage, SystemMessage

from backend.services.llm import get_strong_llm
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
    user_id: str | None = None,
    conversation_history: list[dict] | None = None,
    match_count: int = 8,
    source_types: list[str] | None = None,
    segment_tags: list[str] | None = None,
) -> dict:
    """Full RAG pipeline: memory recall → retrieve → augment → generate → remember.

    Args:
        project_id:           Project UUID to search within.
        query:                User question.
        user_id:              PM user UUID. When provided:
                              - Relevant memories from past sessions are injected.
                              - This exchange is stored as memories for the future.
        conversation_history: Prior turns as [{"role": "user"|"assistant", "content": str}].
        match_count:          Max chunks to retrieve (1–50).
        source_types:         Optional source type filter.
        segment_tags:         Optional segment tag filter.

    Returns:
        Dict with answer, citations, retrieved chunk metadata, and token usage.
    """
    # ------------------------------------------------------------------
    # 1. Retrieve relevant memories from past sessions
    # ------------------------------------------------------------------
    memory_context = ""
    if user_id:
        try:
            from backend.services.memory import search_memories
            memories = search_memories(query, project_id, user_id, limit=4)
            if memories:
                memory_lines = "\n".join(f"- {m['memory']}" for m in memories)
                memory_context = (
                    f"Relevant PM knowledge from past sessions:\n{memory_lines}\n\n"
                )
        except Exception:
            pass  # Memory retrieval failures must not break the RAG response

    # ------------------------------------------------------------------
    # 2. Retrieve relevant chunks via semantic search
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
    # 3. Build the evidence block (memory context + retrieved chunks)
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
        f"{memory_context}"
        f"Research evidence ({len(chunks)} chunks):\n"
        f"{evidence_block}\n\n"
        f"{'=' * 60}\n\n"
        f"Question: {query}"
    )

    # ------------------------------------------------------------------
    # 4. Build message list (prepend history, append augmented question)
    # ------------------------------------------------------------------
    lc_messages = [SystemMessage(content=_RAG_SYSTEM_PROMPT)]
    if conversation_history:
        for msg in conversation_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                from langchain_core.messages import AIMessage
                lc_messages.append(AIMessage(content=content))
    lc_messages.append(HumanMessage(content=augmented_user_message))

    # ------------------------------------------------------------------
    # 5. Generate with the configured strong LLM (provider-agnostic)
    # ------------------------------------------------------------------
    response = get_strong_llm().invoke(lc_messages)
    answer: str = response.content

    # ------------------------------------------------------------------
    # 6. Extract cited chunk IDs (UUIDs appearing after "chunk_id:")
    # ------------------------------------------------------------------
    uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    cited_ids = list(
        dict.fromkeys(
            re.findall(
                rf"chunk_id[:\s]+({uuid_pattern})",
                answer,
                re.IGNORECASE,
            )
        )
    )

    # ------------------------------------------------------------------
    # 7. Normalise usage metadata (provider-agnostic)
    # ------------------------------------------------------------------
    usage_meta = response.usage_metadata or {}
    usage = {
        "input_tokens": usage_meta.get("input_tokens", 0),
        "output_tokens": usage_meta.get("output_tokens", 0),
    }

    # ------------------------------------------------------------------
    # 8. Store this exchange as persistent memory for future sessions
    # ------------------------------------------------------------------
    if user_id:
        try:
            from backend.services.memory import add_memories
            exchange = (conversation_history or []) + [
                {"role": "user", "content": query},
                {"role": "assistant", "content": answer},
            ]
            add_memories(exchange, project_id, user_id)
        except Exception:
            pass  # Memory storage failures must not affect the response

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
        "usage": usage,
    }
