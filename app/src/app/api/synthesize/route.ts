/**
 * POST /api/synthesize
 *
 * Triggers the full three-phase MapReduce synthesis pipeline for a project.
 * Persists the results as a Synthesis + Themes + Opportunities in the DB.
 *
 * Body:
 *   project_id    string (required)
 *   source_ids    string[] (optional — defaults to ALL processed sources)
 *   trigger_type  'manual' | 'chat_query' (optional, default 'manual')
 *
 * Returns:
 *   { synthesis_id, theme_count, opportunity_count, summary }
 */

import { NextResponse } from "next/server";
import { supabaseAdmin } from "@/app/lib/supabaseAdmin";
import { runMapReduceSynthesis, type SourceInput } from "@/app/lib/agent/mapReduceSynthesis";

type SynthesizeBody = {
  project_id?: string;
  source_ids?: string[];
  trigger_type?: string;
};

export async function POST(request: Request) {
  let body: SynthesizeBody;
  try {
    body = (await request.json()) as SynthesizeBody;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const projectId = body.project_id?.trim();
  if (!projectId) {
    return NextResponse.json({ error: "project_id is required." }, { status: 400 });
  }

  const triggerType = body.trigger_type?.trim() ?? "manual";

  // ── 1. Fetch sources ────────────────────────────────────────────────────
  let sourcesQuery = supabaseAdmin
    .from("sources")
    .select("id, name, source_type, segment_tags, raw_content, file_path")
    .eq("project_id", projectId);

  if (Array.isArray(body.source_ids) && body.source_ids.length > 0) {
    sourcesQuery = sourcesQuery.in("id", body.source_ids);
  }

  const { data: sourcesData, error: sourcesError } = await sourcesQuery;

  if (sourcesError) {
    return NextResponse.json({ error: sourcesError.message }, { status: 500 });
  }

  if (!sourcesData || sourcesData.length === 0) {
    return NextResponse.json(
      { error: "No sources found for this project. Upload and process sources first." },
      { status: 400 }
    );
  }

  // ── 2. Build SourceInput list ────────────────────────────────────────────
  // Only include sources that have extractable text.
  const sources: SourceInput[] = sourcesData
    .filter((s) => s.raw_content?.trim())
    .map((s) => ({
      id: s.id as string,
      name: s.name as string,
      content: s.raw_content as string,
      sourceType: s.source_type as string,
      segmentTags: (s.segment_tags as string[]) ?? [],
    }));

  if (sources.length === 0) {
    return NextResponse.json(
      {
        error:
          "None of the selected sources have raw_content. Process the sources via /api/sources/process first.",
      },
      { status: 400 }
    );
  }

  // ── 3. Run MapReduce synthesis ───────────────────────────────────────────
  let synthesisResult;
  try {
    synthesisResult = await runMapReduceSynthesis(sources);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Synthesis pipeline failed.";
    return NextResponse.json({ error: message }, { status: 500 });
  }

  // ── 4. Persist synthesis record ─────────────────────────────────────────
  const { data: synthesis, error: synthError } = await supabaseAdmin
    .from("syntheses")
    .insert({
      project_id: projectId,
      trigger_type: triggerType,
      summary: synthesisResult.synthesisString,
      source_ids: sources.map((s) => s.id),
      model_used: "haiku+sonnet+opus (mapreduce)",
    })
    .select("id")
    .single();

  if (synthError || !synthesis) {
    return NextResponse.json(
      { error: synthError?.message ?? "Failed to create synthesis record." },
      { status: 500 }
    );
  }

  const synthesisId = synthesis.id as string;

  // ── 5. Persist themes ────────────────────────────────────────────────────
  if (synthesisResult.themes.length > 0) {
    const themeRows = synthesisResult.themes.map((theme) => ({
      project_id: projectId,
      synthesis_id: synthesisId,
      title: theme.title,
      description: theme.description,
      frequency_score: theme.frequencyScore,
      severity_score: theme.severityScore,
      segment_distribution: theme.segmentDistribution,
      supporting_quotes: theme.supportingQuotes,
    }));

    const { error: themeError } = await supabaseAdmin.from("themes").insert(themeRows);
    if (themeError) {
      return NextResponse.json({ error: themeError.message }, { status: 500 });
    }
  }

  // ── 6. Persist opportunities ─────────────────────────────────────────────
  if (synthesisResult.opportunities.length > 0) {
    const oppRows = synthesisResult.opportunities.map((opp, rank) => ({
      project_id: projectId,
      synthesis_id: synthesisId,
      title: opp.title,
      problem_statement: opp.problemStatement,
      evidence: opp.evidence,
      affected_segments: opp.affectedSegments,
      confidence_score: opp.confidenceScore,
      why_now: opp.whyNow,
      ai_reasoning: opp.aiReasoning,
      rank: rank + 1,
      status: "proposed",
    }));

    const { error: oppError } = await supabaseAdmin.from("opportunities").insert(oppRows);
    if (oppError) {
      return NextResponse.json({ error: oppError.message }, { status: 500 });
    }
  }

  return NextResponse.json({
    synthesis_id: synthesisId,
    theme_count: synthesisResult.themes.length,
    opportunity_count: synthesisResult.opportunities.length,
    summary: synthesisResult.synthesisString,
  });
}
