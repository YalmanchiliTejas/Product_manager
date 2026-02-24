"""
POST /chat/stream

Streaming RAG chat for a conversation. Steps:
  1. Persist user message.
  2. Retrieve conversation + project context.
  3. Embed the user query, run semantic search (RAG).
  4. Pack retrieved chunks into a token-budgeted context block.
  5. Stream a response from the LLM.
  6. Persist the complete assistant message after the stream finishes.

Returns: text/plain stream (plain text deltas, not SSE frames).
The Next.js proxy forwards this stream directly to the browser.
"""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.orchestration.db import get_supabase, run_sync
from services.orchestration.llm.provider import aembed, astream, to_pgvector_literal
from services.orchestration.agent.context_manager import (
    ContextItem,
    estimate_tokens,
    pack_into_context,
    render_context,
)

router = APIRouter()

# ── Constants ─────────────────────────────────────────────────────────────────

RAG_MATCH_COUNT = 12
RAG_TOKEN_BUDGET = 12_000
HISTORY_WINDOW = 20         # max messages from history
SYSTEM_RESERVE = 2_000      # tokens reserved for system prompt
RESPONSE_RESERVE = 2_048    # tokens reserved for assistant response

_CHAT_SYSTEM = """You are Beacon, an AI product research assistant. You help product managers \
analyse customer interviews, support tickets, and other feedback to identify product opportunities.

You have access to relevant excerpts from the project's source documents (provided in CONTEXT below). \
When answering:
- Cite specific quotes and attribute them to their source.
- Be analytical and opinionated — don't just summarise.
- If the evidence is thin or contradictory, say so.
- Link every insight back to customer impact.

Keep responses concise but substantive. Use markdown for structure when helpful."""


class ChatBody(BaseModel):
    conversation_id: str
    content: str


@router.post("/chat/stream")
async def chat_stream(body: ChatBody):
    supabase = get_supabase()
    conversation_id = body.conversation_id.strip()
    user_content = body.content.strip()

    if not user_content:
        raise HTTPException(status_code=400, detail="content is required.")

    # ── Fetch conversation ────────────────────────────────────────────────
    conv_result = await run_sync(
        lambda: supabase.from_("conversations")
        .select("id, project_id")
        .eq("id", conversation_id)
        .maybe_single()
        .execute()
    )
    if not conv_result.data:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    project_id: str = conv_result.data["project_id"]

    # ── Persist user message ──────────────────────────────────────────────
    await run_sync(
        lambda: supabase.from_("messages")
        .insert({"conversation_id": conversation_id, "role": "user", "content": user_content})
        .execute()
    )

    # ── Conversation history ──────────────────────────────────────────────
    history_result = await run_sync(
        lambda: supabase.from_("messages")
        .select("role, content")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=False)
        .limit(HISTORY_WINDOW)
        .execute()
    )
    history: list[dict] = history_result.data or []

    # ── RAG retrieval ─────────────────────────────────────────────────────
    rag_context = ""
    cited_chunk_ids: list[str] = []

    try:
        query_vec = await aembed(user_content)
        vec_literal = to_pgvector_literal(query_vec)

        rag_result = await run_sync(
            lambda: supabase.rpc(
                "semantic_search_chunks",
                {
                    "input_project_id": project_id,
                    "query_embedding": vec_literal,
                    "match_count": RAG_MATCH_COUNT,
                },
            ).execute()
        )

        chunks = rag_result.data or []
        if chunks:
            items = [
                ContextItem(
                    text=c["content"],
                    label=c.get("metadata", {}).get("name", "Source"),
                )
                for c in chunks
            ]
            cited_chunk_ids = [c["chunk_id"] for c in chunks]
            packed = pack_into_context(items, RAG_TOKEN_BUDGET)
            rag_context = render_context(packed)
    except Exception:
        pass  # RAG failure is non-fatal; proceed without context

    # ── Build system prompt ───────────────────────────────────────────────
    system = (
        f"{_CHAT_SYSTEM}\n\n<CONTEXT>\n{rag_context}\n</CONTEXT>"
        if rag_context
        else _CHAT_SYSTEM
    )

    # ── Trim history to token budget ──────────────────────────────────────
    system_tokens = estimate_tokens(system)
    available = 60_000 - system_tokens - RESPONSE_RESERVE
    claude_messages: list[dict] = []
    used = 0

    for msg in reversed(history):
        tokens = estimate_tokens(msg["content"])
        if used + tokens > available:
            break
        claude_messages.insert(0, {"role": msg["role"], "content": msg["content"]})
        used += tokens

    # ── Stream ────────────────────────────────────────────────────────────
    async def generate():
        full_text = ""
        try:
            async for chunk in astream("balanced", claude_messages, system, max_tokens=2048):
                full_text += chunk
                yield chunk
        finally:
            # Persist assistant message after the stream ends (or on error)
            now = datetime.now(timezone.utc).isoformat()
            await run_sync(
                lambda: supabase.from_("messages")
                .insert(
                    {
                        "conversation_id": conversation_id,
                        "role": "assistant",
                        "content": full_text or "[no response]",
                        "metadata": {
                            "cited_chunk_ids": cited_chunk_ids,
                            "rag_used": bool(cited_chunk_ids),
                        },
                    }
                )
                .execute()
            )
            await run_sync(
                lambda: supabase.from_("conversations")
                .update({"updated_at": now})
                .eq("id", conversation_id)
                .execute()
            )

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")
