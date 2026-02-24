import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/app/lib/supabaseAdmin";

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

type CreateSourceBody = {
  project_id?: string;
  name?: string;
  source_type?: string;
  segment_tags?: string[];
  raw_content?: string;
  file_path?: string;
  metadata?: Record<string, unknown>;
};

export async function POST(request: Request) {
  let body: CreateSourceBody;

  try {
    body = (await request.json()) as CreateSourceBody;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const projectId = body.project_id?.trim();
  const name = body.name?.trim();
  const sourceType = body.source_type?.trim();

  if (!projectId) {
    return NextResponse.json({ error: "project_id is required." }, { status: 400 });
  }

  if (!name) {
    return NextResponse.json({ error: "name is required." }, { status: 400 });
  }

  if (!sourceType) {
    return NextResponse.json({ error: "source_type is required." }, { status: 400 });
  }

  const rawContent = body.raw_content?.trim() || null;
  const filePath = body.file_path?.trim() || null;

  if (!rawContent && !filePath) {
    return NextResponse.json(
      { error: "Either raw_content or file_path is required." },
      { status: 400 }
    );
  }

  const segmentTags = Array.isArray(body.segment_tags)
    ? body.segment_tags.map((t) => t.trim()).filter(Boolean)
    : [];

  const { data, error } = await supabaseAdmin
    .from("sources")
    .insert({
      project_id: projectId,
      name,
      source_type: sourceType,
      segment_tags: segmentTags,
      raw_content: rawContent,
      file_path: filePath,
      metadata: body.metadata ?? {},
    })
    .select("id, project_id, name, source_type, segment_tags, file_path, metadata, created_at")
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ source: data }, { status: 201 });
}
