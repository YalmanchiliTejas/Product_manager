# Python LLM Service Architecture Plan (LLM-Agnostic + Token-Efficient)

## Goals
- Keep CRUD + source-of-truth data model in the existing Next.js/Supabase backend.
- Move AI orchestration into a dedicated Python service layer.
- Stay model-provider agnostic (OpenAI, Anthropic, local vLLM, etc.).
- Support large-context projects without linear token growth.

## High-Level Topology
1. **CRUD Backend (Next.js API + Supabase)**
   - Owns projects, sources, chunks, opportunities, and auth.
   - Exposes internal APIs for source/chunk retrieval and artifact writes.
2. **Ingestion Worker (Python service)**
   - Pulls source processing jobs from a queue.
   - Extracts text, chunks, embeds, and upserts chunk vectors.
3. **Retrieval + Reasoning Service (Python service)**
   - Handles semantic retrieval, reranking, and synthesis.
   - Writes results (theme clusters/opportunities/summaries) back through CRUD APIs.
4. **Model Gateway Adapter Layer (Python package)**
   - Unified interfaces: `embed(texts)`, `generate(messages)`, `json_generate(schema, messages)`.
   - Provider adapters behind feature flags and environment configuration.

## Recommended Python Service Breakdown
- `services/ingestion-api` (FastAPI):
  - Endpoints for enqueueing/retrying source processing.
  - Admin endpoints for job health.
- `services/ingestion-worker`:
  - Queue consumer for extraction/chunk/embed/store jobs.
- `services/reasoning-api` (FastAPI):
  - Endpoints for semantic QA, theme extraction, and opportunity generation.
- `packages/llm_gateway`:
  - Provider abstraction + fallback logic.
- `packages/context_engine`:
  - Retrieval budgeter, compression, deduplication, and citation stitching.

## Token-Efficiency Strategy for Large Contexts
1. **Two-stage retrieval**
   - Stage A: pgvector `top_k` retrieval.
   - Stage B: optional cross-encoder reranking on top 50->10.
2. **Context shaping**
   - Deduplicate near-identical chunks by similarity threshold.
   - Merge adjacent chunks from the same source if semantically contiguous.
   - Apply per-source and per-segment quotas to avoid source dominance.
3. **Hierarchical memory**
   - Maintain rolling summaries per source and per project epoch.
   - Query-time prompt uses: `query + top chunks + summaries`, not full corpus.
4. **Prompt budget manager**
   - Hard token budget per request (e.g. 20k total; 12k evidence; 8k reasoning/output).
   - Truncation strategy prioritizes highest reranked evidence with coverage constraints.
5. **Structured outputs only**
   - JSON-schema constrained outputs to reduce retries and verbose generations.

## API Contract (CRUD <-> Python)
- `POST /internal/sources/:id/process` -> enqueue ingestion job.
- `GET /internal/sources/:id/content` -> raw source payload + metadata.
- `POST /internal/chunks/bulk-upsert` -> chunk text + embedding + tags.
- `POST /internal/search/semantic` -> optional if CRUD hosts DB RPC only.
- `POST /internal/opportunities/bulk-upsert` -> write synthesized outputs.

Use service-to-service auth with short-lived signed JWTs issued by backend.

## Suggested Rollout Plan
1. Keep current Next.js endpoints for baseline capability.
2. Introduce queue and Python ingestion worker first (no frontend contract changes).
3. Move synthesis/search orchestration to Python reasoning service.
4. Add model gateway abstraction and A/B provider routing.
5. Add eval harness (offline golden prompts + regression scoring) before expanding models.

## Observability + Reliability
- Structured logs with request/job IDs.
- Metrics: embedding latency, retrieval recall@k proxy, generation latency, token usage, cost per request.
- Dead-letter queue for failed ingestion jobs.
- Idempotent chunk upserts keyed by `(source_id, chunk_index, content_hash)`.

## Why this architecture works
- Frontend and CRUD APIs stay simple and stable.
- AI pipeline scales independently with worker autoscaling.
- Provider changes do not require app-wide rewrites.
- Retrieval-first design minimizes token spend while preserving evidence quality.
