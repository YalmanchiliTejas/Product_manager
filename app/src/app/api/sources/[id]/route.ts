import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/app/lib/supabaseAdmin";

type Params = { params: Promise<{ id: string }> };

type PatchBody = {
  source_type?: string;
  segment_tags?: string[];
};

export async function PATCH(request: Request, { params }: Params) {
  const { id } = await params;

  if (!id?.trim()) {
    return NextResponse.json({ error: "Source id is required." }, { status: 400 });
  }

  let body: PatchBody;

  try {
    body = (await request.json()) as PatchBody;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const updates: { source_type?: string; segment_tags?: string[] } = {};

  if (typeof body.source_type === "string") {
    updates.source_type = body.source_type.trim();
  }

  if (Array.isArray(body.segment_tags)) {
    updates.segment_tags = body.segment_tags
      .map((tag) => tag.trim())
      .filter(Boolean);
  }

  if (!Object.keys(updates).length) {
    return NextResponse.json(
      { error: "Provide source_type and/or segment_tags to update." },
      { status: 400 }
    );
  }

  const { data, error } = await supabaseAdmin
    .from("sources")
    .update(updates)
    .eq("id", id)
    .select("id, project_id, name, source_type, segment_tags, metadata, created_at")
    .maybeSingle();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  if (!data) {
    return NextResponse.json({ error: "Source not found." }, { status: 404 });
  }

  return NextResponse.json({ source: data });
}

export async function DELETE(_: Request, { params }: Params) {
  const { id } = await params;

  if (!id?.trim()) {
    return NextResponse.json({ error: "Source id is required." }, { status: 400 });
  }

  const { error } = await supabaseAdmin.from("sources").delete().eq("id", id);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return new NextResponse(null, { status: 204 });
}
