# Customer Interview Agent — Implementation Plan

## Context & Inspiration

**Article 1 — Thariq's "Seeing like an Agent"**: Key patterns to adopt:
- **AskUserQuestion pattern**: Structured user elicitation with multiple-choice options that block the agent loop until answered (we build an equivalent `wait_for_input` node)
- **TodoWrite → Task evolution**: Mutable task lists shared across sub-agents, where the model can alter/delete tasks rather than being locked into the original plan
- **Dynamic context building**: Instead of dumping everything into context, let the agent use tools (grep-like retrieval) to progressively build its own context, fetching what it needs just-in-time
- **Progressive disclosure**: Only surface the right information at the right time

**Article 2 — Hierarchical agent architecture**: Deploy a coordinator that dispatches specialized sub-agents for deep research, context assembly, PRD generation, and ticket creation.

---

## Architecture Overview

```
                        ┌─────────────────────────┐
                        │   Orchestrator Agent     │
                        │   (interview_graph.py)   │
                        │                          │
                        │  State: InterviewState   │
                        │  Human-in-the-loop       │
                        └─────────┬───────────────┘
                                  │
              ┌───────────┬───────┴───────┬──────────────┐
              ▼           ▼               ▼              ▼
     ┌──────────────┐ ┌──────────┐ ┌───────────┐ ┌──────────────┐
     │  Research    │ │ Context  │ │   PRD     │ │   Ticket     │
     │  Agent      │ │ Fetcher  │ │ Generator │ │   Creator    │
     │             │ │  Agent   │ │   Agent   │ │   Agent      │
     └──────────────┘ └──────────┘ └───────────┘ └──────────────┘
```

The **Orchestrator** is a LangGraph `StateGraph` with human-in-the-loop interrupts. It:
1. Ingests customer interviews/feedback/market context
2. Waits for user questions (interrupt node)
3. Routes to sub-agents based on the question type
4. Maintains a shared task list the user confirms
5. Produces PRDs with KPIs, then creates tickets

---

## File Plan

### New Files (8 files)

```
backend/
├── agents/
│   ├── __init__.py                   # Package init
│   ├── state.py                      # Shared InterviewState TypedDict + TaskItem model
│   ├── orchestrator.py               # Main LangGraph orchestrator with human-in-the-loop
│   ├── research_agent.py             # Deep research sub-agent (product + web + quantification)
│   ├── context_agent.py              # Dynamic context fetcher sub-agent
│   ├── prd_agent.py                  # PRD generator sub-agent (KPIs, actions, citations)
│   └── ticket_agent.py              # Ticket creator sub-agent (epics → stories → tasks)
├── routers/
│   └── interview.py                  # FastAPI router: /api/interview/*
└── schemas/
    └── (extend models.py)            # New request/response models for interview endpoints
```

### Modified Files (2 files)

```
backend/main.py                       # Register new interview router
backend/schemas/models.py             # Add Interview* request/response schemas
```

### New DB Migration (1 file)

```
db/migrations/
└── 0003_interview_agent.sql          # interview_sessions, tasks, prd_documents, tickets tables
```

---

## Detailed Implementation Steps

### Step 1: Database Migration — `0003_interview_agent.sql`

New tables:

**`interview_sessions`** — tracks each orchestrator run
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| project_id | uuid FK → projects | |
| user_id | text | PM running the session |
| status | text | `intake`, `waiting`, `researching`, `generating`, `complete` |
| interview_data | jsonb | Raw interview transcripts/feedback ingested |
| market_context | jsonb | Market data provided by user |
| current_question | text | The user's current question/directive |
| research_results | jsonb | Accumulated research from sub-agent |
| context_pack | jsonb | Dynamic context assembled by context agent |
| created_at | timestamptz | |
| updated_at | timestamptz | |

**`interview_tasks`** — the shared task list (user-confirmable)
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| session_id | uuid FK → interview_sessions | |
| title | text | Task name |
| description | text | What needs to be done |
| status | text | `proposed`, `confirmed`, `in_progress`, `completed`, `rejected` |
| priority | int | 1–5 |
| agent | text | Which sub-agent owns this |
| output | jsonb | Result when completed |
| created_at | timestamptz | |
| updated_at | timestamptz | |

**`prd_documents`** — generated PRDs
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| session_id | uuid FK → interview_sessions | |
| project_id | uuid FK → projects | |
| title | text | PRD title |
| content | text | Full PRD markdown |
| kpis | jsonb | Array of {metric, target, measurement_method} |
| next_actions | jsonb | Array of {action, owner, deadline} |
| cited_chunk_ids | uuid[] | Evidence citations |
| cited_memory_ids | uuid[] | Memory citations |
| validation_status | text | `draft`, `validated`, `approved` |
| created_at | timestamptz | |

**`tickets`** — implementation tickets created from PRD
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| prd_id | uuid FK → prd_documents | |
| session_id | uuid FK → interview_sessions | |
| project_id | uuid FK → projects | |
| ticket_type | text | `epic`, `story`, `task`, `bug` |
| title | text | |
| description | text | Full ticket body |
| acceptance_criteria | jsonb | Array of strings |
| priority | text | `critical`, `high`, `medium`, `low` |
| estimated_points | int | Story points |
| parent_ticket_id | uuid FK → tickets (self-ref) | For epic→story→task hierarchy |
| labels | text[] | Tags |
| created_at | timestamptz | |

---

### Step 2: Shared State — `backend/agents/state.py`

```python
class TaskItem(TypedDict):
    id: str
    title: str
    description: str
    status: str           # proposed | confirmed | in_progress | completed | rejected
    priority: int
    agent: str            # research | context | prd | ticket
    output: dict | None

class InterviewState(TypedDict):
    # Session identity
    session_id: str
    project_id: str
    user_id: str

    # Inputs
    interview_data: list[dict]       # Raw transcripts/feedback
    market_context: str              # Market context provided by user
    current_question: str            # User's current question/directive

    # Task list (user-confirmable, mutable)
    tasks: list[TaskItem]
    tasks_pending_confirmation: bool # True when tasks need user approval

    # Sub-agent outputs
    research_results: dict           # From research agent
    context_pack: dict               # From context agent
    prd_document: dict               # From PRD agent
    tickets: list[dict]              # From ticket agent

    # Control flow
    phase: str                       # intake | waiting | planning | researching | generating | ticketing | complete
    iteration: int
    user_response: dict | None       # Structured response from user (like AskUserQuestion)
    error: str | None
```

---

### Step 3: Orchestrator — `backend/agents/orchestrator.py`

LangGraph StateGraph with this topology:

```
    intake_node
        │
    wait_for_input  ◄───────────────────────────┐
        │                                        │
    analyze_question                             │
        │                                        │
    plan_tasks                                   │
        │                                        │
    confirm_tasks (interrupt — wait for user)    │
        │                                        │
    ┌───┴───┐                                    │
    │ dispatch_agents (parallel fan-out)          │
    │   ├── run_research_agent                   │
    │   └── run_context_agent                    │
    └───┬───┘                                    │
        │                                        │
    generate_prd                                 │
        │                                        │
    review_prd (interrupt — wait for user)       │
        │                                        │
    [user approves?]─── NO ─────────────────────┘
        │ YES
    create_tickets
        │
    present_results (interrupt — wait for user)
        │
    [continue?]──── YES ────────────────────────┘
        │ NO
       END
```

Key design decisions (inspired by Thariq's article):
- **Interrupt nodes** for `wait_for_input`, `confirm_tasks`, `review_prd`, `present_results` — blocks execution until user responds (like AskUserQuestion)
- **Task list is mutable** — the orchestrator proposes tasks, user confirms/rejects/modifies, agents can add new tasks as they discover work (like TodoWrite → Task evolution)
- **Fan-out dispatch** — research and context agents run in parallel before PRD generation
- **Loop-back** — after presenting results, user can ask a follow-up question, looping back to `wait_for_input`

---

### Step 4: Research Agent — `backend/agents/research_agent.py`

Responsible for deep research to quantify and validate PRD assumptions.

**Tools available to this agent:**
1. `semantic_search` — search project chunks for evidence
2. `hybrid_search` — combined vector + keyword retrieval
3. `memory_search` — retrieve past decisions, constraints, metrics
4. `web_search` — search the web for market data, benchmarks, competitor info (new tool, uses an HTTP search API)
5. `quantify_opportunity` — run the existing opportunity scoring pipeline on specific themes

**Behavior:**
- Takes the user's question + interview data + market context
- Identifies claims that need validation (e.g., "users want X" → find supporting/contradicting evidence)
- Searches internal sources first, then web for market validation
- Returns structured research results: `{validated_claims, contradictions, market_data, quantified_metrics, evidence_citations}`

**Implementation:** A self-contained LangGraph sub-graph:
```
plan_research → search_internal → search_web → quantify → synthesize_findings
```

---

### Step 5: Context Agent — `backend/agents/context_agent.py`

Dynamic context fetcher inspired by the Claude Code pattern — doesn't dump everything in context, but progressively discovers and assembles the right context.

**Tools available:**
1. `get_context_pack` — existing context assembly with token budgeting
2. `hybrid_search_chunks` — targeted evidence retrieval
3. `hybrid_search_memory_items` — retrieve constraints, decisions, personas
4. `get_project_sources` — list available sources
5. `get_memory_index` — compact always-on index

**Behavior:**
- Takes the user's question + task list
- Determines what context is needed (not pre-loading everything)
- Makes targeted searches to build the right context progressively
- Respects token budgets
- Returns: `{assembled_context, memory_items, evidence_chunks, citations, token_usage}`

**Implementation:** Uses existing `context_pack.py` + `hybrid_search.py` services, wrapped in a focused retrieval loop:
```
assess_needs → fetch_index → targeted_search → assemble_context → validate_budget
```

---

### Step 6: PRD Agent — `backend/agents/prd_agent.py`

Generates structured, evidence-backed PRDs.

**Inputs:** Research results + assembled context + user's question + task list

**Output structure:**
```
PRD Document:
├── Title
├── Problem Statement (cited from interviews)
├── User Stories (derived from interview themes)
├── Proposed Solution
├── Success Metrics / KPIs
│   ├── metric name
│   ├── target value (quantified from research)
│   └── measurement method
├── Technical Requirements
├── Constraints & Risks (from memory layer)
├── Next Actions
│   ├── action description
│   ├── owner
│   └── suggested timeline
└── Evidence Citations (chunk_ids, memory_ids)
```

**Validation:** Uses existing `prd_has_required_sections()` + `evidence_integrity_from_rows()` to ensure PRD quality and citation integrity.

**Implementation:** Single strong-model call with structured output parsing, followed by validation:
```
assemble_prompt → generate_prd → parse_structured → validate → persist
```

---

### Step 7: Ticket Agent — `backend/agents/ticket_agent.py`

Breaks PRDs down into implementation tickets.

**Input:** Validated PRD document

**Output:** Hierarchical ticket structure:
```
Epic: "Feature Name"
├── Story: "As a [user], I want [feature]..."
│   ├── Task: "Implement API endpoint for..."
│   │   └── acceptance_criteria: [...]
│   ├── Task: "Add frontend component..."
│   │   └── acceptance_criteria: [...]
│   └── Task: "Write integration tests..."
├── Story: "As a [user], I want [another feature]..."
│   └── ...
```

**Implementation:** Single strong-model call with structured output:
```
analyze_prd → generate_ticket_hierarchy → validate → persist
```

---

### Step 8: FastAPI Router — `backend/routers/interview.py`

New endpoints:

```
POST   /api/interview/sessions              # Create new interview session (ingest data)
GET    /api/interview/sessions/{id}         # Get session state
POST   /api/interview/sessions/{id}/ask     # Submit a question (resume the graph)
POST   /api/interview/sessions/{id}/confirm # Confirm/reject proposed tasks
POST   /api/interview/sessions/{id}/review  # Approve/request changes to PRD
GET    /api/interview/sessions/{id}/tasks   # Get current task list
GET    /api/interview/sessions/{id}/prd     # Get generated PRD
GET    /api/interview/sessions/{id}/tickets # Get generated tickets
```

The router uses LangGraph's `interrupt` / `resume` pattern:
- `POST /ask` sends user input → resumes graph at `wait_for_input`
- `POST /confirm` sends task confirmations → resumes graph at `confirm_tasks`
- `POST /review` sends PRD feedback → resumes graph at `review_prd`

---

### Step 9: Schema Extensions — `backend/schemas/models.py`

New Pydantic models:

```python
# Interview session
InterviewSessionCreate      # project_id, user_id, interview_data, market_context
InterviewSessionResponse    # full session state

# User interaction
InterviewAskRequest         # question: str
InterviewConfirmRequest     # task_decisions: [{task_id, decision: confirmed|rejected}]
InterviewReviewRequest      # approved: bool, feedback: str | None

# Outputs
TaskItemResponse            # id, title, description, status, priority, agent, output
PRDDocumentResponse         # title, content, kpis, next_actions, citations, validation_status
TicketResponse              # ticket_type, title, description, acceptance_criteria, etc.
TicketTreeResponse          # hierarchical: epics containing stories containing tasks
```

---

### Step 10: Register Router — `backend/main.py`

Add:
```python
from backend.routers import interview
app.include_router(interview.router)
```

---

## Implementation Order (Build Sequence)

| # | Task | Files | Depends On |
|---|------|-------|------------|
| 1 | DB migration | `db/migrations/0003_interview_agent.sql` | — |
| 2 | Shared state + task model | `backend/agents/__init__.py`, `state.py` | — |
| 3 | Context agent | `backend/agents/context_agent.py` | Step 2 |
| 4 | Research agent | `backend/agents/research_agent.py` | Step 2 |
| 5 | PRD agent | `backend/agents/prd_agent.py` | Step 2 |
| 6 | Ticket agent | `backend/agents/ticket_agent.py` | Step 2 |
| 7 | Orchestrator graph | `backend/agents/orchestrator.py` | Steps 3–6 |
| 8 | Pydantic schemas | `backend/schemas/models.py` | Step 2 |
| 9 | FastAPI router | `backend/routers/interview.py` | Steps 7–8 |
| 10 | Register router | `backend/main.py` | Step 9 |

Steps 3–6 can be built **in parallel** since they're independent sub-agents that only depend on the shared state definition.

---

## Key Design Principles

1. **Human-in-the-loop at every critical juncture** — The orchestrator never auto-proceeds past intake, task confirmation, or PRD review without user approval.

2. **Mutable task lists** — Tasks are proposed by the orchestrator, confirmed by the user, and can be modified by sub-agents as they discover new work. This follows Thariq's insight that rigid todo lists become constraining as the agent gets smarter.

3. **Dynamic context over static dumps** — The context agent progressively builds context using targeted searches rather than loading everything upfront. This prevents context rot and respects token budgets.

4. **Evidence-grounded outputs** — Every PRD claim must cite a chunk_id or memory_id. The existing `prd_has_required_sections()` and `evidence_integrity_from_rows()` validators are reused.

5. **Reuse existing infrastructure** — All sub-agents build on the existing services (semantic_search, hybrid_search, context_pack, memory, llm provider abstraction). No reinventing the wheel.

6. **Provider-agnostic** — Uses the existing `get_fast_llm()` / `get_strong_llm()` factory. Works with any configured provider.

7. **Parallel sub-agent dispatch** — Research and context agents run concurrently, then their outputs feed into PRD generation. This mirrors the hierarchical fan-out pattern.
