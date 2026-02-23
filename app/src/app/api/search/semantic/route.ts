import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/app/lib/supabaseAdmin";
import { createEmbedding, toPgVectorLiteral } from "@/app/lib/embeddings";

type SearchBody = {
  query?: string;
  project_id?: string;
  match_count?: number;
};

export async function POST(request: Request) {
  let body: SearchBody;

  try {
    body = (await request.json()) as SearchBody;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const query = body.query?.trim();
  const projectId = body.project_id?.trim();
  const matchCount = Math.min(Math.max(body.match_count ?? 8, 1), 50);

  if (!query) {
    return NextResponse.json({ error: "query is required." }, { status: 400 });
  }

  if (!projectId) {
    return NextResponse.json({ error: "project_id is required." }, { status: 400 });
  }

  try {
    const embedding = await createEmbedding(query);

    const { data, error } = await supabaseAdmin.rpc("semantic_search_chunks", {
      input_project_id: projectId,
      query_embedding: toPgVectorLiteral(embedding),
      match_count: matchCount,
    });

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({ matches: data ?? [] });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Semantic search failed.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
