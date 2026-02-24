
### 2.1 Components

**A) Orchestrators (DAG runners)**
- IngestionOrchestrator: parses, chunks, embeds, updates memory indices.
- SynthesisOrchestrator: generates themes + opportunities and persists them.
- ChatOrchestrator: answers questions using recursive context building.

**B) ModelAdapter (provider abstraction)**
Single interface:
- generate(messages, tools, response_schema, params) -> {text|json, tool_calls, usage}

Implementations:
- AnthropicAdapter
- OpenAIAdapter
- GeminiAdapter
- LocalAdapter (optional)

**C) Tool Runtime (capability layer)**
All “agent actions” are tools with stable signatures. The LLM never directly touches DB/storage.

**D) Memory Services**
- Working memory: project_state + conversation_state
- Long-term memory: events + themes/opportunities + graph summaries
- Retrieval: pgvector + graph neighborhood queries

**E) Policy/Guardrails**
- Citation enforcement
- Token budgets
- Output schema validation (Zod)
- Refusal/uncertainty rules (“insufficient evidence”)

---

## 3) Tool contracts (LLM-agnostic API)

These are the only primitives the agent needs. Keep them stable.

### 3.1 Retrieval tools
- search_chunks(query, filters) -> [{chunk_id, score}]
- fetch_chunks(chunk_ids) -> [{chunk_id, content, source_id, metadata}]
- search_artifacts(query, filters) -> [{theme_id|opp_id|event_id, score}]
- fetch_artifact(artifact_id) -> {artifact_json, citations}
- search_graph_nodes(query, filters) -> [{node_id, score}]
- fetch_graph_context(node_ids, depth, filters) -> {nodes, edges, summaries, citations}

### 3.2 State tools
- get_project_state(project_id) -> state_json
- patch_project_state(project_id, patch_json)
- get_conversation_state(conversation_id) -> state_json
- patch_conversation_state(conversation_id, patch_json)

### 3.3 Write tools (persistence)
- log_event(project_id, type, payload_json) -> event_id
- create_synthesis(project_id, trigger_type, source_ids, model_used) -> synthesis_id
- write_themes(project_id, synthesis_id, themes_json) -> [theme_id]
- write_opportunities(project_id, synthesis_id, opportunities_json) -> [opp_id]
- update_opportunity(opp_id, patch_json)
- update_theme(theme_id, patch_json)

### 3.4 Export tools
- export_opportunities_markdown(project_id, opp_ids, options) -> markdown
- export_raw_json(project_id, scope, options) -> json

---

## 4) Memory architecture (what the agent relies on)

Beacon memory is layered so the agent can retrieve *structure first* and *raw evidence only when needed*.

### 4.1 Working memory (small, cheap, always in context)
- project_state: ICP, segments, definitions, constraints, success metrics, current strategy.
- conversation_state: current goal, open questions, last cited ids, cache keys.

### 4.2 Longitudinal memory (auditable, queryable)
- events: immutable record of decisions/changes and their rationale (links to evidence).
- artifacts: themes/opportunities/syntheses with citations.
- graph summaries (optional early, strong later): structured “what we know” by segment/time.

Hard requirement:
- Any summary must store citations: {chunk_ids[], event_ids[]}.

---

## 5) Recursive Context Builder (RLM-style context folding)

The key to long-context + low cost is building the prompt from coarse summaries and expanding only where needed.

### 5.1 Inputs
- user_message
- project_state (short)
- recent conversation messages (short window)
- budgets: token_budget_total, quote_budget, max_chunks

### 5.2 Procedure
1) Classify intent:
- prioritization / drilldown / decision-audit / compare-time / explain-contradictions

2) Coarse retrieval (cheap):
- retrieve top themes/opportunities/events relevant to the intent
- retrieve any segment/time summaries if available

3) Expand recursively (only if needed):
- if low confidence OR contradictions OR user requests evidence:
  - fetch top supporting chunks (exact quotes)
  - fetch linked events (decisions) and their cited evidence

4) Build Evidence Pack:
- project_state excerpt (definitions/constraints only)
- selected artifact summaries (themes/opps/events)
- exact quotes (6–10 max) with chunk_id/source_id
- decision records (event_id) when relevant

5) Generate answer with strict grounding:
- every claim cites chunk_id/event_id
- if insufficient evidence: say so + suggest what data would help

### 5.3 Output
- assistant response
- metadata: cited_chunk_ids, cited_event_ids, cited_theme_ids, cited_opp_ids
- conversation_state updates: cache keys, last retrieval pointers

---

## 6) Model routing (cost control)

Use a two-stage routing pattern:

**Stage A (fast model)**
- intent classification
- retrieval planning
- evidence pack assembly decisions (what to expand)

**Stage B (strong model)**
- final synthesis when:
  - “what should we build next?” across many sources
  - contradiction-heavy analysis
  - generating ranked opportunities

Default:
- most chat turns should complete with Stage A + small Stage B or even Stage A-only if the answer is deterministic.

---

## 7) Core pipelines (agent behavior per feature)

### 7.1 Ingestion pipeline
Trigger: upload/paste

Steps:
- parse -> normalize -> chunk
- embed chunks (once)
- log_event(source_ingested)
- (optional) lightweight entity extraction -> update graph index

Outputs:
- sources, chunks, embeddings

### 7.2 Synthesis pipeline
Trigger: “Synthesize” button

Pass 1 (fast):
- generate themes JSON with supporting quotes (chunk_ids required)

Pass 2 (strong, optional):
- generate opportunities JSON ranked with reasoning + contradictions
- citations required: theme_ids + chunk_ids

Persist:
- create_synthesis -> write_themes -> write_opportunities
- log_event(synthesis_completed)

### 7.3 Chat pipeline
Trigger: user message

Steps:
- get_project_state + recent messages
- build Evidence Pack (recursive)
- generate grounded response
- persist message + citations in metadata

---

## 8) Guardrails (non-negotiable)

- Citation enforcement:
  - Any non-trivial claim must cite chunk_id or event_id.
- Quote integrity:
  - Quotes must be exact text from chunk content.
- Schema validation:
  - Theme/opportunity outputs must validate with Zod schemas; retry with repair prompt if invalid.
- Budget enforcement:
  - hard caps on chunks fetched, quotes included, and evidence pack tokens.
- “Insufficient evidence” behavior:
  - if confidence < threshold or evidence weak, the agent must say what’s missing.

---

## 9) Minimal “agents” as roles (do not over-multi-agent)

Implement as prompts + orchestrator, not separate services:

- Role: Ingestion/Indexer (deterministic + light extraction)
- Role: Synthesizer (themes/opportunities)
- Role: PM Copilot (chat + challenge mode)

This keeps debugging easy and reduces hallucination risk.

---
