import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/app/lib/supabaseAdmin";
import { createEmbedding, toPgVectorLiteral } from "@/app/lib/embeddings";
import { chunkText, extractSourceText } from "@/app/lib/sourcePipeline";

type ProcessBody = {
  source_id?: string;
};

export async function POST(request: Request) {
  let body: ProcessBody;

  try {
    body = (await request.json()) as ProcessBody;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const sourceId = body.source_id?.trim();

  if (!sourceId) {
    return NextResponse.json({ error: "source_id is required." }, { status: 400 });
  }

  const { data: source, error: sourceError } = await supabaseAdmin
    .from("sources")
    .select("id, project_id, raw_content, file_path, metadata")
    .eq("id", sourceId)
    .maybeSingle();

  if (sourceError) {
    return NextResponse.json({ error: sourceError.message }, { status: 500 });
  }

  if (!source) {
    return NextResponse.json({ error: "Source not found." }, { status: 404 });
  }

  try {
    const rawText = await extractSourceText(source.raw_content, source.file_path);
    const chunks = chunkText(rawText);

    if (!chunks.length) {
      return NextResponse.json({ error: "No text content found after extraction." }, { status: 400 });
    }

    await supabaseAdmin.from("chunks").delete().eq("source_id", source.id);

    // Embed chunks sequentially to avoid OpenAI rate-limit bursts.
    const chunkRows: Array<{
      source_id: string;
      project_id: string;
      content: string;
      chunk_index: number;
      embedding: string;
      metadata: Record<string, unknown>;
    }> = [];

    for (let chunkIndex = 0; chunkIndex < chunks.length; chunkIndex++) {
      const content = chunks[chunkIndex];
      const embedding = await createEmbedding(content);

      chunkRows.push({
        source_id: source.id,
        project_id: source.project_id,
        content,
        chunk_index: chunkIndex,
        embedding: toPgVectorLiteral(embedding),
        metadata: source.metadata ?? {},
      });
    }

    const { error: chunkInsertError } = await supabaseAdmin.from("chunks").insert(chunkRows);

    if (chunkInsertError) {
      return NextResponse.json({ error: chunkInsertError.message }, { status: 500 });
    }

    return NextResponse.json({
      source_id: source.id,
      chunk_count: chunks.length,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Source processing failed.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
