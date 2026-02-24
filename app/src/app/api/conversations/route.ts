/**
 * GET  /api/conversations?project_id=<uuid>  — list conversations for a project
 * POST /api/conversations                     — create a conversation
 */

import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/app/lib/supabaseAdmin";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const projectId = searchParams.get("project_id")?.trim();

  if (!projectId) {
    return NextResponse.json({ error: "project_id query param is required." }, { status: 400 });
  }

  const { data, error } = await supabaseAdmin
    .from("conversations")
    .select("id, project_id, title, created_at, updated_at")
    .eq("project_id", projectId)
    .order("updated_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ conversations: data ?? [] });
}

type CreateConversationBody = {
  project_id?: string;
  title?: string;
};

export async function POST(request: Request) {
  let body: CreateConversationBody;
  try {
    body = (await request.json()) as CreateConversationBody;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const projectId = body.project_id?.trim();
  if (!projectId) {
    return NextResponse.json({ error: "project_id is required." }, { status: 400 });
  }

  const title = body.title?.trim() || null;

  const { data, error } = await supabaseAdmin
    .from("conversations")
    .insert({ project_id: projectId, title })
    .select("id, project_id, title, created_at, updated_at")
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ conversation: data }, { status: 201 });
}
