"""Ticket Creator sub-agent.

Takes a validated PRD and breaks it into a hierarchical ticket structure:
  Epic → Story → Task

Each ticket has acceptance criteria, priority, and estimated story points.
"""

from __future__ import annotations

import json
import re
import uuid

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.state import InterviewState
from backend.services.llm import get_strong_llm


_TICKET_GENERATION_PROMPT = """\
You are a technical project manager breaking a PRD into implementation tickets.

Given a PRD, create a hierarchical ticket structure with:
- 1-3 Epics (high-level feature areas)
- 2-4 Stories per Epic (user-facing capabilities)
- 1-4 Tasks per Story (concrete implementation work)

Return a JSON array of ticket objects:
[
  {
    "ticket_type": "epic",
    "title": "Epic title",
    "description": "Epic description",
    "acceptance_criteria": ["Criterion 1"],
    "priority": "high",
    "estimated_points": null,
    "labels": ["feature-area"],
    "children": [
      {
        "ticket_type": "story",
        "title": "As a [user], I want...",
        "description": "Story description with context",
        "acceptance_criteria": ["AC 1", "AC 2"],
        "priority": "high",
        "estimated_points": 5,
        "labels": ["frontend"],
        "children": [
          {
            "ticket_type": "task",
            "title": "Implement X",
            "description": "Technical description",
            "acceptance_criteria": ["Unit tests pass", "API returns 200"],
            "priority": "medium",
            "estimated_points": 2,
            "labels": ["backend", "api"]
          }
        ]
      }
    ]
  }
]

Guidelines:
- Story points: 1 (trivial), 2 (small), 3 (medium), 5 (large), 8 (very large)
- Acceptance criteria must be testable and specific
- Labels should reflect technical domain (frontend, backend, api, database, infra, design)
- Priorities: critical, high, medium, low
- Task descriptions should be specific enough for a developer to start immediately"""


def _flatten_tickets(
    tickets: list[dict],
    parent_id: str | None = None,
) -> list[dict]:
    """Flatten nested ticket structure into a flat list with parent_id references."""
    flat: list[dict] = []
    for ticket in tickets:
        ticket_id = str(uuid.uuid4())
        children = ticket.pop("children", [])

        flat_ticket = {
            "id": ticket_id,
            "ticket_type": ticket.get("ticket_type", "task"),
            "title": ticket.get("title", ""),
            "description": ticket.get("description", ""),
            "acceptance_criteria": ticket.get("acceptance_criteria", []),
            "priority": ticket.get("priority", "medium"),
            "estimated_points": ticket.get("estimated_points"),
            "parent_id": parent_id,
            "labels": ticket.get("labels", []),
        }
        flat.append(flat_ticket)

        if children:
            flat.extend(_flatten_tickets(children, parent_id=ticket_id))

    return flat


def _render_tickets_text(tickets: list[dict]) -> str:
    """Render tickets as readable text for CLI display."""
    lines: list[str] = []
    epics = [t for t in tickets if t["ticket_type"] == "epic"]

    for epic in epics:
        lines.append(f"\n{'='*60}")
        lines.append(f"EPIC: {epic['title']}")
        lines.append(f"  Priority: {epic['priority']}")
        lines.append(f"  {epic['description'][:200]}")

        stories = [t for t in tickets if t.get("parent_id") == epic["id"]]
        for story in stories:
            pts = f" [{story['estimated_points']}pts]" if story.get("estimated_points") else ""
            lines.append(f"\n  STORY: {story['title']}{pts}")
            lines.append(f"    Priority: {story['priority']}")
            if story.get("acceptance_criteria"):
                for ac in story["acceptance_criteria"]:
                    lines.append(f"    - [ ] {ac}")

            tasks = [t for t in tickets if t.get("parent_id") == story["id"]]
            for task in tasks:
                pts = f" [{task['estimated_points']}pts]" if task.get("estimated_points") else ""
                lines.append(f"\n    TASK: {task['title']}{pts}")
                lines.append(f"      Priority: {task['priority']}")
                if task.get("labels"):
                    lines.append(f"      Labels: {', '.join(task['labels'])}")
                if task.get("acceptance_criteria"):
                    for ac in task["acceptance_criteria"]:
                        lines.append(f"      - [ ] {ac}")

    # Summary stats
    total = len(tickets)
    total_pts = sum(t.get("estimated_points") or 0 for t in tickets)
    lines.append(f"\n{'='*60}")
    lines.append(f"Total: {total} tickets, {total_pts} story points")

    return "\n".join(lines)


def run_ticket_agent(state: InterviewState) -> list[dict]:
    """Entry point called by the orchestrator.

    Returns a flat list of TicketItem dicts with parent_id references.

    LLM response is cached by sha256(prd_content) so the same PRD never
    triggers a second API call within or across sessions.
    """
    import hashlib
    from backend.services import cache_manager

    prd = state.get("prd_document", {})

    if not prd:
        return []

    # Build prompt from PRD
    prd_text = prd.get("full_markdown", "")
    if not prd_text:
        # Reconstruct from fields
        parts = [f"Title: {prd.get('title', '')}"]
        if prd.get("problem_statement"):
            parts.append(f"Problem: {prd['problem_statement']}")
        stories = prd.get("user_stories", [])
        if stories:
            parts.append("User Stories:\n" + "\n".join(f"- {s}" for s in stories))
        reqs = prd.get("technical_requirements", [])
        if reqs:
            parts.append("Requirements:\n" + "\n".join(f"- {r}" for r in reqs))
        actions = prd.get("next_actions", [])
        if actions:
            parts.append("Next Actions:\n" + "\n".join(
                f"- {a.get('action', '')} ({a.get('owner', '')})" for a in actions
            ))
        prd_text = "\n\n".join(parts)

    # Check LLM response cache (keyed on PRD content hash)
    prd_hash = hashlib.sha256(prd_text.encode()).hexdigest()
    cached_response = cache_manager.get_llm_response(prd_hash)
    if cached_response:
        try:
            nested_tickets = json.loads(cached_response)
            if isinstance(nested_tickets, list):
                return _flatten_tickets(nested_tickets)
        except (json.JSONDecodeError, TypeError):
            pass  # corrupt cache — regenerate

    llm = get_strong_llm()
    response = llm.invoke([
        SystemMessage(content=_TICKET_GENERATION_PROMPT),
        HumanMessage(content=f"PRD:\n\n{prd_text}"),
    ])

    raw_content = response.content if isinstance(response.content, str) else str(response.content)

    # Parse response
    try:
        nested_tickets = json.loads(raw_content)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw_content)
        if match:
            try:
                nested_tickets = json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                nested_tickets = []
        else:
            nested_tickets = []

    if not isinstance(nested_tickets, list):
        nested_tickets = [nested_tickets] if nested_tickets else []

    # Cache the successful LLM response
    if nested_tickets:
        cache_manager.store_llm_response(prd_hash, json.dumps(nested_tickets))

    # Flatten into ticket list
    return _flatten_tickets(nested_tickets)


def render_tickets(tickets: list[dict]) -> str:
    """Public helper to render tickets as text."""
    return _render_tickets_text(tickets)
