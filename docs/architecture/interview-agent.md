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

## Quick Start — Setup & Run

### Prerequisites

```bash
# Python 3.10+
python --version

# Install dependencies (from project root)
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file in the project root (or export these):

```bash
# Required — pick ONE LLM provider:
LLM_PROVIDER=anthropic          # or: openai, ollama, groq, azure_openai

# Provider API key (match your LLM_PROVIDER):
ANTHROPIC_API_KEY=sk-ant-...    # if LLM_PROVIDER=anthropic
# OPENAI_API_KEY=sk-...         # if LLM_PROVIDER=openai
# GROQ_API_KEY=gsk_...          # if LLM_PROVIDER=groq

# Optional — model overrides:
# FAST_MODEL=claude-haiku-4-5-20251001
# STRONG_MODEL=claude-sonnet-4-6

# Optional — for longitudinal memory persistence (DB-backed):
# SUPABASE_URL=https://xxx.supabase.co
# SUPABASE_SERVICE_ROLE_KEY=eyJ...
# DATABASE_URL=postgresql://postgres:...@db.xxx.supabase.co:5432/postgres

# Optional — for embeddings (needed for DB-backed memory):
# EMBEDDING_PROVIDER=openai
# EMBEDDING_MODEL=text-embedding-3-small
```

**Minimum to run:** Just `LLM_PROVIDER` + the matching API key. Everything
else is optional. The agent works fully without a database — memory persists
within the session via the in-memory DecisionLog.

### Run the CLI

```bash
# Basic — parse interviews from a folder and start REPL
python -m backend.agents.cli ./path/to/interviews/

# With provider switching
python -m backend.agents.cli ./interviews/ --provider openai --model gpt-4o
python -m backend.agents.cli ./interviews/ --provider ollama --model llama3
python -m backend.agents.cli ./interviews/ --provider groq --model mixtral-8x7b

# With market context
python -m backend.agents.cli ./interviews/ --market "B2B SaaS targeting SMBs, $50B TAM"

# Non-interactive (single question, auto-confirm, exports to ./output/)
python -m backend.agents.cli ./interviews/ --auto "What are the top user pain points?"

# With API key inline
python -m backend.agents.cli ./interviews/ --provider anthropic --api-key sk-ant-...
```

### Interview File Formats

Place your files in a folder. Supported formats:

| Format | Extension | Notes |
|--------|-----------|-------|
| Plain text | `.txt` | Interview transcripts, notes |
| Markdown | `.md` | Formatted notes, summaries |
| CSV | `.csv` | Survey responses, NPS data |
| PDF | `.pdf` | Requires `pypdf` (already in requirements) |
| JSON | `.json` | Structured data, arrays of responses |

The parser auto-detects speaker labels (`Name:`, `[Name]`, `Q:/A:`) and
timestamps (`HH:MM:SS`, `MM:SS`).

### REPL Commands

Once in the REPL:

```
/tasks     — show current task list with status icons
/prd       — show generated PRD (markdown)
/tickets   — show generated tickets
/decisions — show decisions/constraints extracted this session
/export    — export PRD + tickets to ./output/
/auto <q>  — ask with auto-confirm (no task confirmation step)
/save      — persist session to longitudinal memory now
/phase     — show current agent phase
/help      — show all commands
/quit      — exit (auto-saves to memory)
```

### Run the API Server

```bash
# Start FastAPI
uvicorn backend.main:app --reload --port 8000

# Then use the interview endpoints:
# POST /api/interview/sessions         — create session
# POST /api/interview/sessions/{id}/ask — submit question
# etc. (see API docs at http://localhost:8000/docs)
```

### Run DB Migrations (optional, for persistence)

```bash
# Apply in your Supabase SQL editor or via psql:
psql $DATABASE_URL -f db/migrations/0001_pgvector_semantic_search.sql
psql $DATABASE_URL -f db/migrations/0002_memory_context_pack.sql
psql $DATABASE_URL -f db/migrations/0003_interview_agent.sql
```

### Test It

```bash
# 1. Create a folder with sample interviews
mkdir -p ./test_interviews
echo "Interviewer: What's your biggest pain point?
User: The onboarding is confusing. I couldn't figure out how to set up my first project.
Interviewer: How often do you use the product?
User: Daily, but I avoid the analytics dashboard because it's too slow." > ./test_interviews/user_interview_1.txt

# 2. Run the agent
python -m backend.agents.cli ./test_interviews/

# 3. Ask a question
# > What are the main pain points?
# (agent analyses, extracts claims, generates research report)

# 4. Confirm tasks when prompted
# > yes

# 5. Review the PRD
# > approve

# 6. Check outputs
# /prd
# /tickets
# /decisions
# /export
```

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
├── memory_hooks.py      # Longitudinal memory: recall, persist, consolidate
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
  - `.end()` — persist session to longitudinal memory
  - `.get_tasks()`, `.get_prd()`, `.get_tickets()` — access outputs
  - `.get_decision_log()` — access extracted decisions/constraints

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

## Longitudinal Memory Architecture

The interview agent integrates with the existing memory infrastructure to
persist decisions, constraints, metrics, and persona insights across sessions.

### How It Works

```
Session N                              Session N+1
=========                              ===========

 ask("pain points?")                    ask("prioritize features")
      │                                      │
      ▼                                      ▼
 HOOK 1: recall_memories()             HOOK 1: recall_memories()
 (DB empty on first run)               ← recalls decisions from Session N
      │                                      │
      ▼                                      ▼
 research + context + prd              research sees past decisions
      │                                 PRD references past constraints
      ▼                                      │
 HOOK 2: persist_phase()               HOOK 2: persist_phase()
 → extracts: "80% cite onboarding      → extracts: "Prioritize onboarding
    friction" (metric)                     over analytics" (decision)
 → extracts: "Must support offline"    → writes to DecisionLog + DB
    (constraint)                             │
 → writes to DecisionLog + DB               ▼
      │                                 HOOK 3: persist_session()
      ▼                                 → conversation → mem0
 HOOK 3: persist_session()             → consolidate (supersede stale)
 → conversation → mem0                 → rebuild compact index
 → consolidate duplicates
 → rebuild compact index
```

### Three Hooks

| Hook | When | What it does |
|------|------|-------------|
| **recall_memories** | Before each question | Searches mem0 + memory_items + local DecisionLog for relevant past context. Injects into state so all sub-agents see it. |
| **persist_phase** | After research, PRD, tickets | LLM extracts structured items (decisions, constraints, metrics, personas) from the phase output. Writes to DecisionLog (always) + memory_items table (if DB connected). |
| **persist_session** | On `/quit`, `/save`, or `.end()` | Feeds full conversation to mem0 for deduplication. Runs consolidation to supersede stale decisions. Rebuilds the compact memory index. |

### DecisionLog (In-Memory)

Every session has a `DecisionLog` that works without a database:

```python
session.get_decision_log()
# → [
#   {"type": "metric", "title": "Onboarding friction rate",
#    "content": "80% of users cited onboarding confusion", "confidence": "high"},
#   {"type": "decision", "title": "Prioritize self-serve onboarding",
#    "content": "Build guided setup wizard before API access", "confidence": "high"},
#   {"type": "constraint", "title": "Offline support required",
#    "content": "Must work without internet for field sales team", "confidence": "medium"},
# ]
```

Use `/decisions` in the CLI to see these at any time.

### DB-Backed Persistence (Optional)

When `SUPABASE_URL` + `DATABASE_URL` are configured:

1. **persist_phase** writes to `memory_items` table with:
   - `type`: decision, constraint, metric, or persona
   - `authority`: 1 (low confidence) → 3 (high confidence)
   - `metadata.extracted_by`: "interview_agent_memory_hook"
   - `metadata.phase`: which phase produced this item
   - `metadata.session_id`: traceability back to the session

2. **persist_session** runs consolidation:
   - Finds duplicate titles within the same type
   - Exact content match → supersedes the older one (`effective_to` set)
   - Different content = conflict → both kept (user resolves)
   - Rebuilds the compact always-on index

3. **recall_memories** searches both:
   - `mem0` memories (semantic, conversation-derived)
   - `memory_items` (structured: decisions, constraints, metrics, personas)

### What Gets Remembered

| Phase | Extracted Types | Example |
|-------|----------------|---------|
| Research | metrics, constraints | "80% cite onboarding friction", "Must support SSO" |
| PRD | decisions, constraints, metrics | "Build wizard before API", "Target: 50% reduction in time-to-first-value" |
| Tickets | decisions | "Sprint 1: onboarding epic (21 points)" |
| Full conversation | mem0 memories | Deduped facts, preferences, open questions |

### Testing Memory Across Sessions

```bash
# Session 1
python -m backend.agents.cli ./interviews/ --project-id my-project
> What are the main pain points?
> yes
> approve
/decisions   # see what was extracted
/quit        # auto-saves to memory

# Session 2 — same project-id, recalls Session 1
python -m backend.agents.cli ./interviews/ --project-id my-project
> Create a PRD for onboarding improvements
# Agent now sees: "80% cite onboarding friction" from Session 1
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
