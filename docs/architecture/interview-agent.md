# Interview Agent — Architecture & File Guide

## Overview

The Interview Agent is a hierarchical multi-agent system that takes customer
interviews, feedback, and market context, then produces evidence-backed PRDs
with KPIs and implementation tickets.

**Inspired by:**
- Thariq's "Seeing like an Agent" — AskUserQuestion pattern, mutable task
  lists, progressive context building
- Hierarchical agent architecture — orchestrator dispatches specialist
  sub-agents for research, context, PRD generation, and ticket creation

**LLM Agnostic:** Every agent uses `get_fast_llm()` / `get_strong_llm()` from
the existing provider factory. Switch providers with `LLM_PROVIDER=openai` or
the CLI `--provider` flag. Supports: Anthropic, OpenAI, Ollama, Groq, Azure.

---

## File Map

```
backend/agents/
├── __init__.py          # Package init
├── __main__.py          # Entry point for: python -m backend.agents ./folder/
├── cli.py               # REPL CLI with folder ingestion + provider switching
├── state.py             # Shared state TypedDict + helper models
├── doc_parser.py        # Document parser (folder → structured interview data)
├── orchestrator.py      # Main LangGraph graph + InterviewSession class
├── context_agent.py     # Dynamic context fetcher sub-agent
├── research_agent.py    # Deep research sub-agent
├── prd_agent.py         # PRD generator sub-agent
└── ticket_agent.py      # Ticket creator sub-agent

backend/routers/
└── interview.py         # FastAPI endpoints for the agent

backend/schemas/
└── models.py            # Extended with Interview* Pydantic models

db/migrations/
└── 0003_interview_agent.sql  # Tables: sessions, tasks, prd_documents, tickets
```

---

## File-by-File Guide

### `state.py` — Shared State

**What it does:** Defines the single `InterviewState` TypedDict that flows
through the entire orchestrator graph. Every node reads from and writes to
slices of this state.

**Key types:**
- `InterviewState` — master state with all fields
- `TaskItem` — a single task in the mutable task list
- `PRDDocument` — structured PRD output
- `TicketItem` — a single ticket
- `KPIItem`, `NextAction` — PRD sub-structures

**Important for debugging:**
- `phase` field controls routing — if the agent seems stuck, check what phase
  it's in (intake, waiting, planning, researching, generating, ticketing, complete)
- `tasks_pending_confirmation` flag — if True, the REPL waits for user input
  before proceeding
- `messages` list — the full conversation log, useful for debugging what the
  agent "said"

**Where to fix things:**
- If you need to add a new field that sub-agents share, add it here
- The `make_task()` helper creates tasks with sensible defaults

---

### `doc_parser.py` — Document Parser

**What it does:** Reads a folder of interview files (.txt, .md, .csv, .pdf,
.json) and returns structured data with metadata (word count, speakers,
timestamps).

**Key functions:**
- `parse_interview_folder(folder_path)` — main entry, returns list of parsed docs
- `parse_interview_file(file_path)` — single file parser
- `summarize_parsed_interviews(interviews)` — human-readable summary for CLI
- `_detect_speakers(text)` — regex-based speaker detection for transcripts
- `_has_timestamps(text)` — detects MM:SS or HH:MM:SS patterns

**Important for debugging:**
- Uses the existing `file_processing.py` for text extraction (PDF, CSV, etc.)
- JSON files are handled specially — arrays of objects are joined with `---`
- If a file fails to parse, it's included with an error in metadata rather
  than crashing the whole batch
- Speaker detection patterns: `Name:`, `[Name]`, `Q:/A:` — extend
  `_detect_speakers()` if your transcripts use a different format
- Chunks use 1200 char size with 150 overlap (same as the rest of the app)

---

### `context_agent.py` — Context Fetcher

**What it does:** Dynamically discovers and assembles the right context for
the current question. Instead of dumping all interview data into the prompt,
it scores chunks by relevance and fetches only what's needed (inspired by
Claude Code's progressive context building).

**Key functions:**
- `run_context_agent(state)` — main entry, returns context_pack dict
- `_assess_context_needs()` — asks the fast LLM what context is needed
- `_build_interview_context()` — keyword-overlap scoring over loaded interviews
- `_fetch_db_context()` — queries the DB for memory items and evidence chunks

**Important for debugging:**
- The assessment uses the fast (cheap) LLM to decide what to fetch — if it
  makes bad decisions, tweak `_CONTEXT_ASSESSMENT_PROMPT`
- Interview context uses simple word overlap scoring — no embeddings needed,
  works offline. If results are poor, the threshold is `overlap > 0.15`
- DB context gracefully degrades — if Supabase is not connected (CLI-only mode),
  it silently returns empty results
- Returns `{assessment, interview_context, db_context}` — the orchestrator
  passes this to the PRD agent

---

### `research_agent.py` — Research Agent

**What it does:** Deep research pipeline that extracts claims from interviews,
searches for supporting/contradicting evidence, and synthesises findings into
a structured report.

**Pipeline:** extract_claims → search_internal → search_db → synthesise

**Key functions:**
- `run_research_agent(state)` — main entry, returns research results dict
- `_extract_claims()` — fast LLM extracts testable claims from interviews
- `_search_internal_evidence()` — keyword overlap search over loaded interviews
- `_search_db_evidence()` — hybrid search over DB chunks (if available)
- `_synthesise_findings()` — strong LLM synthesises everything into structured output

**Important for debugging:**
- Claim extraction truncates interview text to 12k chars — if you have very
  long interviews, increase this in `_extract_claims()`
- Internal search uses word overlap with threshold 0.15 — adjust if too noisy/quiet
- DB search processes at most 8 claims to avoid slow queries — increase in
  `_search_db_evidence()` if needed
- Synthesis uses the strong (expensive) LLM — this is the most costly call
- If JSON parsing fails, it tries to extract from markdown code blocks, then
  falls back to returning raw text as `summary`
- Output shape: `{validated_claims, contradictions, quantified_metrics, gaps,
  key_themes, summary, raw_claims, claim_count, internal_evidence_count}`

---

### `prd_agent.py` — PRD Generator

**What it does:** Takes research results + context + user question and
generates a structured PRD with KPIs, user stories, and next actions.

**Key functions:**
- `run_prd_agent(state)` — main entry, returns PRD dict
- `_build_prd_prompt()` — assembles the prompt from all available data
- `_parse_prd_response()` — parses JSON from LLM response
- `_render_prd_markdown()` — converts PRD dict to clean markdown

**Important for debugging:**
- The PRD prompt includes: research summary, validated claims, contradictions,
  quantified metrics, key themes, gaps, relevant interview excerpts, project
  memory, and confirmed tasks
- Uses the strong LLM — this is an expensive call
- If the LLM returns malformed JSON, the fallback puts the entire response
  into `problem_statement`
- The markdown renderer produces a clean document with tables for KPIs and
  next actions
- The `_PRD_GENERATION_PROMPT` requires at least 3 KPIs, 3 user stories, and
  3 next actions — relax these if you want simpler PRDs

---

### `ticket_agent.py` — Ticket Creator

**What it does:** Takes a validated PRD and breaks it into a hierarchical
ticket structure: Epic → Story → Task.

**Key functions:**
- `run_ticket_agent(state)` — main entry, returns flat list of tickets
- `_flatten_tickets()` — converts nested JSON to flat list with parent_id refs
- `render_tickets(tickets)` — pretty-prints tickets for CLI display

**Important for debugging:**
- Expects nested JSON with `children` arrays — flattens to a flat list with
  `parent_id` references for DB storage
- Story point scale: 1 (trivial), 2 (small), 3 (medium), 5 (large), 8 (very large)
- Each ticket gets a UUID `id` generated at flatten time
- If the PRD is empty, returns an empty list (no crash)
- The `_TICKET_GENERATION_PROMPT` asks for 1-3 epics with 2-4 stories each —
  adjust if you want different granularity

---

### `orchestrator.py` — Main Agent Graph

**What it does:** The core LangGraph StateGraph that orchestrates the entire
pipeline with human-in-the-loop interrupts.

**Graph topology:**
```
intake → analyze_question → plan_tasks → confirm_tasks
    → dispatch_research → generate_prd → review_prd → create_tickets
    → present_results → END
```

**Key classes:**
- `InterviewSession` — high-level wrapper for REPL-style interaction
  - `.start()` — run intake
  - `.ask(question, auto_confirm=False)` — submit question, run pipeline
  - `.confirm(response)` — confirm/reject tasks
  - `.review_prd(response)` — approve/revise PRD
  - `.get_tasks()`, `.get_prd()`, `.get_tickets()` — access outputs

**Key nodes:**
- `intake_node` — counts loaded interviews, sets phase to "waiting"
- `analyze_question_node` — fast LLM classifies question type
- `plan_tasks_node` — creates task list based on analysis
- `confirm_tasks_node` — processes user confirmation (interrupt point)
- `dispatch_research_node` — runs research + context agents
- `generate_prd_node` — runs PRD agent
- `review_prd_node` — processes user review (interrupt point)
- `create_tickets_node` — runs ticket agent
- `present_results_node` — increments iteration counter

**Routing functions:**
- `should_continue_after_confirm` — research or wait
- `should_generate_prd` — prd, tickets, or complete
- `should_create_tickets` — tickets or complete

**Important for debugging:**
- The `InterviewSession.ask()` method with `auto_confirm=True` runs the
  entire pipeline without pausing — useful for testing
- Without `auto_confirm`, the pipeline pauses at `plan_tasks` and the caller
  must call `.confirm()` to proceed
- State is mutated in place via dict merge (`{**self.state, **node_result}`)
- The graph is compiled once in `build_interview_graph()` and reused
- If the graph seems to skip steps, check the routing functions — they
  look at task statuses to decide what to do next

---

### `cli.py` — REPL CLI

**What it does:** Interactive command-line interface for the interview agent.
Parses a folder of interviews, starts a session, and runs a REPL loop.

**Usage:**
```bash
# Basic usage
python -m backend.agents.cli ./interviews/

# With provider switching (LLM-agnostic like Cursor)
python -m backend.agents.cli ./interviews/ --provider openai --model gpt-4o
python -m backend.agents.cli ./interviews/ --provider ollama --model llama3
python -m backend.agents.cli ./interviews/ --provider groq --model mixtral-8x7b

# With market context
python -m backend.agents.cli ./interviews/ --market "B2B SaaS, $50B TAM"

# Non-interactive (single question, auto-confirm, export results)
python -m backend.agents.cli ./interviews/ --auto "What are the top pain points?"
```

**REPL commands:**
- `/tasks` — show current task list with status icons
- `/prd` — show generated PRD markdown
- `/tickets` — show generated tickets
- `/export [dir]` — export PRD + tickets to files (default: ./output/)
- `/auto <question>` — run with auto-confirm
- `/phase` — show current agent phase
- `/help` — show commands
- `/quit` — exit

**Important for debugging:**
- Provider is set via env vars BEFORE any imports — this is critical because
  the LLM factory caches instances with `@lru_cache`
- The `--api-key` flag auto-maps to the right env var based on provider
- REPL routes input based on `phase` — if phase is "planning" and tasks are
  pending, input goes to `confirm()` instead of `ask()`
- Export creates both `.md` and `.json` for PRDs, and `.json` + `.txt` for tickets

---

### `interview.py` (router) — FastAPI Endpoints

**What it does:** REST API for the interview agent. Sessions are stored
in-memory (dict) — production would use DB + Redis.

**Endpoints:**
```
POST   /api/interview/sessions              — create session
GET    /api/interview/sessions/{id}         — get state
POST   /api/interview/sessions/{id}/ask     — submit question
POST   /api/interview/sessions/{id}/confirm — confirm tasks
POST   /api/interview/sessions/{id}/review  — review PRD
GET    /api/interview/sessions/{id}/tasks   — task list
GET    /api/interview/sessions/{id}/prd     — generated PRD
GET    /api/interview/sessions/{id}/tickets — generated tickets
```

**Important for debugging:**
- `_sessions` dict stores sessions in memory — they're lost on restart
- All endpoints return `InterviewSessionResponse` with full state
- Error handling is minimal — add try/except around agent calls for production

---

### `0003_interview_agent.sql` — Database Migration

**Tables:**
- `interview_sessions` — orchestrator run state
- `interview_tasks` — shared task list with status checks
- `prd_documents` — generated PRDs with KPI JSON and citation arrays
- `tickets` — hierarchical tickets with self-referencing `parent_ticket_id`

**Important:** These tables are for persistence in production. The CLI works
entirely without them — all state is in-memory via `InterviewState`.

---

## Data Flow

```
                          User provides:
                    ┌─── interviews folder ──────────────┐
                    │    market context                   │
                    │    questions via REPL               │
                    └────────────────────────────────────┘
                                  │
                                  ▼
                    ┌─── doc_parser.py ──────────────────┐
                    │  Parse .txt/.md/.csv/.pdf/.json     │
                    │  Extract text, chunk, detect speakers│
                    └────────────┬───────────────────────┘
                                 │ interview_data: list[dict]
                                 ▼
                    ┌─── orchestrator.py ────────────────┐
                    │  LangGraph StateGraph               │
                    │  Human-in-the-loop REPL              │
                    │                                      │
                    │  intake → analyze → plan → confirm   │
                    │       │                              │
                    │       ├── context_agent.py ──────►  │
                    │       │   (dynamic context fetch)    │
                    │       │                              │
                    │       ├── research_agent.py ─────►  │
                    │       │   (claim extraction +        │
                    │       │    evidence search +         │
                    │       │    synthesis)                 │
                    │       │                              │
                    │       ├── prd_agent.py ──────────►  │
                    │       │   (structured PRD with KPIs) │
                    │       │                              │
                    │       └── ticket_agent.py ───────►  │
                    │           (epic → story → task)      │
                    └─────────────┬────────────────────────┘
                                  │
                    ┌─────────────▼────────────────────────┐
                    │  Outputs:                            │
                    │  - PRD (markdown + JSON)              │
                    │  - Tickets (hierarchical)             │
                    │  - Research report                    │
                    │  - Task list                          │
                    └──────────────────────────────────────┘
```

## Memory Hooks — Cross-Session Persistence

The interview agent integrates with the existing memory system via three
hooks in `backend/agents/memory_hooks.py`. These ensure that research
findings, PRD decisions, and ticket plans survive across sessions.

### Architecture

```
                    ┌── HOOK 1: Session Start ──┐
                    │  Recall past decisions     │
                    │  from mem0 + memory_items  │
                    │  Inject into state.messages│
                    └────────────┬───────────────┘
                                 │
    research → prd → tickets     │
                                 │
                    ┌── HOOK 2: After Each Phase ─┐
                    │  Extract & store:            │
                    │  - research → metrics/claims │
                    │  - PRD → decisions/constraints│
                    │  - tickets → snapshot         │
                    │  LLM-powered type inference   │
                    └────────────┬─────────────────┘
                                 │
                    ┌── HOOK 3: Session End ───────┐
                    │  Full conversation → mem0     │
                    │  Consolidate + supersede      │
                    │  Rebuild compact index         │
                    └───────────────────────────────┘
```

### Hook 1 — Recall Past Decisions (`recall_past_decisions`)

**When:** On every new question (`analyze_question_node`)

**What it does:**
1. Searches **mem0** for conversational memories matching the question
2. Searches **memory_items** table for structured decisions, constraints,
   metrics, and personas related to the project
3. Formats them as a `[Prior Context]` message injected into `state.messages`
4. Passes prior context to the analysis LLM so it factors in past decisions

**Graceful degradation:** If mem0 or the DB is unavailable (CLI-only mode),
the hook silently returns an empty list and the pipeline proceeds normally.

### Hook 2 — After Each Phase (`extract_and_store_*_memories`)

**When:** After each major phase completes in the orchestrator

**Three variants:**
- `extract_and_store_research_memories` — after `dispatch_research_node`
  - Extracts validated claims, quantified metrics, key themes
  - Uses LLM-powered type inference (not keyword-based)
  - Writes to `memory_items` with authority 2 (research-level)

- `extract_and_store_prd_memories` — after `generate_prd_node`
  - Extracts decisions, constraints, KPIs from the PRD
  - Writes to `memory_items` with authority 3 (PRD-level)

- `extract_and_store_ticket_memories` — after `create_tickets_node`
  - Stores a compact snapshot (epic titles, story counts, total points)
  - Writes to `memory_items` as type `snapshot` with authority 4

**LLM-powered extraction:** Uses the fast LLM with a structured prompt to
classify content into decision/constraint/metric/persona/theme items.
This is more accurate than the keyword-based approach in `memory_update_graph.py`.

### Hook 3 — Session End (`persist_session_to_memory`)

**When:** At `present_results_node` (automatic) or via `POST /api/interview/sessions/{id}/end` (explicit)

**What it does:**
1. Feeds the full conversation history to **mem0** (`add_memories`)
   - mem0 uses its LLM to decide what's worth remembering
   - Handles deduplication and updates automatically
2. Runs **consolidation + supersede** on `memory_items`
   - Detects duplicate decisions/constraints by matching title+type
   - Marks exact duplicates as superseded (sets `effective_to`)
3. Rebuilds the **compact index** (`rebuild_index_memory`)
   - Updates the always-on pointer-style index for quick context lookups

### File Map (new)

```
backend/agents/
├── memory_hooks.py      # All 3 memory hooks + LLM extraction logic
└── orchestrator.py      # Modified: hooks wired into graph nodes

backend/agents/state.py  # Modified: added recalled_memories field

backend/routers/
└── interview.py         # Modified: added POST /sessions/{id}/end endpoint
```

---

## Setup & Running the Interview Agent

### Prerequisites

1. **Python 3.11+** with dependencies installed:
   ```bash
   pip install -r requirements.txt
   ```

2. **Environment variables** — create a `.env` file in the project root:
   ```bash
   # Required: LLM provider
   LLM_PROVIDER=anthropic          # or: openai, ollama, groq, azure_openai
   ANTHROPIC_API_KEY=sk-ant-...    # (or the key for your chosen provider)

   # Required: Embedding provider (for memory search)
   EMBEDDING_PROVIDER=openai
   OPENAI_API_KEY=sk-...

   # Optional but recommended: Supabase (enables persistent memory)
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=eyJ...

   # Optional: PostgreSQL for mem0 persistent storage
   DATABASE_URL=postgresql://user:pass@host:5432/dbname

   # Optional: Model overrides
   STRONG_MODEL=claude-sonnet-4-6
   FAST_MODEL=claude-haiku-4-5-20251001
   ```

3. **Database migrations** (if using Supabase):
   ```bash
   # Run in order against your Supabase SQL editor:
   cat db/migrations/0001_pgvector_semantic_search.sql
   cat db/migrations/0002_memory_context_pack.sql
   cat db/migrations/0003_interview_agent.sql
   ```

### Running the CLI

```bash
# Basic usage — analyse interviews in a folder
python -m backend.agents.cli ./interviews/

# With a specific LLM provider
python -m backend.agents.cli ./interviews/ --provider openai --model gpt-4o

# With Ollama (local, free)
python -m backend.agents.cli ./interviews/ --provider ollama --model llama3

# With market context
python -m backend.agents.cli ./interviews/ --market "B2B SaaS, $50B TAM"

# Non-interactive (auto-confirm, exports to ./output/)
python -m backend.agents.cli ./interviews/ --auto "What are the top pain points?"

# With an existing project (enables full memory recall)
python -m backend.agents.cli ./interviews/ --project-id <uuid>
```

**REPL commands:**
| Command    | Description                              |
|------------|------------------------------------------|
| `/tasks`   | Show current task list with status icons  |
| `/prd`     | Show generated PRD markdown               |
| `/tickets` | Show generated tickets                    |
| `/export`  | Export PRD + tickets to `./output/`       |
| `/auto Q`  | Ask with auto-confirm (no confirmation)   |
| `/phase`   | Show current agent phase                  |
| `/help`    | Show all commands                         |
| `/quit`    | Exit                                      |

### Running the API Server

```bash
# Start the FastAPI server
uvicorn backend.main:app --reload --port 8000
```

**Interview API endpoints:**

| Method | Endpoint                              | Description               |
|--------|---------------------------------------|---------------------------|
| POST   | `/api/interview/sessions`             | Create a new session      |
| GET    | `/api/interview/sessions/{id}`        | Get session state         |
| POST   | `/api/interview/sessions/{id}/ask`    | Submit a question         |
| POST   | `/api/interview/sessions/{id}/confirm`| Confirm/reject tasks      |
| POST   | `/api/interview/sessions/{id}/review` | Approve/revise PRD        |
| GET    | `/api/interview/sessions/{id}/tasks`  | Get task list             |
| GET    | `/api/interview/sessions/{id}/prd`    | Get generated PRD         |
| GET    | `/api/interview/sessions/{id}/tickets`| Get generated tickets     |
| POST   | `/api/interview/sessions/{id}/end`    | End session + persist memory |

### Memory Hooks Configuration

The memory hooks work automatically with no extra configuration. They
gracefully degrade when infrastructure isn't available:

| Feature                 | Without DB      | With Supabase + DATABASE_URL |
|-------------------------|-----------------|------------------------------|
| Hook 1 (recall)         | Skipped silently| Searches mem0 + memory_items |
| Hook 2 (extract+store)  | Skipped silently| LLM extracts → memory_items  |
| Hook 3 (persist+index)  | Skipped silently| mem0 + consolidate + reindex |
| Core pipeline           | Works fully     | Works fully                  |

**For full memory persistence, set both:**
- `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` (for memory_items table)
- `DATABASE_URL` (for mem0 pgvector backend)

Without these, the agent still works — interview analysis, PRD generation,
and ticket creation all function without persistent memory. You just won't
get cross-session recall.

### Testing the Agent

**Quick smoke test (no DB required):**
```bash
# Create a test interviews folder
mkdir -p test_interviews
echo "User: The onboarding process is really confusing. I spent 20 minutes
trying to figure out how to invite my team. The API docs are great though." \
  > test_interviews/interview1.txt

# Run with auto-confirm
python -m backend.agents.cli ./test_interviews/ --auto "What are the top pain points?"
```

**Full pipeline test (with DB):**
```bash
# 1. Start the server
uvicorn backend.main:app --reload --port 8000

# 2. Create a session
curl -X POST http://localhost:8000/api/interview/sessions \
  -H "Content-Type: application/json" \
  -d '{"interview_data": [{"filename": "test.txt", "content": "...", "metadata": {}}],
       "project_id": "test-project", "user_id": "test-user"}'

# 3. Ask a question (auto-confirm)
curl -X POST http://localhost:8000/api/interview/sessions/{session_id}/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the top pain points?", "auto_confirm": true}'

# 4. End session (triggers memory persistence)
curl -X POST http://localhost:8000/api/interview/sessions/{session_id}/end

# 5. Start a NEW session with the same project_id
#    Hook 1 will now recall decisions from the previous session
```

---

## Extending the System

**Add a new sub-agent:**
1. Create `backend/agents/my_agent.py` with `run_my_agent(state) -> dict`
2. Add a node in `orchestrator.py`: `graph.add_node("my_agent", my_agent_node)`
3. Wire it into the routing logic
4. Add the agent name to the `agent` check constraint in `state.py`'s TaskItem

**Add a new LLM provider:**
1. Add provider case in `backend/services/llm.py`'s `_build_llm()`
2. Add config fields in `backend/config.py`
3. The CLI `--provider` flag auto-works if you follow the pattern

**Change PRD structure:**
1. Edit `_PRD_GENERATION_PROMPT` in `prd_agent.py`
2. Update `_render_prd_markdown()` for new sections
3. Update `PRDDocument` TypedDict in `state.py`

**Change ticket granularity:**
1. Edit `_TICKET_GENERATION_PROMPT` in `ticket_agent.py`
2. Adjust the "1-3 Epics, 2-4 Stories, 1-4 Tasks" guidance
