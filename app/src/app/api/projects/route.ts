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
  let body: CreateProjectBody;

  try {
    body = (await request.json()) as CreateProjectBody;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const userId = (body.user_id ?? "").trim();
  const name = (body.name ?? "").trim();
  const description = body.description?.trim() || null;

  if (!userId || !name) {
    return NextResponse.json(
      { error: "Both user_id and name are required." },
      { status: 400 }
    );
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
