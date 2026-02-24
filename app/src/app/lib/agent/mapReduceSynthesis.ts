/**
 * MapReduce Synthesis Pipeline
 * ─────────────────────────────────────────────────────────────────────────────
 * Large corpora of customer feedback (15+ interviews, 200+ support tickets)
 * can easily exceed 100k–500k tokens — far more than any single LLM call can
 * handle, and expensive even when it fits.
 *
 * The MapReduce pattern solves this by splitting the work into:
 *
 *   MAP   — process each source independently (parallel, Haiku)
 *           Each document → { themes[], quotes[], segment }
 *
 *   REDUCE — merge per-source extractions into cross-source themes (Sonnet)
 *            If there are many sources the intermediary summaries are batched
 *            and reduced again (recursive/hierarchical reduce).
 *
 *   SCORE  — rank merged themes as product opportunities (Opus)
 *            Returns fully-formed opportunity briefs.
 *
 * This is the canonical pattern for LLM-based document analysis at scale.
 * The term "Recursive Language Models" refers to this recursive reduce step —
 * not a fundamentally different model architecture.  The recursion is in the
 * *orchestration*, not the model itself.
 */

import { completeJSON, CLAUDE_FAST, CLAUDE_BALANCED, CLAUDE_DEEP } from "@/app/lib/claude";
import {
  packIntoContext,
  renderContext,
  batchByTokenBudget,
  type ContextItem,
} from "@/app/lib/agent/contextManager";

// ─── Shared types ──────────────────────────────────────────────────────────

export interface SourceInput {
  id: string;      // source UUID
  name: string;    // filename / title
  content: string; // full text of the source
  sourceType: string;
  segmentTags: string[];
}

export interface ExtractedQuote {
  quote: string;
  sourceId: string;
  sourceName: string;
}

export interface PerSourceTheme {
  title: string;
  description: string;
  severity: number; // 1–5
  quotes: string[];
  segmentHint: string;
}

export interface PerSourceResult {
  sourceId: string;
  sourceName: string;
  sourceType: string;
  segmentTags: string[];
  themes: PerSourceTheme[];
}

export interface MergedTheme {
  title: string;
  description: string;
  frequencyScore: number;       // 0–1: fraction of sources mentioning this
  severityScore: number;        // 0–1: normalised from 1–5 scale
  segmentDistribution: Record<string, number>; // { enterprise: 0.8, smb: 0.3 }
  supportingQuotes: ExtractedQuote[];
  contradictions?: string[];    // noted conflicts across sources
}

export interface OpportunityBrief {
  title: string;
  problemStatement: string;
  affectedSegments: string[];
  confidenceScore: number; // 0–1
  whyNow: string;
  aiReasoning: string;
  evidence: Array<{ quote: string; sourceName: string; theme: string }>;
}

export interface SynthesisResult {
  themes: MergedTheme[];
  opportunities: OpportunityBrief[];
  synthesisString: string;
}

// ─── MAP phase ─────────────────────────────────────────────────────────────

const MAP_SYSTEM = `You are a product research analyst. Your job is to extract recurring themes from a single customer feedback document.

Respond ONLY with a valid JSON object. No prose, no markdown fences.
Schema:
{
  "themes": [
    {
      "title": "short theme name",
      "description": "1–2 sentence description of the pain/need",
      "severity": 1,
      "quotes": ["exact verbatim quote from the text"],
      "segmentHint": "enterprise|smb|free|unknown"
    }
  ]
}

Rules:
- Extract 3–7 themes. Fewer is better than padding.
- Quotes must be exact text lifted from the document.
- severity is 1 (minor) to 5 (critical blocker).
- If the document mentions a user segment, populate segmentHint; otherwise "unknown".`;

async function mapSource(source: SourceInput): Promise<PerSourceResult> {
  // Truncate very long sources to ~60k tokens to keep Haiku costs predictable.
  const packed = packIntoContext(
    [{ text: source.content, label: source.name }],
    60_000,
    500 // reserve for system + response
  );

  const userPrompt = `Document type: ${source.sourceType}\nSegment tags: ${source.segmentTags.join(", ") || "none"}\n\n${renderContext(packed)}`;

  const result = await completeJSON<{ themes: PerSourceTheme[] }>(
    CLAUDE_FAST,
    MAP_SYSTEM,
    userPrompt,
    1500
  );

  return {
    sourceId: source.id,
    sourceName: source.name,
    sourceType: source.sourceType,
    segmentTags: source.segmentTags,
    themes: result.themes ?? [],
  };
}

// Run map phase: process all sources concurrently (bounded by Promise.all).
// For very large sets (>20 sources) consider batching Promise.all into groups
// of 10 to avoid overwhelming the API.
export async function mapPhase(sources: SourceInput[]): Promise<PerSourceResult[]> {
  const CONCURRENCY = 10;
  const results: PerSourceResult[] = [];

  for (let i = 0; i < sources.length; i += CONCURRENCY) {
    const batch = sources.slice(i, i + CONCURRENCY);
    const batchResults = await Promise.all(batch.map(mapSource));
    results.push(...batchResults);
  }

  return results;
}

// ─── REDUCE phase ──────────────────────────────────────────────────────────

const REDUCE_SYSTEM = `You are a senior product researcher. You have received per-document theme extractions from multiple customer interviews / feedback sources.

Your job is to MERGE these into cross-source, de-duplicated themes and surface important contradictions.

Respond ONLY with valid JSON. No prose, no markdown fences.
Schema:
{
  "themes": [
    {
      "title": "short theme name",
      "description": "2–3 sentence synthesis",
      "frequencyScore": 0.75,
      "severityScore": 0.8,
      "segmentDistribution": { "enterprise": 0.8, "smb": 0.3 },
      "supportingQuotes": [
        { "quote": "exact text", "sourceName": "filename.txt" }
      ],
      "contradictions": ["optional: note any conflicting signals"]
    }
  ]
}

Rules:
- Merge similar themes; do not create near-duplicates.
- frequencyScore = fraction of source documents that mention this theme (0–1).
- severityScore = average severity normalised to 0–1 (severity 5 → 1.0, severity 1 → 0.2).
- Include the 2–4 best quotes per merged theme, with the source name.
- Limit to 10 themes maximum.`;

async function reduceOneBatch(
  perSourceResults: PerSourceResult[],
  totalSourceCount: number
): Promise<MergedTheme[]> {
  const items: ContextItem[] = perSourceResults.map((r) => ({
    label: `${r.sourceName} (${r.sourceType})`,
    text: JSON.stringify(r.themes),
  }));

  const packed = packIntoContext(items, 80_000, 2000);
  const userPrompt = `Total sources in project: ${totalSourceCount}\nSources in this batch: ${perSourceResults.length}\n\n${renderContext(packed)}`;

  const result = await completeJSON<{ themes: MergedTheme[] }>(
    CLAUDE_BALANCED,
    REDUCE_SYSTEM,
    userPrompt,
    3000
  );

  return result.themes ?? [];
}

/**
 * Recursive reduce: if there are too many per-source results to fit in one
 * call, split them into batches, reduce each batch, then reduce the results
 * again.  This recurses until we have a single list of merged themes.
 */
export async function reducePhase(
  perSourceResults: PerSourceResult[],
  totalSourceCount: number
): Promise<MergedTheme[]> {
  if (perSourceResults.length === 0) return [];

  // Estimate token cost of all results; batch if necessary.
  const allItems: ContextItem[] = perSourceResults.map((r) => ({
    label: r.sourceName,
    text: JSON.stringify(r.themes),
  }));

  const BATCH_BUDGET = 60_000;
  const batches = batchByTokenBudget(allItems, BATCH_BUDGET);

  if (batches.length === 1) {
    // Everything fits in one call — do a direct reduce.
    return reduceOneBatch(perSourceResults, totalSourceCount);
  }

  // Recursive case: reduce each batch, then reduce those intermediate results.
  const intermediatePromises = batches.map((batch) => {
    const batchSources = batch.map((item) => {
      return perSourceResults.find((r) => r.sourceName === item.label)!;
    });
    return reduceOneBatch(batchSources, totalSourceCount);
  });

  const intermediateThemes = await Promise.all(intermediatePromises);
  const flat = intermediateThemes.flat();

  // Convert merged themes back into a pseudo-PerSourceResult for the final pass.
  const pseudoSource: PerSourceResult = {
    sourceId: "intermediate",
    sourceName: "intermediate-merge",
    sourceType: "merge",
    segmentTags: [],
    themes: flat.map((t) => ({
      title: t.title,
      description: t.description,
      severity: Math.round(t.severityScore * 5),
      quotes: t.supportingQuotes.map((q) => q.quote),
      segmentHint: Object.keys(t.segmentDistribution)[0] ?? "unknown",
    })),
  };

  return reduceOneBatch([pseudoSource], totalSourceCount);
}

// ─── SCORE phase (opportunity ranking) ────────────────────────────────────

const SCORE_SYSTEM = `You are a product strategy expert and former PM at a top tech company.

You have been given a set of synthesised customer themes. Your job is to:
1. Rank them as product opportunities.
2. Write a concise opportunity brief for each.
3. Detect contradictions or risks.
4. Write a short executive synthesis summary.

Respond ONLY with valid JSON. No prose, no markdown fences.
Schema:
{
  "opportunities": [
    {
      "title": "short opportunity name",
      "problemStatement": "1–2 sentences on what problem this solves",
      "affectedSegments": ["enterprise"],
      "confidenceScore": 0.85,
      "whyNow": "why this is urgent / timely",
      "aiReasoning": "why this is ranked here vs alternatives",
      "evidence": [
        { "quote": "exact text", "sourceName": "filename.txt", "theme": "theme title" }
      ]
    }
  ],
  "synthesissummary": "3–5 sentence executive summary of all findings"
}

Ranking criteria (in order of weight):
1. Frequency — how many sources mention it
2. Severity — how painful it is for users
3. Segment distribution — cross-segment issues score higher
4. Feasibility signal — flag if sources hint at easy vs hard solutions
5. Contradiction risk — lower confidence if sources conflict`;

export async function scorePhase(themes: MergedTheme[]): Promise<{
  opportunities: OpportunityBrief[];
  synthesisString: string;
}> {
  const packed = packIntoContext(
    [{ text: JSON.stringify(themes, null, 2) }],
    100_000,
    4000
  );

  const result = await completeJSON<{
    opportunities: OpportunityBrief[];
    synthesisstring: string;
    synthesissummary?: string;
  }>(CLAUDE_DEEP, SCORE_SYSTEM, renderContext(packed), 4096);

  return {
    opportunities: result.opportunities ?? [],
    synthesisString:
      result.synthesissummary ??
      result.synthesisstring ??
      "No synthesis summary generated.",
  };
}

// ─── Orchestrator ──────────────────────────────────────────────────────────

/**
 * Run the full three-phase synthesis pipeline.
 *
 * 1. Map  — parallel per-source theme extraction (Claude Haiku)
 * 2. Reduce — recursive cross-source theme merging (Claude Sonnet)
 * 3. Score — opportunity ranking + brief generation (Claude Opus)
 */
export async function runMapReduceSynthesis(
  sources: SourceInput[]
): Promise<SynthesisResult> {
  if (sources.length === 0) {
    throw new Error("At least one source is required for synthesis.");
  }

  const perSourceResults = await mapPhase(sources);
  const mergedThemes = await reducePhase(perSourceResults, sources.length);
  const { opportunities, synthesisString } = await scorePhase(mergedThemes);

  return {
    themes: mergedThemes,
    opportunities,
    synthesisString,
  };
}
