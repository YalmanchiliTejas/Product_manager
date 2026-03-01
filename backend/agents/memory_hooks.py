"""Memory hooks for the interview agent.

Three hooks wire the interview orchestrator into the existing memory system:

Hook 1 — Session Start / New Question
    Recall past decisions, constraints, and metrics from both mem0 and
    memory_items, then inject them into state.messages so every sub-agent
    sees prior context.

Hook 2 — After Each Phase
    Extract structured memory items (decisions, constraints, metrics,
    personas) from research results, PRD outputs, and ticket snapshots.
    Uses LLM-powered type inference and writes directly to memory_items.

Hook 3 — Session End
    Feed the full conversation to mem0 (add_memories), run consolidation
    + supersede to deduplicate, and rebuild the compact index.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.state import InterviewState
from backend.services.llm import get_fast_llm

logger = logging.getLogger(__name__)

# ── Prompts ──────────────────────────────────────────────────────────────

_EXTRACTION_PROMPT = """\
You are a memory-extraction specialist for a product management AI system.

Given the content below (research findings, PRD decisions, or ticket snapshots),
extract structured memory items that should be persisted for future sessions.

Return a JSON array of objects:
[
  {
    "type": "decision|constraint|metric|persona|theme",
    "title": "Short descriptive title (max 120 chars)",
    "content": "Full detail of the item (max 500 chars)",
    "authority": 1-5,
    "tags": ["tag1", "tag2"]
  }
]

Type guidelines:
- decision: A product choice that was made ("we chose self-serve onboarding over API-first")
- constraint: A requirement or limitation ("must support WCAG 2.1 AA")
- metric: A quantified finding ("80% of users cited onboarding friction")
- persona: A user segment or archetype identified
- theme: A recurring pattern across interviews

Authority scale:
- 1: Inferred from single mention
- 2: Supported by multiple data points
- 3: Validated by research with evidence
- 4: Confirmed by user / stakeholder review
- 5: Formal decision (approved PRD, confirmed ticket plan)

Extract only genuinely important items. Prefer fewer high-quality items over many low-quality ones.
Return an empty array [] if nothing is worth persisting."""


# ── Hook 1: Recall Past Decisions ────────────────────────────────────────

def recall_past_decisions(state: InterviewState) -> dict:
    """Recall relevant past decisions and inject them into state.

    Searches both mem0 (conversation-derived memories) and the memory_items
    table (structured decisions/constraints/metrics) for the current project.
    Returns a dict to merge into state.
    """
    project_id = state.get("project_id", "")
    user_id = state.get("user_id", "")
    question = state.get("current_question", "")

    if not project_id or not question:
        return {"recalled_memories": []}

    recalled: list[dict] = []

    # 1. Search mem0 for conversational memories
    try:
        from backend.services.memory import search_memories
        mem0_results = search_memories(
            query=question,
            project_id=project_id,
            user_id=user_id,
            limit=8,
        )
        for item in mem0_results:
            recalled.append({
                "source": "mem0",
                "content": item.get("memory", ""),
                "score": item.get("score", 0),
            })
    except Exception as exc:
        logger.debug("mem0 recall skipped: %s", exc)

    # 2. Search memory_items table for structured items
    try:
        from backend.services.hybrid_search import hybrid_search_memory_items
        db_items = hybrid_search_memory_items(
            project_id=project_id,
            query=question,
            match_count=10,
        )
        for item in db_items:
            if item.get("type") in ("decision", "constraint", "metric", "persona"):
                recalled.append({
                    "source": "memory_items",
                    "type": item.get("type"),
                    "title": item.get("title", ""),
                    "content": item.get("content", ""),
                    "authority": item.get("authority", 0),
                })
    except Exception as exc:
        logger.debug("memory_items recall skipped: %s", exc)

    # 3. Build context message for sub-agents
    if recalled:
        context_lines = ["[Prior Context — recalled from past sessions]"]
        for mem in recalled:
            if mem["source"] == "mem0":
                context_lines.append(f"• {mem['content']}")
            else:
                tag = f"[{mem.get('type', 'info')}]"
                context_lines.append(
                    f"• {tag} {mem.get('title', '')}: {mem.get('content', '')}"
                )

        messages = state.get("messages", [])
        messages.append({
            "role": "assistant",
            "content": "\n".join(context_lines),
        })
        return {"recalled_memories": recalled, "messages": messages}

    return {"recalled_memories": []}


# ── Hook 2: Extract and Store Phase Memories ─────────────────────────────

def extract_and_store_research_memories(state: InterviewState) -> None:
    """Extract memory items from research results and store them.

    Called after dispatch_research completes. Extracts validated claims,
    quantified metrics, and key themes from the research output.
    """
    project_id = state.get("project_id", "")
    research = state.get("research_results", {})

    if not project_id or not research:
        return

    # Build content block for LLM extraction
    content_parts = []
    if research.get("summary"):
        content_parts.append(f"Research Summary:\n{research['summary']}")

    if research.get("validated_claims"):
        claims_text = json.dumps(research["validated_claims"], indent=2)
        content_parts.append(f"Validated Claims:\n{claims_text}")

    if research.get("quantified_metrics"):
        metrics_text = json.dumps(research["quantified_metrics"], indent=2)
        content_parts.append(f"Quantified Metrics:\n{metrics_text}")

    if research.get("key_themes"):
        themes_text = json.dumps(research["key_themes"], indent=2)
        content_parts.append(f"Key Themes:\n{themes_text}")

    if research.get("contradictions"):
        contra_text = json.dumps(research["contradictions"], indent=2)
        content_parts.append(f"Contradictions:\n{contra_text}")

    if not content_parts:
        return

    _extract_and_write(
        project_id=project_id,
        phase="research",
        content="\n\n".join(content_parts),
    )


def extract_and_store_prd_memories(state: InterviewState) -> None:
    """Extract memory items from PRD document and store them.

    Called after generate_prd completes. Extracts decisions, constraints,
    KPIs, and user stories from the PRD output.
    """
    project_id = state.get("project_id", "")
    prd = state.get("prd_document", {})

    if not project_id or not prd:
        return

    content_parts = []
    if prd.get("title"):
        content_parts.append(f"PRD Title: {prd['title']}")

    if prd.get("problem_statement"):
        content_parts.append(f"Problem Statement:\n{prd['problem_statement']}")

    if prd.get("proposed_solution"):
        content_parts.append(f"Proposed Solution:\n{prd['proposed_solution']}")

    if prd.get("kpis"):
        kpis_text = json.dumps(prd["kpis"], indent=2)
        content_parts.append(f"KPIs:\n{kpis_text}")

    if prd.get("constraints_and_risks"):
        constraints = "\n".join(f"- {c}" for c in prd["constraints_and_risks"])
        content_parts.append(f"Constraints and Risks:\n{constraints}")

    if prd.get("user_stories"):
        stories = "\n".join(f"- {s}" for s in prd["user_stories"])
        content_parts.append(f"User Stories:\n{stories}")

    if prd.get("next_actions"):
        actions_text = json.dumps(prd["next_actions"], indent=2)
        content_parts.append(f"Next Actions:\n{actions_text}")

    if not content_parts:
        return

    _extract_and_write(
        project_id=project_id,
        phase="prd",
        content="\n\n".join(content_parts),
        base_authority=3,  # PRD decisions get higher authority
    )


def extract_and_store_ticket_memories(state: InterviewState) -> None:
    """Store a snapshot of created tickets as a memory item.

    Called after create_tickets completes. Writes a compact snapshot
    rather than extracting individual items.
    """
    project_id = state.get("project_id", "")
    tickets = state.get("tickets", [])
    prd = state.get("prd_document", {})

    if not project_id or not tickets:
        return

    # Build a compact snapshot
    epics = [t for t in tickets if t.get("ticket_type") == "epic"]
    stories = [t for t in tickets if t.get("ticket_type") == "story"]
    tasks = [t for t in tickets if t.get("ticket_type") == "task"]
    total_points = sum(t.get("estimated_points") or 0 for t in tickets)

    snapshot = {
        "prd_title": prd.get("title", "Untitled"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "epics": len(epics),
            "stories": len(stories),
            "tasks": len(tasks),
            "total_points": total_points,
        },
        "epic_titles": [e.get("title", "") for e in epics],
        "question": state.get("current_question", ""),
    }

    try:
        from backend.db.supabase_client import get_supabase
        db = get_supabase()
        db.table("memory_items").insert({
            "project_id": project_id,
            "type": "snapshot",
            "title": f"Ticket plan: {prd.get('title', 'Untitled')}",
            "content": json.dumps(snapshot),
            "authority": 4,
            "tags": ["tickets", "implementation_plan"],
            "metadata": {
                "session_id": state.get("session_id", ""),
                "extracted_by": "interview_agent_hook2",
                "phase": "tickets",
            },
        }).execute()
        logger.info(
            "Stored ticket snapshot for project %s (%d tickets, %d pts)",
            project_id, len(tickets), total_points,
        )
    except Exception as exc:
        logger.debug("Ticket snapshot storage skipped: %s", exc)


def _extract_and_write(
    project_id: str,
    phase: str,
    content: str,
    base_authority: int = 2,
) -> int:
    """LLM-powered extraction of structured memory items from phase output.

    Uses the fast LLM to classify content into decision/constraint/metric/
    persona/theme items, then writes them to the memory_items table.

    Returns the number of items written.
    """
    # Truncate content to avoid token limits
    truncated = content[:8000]

    try:
        llm = get_fast_llm()
        response = llm.invoke([
            SystemMessage(content=_EXTRACTION_PROMPT),
            HumanMessage(content=f"Phase: {phase}\n\n{truncated}"),
        ])

        items = _parse_extraction_response(response.content)
    except Exception as exc:
        logger.debug("LLM extraction failed for phase %s: %s", phase, exc)
        return 0

    if not items:
        return 0

    written = 0
    try:
        from backend.db.supabase_client import get_supabase
        db = get_supabase()

        for item in items:
            item_type = item.get("type", "decision")
            if item_type not in ("decision", "constraint", "metric", "persona", "theme"):
                continue

            authority = min(
                max(item.get("authority", base_authority), 1),
                5,
            )

            db.table("memory_items").insert({
                "project_id": project_id,
                "type": item_type,
                "title": (item.get("title") or "")[:120],
                "content": (item.get("content") or "")[:2000],
                "authority": authority,
                "tags": item.get("tags", []),
                "metadata": {
                    "extracted_by": "interview_agent_hook2",
                    "phase": phase,
                },
            }).execute()
            written += 1

        logger.info(
            "Extracted %d memory items from %s phase for project %s",
            written, phase, project_id,
        )
    except Exception as exc:
        logger.debug("Memory item storage failed: %s", exc)

    return written


def _parse_extraction_response(text: str) -> list[dict]:
    """Parse the LLM extraction response into a list of memory items."""
    import re

    # Try direct JSON parse
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        return []
    except (json.JSONDecodeError, TypeError):
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        try:
            result = json.loads(match.group(1))
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, TypeError):
            pass

    return []


# ── Hook 3: Session End — Persist to mem0 + Consolidate ─────────────────

def persist_session_to_memory(state: InterviewState) -> dict:
    """Feed the full conversation to mem0 and run consolidation.

    Called when the session reaches the 'complete' phase. This:
    1. Feeds the conversation history to mem0's add_memories()
    2. Runs consolidation + supersede on the project's memory_items
    3. Rebuilds the compact index

    Returns a dict with stats about what was persisted.
    """
    project_id = state.get("project_id", "")
    user_id = state.get("user_id", "")
    messages = state.get("messages", [])
    session_id = state.get("session_id", "")

    stats = {
        "mem0_added": 0,
        "consolidated": False,
        "index_rebuilt": False,
    }

    if not project_id or not messages:
        return stats

    # 1. Feed conversation to mem0
    try:
        from backend.services.memory import add_memories

        # Format messages for mem0 (expects role/content dicts)
        conversation = [
            {"role": m.get("role", "assistant"), "content": m.get("content", "")}
            for m in messages
            if m.get("content")
        ]

        if conversation:
            added = add_memories(
                messages=conversation,
                project_id=project_id,
                user_id=user_id,
            )
            stats["mem0_added"] = len(added)
            logger.info(
                "Persisted %d memories to mem0 for session %s",
                len(added), session_id,
            )
    except Exception as exc:
        logger.debug("mem0 persistence skipped: %s", exc)

    # 2. Run consolidation + supersede on memory_items
    try:
        from backend.db.supabase_client import get_supabase
        db = get_supabase()

        rows = (
            db.table("memory_items")
            .select("id, type, title, content, supersedes_id")
            .eq("project_id", project_id)
            .is_("effective_to", "null")
            .in_("type", ["decision", "constraint"])
            .order("created_at", desc=False)
            .execute()
            .data
            or []
        )

        seen: dict[tuple[str, str], dict] = {}
        for row in rows:
            key = (row["type"], row["title"].strip().lower())
            if key not in seen:
                seen[key] = row
                continue
            prior = seen[key]
            # Exact duplicate — supersede the older one
            if prior["content"].strip() == row["content"].strip():
                db.table("memory_items").update({
                    "effective_to": datetime.now(timezone.utc).isoformat(),
                    "supersedes_id": prior["id"],
                }).eq("id", row["id"]).execute()

        stats["consolidated"] = True
        logger.info("Consolidation complete for project %s", project_id)
    except Exception as exc:
        logger.debug("Consolidation skipped: %s", exc)

    # 3. Rebuild the compact index
    try:
        from backend.services.memory_index import rebuild_index_memory
        rebuild_index_memory(project_id)
        stats["index_rebuilt"] = True
        logger.info("Index rebuilt for project %s", project_id)
    except Exception as exc:
        logger.debug("Index rebuild skipped: %s", exc)

    return stats
