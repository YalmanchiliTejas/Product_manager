"""Longitudinal memory hooks for the interview agent.

Wires the interview agent into the existing memory infrastructure so
decisions, research findings, and PRD choices persist across sessions.

Three hooks:
  1. recall_memories()   — Session start: fetch past decisions/constraints
  2. persist_phase()     — After each phase: extract & store structured items
  3. persist_session()   — Session end: full conversation → mem0 + consolidate

Works without a DB (CLI-only mode) by maintaining a local in-memory
decision log that persists within a single session.  When Supabase is
connected, it writes to the memory_items table and runs consolidation.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.state import InterviewState
from backend.services.llm import get_fast_llm


# ── Extraction prompt ────────────────────────────────────────────────────

_MEMORY_EXTRACTION_PROMPT = """\
You are a memory extraction system for a product management AI.

Given the output of an agent phase, extract structured memory items that
should be persisted for future sessions.  Each item is a decision,
constraint, metric, or persona insight that would affect future product
decisions.

Return a JSON array:
[
  {
    "type": "decision|constraint|metric|persona",
    "title": "Short descriptive title (max 120 chars)",
    "content": "Full detail of the item",
    "confidence": "high|medium|low",
    "source": "Which phase/data produced this"
  }
]

Guidelines:
- decision: A choice that was made (e.g. "Prioritise onboarding over retention")
- constraint: A hard requirement or limitation (e.g. "Must support offline mode")
- metric: A quantified finding (e.g. "80% of users cited onboarding friction")
- persona: A user archetype with needs (e.g. "Power users want API access")
- Only extract items that are actionable and would affect future decisions
- Be specific — "users want better UX" is too vague
- Include the evidence source where possible"""


# ── Local decision log (session-scoped, no DB needed) ────────────────────

class DecisionLog:
    """In-memory decision log for a single session.

    Always available, even without a DB.  When the DB is connected,
    items are also written to memory_items.
    """

    def __init__(self):
        self.items: list[dict] = []

    def add(self, item: dict) -> None:
        item.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        self.items.append(item)

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Simple keyword search over the local log."""
        query_words = set(query.lower().split())
        scored: list[tuple[float, dict]] = []
        for item in self.items:
            text = f"{item.get('title', '')} {item.get('content', '')}".lower()
            text_words = set(text.split())
            overlap = len(query_words & text_words) / max(len(query_words), 1)
            scored.append((overlap, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def get_by_type(self, item_type: str) -> list[dict]:
        return [i for i in self.items if i.get("type") == item_type]

    def get_all(self) -> list[dict]:
        return list(self.items)

    def summary(self) -> str:
        """Compact summary for injection into agent prompts."""
        if not self.items:
            return ""
        lines = ["Past decisions and findings from this session:"]
        for item in self.items[-20:]:  # last 20 items
            lines.append(
                f"- [{item.get('type', '?')}] {item.get('title', '?')}: "
                f"{item.get('content', '')[:150]}"
            )
        return "\n".join(lines)


# ── HOOK 1: Session start — recall past memories ─────────────────────────

def recall_memories(state: InterviewState, decision_log: DecisionLog) -> dict:
    """Recall relevant memories from past sessions and inject into state.

    Searches both the DB memory layer (if available) and the local
    decision log.  Returns a dict to merge into state.
    """
    project_id = state.get("project_id", "")
    user_id = state.get("user_id", "")
    question = state.get("current_question", "")
    messages = state.get("messages", [])

    recalled: list[dict] = []

    # 1. Search DB memories (mem0 + memory_items)
    if project_id and user_id:
        try:
            from backend.services.memory import search_memories
            db_memories = search_memories(question, project_id, user_id, limit=5)
            for mem in db_memories:
                recalled.append({
                    "source": "mem0",
                    "type": "memory",
                    "content": mem.get("memory", ""),
                    "score": mem.get("score", 0),
                })
        except Exception:
            pass  # DB not available

        # Also search structured memory_items (decisions, constraints)
        try:
            from backend.services.hybrid_search import hybrid_search_memory_items
            items = hybrid_search_memory_items(
                project_id=project_id,
                query=question or "product decisions constraints metrics",
                match_count=8,
            )
            for item in items:
                if item.get("type") in ("decision", "constraint", "metric", "persona"):
                    recalled.append({
                        "source": "memory_items",
                        "type": item.get("type"),
                        "title": item.get("title", ""),
                        "content": item.get("content", ""),
                    })
        except Exception:
            pass

    # 2. Search local decision log
    if question:
        local = decision_log.search(question, limit=5)
        for item in local:
            recalled.append({
                "source": "session_log",
                "type": item.get("type", "decision"),
                "title": item.get("title", ""),
                "content": item.get("content", ""),
            })

    # 3. Inject into messages if we found anything
    if recalled:
        recall_text = _format_recalled_memories(recalled)
        messages.append({
            "role": "assistant",
            "content": f"Recalled {len(recalled)} relevant memories from past sessions:\n{recall_text}",
        })

    return {
        "messages": messages,
        "recalled_memories": recalled,
    }


def _format_recalled_memories(memories: list[dict]) -> str:
    """Format recalled memories for display / prompt injection."""
    lines: list[str] = []
    for mem in memories:
        source = mem.get("source", "?")
        mtype = mem.get("type", "?")
        title = mem.get("title", "")
        content = mem.get("content", "")
        if title:
            lines.append(f"  [{mtype}] {title}: {content[:200]} (from {source})")
        else:
            lines.append(f"  [{mtype}] {content[:250]} (from {source})")
    return "\n".join(lines)


# ── HOOK 2: After phase — extract and persist structured items ───────────

def persist_phase(
    state: InterviewState,
    decision_log: DecisionLog,
    phase_name: str,
) -> None:
    """Extract structured memory items from a completed phase and persist.

    Called after: research, prd_generation, ticket_creation.
    """
    phase_data = _get_phase_data(state, phase_name)
    if not phase_data:
        return

    # Use LLM to extract structured items
    items = _extract_memory_items(phase_name, phase_data)

    # Store in local decision log (always works)
    for item in items:
        item["phase"] = phase_name
        item["session_id"] = state.get("session_id", "")
        decision_log.add(item)

    # Store in DB if available
    _persist_to_db(state, items)


def _get_phase_data(state: InterviewState, phase_name: str) -> str:
    """Get the relevant data from a completed phase for extraction."""
    if phase_name == "research":
        research = state.get("research_results", {})
        if not research:
            return ""
        parts = []
        summary = research.get("summary", "")
        if summary:
            parts.append(f"Research Summary:\n{summary}")
        for claim in research.get("validated_claims", [])[:10]:
            parts.append(
                f"Validated: {claim.get('claim', '')} "
                f"(confidence: {claim.get('confidence', '?')})"
            )
        for contra in research.get("contradictions", [])[:5]:
            parts.append(
                f"Contradiction: {contra.get('claim_a', '')} vs {contra.get('claim_b', '')}"
            )
        for metric in research.get("quantified_metrics", [])[:10]:
            parts.append(
                f"Metric: {metric.get('metric', '')} = {metric.get('value', '')}"
            )
        return "\n".join(parts)

    elif phase_name == "prd":
        prd = state.get("prd_document", {})
        if not prd:
            return ""
        parts = [f"PRD Title: {prd.get('title', '')}"]
        if prd.get("problem_statement"):
            parts.append(f"Problem: {prd['problem_statement'][:500]}")
        for story in prd.get("user_stories", [])[:5]:
            parts.append(f"User Story: {story}")
        for kpi in prd.get("kpis", [])[:5]:
            parts.append(
                f"KPI: {kpi.get('metric', '')} → {kpi.get('target', '')}"
            )
        for risk in prd.get("constraints_and_risks", [])[:5]:
            parts.append(f"Constraint/Risk: {risk}")
        for action in prd.get("next_actions", [])[:5]:
            parts.append(
                f"Next Action: {action.get('action', '')} "
                f"(owner: {action.get('owner', '?')})"
            )
        return "\n".join(parts)

    elif phase_name == "tickets":
        tickets = state.get("tickets", [])
        if not tickets:
            return ""
        parts = [f"Created {len(tickets)} tickets:"]
        for t in tickets[:10]:
            pts = f" [{t.get('estimated_points')}pts]" if t.get("estimated_points") else ""
            parts.append(f"- [{t.get('ticket_type', '?')}] {t.get('title', '')}{pts}")
        total_pts = sum(t.get("estimated_points") or 0 for t in tickets)
        parts.append(f"Total: {total_pts} story points")
        return "\n".join(parts)

    return ""


def _extract_memory_items(phase_name: str, phase_data: str) -> list[dict]:
    """Use the fast LLM to extract structured memory items."""
    llm = get_fast_llm()
    response = llm.invoke([
        SystemMessage(content=_MEMORY_EXTRACTION_PROMPT),
        HumanMessage(content=(
            f"Phase: {phase_name}\n\n"
            f"Phase Output:\n{phase_data[:8000]}"
        )),
    ])

    try:
        items = json.loads(response.content)
        if isinstance(items, list):
            return items
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response.content)
        if match:
            try:
                items = json.loads(match.group(1))
                if isinstance(items, list):
                    return items
            except (json.JSONDecodeError, TypeError):
                pass

    return []


def _persist_to_db(state: InterviewState, items: list[dict]) -> None:
    """Write extracted memory items to the memory_items table.

    Gracefully skips if DB is unavailable.
    """
    project_id = state.get("project_id", "")
    if not project_id:
        return

    try:
        from backend.db.supabase_client import get_supabase
        db = get_supabase()

        for item in items:
            item_type = item.get("type", "decision")
            if item_type not in ("decision", "constraint", "metric", "persona"):
                continue

            db.table("memory_items").insert({
                "project_id": project_id,
                "type": item_type,
                "title": (item.get("title", "") or "")[:120],
                "content": (item.get("content", "") or "")[:2000],
                "authority": {"high": 3, "medium": 2, "low": 1}.get(
                    item.get("confidence", "medium"), 2
                ),
                "metadata": {
                    "source": item.get("source", ""),
                    "phase": item.get("phase", ""),
                    "session_id": item.get("session_id", ""),
                    "extracted_by": "interview_agent_memory_hook",
                },
            }).execute()
    except Exception:
        pass  # DB not available


# ── HOOK 3: Session end — full conversation → mem0 + consolidate ─────────

def persist_session(state: InterviewState, decision_log: DecisionLog) -> dict:
    """Persist the full session to longitudinal memory.

    1. Feed conversation to mem0 (deduplication + extraction)
    2. Write decision log items to DB
    3. Run consolidation to supersede stale decisions
    4. Rebuild the compact index

    Returns stats dict.
    """
    project_id = state.get("project_id", "")
    user_id = state.get("user_id", "")
    messages = state.get("messages", [])

    stats = {
        "mem0_stored": 0,
        "decision_log_items": len(decision_log.get_all()),
        "consolidation_run": False,
        "index_rebuilt": False,
    }

    # 1. Feed conversation to mem0
    if project_id and user_id and messages:
        try:
            from backend.services.memory import add_memories
            mem0_messages = [
                {"role": m["role"], "content": m["content"]}
                for m in messages
                if m.get("role") in ("user", "assistant") and m.get("content")
            ]
            if mem0_messages:
                result = add_memories(mem0_messages, project_id, user_id)
                stats["mem0_stored"] = len(result)
        except Exception:
            pass

    # 2. Persist any remaining decision log items to DB
    remaining_items = decision_log.get_all()
    if remaining_items:
        _persist_to_db(state, remaining_items)

    # 3. Run consolidation (supersede stale decisions)
    if project_id:
        try:
            from backend.db.supabase_client import get_supabase
            from datetime import datetime, timezone
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
                if prior["content"].strip() == row["content"].strip():
                    # Exact duplicate — supersede the older one
                    db.table("memory_items").update({
                        "effective_to": datetime.now(timezone.utc).isoformat(),
                        "supersedes_id": prior["id"],
                    }).eq("id", row["id"]).execute()
                # Different content = conflict — leave both, let user resolve

            stats["consolidation_run"] = True
        except Exception:
            pass

    # 4. Rebuild compact index
    if project_id:
        try:
            from backend.services.memory_index import rebuild_index_memory
            rebuild_index_memory(project_id)
            stats["index_rebuilt"] = True
        except Exception:
            pass

    return stats


# ── Lightweight per-ask mem0 persist ─────────────────────────────────────

def persist_to_mem0(state: InterviewState) -> None:
    """Persist recent conversation turns to mem0 without full consolidation.

    Called after each significant phase (research complete, PRD approved,
    tickets created) so durability doesn't depend on session.end() being
    called.  mem0 deduplicates internally, so repeated calls are safe.
    """
    project_id = state.get("project_id", "")
    user_id = state.get("user_id", "")
    messages = state.get("messages", [])

    if not project_id or not user_id or not messages:
        return

    try:
        from backend.services.memory import add_memories
        recent = [
            {"role": m["role"], "content": m["content"]}
            for m in messages[-30:]  # last 30 turns to bound cost
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        if recent:
            add_memories(recent, project_id, user_id)
    except Exception:
        pass  # mem0 unavailable — structured items already persisted by Hook 2


# ── Context injection helper ─────────────────────────────────────────────

def build_memory_context(
    recalled: list[dict],
    decision_log: DecisionLog,
) -> str:
    """Build a memory context block for injection into sub-agent prompts.

    Combines recalled DB memories with the local decision log into a
    single text block that sub-agents can reference.
    """
    parts: list[str] = []

    # Recalled memories from past sessions
    if recalled:
        parts.append("=== Past Session Memory ===")
        for mem in recalled:
            mtype = mem.get("type", "memory")
            title = mem.get("title", "")
            content = mem.get("content", "")
            if title:
                parts.append(f"[{mtype}] {title}: {content[:200]}")
            else:
                parts.append(f"[{mtype}] {content[:250]}")

    # Current session decision log
    log_summary = decision_log.summary()
    if log_summary:
        parts.append("")
        parts.append("=== Current Session Decisions ===")
        parts.append(log_summary)

    return "\n".join(parts)
