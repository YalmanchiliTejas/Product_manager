"""
MapReduce Synthesis Pipeline
──────────────────────────────────────────────────────────────────────────────
Handles corpora that are too large to fit in a single LLM context window
(e.g. 50 customer interviews × 5 000 words = 250 000 words).

Phases
──────
  MAP    — per-source theme extraction   (fast tier, fully parallel)
  REDUCE — recursive cross-source merge  (balanced tier, batched if needed)
  SCORE  — opportunity ranking + briefs  (deep tier, single call)

The "recursive" step lives inside REDUCE: if all per-source summaries still
exceed the context budget after the first reduce pass, the intermediate
results are batched and reduced again until a single merged list is produced.
This is the hierarchical summarisation pattern — the recursion is in the
orchestration layer, not in the model itself.
"""

import asyncio
import json
from dataclasses import dataclass, field

from services.orchestration.llm.provider import acomplete_json
from services.orchestration.agent.context_manager import (
    ContextItem,
    batch_by_token_budget,
    pack_into_context,
    render_context,
)

# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class SourceInput:
    id: str
    name: str
    content: str
    source_type: str
    segment_tags: list[str] = field(default_factory=list)


@dataclass
class ExtractedQuote:
    quote: str
    source_id: str
    source_name: str


@dataclass
class PerSourceTheme:
    title: str
    description: str
    severity: int  # 1–5
    quotes: list[str]
    segment_hint: str


@dataclass
class PerSourceResult:
    source_id: str
    source_name: str
    source_type: str
    segment_tags: list[str]
    themes: list[PerSourceTheme]


@dataclass
class MergedTheme:
    title: str
    description: str
    frequency_score: float
    severity_score: float
    segment_distribution: dict[str, float]
    supporting_quotes: list[ExtractedQuote]
    contradictions: list[str] = field(default_factory=list)


@dataclass
class OpportunityBrief:
    title: str
    problem_statement: str
    affected_segments: list[str]
    confidence_score: float
    why_now: str
    ai_reasoning: str
    evidence: list[dict]


@dataclass
class SynthesisResult:
    themes: list[MergedTheme]
    opportunities: list[OpportunityBrief]
    synthesis_string: str


# ── MAP phase ─────────────────────────────────────────────────────────────────

_MAP_SYSTEM = """You are a product research analyst extracting themes from a single customer feedback document.

Respond ONLY with valid JSON. No prose, no markdown fences.
Schema:
{
  "themes": [
    {
      "title": "short theme name",
      "description": "1-2 sentence description of the pain/need",
      "severity": 3,
      "quotes": ["exact verbatim quote from the text"],
      "segment_hint": "enterprise|smb|free|unknown"
    }
  ]
}
Rules:
- Extract 3-7 themes. Fewer is better than padding.
- quotes must be exact text lifted from the document.
- severity: 1 (minor) to 5 (critical blocker).
- If the document mentions a user segment, populate segment_hint; otherwise "unknown"."""


async def _map_source(source: SourceInput) -> PerSourceResult:
    packed = pack_into_context(
        [ContextItem(text=source.content, label=source.name)],
        budget=60_000,
        reserve=500,
    )
    user_prompt = (
        f"Document type: {source.source_type}\n"
        f"Segment tags: {', '.join(source.segment_tags) or 'none'}\n\n"
        f"{render_context(packed)}"
    )

    result = await acomplete_json("fast", _MAP_SYSTEM, user_prompt, max_tokens=1500)
    raw_themes = result.get("themes", [])

    themes = [
        PerSourceTheme(
            title=t.get("title", ""),
            description=t.get("description", ""),
            severity=int(t.get("severity", 3)),
            quotes=t.get("quotes", []),
            segment_hint=t.get("segment_hint", "unknown"),
        )
        for t in raw_themes
    ]

    return PerSourceResult(
        source_id=source.id,
        source_name=source.name,
        source_type=source.source_type,
        segment_tags=source.segment_tags,
        themes=themes,
    )


async def map_phase(sources: list[SourceInput]) -> list[PerSourceResult]:
    """Process all sources concurrently, batched in groups of 10."""
    CONCURRENCY = 10
    results: list[PerSourceResult] = []
    for i in range(0, len(sources), CONCURRENCY):
        batch = sources[i : i + CONCURRENCY]
        batch_results = await asyncio.gather(*[_map_source(s) for s in batch])
        results.extend(batch_results)
    return results


# ── REDUCE phase ──────────────────────────────────────────────────────────────

_REDUCE_SYSTEM = """You are a senior product researcher merging per-document theme extractions into cross-source insights.

Respond ONLY with valid JSON. No prose, no markdown fences.
Schema:
{
  "themes": [
    {
      "title": "short theme name",
      "description": "2-3 sentence synthesis",
      "frequency_score": 0.75,
      "severity_score": 0.8,
      "segment_distribution": { "enterprise": 0.8, "smb": 0.3 },
      "supporting_quotes": [
        { "quote": "exact text", "source_name": "filename.txt" }
      ],
      "contradictions": ["optional: conflicting signals across sources"]
    }
  ]
}
Rules:
- Merge similar themes; do not create near-duplicates.
- frequency_score = fraction of source documents mentioning this theme (0-1).
- severity_score = average severity normalised to 0-1 (severity 5 → 1.0, 1 → 0.2).
- Include 2-4 best quotes per theme with source name.
- Maximum 10 themes."""


async def _reduce_one_batch(
    per_source: list[PerSourceResult],
    total_source_count: int,
) -> list[MergedTheme]:
    items = [
        ContextItem(
            label=f"{r.source_name} ({r.source_type})",
            text=json.dumps([
                {
                    "title": t.title,
                    "description": t.description,
                    "severity": t.severity,
                    "quotes": t.quotes,
                    "segment_hint": t.segment_hint,
                }
                for t in r.themes
            ]),
        )
        for r in per_source
    ]
    packed = pack_into_context(items, budget=80_000, reserve=2000)
    user_prompt = (
        f"Total sources in project: {total_source_count}\n"
        f"Sources in this batch: {len(per_source)}\n\n"
        f"{render_context(packed)}"
    )

    result = await acomplete_json("balanced", _REDUCE_SYSTEM, user_prompt, max_tokens=3000)
    raw_themes = result.get("themes", [])

    return [
        MergedTheme(
            title=t.get("title", ""),
            description=t.get("description", ""),
            frequency_score=float(t.get("frequency_score", 0)),
            severity_score=float(t.get("severity_score", 0)),
            segment_distribution=t.get("segment_distribution", {}),
            supporting_quotes=[
                ExtractedQuote(
                    quote=q.get("quote", ""),
                    source_id="",
                    source_name=q.get("source_name", ""),
                )
                for q in t.get("supporting_quotes", [])
            ],
            contradictions=t.get("contradictions", []),
        )
        for t in raw_themes
    ]


async def reduce_phase(
    per_source_results: list[PerSourceResult],
    total_source_count: int,
) -> list[MergedTheme]:
    """
    Recursive reduce: if per-source results exceed the context budget, split
    into batches, reduce each batch, then reduce the intermediate results.
    """
    if not per_source_results:
        return []

    all_items = [
        ContextItem(label=r.source_name, text=json.dumps([t.__dict__ for t in r.themes]))
        for r in per_source_results
    ]

    BATCH_BUDGET = 60_000
    batches = batch_by_token_budget(all_items, BATCH_BUDGET)

    if len(batches) == 1:
        return await _reduce_one_batch(per_source_results, total_source_count)

    # Recursive case: reduce each batch in parallel, then reduce intermediates.
    batch_tasks = []
    for batch in batches:
        batch_source_names = {item.label for item in batch}
        batch_sources = [r for r in per_source_results if r.source_name in batch_source_names]
        batch_tasks.append(_reduce_one_batch(batch_sources, total_source_count))

    intermediate_lists = await asyncio.gather(*batch_tasks)
    flat_themes = [t for sublist in intermediate_lists for t in sublist]

    # Convert merged themes into a pseudo source for the final reduce pass.
    pseudo = PerSourceResult(
        source_id="intermediate",
        source_name="intermediate-merge",
        source_type="merge",
        segment_tags=[],
        themes=[
            PerSourceTheme(
                title=t.title,
                description=t.description,
                severity=round(t.severity_score * 5),
                quotes=[q.quote for q in t.supporting_quotes],
                segment_hint=next(iter(t.segment_distribution), "unknown"),
            )
            for t in flat_themes
        ],
    )
    return await _reduce_one_batch([pseudo], total_source_count)


# ── SCORE phase ───────────────────────────────────────────────────────────────

_SCORE_SYSTEM = """You are a product strategy expert and former PM at a top tech company.

Given synthesised customer themes, produce ranked opportunity briefs.

Respond ONLY with valid JSON. No prose, no markdown fences.
Schema:
{
  "opportunities": [
    {
      "title": "short opportunity name",
      "problem_statement": "1-2 sentences on what problem this solves",
      "affected_segments": ["enterprise"],
      "confidence_score": 0.85,
      "why_now": "why this is urgent / timely",
      "ai_reasoning": "why this is ranked here vs alternatives",
      "evidence": [
        { "quote": "exact text", "source_name": "filename.txt", "theme": "theme title" }
      ]
    }
  ],
  "synthesis_summary": "3-5 sentence executive summary of all findings"
}
Ranking criteria (in order of weight):
1. Frequency — how many sources mention it
2. Severity — how painful for users
3. Segment distribution — cross-segment issues score higher
4. Contradiction risk — lower confidence when sources conflict"""


async def score_phase(themes: list[MergedTheme]) -> tuple[list[OpportunityBrief], str]:
    themes_json = json.dumps(
        [
            {
                "title": t.title,
                "description": t.description,
                "frequency_score": t.frequency_score,
                "severity_score": t.severity_score,
                "segment_distribution": t.segment_distribution,
                "supporting_quotes": [
                    {"quote": q.quote, "source_name": q.source_name}
                    for q in t.supporting_quotes
                ],
                "contradictions": t.contradictions,
            }
            for t in themes
        ],
        indent=2,
    )

    packed = pack_into_context(
        [ContextItem(text=themes_json)], budget=100_000, reserve=4000
    )
    result = await acomplete_json("deep", _SCORE_SYSTEM, render_context(packed), max_tokens=4096)

    opportunities = [
        OpportunityBrief(
            title=o.get("title", ""),
            problem_statement=o.get("problem_statement", ""),
            affected_segments=o.get("affected_segments", []),
            confidence_score=float(o.get("confidence_score", 0)),
            why_now=o.get("why_now", ""),
            ai_reasoning=o.get("ai_reasoning", ""),
            evidence=o.get("evidence", []),
        )
        for o in result.get("opportunities", [])
    ]

    summary = result.get("synthesis_summary", "No synthesis summary generated.")
    return opportunities, summary


# ── Orchestrator ──────────────────────────────────────────────────────────────

async def run_map_reduce_synthesis(sources: list[SourceInput]) -> SynthesisResult:
    """
    Full three-phase pipeline:
      1. Map   — parallel per-source theme extraction (fast tier)
      2. Reduce — recursive cross-source merging     (balanced tier)
      3. Score  — opportunity ranking + briefs        (deep tier)
    """
    if not sources:
        raise ValueError("At least one source is required for synthesis.")

    per_source = await map_phase(sources)
    merged_themes = await reduce_phase(per_source, len(sources))
    opportunities, synthesis_string = await score_phase(merged_themes)

    return SynthesisResult(
        themes=merged_themes,
        opportunities=opportunities,
        synthesis_string=synthesis_string,
    )
