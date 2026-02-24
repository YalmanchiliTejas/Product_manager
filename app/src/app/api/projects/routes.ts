import { NextResponse } from "next/server";
import { supabaseAdmin } from "../../lib/supabaseAdmin"

export async function GET() {
  const { data, error } = await supabaseAdmin
    .from("projects")
    .select("id,user_id,name,description,created_at,updated_at")
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json({ projects: data ?? [] });
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));

  const name = String(body.name ?? "").trim();
  const description = body.description ? String(body.description) : null;

  // For now (no auth): you must provide a user_id in request
  // Or hardcode a dummy UUID if you want.
  const user_id = String(body.user_id ?? "").trim();

  if (!name) return NextResponse.json({ error: "name is required" }, { status: 400 });
  if (!user_id) return NextResponse.json({ error: "user_id is required (for now)" }, { status: 400 });

  const { data, error } = await supabaseAdmin
    .from("projects")
    .insert({ user_id, name, description })
    .select("id,user_id,name,description,created_at,updated_at")
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json({ project: data }, { status: 201 });
}