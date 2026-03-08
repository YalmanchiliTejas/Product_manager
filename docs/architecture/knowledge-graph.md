# Knowledge Graph Core Architecture

## Overview

The Knowledge Graph is the persistent, evolving intelligence layer that sits at the
heart of the product. Unlike competitors that do batch synthesis (upload stuff, cluster it,
done), the Knowledge Graph gets smarter over time — every piece of feedback ingested gets
embedded and linked to a timeline, a customer segment, and previous related signals.

When a PM uploads new interviews in month 3, the system doesn't just analyze those
interviews — it says "this theme first appeared 8 weeks ago from 2 enterprise accounts,
has grown to 14 mentions across 3 segments, and correlates with a support ticket spike
you saw in week 5."

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                   TEMPORAL SYNTHESIS API                      │
│              POST /api/knowledge-graph/synthesis/temporal     │
└─────────────────────┬───────────────────────────────────────┘
                      │
          ┌───────────▼───────────┐
          │   Temporal Context    │ ◄── Loads previous themes, trends,
          │      Builder          │     correlations before synthesis
          └───────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │   Core Synthesis      │     LangGraph pipeline:
          │     Pipeline          │     fetch → extract → evaluate →
          │  (synthesis_graph.py) │     drill_down → persist → score
          └───────────┬───────────┘
                      │
    ┌─────────────────┼─────────────────┐
    │                 │                 │
    ▼                 ▼                 ▼
┌────────┐   ┌──────────────┐   ┌────────────────┐
│ Entity │   │    Trend     │   │    Signal       │
│Extract │   │  Detection   │   │  Correlation    │
│        │   │              │   │    Engine        │
└───┬────┘   └──────┬───────┘   └───────┬────────┘
    │               │                   │
    ▼               ▼                   ▼
┌────────┐   ┌──────────────┐   ┌────────────────┐
│entities│   │ theme_trends │   │theme_relations │
│entity_ │   │              │   │signal_         │
│mentions│   │              │   │correlations    │
└────────┘   └──────────────┘   └────────────────┘
                      │
          ┌───────────▼───────────┐
          │  Synthesis Comparison │ ◄── "What changed since last time?"
          │   (auto-diffing)      │
          └───────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │   Temporal Report     │ ◄── Human-readable intelligence
          │     Generator         │     with trend trajectories
          └───────────────────────┘
```

## Database Schema

### New Tables (Migration 0004)

| Table | Purpose |
|-------|---------|
| `entities` | Extracted people, products, features, segments, companies, concepts |
| `entity_mentions` | Links entities → chunks → sources (provenance tracking) |
| `theme_relationships` | Edges between themes: co_occurs, depends_on, contradicts, evolves_into, amplifies |
| `signal_correlations` | Cross-theme pattern detection: co-occurrence, segment divergence, temporal spikes |
| `theme_trends` | Time-series of theme strength per synthesis run: direction + velocity |
| `synthesis_comparisons` | Structured diffs between two synthesis runs |
| `snapshot_comparisons` | Structured diffs between two memory snapshots |

### Entity-Relationship Model

```
projects
  ├── entities
  │   ├── entity_mentions → chunks, sources
  │   └── embedding (vector for semantic matching)
  │
  ├── syntheses
  │   ├── themes
  │   │   ├── theme_relationships (edges between themes)
  │   │   └── theme_trends (time-series per theme)
  │   ├── opportunities
  │   └── synthesis_comparisons (diffs between runs)
  │
  ├── signal_correlations (cross-theme patterns)
  │
  ├── memory_items (temporal knowledge)
  │   └── snapshot_comparisons (diffs between snapshots)
  │
  └── sources → chunks (with embeddings)
```

## Service Layer

### 1. Entity Extraction (`entity_extraction.py`)

Extracts named entities from feedback chunks using the fast LLM:
- **Types**: person, product, feature, segment, company, concept
- **Matching**: fuzzy alias matching against existing canonical entries
- **Linking**: every mention is linked to its chunk and source for provenance
- **Deduplication**: "CSV export" and "csv exporting" resolve to the same entity

```python
# Extract entities from all sources in a project
result = extract_entities_for_project(project_id)
# → {sources_processed: 12, entities_found: 47, mentions_created: 183}
```

### 2. Trend Detection (`trend_detection.py`)

Computes how themes evolve across synthesis runs:
- **emerging**: first time this theme appears
- **accelerating**: mention count and/or segment spread is growing
- **stable**: roughly same strength as before
- **declining**: losing evidence strength
- **resurgent**: was declining but has bounced back

Velocity is computed as a weighted blend of mention change (70%) and segment spread change (30%).

```python
# After a synthesis run
trends = compute_trends_for_synthesis(project_id, synthesis_id)
# → [{theme_title: "Onboarding Friction", trend_direction: "accelerating", velocity: 0.45}, ...]
```

### 3. Signal Correlation Engine (`signal_correlation.py`)

Detects relationships between themes using both heuristic and LLM analysis:

**Heuristic layer:**
- Chunk overlap: themes sharing evidence chunks → co-occurrence
- Segment distribution: themes with opposite segment patterns → divergence

**LLM layer:**
- Dependency detection: "solving A requires solving B first"
- Contradiction detection: "segment A says X, segment B says opposite"
- Amplification: "theme A makes theme B more urgent"
- Evolution: "theme A is an earlier version of theme B"

```python
result = detect_theme_relationships(project_id, synthesis_id)
# → {relationships: [...], correlations: [...], segment_divergences: [...]}
```

### 4. Snapshot Comparison (`snapshot_comparison.py`)

Compares memory snapshots (weekly point-in-time captures) to detect:
- New memory items that appeared
- Items no longer active (superseded or removed)
- Items that changed (same title but different content/id)

```python
result = compare_latest_snapshots(project_id)
# → {new_items: [...], removed_items: [...], changed_items: [...], summary: "..."}
```

### 5. Synthesis Comparison (`synthesis_comparison.py`)

Compares two synthesis runs using LLM-based semantic matching:
- **New themes**: appeared in current but not in baseline
- **Removed themes**: in baseline but absent from current
- **Accelerating/declining**: present in both but changed in strength
- **Contradictions**: themes where signals reversed

Produces an executive summary explaining what changed and why it matters.

```python
result = compare_with_previous(project_id, current_synthesis_id)
# → {new_themes: [...], accelerating_themes: [...], summary: "Two new enterprise themes emerged..."}
```

### 6. Temporal Synthesis (`temporal_synthesis.py`)

The orchestration layer that ties everything together:

1. **Pre-synthesis**: `build_temporal_context()` loads previous themes, trends, and correlations
2. **Core synthesis**: runs the existing LangGraph pipeline
3. **Post-synthesis**: `run_temporal_synthesis_postprocess()` triggers:
   - Trend computation
   - Relationship detection
   - Cross-synthesis comparison
4. **Report generation**: `generate_temporal_report()` produces human-readable output

## API Endpoints

### Primary Entry Point

```
POST /api/knowledge-graph/synthesis/temporal
```

This is the endpoint that replaces the standard `/api/synthesis/run` when you want
temporally-aware analysis. Request body:

```json
{
  "project_id": "uuid",
  "source_ids": ["uuid", ...],        // optional: restrict to specific sources
  "max_drill_down_iterations": 2,      // recursive evidence drilling
  "extract_entities": true             // run entity extraction
}
```

Response includes everything the standard synthesis returns plus:
- `temporal_context`: what the system knew before this synthesis
- `postprocess`: trend/correlation/comparison summaries
- `report`: human-readable temporal intelligence report

### Entity Graph

```
POST /api/knowledge-graph/entities/extract    — Extract entities from sources
GET  /api/knowledge-graph/entities/{project_id}?entity_type=feature
GET  /api/knowledge-graph/entities/{entity_id}/connections
```

### Trends

```
GET  /api/knowledge-graph/trends/{project_id}?theme_title=Onboarding
POST /api/knowledge-graph/trends/trending     — {project_id, direction: "accelerating"}
```

### Correlations & Relationships

```
POST /api/knowledge-graph/correlations/detect — {project_id, synthesis_id}
GET  /api/knowledge-graph/correlations/{project_id}?correlation_type=segment_divergence
GET  /api/knowledge-graph/relationships/{project_id}
```

### Comparisons

```
POST /api/knowledge-graph/synthesis/compare   — {project_id, baseline_synthesis_id, current_synthesis_id}
GET  /api/knowledge-graph/synthesis/timeline/{project_id}
POST /api/knowledge-graph/snapshots/compare   — {project_id, baseline_snapshot_id, current_snapshot_id}
POST /api/knowledge-graph/snapshots/compare-latest — Auto-compare latest two
```

## Design Decisions

### Why not Neo4j?

We deliberately avoided introducing a separate graph database for the MVP:

1. **Complexity**: Adding Neo4j doubles the infrastructure and deployment surface
2. **Sufficient**: PostgreSQL with structured tables and pgvector handles our scale
3. **Upgrade path**: The `theme_relationships` and `signal_correlations` tables
   are essentially an adjacency list — migrating to Neo4j later is straightforward
4. **Cold start**: Even the first upload starts building the graph through entity
   extraction and the temporal context builder

### Why LLM-based relationship detection?

Heuristic chunk-overlap is good for co-occurrence, but insufficient for nuanced
relationships like dependency, contradiction, and amplification. The strong LLM
provides the semantic reasoning needed while chunk overlap provides the quantitative
backing. Both signals are stored.

### How the cold start problem is solved

1. First upload → entity extraction runs, creating the initial entity graph
2. First synthesis → themes extracted, no comparisons possible yet (noted in report)
3. Second upload → new entities link to existing ones, mention counts grow
4. Second synthesis → trends computed (all "emerging"), comparison shows what's new
5. Third synthesis onward → full temporal awareness, acceleration/decline detection

Value compounds visibly with each additional data point.

## Files

| File | Purpose |
|------|---------|
| `db/migrations/0004_knowledge_graph.sql` | Schema for all knowledge graph tables |
| `backend/services/entity_extraction.py` | Entity extraction and linking |
| `backend/services/trend_detection.py` | Theme trend computation |
| `backend/services/signal_correlation.py` | Cross-theme relationship detection |
| `backend/services/snapshot_comparison.py` | Memory snapshot diffing |
| `backend/services/synthesis_comparison.py` | Synthesis run diffing |
| `backend/services/temporal_synthesis.py` | Temporal orchestration and report generation |
| `backend/routers/knowledge_graph.py` | FastAPI router with all endpoints |
| `backend/schemas/models.py` | Pydantic request/response models |
