import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/app/lib/supabaseAdmin";

type CreateSourceBody = {
  project_id?: string;
  name?: string;
  source_type?: string;
  segment_tags?: string[];
  raw_content?: string | null;
  file_path?: string | null;
  metadata?: Record<string, unknown>;
};

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const projectId = searchParams.get("project_id")?.trim();

  let query = supabaseAdmin
    .from("sources")
    .select("id, project_id, name, source_type, segment_tags, file_path, metadata, created_at")
    .order("created_at", { ascending: false });

  if (projectId) {
    query = query.eq("project_id", projectId);
  }

  const { data, error } = await query;

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ sources: data ?? [] });
}

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as CreateSourceBody | null;

  if (!body) {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const projectId = body.project_id?.trim();
  const name = body.name?.trim();

  if (!projectId) {
    return NextResponse.json({ error: "project_id is required." }, { status: 400 });
  }

  if (!name) {
    return NextResponse.json({ error: "name is required." }, { status: 400 });
  }

  const sourceType = body.source_type?.trim() || "untyped";
  const segmentTags = Array.isArray(body.segment_tags)
    ? body.segment_tags.map((tag) => tag.trim()).filter(Boolean)
    : [];

  const { data, error } = await supabaseAdmin
    .from("sources")
    .insert({
      project_id: projectId,
      name,
      source_type: sourceType,
      segment_tags: segmentTags,
      raw_content: body.raw_content ? String(body.raw_content) : null,
      file_path: body.file_path?.trim() || null,
      metadata: body.metadata ?? {},
    })
    .select("id, project_id, name, source_type, segment_tags, file_path, metadata, created_at")
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ source: data }, { status: 201 });
}
