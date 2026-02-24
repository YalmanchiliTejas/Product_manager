import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/app/lib/supabaseAdmin";

type CreateProjectBody = {
  user_id?: string;
  name?: string;
  description?: string | null;
};

export async function GET() {
  const { data, error } = await supabaseAdmin
    .from("projects")
    .select("id, user_id, name, description, created_at, updated_at")
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ projects: data ?? [] });
}

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as CreateProjectBody | null;

  if (!body) {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const userId = body.user_id?.trim();
  const name = body.name?.trim();
  const description = body.description ? String(body.description) : null;

  if (!userId) {
    return NextResponse.json({ error: "user_id is required." }, { status: 400 });
  }

  if (!name) {
    return NextResponse.json({ error: "name is required." }, { status: 400 });
  }

  const { data, error } = await supabaseAdmin
    .from("projects")
    .insert({ user_id: userId, name, description })
    .select("id, user_id, name, description, created_at, updated_at")
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ project: data }, { status: 201 });
}
