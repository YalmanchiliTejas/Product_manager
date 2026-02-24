/**
 * GET    /api/conversations/[id]  — fetch a single conversation
 * PATCH  /api/conversations/[id]  — update title
 * DELETE /api/conversations/[id]  — delete (cascades messages)
 */

import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/app/lib/supabaseAdmin";

type Params = { params: Promise<{ id: string }> };

export async function GET(_: Request, { params }: Params) {
  const { id } = await params;

  if (!id?.trim()) {
    return NextResponse.json({ error: "Conversation id is required." }, { status: 400 });
  }

  const { data, error } = await supabaseAdmin
    .from("conversations")
    .select("id, project_id, title, created_at, updated_at")
    .eq("id", id)
    .maybeSingle();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  if (!data) return NextResponse.json({ error: "Conversation not found." }, { status: 404 });

  return NextResponse.json({ conversation: data });
}

export async function PATCH(request: Request, { params }: Params) {
  const { id } = await params;

  if (!id?.trim()) {
    return NextResponse.json({ error: "Conversation id is required." }, { status: 400 });
  }

  let body: { title?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const title = typeof body.title === "string" ? body.title.trim() || null : undefined;

  if (title === undefined) {
    return NextResponse.json({ error: "Provide title to update." }, { status: 400 });
  }

  const { data, error } = await supabaseAdmin
    .from("conversations")
    .update({ title })
    .eq("id", id)
    .select("id, project_id, title, created_at, updated_at")
    .maybeSingle();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  if (!data) return NextResponse.json({ error: "Conversation not found." }, { status: 404 });

  return NextResponse.json({ conversation: data });
}

export async function DELETE(_: Request, { params }: Params) {
  const { id } = await params;

  if (!id?.trim()) {
    return NextResponse.json({ error: "Conversation id is required." }, { status: 400 });
  }

  const { error } = await supabaseAdmin.from("conversations").delete().eq("id", id);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  return new NextResponse(null, { status: 204 });
}
