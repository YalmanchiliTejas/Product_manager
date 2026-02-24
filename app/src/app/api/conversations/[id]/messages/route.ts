/**
 * GET  /api/conversations/[id]/messages  — list all messages (pure CRUD, Next.js)
 * POST /api/conversations/[id]/messages  — streaming chat (proxied to Python)
 */
import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/app/lib/supabaseAdmin";
import { proxyStream } from "@/app/lib/pythonService";

type Params = { params: Promise<{ id: string }> };

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

export async function POST(request: Request, { params }: Params) {
  const { id: conversationId } = await params;

  if (!conversationId?.trim()) {
    return NextResponse.json({ error: "Conversation id is required." }, { status: 400 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  // Forward to Python with the conversation_id from the URL
  return proxyStream("/chat/stream", { ...(body as object), conversation_id: conversationId });
}
