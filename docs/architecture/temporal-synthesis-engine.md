# Temporal Synthesis Engine Architecture

## Overview

The AI Synthesis Engine is built specifically to feed the Knowledge Graph, not as
standalone analysis. Every synthesis output is temporally aware: new themes,
accelerating themes, declining themes, contradictions between what segment A said
last month vs. this month.

The synthesis engine isn't the product — it's the read layer on top of the knowledge graph.

## How It Differs From Competitors

Most tools optimize for **"here's what your feedback says"** — a one-shot analysis.

We optimize for **"here's what changed since last time and why it matters"**:

| Aspect | Typical Tool | Our Approach |
|--------|-------------|--------------|
| Analysis | Atomic per batch | Temporally linked across runs |
| Themes | Static extraction | Tracked with trend direction + velocity |
| Segments | Optional filter | First-class: divergence detection across segments |
| Output | "Here are themes" | "Theme X accelerated 45% across 3 new segments" |
| History | None | Full synthesis timeline with diffs |
| Relationships | None | Co-occurrence, dependency, contradiction, amplification |

## Pipeline Architecture

### Pre-Synthesis: Temporal Context Building

Before any synthesis runs, the system loads what it already knows:

```python
temporal_context = build_temporal_context(project_id)
# Returns:
# {
#   "has_history": true,
#   "previous_themes": [
#     {"title": "Onboarding Friction", "trend": "accelerating", "velocity": 0.45},
#     {"title": "Mobile Performance", "trend": "stable", "velocity": 0.02},
#   ],
#   "correlations": [...],
#   "context_note": "Previous synthesis found 8 themes. Accelerating: Onboarding Friction..."
# }
```

This context is available to inject into synthesis prompts so the LLM can reference
what was seen before.

### Core Synthesis: LangGraph Pipeline

The existing pipeline runs unchanged:

```
fetch_chunks → extract_themes → evaluate_themes → [drill_down loop] → persist_themes → score_opportunities
```

Key capability: recursive evidence drilling for weak themes (< 2 supporting chunks)
triggers semantic search for additional evidence, then re-runs extraction. Up to N
iterations (configurable).

### Post-Synthesis: Intelligence Passes

After core synthesis completes, three intelligence passes run:

#### Pass 1: Trend Detection

For each theme in the new synthesis:
1. Look up the same theme title in the previous synthesis
2. Compare mention_count, segment_spread, source_count
3. Classify direction: emerging / accelerating / stable / declining / resurgent
4. Compute velocity (weighted: 70% mention change + 30% segment spread change)

```
Theme "Data Export Issues"
  Previous: 3 mentions, 1 segment
  Current:  8 mentions, 3 segments
  → Direction: accelerating, Velocity: +0.93
```

#### Pass 2: Signal Correlation

Two analysis layers run in sequence:

**Heuristic layer** (fast, deterministic):
- Chunk overlap: themes sharing the same evidence chunks → co_occurs
- Segment distribution comparison → potential divergence

**LLM layer** (slower, semantic):
- Dependency: "solving onboarding requires solving docs first"
- Contradiction: "enterprise users want X, SMBs want the opposite"
- Amplification: "mobile issues make the onboarding problem worse"
- Evolution: "what was a data issue last month is now a compliance issue"

Both signals are stored — heuristic provides quantitative backing, LLM provides
semantic reasoning.

#### Pass 3: Synthesis Comparison

Compares the new synthesis against the most recent previous one:
- Uses LLM semantic matching (theme titles may change slightly between runs)
- Categorizes each theme: new / removed / accelerating / declining / stable / contradiction
- Generates an executive summary

### Report Generation

The final output is a human-readable temporal intelligence report:

```markdown
# Temporal Intelligence Report

## Onboarding Friction
- **Trend**: accelerating (velocity: +0.45)
- **History**: First appeared 2025-12-01, tracked across 4 synthesis runs
- **Total mentions**: 23 across up to 3 segments
- **Mention trajectory**: 2 → 5 → 8 → 8
- **co_occurs** → Documentation Gaps (strength: 0.72) — Users struggling with
  onboarding frequently also mention missing documentation

## Signal Correlations
- **segment_divergence**: Enterprise ↔ SMB — Enterprise users need SSO in
  onboarding, SMBs find the flow too complex
```

## Trend Classification Logic

```
                  ┌──────────────┐
                  │ Is this the  │
                  │ first time   │──── YES ──→ EMERGING
                  │ we see this? │
                  └──────┬───────┘
                         │ NO
                  ┌──────▼───────┐
                  │  Compute     │
                  │  velocity    │
                  └──────┬───────┘
                         │
           ┌─────────────┼─────────────┐
           │             │             │
    velocity > 0.3  -0.3 < v < 0.3  velocity < -0.3
           │             │             │
           ▼             ▼             ▼
    ┌─────────────┐ ┌────────┐  ┌──────────┐
    │Was previously│ │ STABLE │  │ DECLINING│
    │declining?    │ └────────┘  └──────────┘
    └──────┬──────┘
           │
     YES ──┼── NO
           │      │
           ▼      ▼
    RESURGENT  ACCELERATING
```

Velocity formula:
```
velocity = 0.7 × (mention_change / prev_mentions) + 0.3 × (segment_change / prev_segments)
```

## Data Flow

```
Upload interview → Ingest → Chunk → Embed
                                      │
                              ┌───────▼────────┐
                              │ Entity Extract  │ → entities, entity_mentions
                              └───────┬────────┘
                                      │
                              ┌───────▼────────┐
                              │   Synthesis     │ → themes, opportunities
                              │   Pipeline      │
                              └───────┬────────┘
                                      │
                    ┌─────────────────┼──────────────────┐
                    │                 │                   │
            ┌───────▼──────┐ ┌───────▼──────┐  ┌────────▼───────┐
            │ Trend Detect │ │ Correlation  │  │ Synth Compare  │
            └───────┬──────┘ │   Engine     │  └────────┬───────┘
                    │        └───────┬──────┘           │
                    │                │                   │
            theme_trends    theme_relationships    synthesis_comparisons
                            signal_correlations
                                      │
                              ┌───────▼────────┐
                              │  Report Gen    │ → Human-readable output
                              └────────────────┘
```

## API Usage Example

### First Synthesis (cold start)

```bash
curl -X POST /api/knowledge-graph/synthesis/temporal \
  -d '{"project_id": "abc-123"}'
```

Response:
```json
{
  "synthesis_id": "syn-001",
  "themes": [...],
  "opportunities": [...],
  "temporal_context": {
    "has_history": false,
    "context_note": "This is the first synthesis for this project."
  },
  "postprocess": {
    "trends": {"total": 5, "emerging": 5, "accelerating": 0},
    "relationships": {"theme_relationships": 3, "signal_correlations": 2},
    "comparison": null
  },
  "report": "# Temporal Intelligence Report\n\n## Theme A\n- **Trend**: emerging..."
}
```

### Second Synthesis (temporal awareness kicks in)

```bash
curl -X POST /api/knowledge-graph/synthesis/temporal \
  -d '{"project_id": "abc-123"}'
```

Response now includes:
```json
{
  "temporal_context": {
    "has_history": true,
    "previous_themes": [
      {"title": "Onboarding Friction", "trend": "emerging", "velocity": 1.0}
    ]
  },
  "postprocess": {
    "trends": {"total": 7, "emerging": 2, "accelerating": 3, "stable": 1, "declining": 1},
    "comparison": {
      "summary": "Two new themes emerged around data portability. Onboarding Friction accelerated significantly.",
      "new_themes": 2,
      "accelerating": 3,
      "declining": 1
    }
  }
}
```

### Check What's Trending

```bash
curl -X POST /api/knowledge-graph/trends/trending \
  -d '{"project_id": "abc-123", "direction": "accelerating"}'
```

### Compare Any Two Syntheses

```bash
curl -X POST /api/knowledge-graph/synthesis/compare \
  -d '{"project_id": "abc-123", "baseline_synthesis_id": "syn-001", "current_synthesis_id": "syn-003"}'
```

## Files

| File | Lines | Purpose |
|------|-------|---------|
| `backend/services/temporal_synthesis.py` | ~200 | Orchestration: pre/post synthesis + report gen |
| `backend/services/trend_detection.py` | ~200 | Trend classification and velocity computation |
| `backend/services/signal_correlation.py` | ~250 | Heuristic + LLM relationship detection |
| `backend/services/synthesis_comparison.py` | ~200 | Cross-synthesis diffing with LLM matching |
| `backend/services/snapshot_comparison.py` | ~150 | Memory snapshot diffing |
| `backend/services/entity_extraction.py` | ~230 | Entity extraction, matching, and linking |
| `backend/routers/knowledge_graph.py` | ~300 | All knowledge graph API endpoints |
| `db/migrations/0004_knowledge_graph.sql` | ~160 | Database schema for all new tables |
