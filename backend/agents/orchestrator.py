"""Orchestrator — the main LangGraph agent loop.

Implements a human-in-the-loop REPL-style graph:

  intake → wait_for_input → analyze → plan_tasks → confirm_tasks
       → dispatch_agents → generate_prd → review_prd → create_tickets
       → present_results → (loop back to wait_for_input)

Each "wait" node is an interrupt point where the graph pauses and
returns control to the caller (CLI or API).  The caller feeds user
input back via `resume()`.

This is inspired by:
  - Thariq's AskUserQuestion pattern (structured interrupts)
  - TodoWrite → Task evolution (mutable, shared task lists)
  - Claude Code's dynamic context building (just-in-time fetching)
"""

from __future__ import annotations

import json
import uuid
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.state import InterviewState, TaskItem, make_task
from backend.agents.context_agent import run_context_agent
from backend.agents.research_agent import run_research_agent
from backend.agents.prd_agent import run_prd_agent
from backend.agents.ticket_agent import run_ticket_agent
from backend.services.llm import get_fast_llm


# ── Prompts ──────────────────────────────────────────────────────────────

_ANALYSIS_PROMPT = """\
You are a product management AI analysing a PM's question about their product.

Given the question and available interview data, determine:
1. What type of work is needed (research, PRD generation, ticket creation, general analysis)
2. What specific tasks should be created to answer this question

Return a JSON object:
{
  "question_type": "research|prd|tickets|analysis|full_pipeline",
  "reasoning": "Why this classification",
  "suggested_tasks": [
    {
      "title": "Task title",
      "description": "What this task involves",
      "agent": "research|context|prd|ticket",
      "priority": 1-5
    }
  ]
}

Guidelines:
- If the question asks about user needs, pain points, or market data → research
- If the question asks to create or write a PRD → prd (which implies research first)
- If the question asks to break down work or create tickets → tickets (which implies prd first)
- If the question is broad ("analyse these interviews") → full_pipeline
- For full_pipeline, suggest tasks for research, prd, and tickets"""


# ── Graph nodes ──────────────────────────────────────────────────────────

def intake_node(state: InterviewState) -> dict:
    """Process initial interview data and prepare session."""
    interview_data = state.get("interview_data", [])
    total_words = sum(
        d.get("metadata", {}).get("word_count", 0) for d in interview_data
    )
    total_files = len(interview_data)

    messages = state.get("messages", [])
    messages.append({
        "role": "assistant",
        "content": (
            f"Loaded {total_files} interview file(s) ({total_words:,} words total). "
            f"I'm ready to analyse them. What would you like to explore?"
        ),
    })

    return {
        "phase": "waiting",
        "messages": messages,
        "iteration": 0,
    }


def analyze_question_node(state: InterviewState) -> dict:
    """Analyse the user's question and classify the work needed."""
    question = state["current_question"]
    interview_data = state.get("interview_data", [])

    # Summarise interviews for context
    summaries = []
    for doc in interview_data:
        meta = doc.get("metadata", {})
        summaries.append(f"- {doc.get('filename', '?')}: {meta.get('word_count', 0)} words")
    interview_summary = "\n".join(summaries) if summaries else "No interviews loaded."

    llm = get_fast_llm()
    response = llm.invoke([
        SystemMessage(content=_ANALYSIS_PROMPT),
        HumanMessage(content=(
            f"PM Question: {question}\n\n"
            f"Available interviews:\n{interview_summary}"
        )),
    ])

    try:
        analysis = json.loads(response.content)
    except (json.JSONDecodeError, TypeError):
        import re
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response.content)
        if match:
            try:
                analysis = json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                analysis = {
                    "question_type": "full_pipeline",
                    "reasoning": "Could not parse analysis; running full pipeline.",
                    "suggested_tasks": [],
                }
        else:
            analysis = {
                "question_type": "full_pipeline",
                "reasoning": "Could not parse analysis; running full pipeline.",
                "suggested_tasks": [],
            }

    return {
        "phase": "planning",
        "user_response": analysis,
    }


def plan_tasks_node(state: InterviewState) -> dict:
    """Create the task list based on question analysis."""
    analysis = state.get("user_response", {})
    question_type = analysis.get("question_type", "full_pipeline")
    suggested = analysis.get("suggested_tasks", [])

    tasks: list[TaskItem] = []

    if suggested:
        for s in suggested:
            tasks.append(make_task(
                title=s.get("title", "Unnamed task"),
                description=s.get("description", ""),
                agent=s.get("agent", "orchestrator"),
                priority=s.get("priority", 3),
            ))
    else:
        # Default task plans by question type
        if question_type in ("research", "full_pipeline", "analysis"):
            tasks.append(make_task(
                title="Deep research on interview data",
                description="Extract claims, validate with evidence, quantify metrics",
                agent="research",
                priority=1,
            ))
            tasks.append(make_task(
                title="Assemble relevant context",
                description="Fetch context from interviews, memory, and project data",
                agent="context",
                priority=1,
            ))

        if question_type in ("prd", "full_pipeline"):
            tasks.append(make_task(
                title="Generate evidence-backed PRD",
                description="Create PRD with KPIs, user stories, and next actions",
                agent="prd",
                priority=2,
            ))

        if question_type in ("tickets", "full_pipeline"):
            tasks.append(make_task(
                title="Create implementation tickets",
                description="Break PRD into epics, stories, and tasks",
                agent="ticket",
                priority=3,
            ))

    messages = state.get("messages", [])
    reasoning = analysis.get("reasoning", "")
    task_summary = "\n".join(
        f"  {i}. [{t['agent']}] {t['title']}" for i, t in enumerate(tasks, 1)
    )
    messages.append({
        "role": "assistant",
        "content": (
            f"Analysis: {reasoning}\n\n"
            f"Proposed task plan:\n{task_summary}\n\n"
            f"Confirm these tasks? (yes/no, or modify)"
        ),
    })

    return {
        "tasks": tasks,
        "tasks_pending_confirmation": True,
        "phase": "planning",
        "messages": messages,
    }


def confirm_tasks_node(state: InterviewState) -> dict:
    """Process user confirmation of the task list.

    This is an interrupt point — the orchestrator pauses here
    and waits for user input.
    """
    user_response = state.get("user_response", {})
    response_text = str(user_response.get("text", "yes")).lower().strip()

    tasks = state.get("tasks", [])

    if response_text in ("yes", "y", "confirm", "ok", ""):
        for task in tasks:
            if task["status"] == "proposed":
                task["status"] = "confirmed"
    elif response_text in ("no", "n", "reject"):
        for task in tasks:
            task["status"] = "rejected"
        messages = state.get("messages", [])
        messages.append({
            "role": "assistant",
            "content": "Tasks rejected. What would you like to do instead?",
        })
        return {
            "tasks": tasks,
            "tasks_pending_confirmation": False,
            "phase": "waiting",
            "messages": messages,
        }
    else:
        # Treat as modification — keep existing tasks, add note
        messages = state.get("messages", [])
        messages.append({
            "role": "assistant",
            "content": f"Noted: '{response_text}'. Proceeding with adjusted plan.",
        })
        for task in tasks:
            if task["status"] == "proposed":
                task["status"] = "confirmed"

    return {
        "tasks": tasks,
        "tasks_pending_confirmation": False,
        "phase": "researching",
    }


def dispatch_research_node(state: InterviewState) -> dict:
    """Run research + context agents (would run in parallel in production)."""
    tasks = state.get("tasks", [])
    messages = state.get("messages", [])

    # Mark research/context tasks as in_progress
    for task in tasks:
        if task["agent"] in ("research", "context") and task["status"] == "confirmed":
            task["status"] = "in_progress"

    messages.append({"role": "assistant", "content": "Running research and context agents..."})

    # Run context agent
    context_pack = run_context_agent(state)

    # Run research agent
    research_results = run_research_agent(state)

    # Mark tasks completed
    for task in tasks:
        if task["agent"] == "research" and task["status"] == "in_progress":
            task["status"] = "completed"
            task["output"] = {"claim_count": research_results.get("claim_count", 0)}
        if task["agent"] == "context" and task["status"] == "in_progress":
            task["status"] = "completed"

    summary = research_results.get("summary", "Research complete.")
    claim_count = research_results.get("claim_count", 0)
    evidence_count = research_results.get("internal_evidence_count", 0)

    messages.append({
        "role": "assistant",
        "content": (
            f"Research complete: {claim_count} claims extracted, "
            f"{evidence_count} evidence pieces found.\n\n"
            f"Summary: {summary[:500]}"
        ),
    })

    return {
        "research_results": research_results,
        "context_pack": context_pack,
        "tasks": tasks,
        "messages": messages,
    }


def generate_prd_node(state: InterviewState) -> dict:
    """Run the PRD generator agent."""
    tasks = state.get("tasks", [])
    messages = state.get("messages", [])

    # Check if PRD generation is in the task list
    prd_tasks = [t for t in tasks if t["agent"] == "prd" and t["status"] == "confirmed"]
    if not prd_tasks:
        return {"phase": "complete"}

    for task in tasks:
        if task["agent"] == "prd" and task["status"] == "confirmed":
            task["status"] = "in_progress"

    messages.append({"role": "assistant", "content": "Generating PRD..."})

    prd = run_prd_agent(state)

    for task in tasks:
        if task["agent"] == "prd" and task["status"] == "in_progress":
            task["status"] = "completed"
            task["output"] = {"title": prd.get("title", "")}

    messages.append({
        "role": "assistant",
        "content": (
            f"PRD generated: **{prd.get('title', 'Untitled')}**\n\n"
            f"{prd.get('full_markdown', '')[:1000]}...\n\n"
            f"Review this PRD? (approve/revise/skip)"
        ),
    })

    return {
        "prd_document": prd,
        "tasks": tasks,
        "phase": "generating",
        "messages": messages,
    }


def review_prd_node(state: InterviewState) -> dict:
    """Process user review of the PRD. Interrupt point."""
    user_response = state.get("user_response", {})
    response_text = str(user_response.get("text", "approve")).lower().strip()
    messages = state.get("messages", [])

    if response_text in ("approve", "yes", "y", "ok", ""):
        messages.append({"role": "assistant", "content": "PRD approved."})
        return {"phase": "ticketing", "messages": messages}
    elif response_text in ("skip", "s"):
        messages.append({"role": "assistant", "content": "PRD review skipped."})
        return {"phase": "ticketing", "messages": messages}
    else:
        # User wants revisions — loop back
        messages.append({
            "role": "assistant",
            "content": f"Noted feedback: '{response_text}'. Revising PRD...",
        })
        return {
            "current_question": f"Revise the PRD based on this feedback: {response_text}",
            "phase": "generating",
            "messages": messages,
        }


def create_tickets_node(state: InterviewState) -> dict:
    """Run the ticket creator agent."""
    tasks = state.get("tasks", [])
    messages = state.get("messages", [])

    ticket_tasks = [t for t in tasks if t["agent"] == "ticket" and t["status"] == "confirmed"]
    if not ticket_tasks:
        return {"phase": "complete"}

    for task in tasks:
        if task["agent"] == "ticket" and task["status"] == "confirmed":
            task["status"] = "in_progress"

    messages.append({"role": "assistant", "content": "Creating implementation tickets..."})

    tickets = run_ticket_agent(state)

    for task in tasks:
        if task["agent"] == "ticket" and task["status"] == "in_progress":
            task["status"] = "completed"
            task["output"] = {"ticket_count": len(tickets)}

    total_pts = sum(t.get("estimated_points") or 0 for t in tickets)
    messages.append({
        "role": "assistant",
        "content": (
            f"Created {len(tickets)} tickets ({total_pts} story points total).\n\n"
            f"Would you like to explore something else, or are we done?"
        ),
    })

    return {
        "tickets": tickets,
        "tasks": tasks,
        "phase": "complete",
        "messages": messages,
    }


def present_results_node(state: InterviewState) -> dict:
    """Final results node. User can loop back or end."""
    return {
        "phase": "complete",
        "iteration": state.get("iteration", 0) + 1,
    }


# ── Routing logic ────────────────────────────────────────────────────────

def should_generate_prd(state: InterviewState) -> Literal["generate_prd", "create_tickets", "complete"]:
    tasks = state.get("tasks", [])
    has_prd_task = any(t["agent"] == "prd" and t["status"] == "confirmed" for t in tasks)
    has_ticket_task = any(t["agent"] == "ticket" and t["status"] == "confirmed" for t in tasks)

    if has_prd_task:
        return "generate_prd"
    elif has_ticket_task:
        return "create_tickets"
    return "complete"


def should_create_tickets(state: InterviewState) -> Literal["create_tickets", "complete"]:
    tasks = state.get("tasks", [])
    has_ticket_task = any(t["agent"] == "ticket" and t["status"] == "confirmed" for t in tasks)
    return "create_tickets" if has_ticket_task else "complete"


def should_continue_after_confirm(state: InterviewState) -> Literal["dispatch_research", "waiting"]:
    tasks = state.get("tasks", [])
    has_confirmed = any(t["status"] == "confirmed" for t in tasks)
    return "dispatch_research" if has_confirmed else "waiting"


# ── Graph builder ────────────────────────────────────────────────────────

def build_interview_graph():
    """Build and compile the LangGraph orchestrator.

    Returns a compiled graph that can be invoked with InterviewState.
    """
    from langgraph.graph import StateGraph, START, END

    graph = StateGraph(InterviewState)

    # Add nodes
    graph.add_node("intake", intake_node)
    graph.add_node("analyze_question", analyze_question_node)
    graph.add_node("plan_tasks", plan_tasks_node)
    graph.add_node("confirm_tasks", confirm_tasks_node)
    graph.add_node("dispatch_research", dispatch_research_node)
    graph.add_node("generate_prd", generate_prd_node)
    graph.add_node("review_prd", review_prd_node)
    graph.add_node("create_tickets", create_tickets_node)
    graph.add_node("present_results", present_results_node)

    # Edges
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "analyze_question")
    graph.add_edge("analyze_question", "plan_tasks")
    graph.add_edge("plan_tasks", "confirm_tasks")
    graph.add_conditional_edges(
        "confirm_tasks",
        should_continue_after_confirm,
        {"dispatch_research": "dispatch_research", "waiting": END},
    )
    graph.add_conditional_edges(
        "dispatch_research",
        should_generate_prd,
        {
            "generate_prd": "generate_prd",
            "create_tickets": "create_tickets",
            "complete": "present_results",
        },
    )
    graph.add_edge("generate_prd", "review_prd")
    graph.add_conditional_edges(
        "review_prd",
        should_create_tickets,
        {"create_tickets": "create_tickets", "complete": "present_results"},
    )
    graph.add_edge("create_tickets", "present_results")
    graph.add_edge("present_results", END)

    return graph.compile()


# ── REPL-friendly runner ─────────────────────────────────────────────────

class InterviewSession:
    """Manages a stateful interview agent session with REPL-style interaction.

    Usage:
        session = InterviewSession(interview_data=[...])
        session.start()               # initial intake
        session.ask("What are the top user pain points?")  # run full pipeline
        session.ask("Create a PRD for the onboarding flow")
    """

    def __init__(
        self,
        interview_data: list[dict] | None = None,
        market_context: str = "",
        project_id: str = "",
        user_id: str = "cli-user",
    ):
        self.state: InterviewState = {
            "session_id": str(uuid.uuid4()),
            "project_id": project_id or str(uuid.uuid4()),
            "user_id": user_id,
            "interview_data": interview_data or [],
            "market_context": market_context,
            "current_question": "",
            "tasks": [],
            "tasks_pending_confirmation": False,
            "research_results": {},
            "context_pack": {},
            "prd_document": {},
            "tickets": [],
            "phase": "intake",
            "iteration": 0,
            "user_response": None,
            "messages": [],
            "error": None,
        }
        self.graph = build_interview_graph()

    def start(self) -> list[dict]:
        """Run the intake node and return messages."""
        self.state = self.graph.invoke(self.state)
        return self._new_messages()

    def ask(self, question: str, auto_confirm: bool = False) -> list[dict]:
        """Submit a question and run the full pipeline.

        If auto_confirm=True, tasks are auto-confirmed without waiting.
        Otherwise the pipeline pauses at confirm_tasks and the caller
        should call confirm() / reject().
        """
        self.state["current_question"] = question
        self.state["phase"] = "waiting"
        self.state["user_response"] = None
        self.state["messages"].append({"role": "user", "content": question})

        # Run analysis + planning
        self.state = {**self.state, **analyze_question_node(self.state)}
        self.state = {**self.state, **plan_tasks_node(self.state)}

        if auto_confirm:
            self.state["user_response"] = {"text": "yes"}
            self.state = {**self.state, **confirm_tasks_node(self.state)}

            if self.state["phase"] == "researching":
                self.state = {**self.state, **dispatch_research_node(self.state)}
                self.state = {**self.state, **generate_prd_node(self.state)}

                if self.state.get("prd_document"):
                    self.state["user_response"] = {"text": "approve"}
                    self.state = {**self.state, **review_prd_node(self.state)}

                    if self.state["phase"] == "ticketing":
                        self.state = {**self.state, **create_tickets_node(self.state)}

                self.state = {**self.state, **present_results_node(self.state)}

        return self._new_messages()

    def confirm(self, response: str = "yes") -> list[dict]:
        """Confirm or modify the proposed task list."""
        self.state["user_response"] = {"text": response}
        self.state["messages"].append({"role": "user", "content": response})
        self.state = {**self.state, **confirm_tasks_node(self.state)}

        if self.state["phase"] == "researching":
            self.state = {**self.state, **dispatch_research_node(self.state)}
            self.state = {**self.state, **generate_prd_node(self.state)}

        return self._new_messages()

    def review_prd(self, response: str = "approve") -> list[dict]:
        """Approve or request revision of the generated PRD."""
        self.state["user_response"] = {"text": response}
        self.state["messages"].append({"role": "user", "content": response})
        self.state = {**self.state, **review_prd_node(self.state)}

        if self.state["phase"] == "ticketing":
            self.state = {**self.state, **create_tickets_node(self.state)}

        self.state = {**self.state, **present_results_node(self.state)}
        return self._new_messages()

    def get_tasks(self) -> list[TaskItem]:
        """Return current task list."""
        return self.state.get("tasks", [])

    def get_prd(self) -> dict:
        """Return the generated PRD."""
        return self.state.get("prd_document", {})

    def get_tickets(self) -> list[dict]:
        """Return generated tickets."""
        return self.state.get("tickets", [])

    def get_phase(self) -> str:
        """Return current orchestrator phase."""
        return self.state.get("phase", "unknown")

    def _new_messages(self) -> list[dict]:
        """Return only assistant messages from the latest interaction."""
        return [m for m in self.state.get("messages", []) if m["role"] == "assistant"]
