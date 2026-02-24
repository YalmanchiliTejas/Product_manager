/**
 * GET  /api/conversations/[id]/messages  — list all messages in a conversation
 * POST /api/conversations/[id]/messages  — send a message, get streamed reply
 *
 * The POST handler:
 *   1. Persists the user message.
 *   2. Fetches the full conversation history.
 *   3. Runs semantic search (RAG) to retrieve relevant chunks.
 *   4. Packs retrieved chunks into a context budget.
 *   5. Streams a Claude response back to the client (Server-Sent Events).
 *   6. After the stream completes, persists the assistant message with citations.
 */

import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/app/lib/supabaseAdmin";
import { getClaudeClient, CLAUDE_BALANCED } from "@/app/lib/claude";
import { createEmbedding, toPgVectorLiteral } from "@/app/lib/embeddings";
import {
  packIntoContext,
  renderContext,
  estimateTokens,
  type ContextItem,
} from "@/app/lib/agent/contextManager";

type Params = { params: Promise<{ id: string }> };

// ── GET: list messages ───────────────────────────────────────────────────────

export async function GET(_: Request, { params }: Params) {
  const { id } = await params;

  if (!id?.trim()) {
    return NextResponse.json({ error: "Conversation id is required." }, { status: 400 });
  }

  const { data, error } = await supabaseAdmin
    .from("messages")
    .select("id, conversation_id, role, content, metadata, created_at")
    .eq("conversation_id", id)
    .order("created_at", { ascending: true });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  return NextResponse.json({ messages: data ?? [] });
}

// ── POST: send message + streamed reply ──────────────────────────────────────

type SendMessageBody = {
  content?: string;
};

const CHAT_SYSTEM = `You are Beacon, an AI product research assistant. You help product managers analyse customer interviews, support tickets, and other feedback to identify product opportunities.

You have access to relevant excerpts from the project's source documents (provided in the CONTEXT section below). When answering:
- Cite specific quotes and attribute them to their source.
- Be analytical and opinionated — don't just summarise.
- If the evidence is thin or contradictory, say so.
- Always link insights back to customer impact.

Keep responses concise but substantive. Use markdown for structure when helpful.`;

// Max tokens to use for retrieved RAG context
const RAG_CONTEXT_TOKEN_BUDGET = 12_000;
// Max messages from history to include (most recent N)
const HISTORY_WINDOW = 20;
// RAG top-k
const RAG_MATCH_COUNT = 12;

export async function POST(request: Request, { params }: Params) {
  const { id: conversationId } = await params;

  if (!conversationId?.trim()) {
    return NextResponse.json({ error: "Conversation id is required." }, { status: 400 });
  }

  let body: SendMessageBody;
  try {
    body = (await request.json()) as SendMessageBody;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const userContent = body.content?.trim();
  if (!userContent) {
    return NextResponse.json({ error: "content is required." }, { status: 400 });
  }

  // ── 1. Fetch conversation to get project_id ────────────────────────────
  const { data: conv, error: convError } = await supabaseAdmin
    .from("conversations")
    .select("id, project_id")
    .eq("id", conversationId)
    .maybeSingle();

  if (convError) return NextResponse.json({ error: convError.message }, { status: 500 });
  if (!conv) return NextResponse.json({ error: "Conversation not found." }, { status: 404 });

  const projectId = conv.project_id as string;

  // ── 2. Persist user message ────────────────────────────────────────────
  const { error: userMsgError } = await supabaseAdmin.from("messages").insert({
    conversation_id: conversationId,
    role: "user",
    content: userContent,
  });

  if (userMsgError) {
    return NextResponse.json({ error: userMsgError.message }, { status: 500 });
  }

  // ── 3. Fetch conversation history ──────────────────────────────────────
  const { data: history } = await supabaseAdmin
    .from("messages")
    .select("role, content")
    .eq("conversation_id", conversationId)
    .order("created_at", { ascending: true })
    .limit(HISTORY_WINDOW);

  // ── 4. RAG retrieval ──────────────────────────────────────────────────
  let ragContext = "";
  const citedChunkIds: string[] = [];

  try {
    const queryEmbedding = await createEmbedding(userContent);
    const { data: chunks } = await supabaseAdmin.rpc("semantic_search_chunks", {
      input_project_id: projectId,
      query_embedding: toPgVectorLiteral(queryEmbedding),
      match_count: RAG_MATCH_COUNT,
    });

    if (chunks && chunks.length > 0) {
      const items: ContextItem[] = chunks.map(
        (c: { chunk_id: string; content: string; metadata: Record<string, unknown> }) => {
          citedChunkIds.push(c.chunk_id);
          return {
            label: (c.metadata?.name as string) ?? "Source",
            text: c.content,
            metadata: c.metadata,
          };
        }
      );

      const packed = packIntoContext(items, RAG_CONTEXT_TOKEN_BUDGET);
      ragContext = renderContext(packed);
    }
  } catch {
    // RAG failure is non-fatal; we proceed without context.
  }

  // ── 5. Build messages for Claude ──────────────────────────────────────
  const systemWithContext = ragContext
    ? `${CHAT_SYSTEM}\n\n<CONTEXT>\n${ragContext}\n</CONTEXT>`
    : CHAT_SYSTEM;

  // Trim history to fit the remaining token budget.
  // Reserve 4096 for the assistant response.
  const historyBudget = 60_000 - estimateTokens(systemWithContext) - 4096;
  const claudeMessages: Array<{ role: "user" | "assistant"; content: string }> = [];
  let historyTokens = 0;

  // Walk history in reverse, keep the most recent that fit.
  const reversedHistory = [...(history ?? [])].reverse();
  const kept: typeof reversedHistory = [];
  for (const msg of reversedHistory) {
    const tokens = estimateTokens(msg.content as string);
    if (historyTokens + tokens > historyBudget) break;
    kept.push(msg);
    historyTokens += tokens;
  }

  for (const msg of kept.reverse()) {
    claudeMessages.push({
      role: msg.role as "user" | "assistant",
      content: msg.content as string,
    });
  }

  // ── 6. Stream response ────────────────────────────────────────────────
  const client = getClaudeClient();

  const encoder = new TextEncoder();
  let assistantText = "";

  const stream = new ReadableStream({
    async start(controller) {
      try {
        const claudeStream = await client.messages.stream({
          model: CLAUDE_BALANCED,
          max_tokens: 2048,
          system: systemWithContext,
          messages: claudeMessages,
        });

        for await (const chunk of claudeStream) {
          if (
            chunk.type === "content_block_delta" &&
            chunk.delta.type === "text_delta"
          ) {
            const text = chunk.delta.text;
            assistantText += text;
            controller.enqueue(encoder.encode(text));
          }
        }

        // ── 7. Persist assistant message after stream completes ──────────
        await supabaseAdmin.from("messages").insert({
          conversation_id: conversationId,
          role: "assistant",
          content: assistantText,
          metadata: {
            cited_chunk_ids: citedChunkIds,
            rag_used: citedChunkIds.length > 0,
          },
        });

        // Bump conversation updated_at
        await supabaseAdmin
          .from("conversations")
          .update({ updated_at: new Date().toISOString() })
          .eq("id", conversationId);

        controller.close();
      } catch (err) {
        const message = err instanceof Error ? err.message : "Stream failed.";
        controller.enqueue(encoder.encode(`\n\n[Error: ${message}]`));
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Transfer-Encoding": "chunked",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
