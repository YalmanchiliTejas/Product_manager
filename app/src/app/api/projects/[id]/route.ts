import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/app/lib/supabaseAdmin";

type Params = {
  params: Promise<{
    id: string;
  }>;
};

export async function GET(_: Request, { params }: Params) {
  const { id } = await params;

  if (!id?.trim()) {
    return NextResponse.json({ error: "Project id is required." }, { status: 400 });
  }

  const { data, error } = await supabaseAdmin
    .from("projects")
    .select("id, user_id, name, description, created_at, updated_at")
    .eq("id", id)
    .maybeSingle();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  if (!data) {
    return NextResponse.json({ error: "Project not found." }, { status: 404 });
  }

  return NextResponse.json({ project: data });
}

type PatchBody = {
  name?: string;
  description?: string | null;
};

export async function PATCH(request: Request, { params }: Params) {
  const { id } = await params;

  if (!id?.trim()) {
    return NextResponse.json({ error: "Project id is required." }, { status: 400 });
  }

  let body: PatchBody;
  try {
    body = (await request.json()) as PatchBody;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const updates: { name?: string; description?: string | null } = {};

  if (typeof body.name === "string") {
    const trimmed = body.name.trim();
    if (!trimmed) {
      return NextResponse.json({ error: "name cannot be empty." }, { status: 400 });
    }
    updates.name = trimmed;
  }

  if ("description" in body) {
    updates.description = body.description?.trim() || null;
  }

  if (!Object.keys(updates).length) {
    return NextResponse.json(
      { error: "Provide name and/or description to update." },
      { status: 400 }
    );
  }

  const { data, error } = await supabaseAdmin
    .from("projects")
    .update(updates)
    .eq("id", id)
    .select("id, user_id, name, description, created_at, updated_at")
    .maybeSingle();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  if (!data) {
    return NextResponse.json({ error: "Project not found." }, { status: 404 });
  }

  return NextResponse.json({ project: data });
}

export async function DELETE(_: Request, { params }: Params) {
  const { id } = await params;

  if (!id?.trim()) {
    return NextResponse.json({ error: "Project id is required." }, { status: 400 });
  }

  const { error } = await supabaseAdmin.from("projects").delete().eq("id", id);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return new NextResponse(null, { status: 204 });
}
