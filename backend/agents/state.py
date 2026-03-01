"""Shared state definitions for the interview agent graph.

InterviewState is the single TypedDict flowing through every node in the
orchestrator LangGraph.  Sub-agents read from and write to slices of this
state so they stay decoupled from each other.
"""

from __future__ import annotations

import uuid
from typing import TypedDict


# ── Task item (the mutable, user-confirmable task list) ──────────────────

class TaskItem(TypedDict):
    id: str
    title: str
    description: str
    status: str        # proposed | confirmed | in_progress | completed | rejected
    priority: int      # 1 (highest) – 5 (lowest)
    agent: str         # orchestrator | research | context | prd | ticket
    output: dict | None


def make_task(
    title: str,
    description: str = "",
    agent: str = "orchestrator",
    priority: int = 3,
) -> TaskItem:
    """Helper to create a new proposed task."""
    return TaskItem(
        id=str(uuid.uuid4()),
        title=title,
        description=description,
        status="proposed",
        priority=priority,
        agent=agent,
        output=None,
    )


# ── KPI / Next-action helpers ────────────────────────────────────────────

class KPIItem(TypedDict):
    metric: str
    target: str
    measurement_method: str


class NextAction(TypedDict):
    action: str
    owner: str
    timeline: str


# ── PRD document structure ───────────────────────────────────────────────

class PRDDocument(TypedDict):
    title: str
    problem_statement: str
    user_stories: list[str]
    proposed_solution: str
    kpis: list[KPIItem]
    technical_requirements: list[str]
    constraints_and_risks: list[str]
    next_actions: list[NextAction]
    cited_chunk_ids: list[str]
    cited_memory_ids: list[str]
    full_markdown: str


# ── Ticket structure ─────────────────────────────────────────────────────

class TicketItem(TypedDict):
    id: str
    ticket_type: str      # epic | story | task | bug
    title: str
    description: str
    acceptance_criteria: list[str]
    priority: str          # critical | high | medium | low
    estimated_points: int | None
    parent_id: str | None  # links story→epic, task→story
    labels: list[str]


# ── Master orchestrator state ────────────────────────────────────────────

class InterviewState(TypedDict):
    # Session identity
    session_id: str
    project_id: str
    user_id: str

    # Inputs
    interview_data: list[dict]      # parsed interview docs [{filename, content, metadata}]
    market_context: str             # free-text or structured market context
    current_question: str           # the user's latest question / directive

    # Task list (mutable, user-confirmable)
    tasks: list[TaskItem]
    tasks_pending_confirmation: bool

    # Sub-agent outputs
    research_results: dict          # from research agent
    context_pack: dict              # from context agent
    prd_document: dict              # from PRD agent (PRDDocument-shaped)
    tickets: list[dict]             # from ticket agent (list of TicketItem)

    # Memory (populated by memory hooks)
    recalled_memories: list[dict]   # past decisions/constraints injected at session start

    # Control flow
    phase: str                      # intake|waiting|planning|researching|generating|ticketing|complete
    iteration: int
    user_response: dict | None      # structured response from user at interrupt points
    messages: list[dict]            # conversation log [{role, content}]
    error: str | None
