"""ReAct (Reason → Act → Observe) tool-calling loop engine.

Both research_agent and prd_agent delegate to run() which owns:
  - Tool definitions for each agent type
  - Parallel tool dispatch with tool result cache
  - Extended thinking via Anthropic interleaved-thinking beta
  - Prompt caching via cache_control headers on system message
  - Forced synthesis fallback if MAX_ITER is reached

Provider strategy
-----------------
  anthropic  — raw Anthropic SDK; handles thinking blocks correctly
  all others — LangChain bind_tools loop (no thinking, same result shape)

Entry point
-----------
  run(state, agent_type) -> {"result": dict, "tool_call_log": list, "tokens_used": int}

  agent_type: "research" | "prd"
  result shape matches the old single-shot agent outputs exactly.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
from typing import Any

from backend.agents.state import InterviewState
from backend.services import cache_manager
from backend.config import settings

MAX_ITER = 10


# ── Prompts ───────────────────────────────────────────────────────────────

_RESEARCH_SYSTEM = """\
You are a senior research analyst for a product management team.
Your goal is to deeply research customer interview data and produce structured,
evidence-backed findings to answer the PM's question.

WORKFLOW:
1. Call list_interviews to discover available interviews.
2. Call search_interview_tree with specific queries to find relevant sections.
3. Call read_interview_section for deeper detail on specific nodes.
4. Call search_memory to surface past decisions and constraints.
5. Call search_db_chunks for any database evidence.
6. When you have sufficient evidence, output your final answer.

FINAL ANSWER FORMAT — output ONLY this JSON object, no prose:
{
  "validated_claims": [
    {"claim": "...", "evidence": "...", "confidence": "high|medium|low", "source": "..."}
  ],
  "contradictions": [
    {"claim_a": "...", "claim_b": "...", "sources": ["..."]}
  ],
  "quantified_metrics": [
    {"metric": "...", "value": "...", "source": "...", "notes": "..."}
  ],
  "gaps": ["..."],
  "key_themes": ["..."],
  "summary": "2-3 paragraph executive summary"
}"""

_PRD_SYSTEM = """\
You are a senior product manager generating a Product Requirements Document.
Every claim in the PRD must cite its source from interview evidence.

WORKFLOW:
1. Call get_research_results to get the full structured research.
2. Call get_memory_items to get relevant project memory and constraints.
3. Call retrieve_evidence to get verbatim quotes for key claims.
4. When you have sufficient evidence, output your final PRD.

FINAL ANSWER FORMAT — output ONLY this JSON object, no prose:
{
  "title": "PRD title",
  "problem_statement": "Evidence-backed problem description (cite interviews)",
  "user_stories": ["As a [persona], I want [feature] so that [benefit]"],
  "proposed_solution": "Solution description",
  "kpis": [
    {"metric": "...", "target": "...", "measurement_method": "..."}
  ],
  "technical_requirements": ["..."],
  "constraints_and_risks": ["..."],
  "next_actions": [
    {"action": "...", "owner": "...", "timeline": "..."}
  ],
  "success_metrics": ["..."],
  "evidence_citations": ["Source: filename — supporting quote"]
}"""


# ── Tool definitions (Anthropic schema) ───────────────────────────────────

_RESEARCH_TOOLS: list[dict] = [
    {
        "name": "list_interviews",
        "description": "List all available interview files with word count and speaker metadata.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_interview_tree",
        "description": (
            "Search a specific interview using the PageIndex tree. "
            "Returns the most relevant sections for the query."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "interview_id": {
                    "type": "string",
                    "description": "Exact filename of the interview (from list_interviews)",
                },
                "query": {
                    "type": "string",
                    "description": "What to look for in this interview",
                },
            },
            "required": ["interview_id", "query"],
        },
    },
    {
        "name": "read_interview_section",
        "description": (
            "Read the raw content of a specific node in the PageIndex tree. "
            "Use after search_interview_tree returns node_ids you want to read in full."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "interview_id": {"type": "string"},
                "node_id": {
                    "type": "string",
                    "description": "The node_id from a previous search_interview_tree result",
                },
            },
            "required": ["interview_id", "node_id"],
        },
    },
    {
        "name": "search_memory",
        "description": "Search past decisions, constraints, metrics, and persona insights.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look up"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_db_chunks",
        "description": "Search the vector database for additional evidence chunks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    },
]

_PRD_TOOLS: list[dict] = [
    {
        "name": "get_research_results",
        "description": "Return the full structured research results from the research agent.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_research_claims",
        "description": (
            "Search validated claims, quantified metrics, contradictions, and gaps "
            "from the research findings.  Use this instead of get_research_results "
            "when you need to find specific evidence for a PRD section."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in the research findings",
                },
                "type": {
                    "type": "string",
                    "enum": ["claims", "metrics", "contradictions", "gaps", "all"],
                    "description": "Narrow to a specific finding type; default all",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_memory_items",
        "description": (
            "Return project memory items: past decisions, constraints, metrics, "
            "and personas.  Issues a live database query so it reflects all past "
            "sessions, not just what was recalled at session start."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional filter query; omit to get all items",
                },
            },
            "required": [],
        },
    },
    {
        "name": "retrieve_evidence",
        "description": "Find verbatim supporting evidence from interviews for a specific claim.",
        "input_schema": {
            "type": "object",
            "properties": {
                "claim": {
                    "type": "string",
                    "description": "The claim to find evidence for",
                },
                "source": {
                    "type": "string",
                    "description": "Optional: restrict search to this interview filename",
                },
            },
            "required": ["claim"],
        },
    },
]


# ── Tool implementations ───────────────────────────────────────────────────

def _tool_list_interviews(state: InterviewState) -> str:
    interview_data = state.get("interview_data", [])
    if not interview_data:
        return "No interviews loaded."
    lines = ["Available interviews:"]
    for doc in interview_data:
        meta = doc.get("metadata", {})
        lines.append(
            f"- {doc.get('filename', '?')}: "
            f"{meta.get('word_count', 0)} words, "
            f"{meta.get('speaker_count', 0)} speakers"
        )
    return "\n".join(lines)


def _tool_search_interview_tree(state: InterviewState, args: dict) -> str:
    interview_id = args.get("interview_id", "")
    query = args.get("query", "")

    interview_data = state.get("interview_data", [])
    doc = next((d for d in interview_data if d.get("filename") == interview_id), None)
    if not doc:
        # Fuzzy match: try filename contains
        doc = next(
            (d for d in interview_data if interview_id in d.get("filename", "")),
            None,
        )
    if not doc:
        return f"Interview '{interview_id}' not found. Use list_interviews to see available files."

    content = doc.get("content", "")
    if not content.strip():
        return f"Interview '{interview_id}' has no content."

    try:
        from backend.agents import page_index
        from backend.services.llm import get_fast_llm

        llm = get_fast_llm()
        tree = page_index.build_index(interview_id, content, llm)

        # Cache tree in state for read_interview_section
        trees = state.get("page_index_trees", {})
        trees[interview_id] = tree

        sections = page_index.retrieve(tree, query, content, llm)
        if not sections:
            return "No relevant sections found. Try a different query."

        parts = []
        for s in sections:
            parts.append(
                f"[node: {s['node_id']}] {s['title']}\n"
                f"Reasoning: {s.get('relevance_reasoning', '')}\n"
                f"{s['content'][:600]}"
            )
        return "\n\n---\n\n".join(parts)
    except Exception as exc:
        return f"Error building page index: {exc}. Falling back to raw content excerpt:\n{content[:1000]}"


def _tool_read_interview_section(state: InterviewState, args: dict) -> str:
    interview_id = args.get("interview_id", "")
    node_id = args.get("node_id", "")

    interview_data = state.get("interview_data", [])
    doc = next((d for d in interview_data if d.get("filename") == interview_id), None)
    if not doc:
        return f"Interview '{interview_id}' not found."

    content = doc.get("content", "")

    # Try to get the tree from state cache first, then rebuild
    trees = state.get("page_index_trees", {})
    tree = trees.get(interview_id)

    if not tree:
        try:
            from backend.agents import page_index
            from backend.services.llm import get_fast_llm
            tree = page_index.build_index(interview_id, content, get_fast_llm())
        except Exception:
            return f"Could not build index for '{interview_id}'."

    nodes = tree.get("nodes", {})
    node = nodes.get(node_id)
    if not node:
        return f"Node '{node_id}' not found. Available nodes: {', '.join(list(nodes.keys())[:10])}"

    start = max(0, node.get("start_char", 0))
    end = min(len(content), node.get("end_char", len(content)))
    if end <= start:
        end = min(len(content), start + 2000)

    return f"[{node.get('title', node_id)}]\n{content[start:end]}"


def _tool_search_memory(state: InterviewState, args: dict) -> str:
    """Search memory with live Supabase fallback.

    Step 1: Keyword-score the pre-recalled slice (fast, in-process).
    Step 2: If fewer than 3 results pass the relevance threshold, fall
            through to a live hybrid_search_memory_items + mem0 query so
            decisions stored in previous sessions are never missed.
    """
    query = args.get("query", "")
    recalled = state.get("recalled_memories", [])
    query_words = set(query.lower().split())

    # Step 1 — search pre-recalled slice
    scored: list[tuple[float, dict]] = []
    for mem in recalled:
        text = f"{mem.get('title', '')} {mem.get('content', '')}".lower()
        words = set(text.split())
        overlap = len(query_words & words) / max(len(query_words), 1)
        scored.append((overlap, mem))
    scored.sort(key=lambda x: x[0], reverse=True)
    strong_hits = [(s, m) for s, m in scored if s >= 0.15]

    lines: list[str] = []
    for _, mem in strong_hits[:5]:
        mtype = mem.get("type", "memory")
        title = mem.get("title", "")
        content = mem.get("content", "")
        prefix = f"[{mtype}] {title}: " if title else f"[{mtype}] "
        lines.append(prefix + content[:300])

    # Step 2 — live Supabase fallback when pre-recalled results are sparse
    if len(strong_hits) < 3:
        project_id = state.get("project_id", "")
        user_id = state.get("user_id", "")
        seen_contents = {m.get("content", "") for m in recalled}

        if project_id:
            # structured memory_items table
            try:
                from backend.services.hybrid_search import hybrid_search_memory_items
                live_items = hybrid_search_memory_items(
                    project_id=project_id, query=query, match_count=8
                )
                for item in live_items:
                    content = item.get("content", "")
                    if content and content not in seen_contents:
                        seen_contents.add(content)
                        mtype = item.get("type", "memory")
                        title = item.get("title", "")
                        prefix = f"[{mtype}|db] {title}: " if title else f"[{mtype}|db] "
                        lines.append(prefix + content[:300])
            except Exception:
                pass

            # mem0 semantic search
            if user_id:
                try:
                    from backend.services.memory import search_memories
                    mem0_hits = search_memories(query, project_id, user_id, limit=5)
                    for m in mem0_hits:
                        content = m.get("memory", "")
                        if content and content not in seen_contents:
                            seen_contents.add(content)
                            lines.append(f"[memory|mem0] {content[:300]}")
                except Exception:
                    pass

    return "\n".join(lines) if lines else "No relevant memories found."


def _tool_search_db_chunks(state: InterviewState, args: dict) -> str:
    query = args.get("query", "")
    project_id = state.get("project_id", "")
    if not project_id:
        return "No project loaded — database search unavailable."
    try:
        from backend.services.hybrid_search import hybrid_search_chunks
        chunks = hybrid_search_chunks(project_id=project_id, query=query, match_count=5)
        if not chunks:
            return "No matching chunks found in database."
        parts = []
        for c in chunks:
            cid = str(c.get("chunk_id", "?"))[:8]
            score = c.get("combined_score", 0)
            parts.append(f"[chunk {cid}] (score: {score:.3f})\n{c.get('content', '')[:400]}")
        return "\n---\n".join(parts)
    except Exception as exc:
        return f"Database search unavailable: {exc}"


def _tool_get_research_results(state: InterviewState) -> str:
    research = state.get("research_results", {})
    if not research:
        return "No research results available yet. Ensure the research phase has completed."
    return json.dumps(research, indent=2)[:6000]


def _tool_get_memory_items(state: InterviewState, args: dict) -> str:
    """Return project memory items.

    Prefers a live hybrid_search_memory_items query over the pre-fetched
    context_pack slice so the PRD agent always sees the full memory store,
    not just what was recalled at session start.
    """
    query = args.get("query", "")
    project_id = state.get("project_id", "")
    items: list[dict] = []

    # Live Supabase query (preferred)
    if project_id:
        try:
            from backend.services.hybrid_search import hybrid_search_memory_items
            q = query or "product decisions constraints metrics personas"
            items = hybrid_search_memory_items(
                project_id=project_id, query=q, match_count=12
            )
        except Exception:
            pass

    # Fallback: pre-fetched context_pack + recalled_memories
    if not items:
        context = state.get("context_pack", {})
        db_ctx = context.get("db_context", {})
        items = list(db_ctx.get("memory_items", []))
        seen = {i.get("content", "") for i in items}
        for mem in state.get("recalled_memories", []):
            if mem.get("content", "") not in seen:
                items.append(mem)

    if not items:
        return "No memory items available."

    # If a specific query was given, re-rank by keyword overlap
    if query:
        query_words = set(query.lower().split())
        scored: list[tuple[float, dict]] = []
        for item in items:
            text = f"{item.get('title', '')} {item.get('content', '')}".lower()
            words = set(text.split())
            overlap = len(query_words & words) / max(len(query_words), 1)
            scored.append((overlap, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        items = [item for _, item in scored[:10]]

    lines = []
    for item in items[:10]:
        mtype = item.get("type", "?")
        title = item.get("title", "")
        content = item.get("content", "")
        prefix = f"[{mtype}] {title}: " if title else f"[{mtype}] "
        lines.append(prefix + content[:300])
    return "\n".join(lines)


def _tool_search_research_claims(state: InterviewState, args: dict) -> str:
    """Search structured research findings by keyword, ranked by relevance."""
    query = args.get("query", "")
    search_type = args.get("type", "all")
    research = state.get("research_results", {})

    if not research:
        return "No research results available. Research must complete before PRD generation."

    query_words = set(query.lower().split())
    results: list[tuple[float, str, dict]] = []

    if search_type in ("claims", "all"):
        for claim in research.get("validated_claims", []):
            text = f"{claim.get('claim', '')} {claim.get('evidence', '')}".lower()
            overlap = len(query_words & set(text.split())) / max(len(query_words), 1)
            if overlap > 0.08:
                results.append((overlap, "claim", claim))

    if search_type in ("metrics", "all"):
        for metric in research.get("quantified_metrics", []):
            text = f"{metric.get('metric', '')} {metric.get('value', '')} {metric.get('notes', '')}".lower()
            overlap = len(query_words & set(text.split())) / max(len(query_words), 1)
            if overlap > 0.05:
                results.append((overlap, "metric", metric))

    if search_type in ("contradictions", "all"):
        for contra in research.get("contradictions", []):
            text = f"{contra.get('claim_a', '')} {contra.get('claim_b', '')}".lower()
            overlap = len(query_words & set(text.split())) / max(len(query_words), 1)
            if overlap > 0.08:
                results.append((overlap, "contradiction", contra))

    if search_type in ("gaps", "all"):
        for gap in research.get("gaps", []):
            overlap = len(query_words & set(gap.lower().split())) / max(len(query_words), 1)
            if overlap > 0.08:
                results.append((overlap, "gap", {"gap": gap}))

    results.sort(key=lambda x: x[0], reverse=True)

    if not results:
        return f"No matching research findings for: {query}"

    lines: list[str] = []
    for _, rtype, item in results[:8]:
        if rtype == "claim":
            conf = item.get("confidence", "?")
            lines.append(
                f"[CLAIM|{conf}] {item.get('claim', '')}\n"
                f"  Evidence: {item.get('evidence', '')[:250]}\n"
                f"  Source: {item.get('source', '?')}"
            )
        elif rtype == "metric":
            lines.append(
                f"[METRIC] {item.get('metric', '')}: {item.get('value', '')}"
                + (f" — {item.get('notes', '')}" if item.get("notes") else "")
                + f"\n  Source: {item.get('source', '?')}"
            )
        elif rtype == "contradiction":
            lines.append(
                f"[CONTRADICTION] {item.get('claim_a', '')} vs {item.get('claim_b', '')}"
            )
        elif rtype == "gap":
            lines.append(f"[GAP] {item.get('gap', '')}")
    return "\n---\n".join(lines)


def _tool_retrieve_evidence(state: InterviewState, args: dict) -> str:
    claim = args.get("claim", "")
    source_filter = args.get("source", "")
    interview_data = state.get("interview_data", [])

    search_words = set(claim.lower().split())
    results: list[tuple[float, str, str]] = []

    for doc in interview_data:
        fname = doc.get("filename", "?")
        if source_filter and source_filter not in fname:
            continue
        for chunk in doc.get("chunks", []):
            chunk_words = set(chunk.lower().split())
            overlap = len(search_words & chunk_words) / max(len(search_words), 1)
            if overlap > 0.08:
                results.append((overlap, fname, chunk))

    results.sort(key=lambda x: x[0], reverse=True)
    if not results:
        return f"No evidence found for: {claim}"

    parts = []
    for score, fname, chunk in results[:3]:
        parts.append(f"[{fname}] (relevance: {score:.3f})\n{chunk[:500]}")
    return "\n---\n".join(parts)


# ── Tool dispatcher ───────────────────────────────────────────────────────

def _dispatch_tool(tool_name: str, args: dict, state: InterviewState) -> str:
    """Route a tool call to its implementation. Always returns a string."""
    dispatch: dict[str, Any] = {
        "list_interviews":         lambda: _tool_list_interviews(state),
        "search_interview_tree":   lambda: _tool_search_interview_tree(state, args),
        "read_interview_section":  lambda: _tool_read_interview_section(state, args),
        "search_memory":           lambda: _tool_search_memory(state, args),
        "search_db_chunks":        lambda: _tool_search_db_chunks(state, args),
        "get_research_results":    lambda: _tool_get_research_results(state),
        "search_research_claims":  lambda: _tool_search_research_claims(state, args),
        "get_memory_items":        lambda: _tool_get_memory_items(state, args),
        "retrieve_evidence":       lambda: _tool_retrieve_evidence(state, args),
    }
    fn = dispatch.get(tool_name)
    if fn is None:
        return f"Unknown tool: {tool_name}"
    try:
        return str(fn())
    except Exception as exc:
        return f"Tool error ({tool_name}): {exc}"


# ── Parallel tool executor ────────────────────────────────────────────────

def _parallel_execute(
    tool_uses: list[dict],
    state: InterviewState,
    tool_call_log: list,
) -> list[dict]:
    """Execute tool calls (potentially in parallel) with cache check.

    Returns a list of Anthropic-format tool_result content blocks.
    """
    session_id = state.get("session_id", "")

    def execute_one(tu: dict) -> dict:
        tool_name = tu["name"]
        args = tu.get("input", {})
        tool_use_id = tu["id"]

        # Check tool result cache
        cached = cache_manager.get_tool_result_cached(tool_name, args, session_id)
        if cached is not None:
            tool_call_log.append({
                "tool": tool_name,
                "args": args,
                "result_preview": cached[:200],
                "tokens_used": 0,
                "cached": True,
            })
            return {"type": "tool_result", "tool_use_id": tool_use_id, "content": cached}

        result = _dispatch_tool(tool_name, args, state)
        cache_manager.store_tool_result(tool_name, args, session_id, result)
        tool_call_log.append({
            "tool": tool_name,
            "args": args,
            "result_preview": result[:200],
            "tokens_used": 0,
            "cached": False,
        })
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": result}

    if len(tool_uses) == 1:
        return [execute_one(tool_uses[0])]

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(tool_uses))) as pool:
        futures = [pool.submit(execute_one, tu) for tu in tool_uses]
        return [f.result() for f in concurrent.futures.as_completed(futures)]


# ── JSON result parser ────────────────────────────────────────────────────

def _extract_json(text: str) -> Any:
    """Robustly extract the first JSON value from text."""
    text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group())
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _parse_final_result(text: str, agent_type: str) -> dict:
    """Parse final LLM text into the expected result dict shape."""
    parsed = _extract_json(text)
    if isinstance(parsed, dict):
        return parsed

    # Fallback shapes when JSON parse fails
    if agent_type == "research":
        return {
            "validated_claims": [],
            "contradictions": [],
            "quantified_metrics": [],
            "gaps": ["Could not parse structured output"],
            "key_themes": [],
            "summary": text[:2000],
        }
    # prd
    return {
        "title": "Generated PRD",
        "problem_statement": text[:2000],
        "user_stories": [],
        "proposed_solution": "",
        "kpis": [],
        "technical_requirements": [],
        "constraints_and_risks": [],
        "next_actions": [],
        "success_metrics": [],
        "evidence_citations": [],
    }


# ── Build initial (lazy) message ──────────────────────────────────────────

def _build_initial_message(agent_type: str, state: InterviewState) -> str:
    question = state.get("current_question", "")
    interview_data = state.get("interview_data", [])

    if agent_type == "research":
        summaries = []
        for doc in interview_data:
            meta = doc.get("metadata", {})
            summaries.append(
                f"- {doc.get('filename', '?')}: "
                f"{meta.get('word_count', 0)} words"
            )
        interview_list = "\n".join(summaries) or "No interviews loaded."
        return (
            f"PM Question: {question}\n\n"
            f"Available interviews (use tools to fetch content):\n{interview_list}\n\n"
            "Start by calling list_interviews, then search the relevant interviews."
        )
    else:
        research = state.get("research_results", {})
        summary = research.get("summary", "")
        return (
            f"PM Question: {question}\n\n"
            f"Research is available (call get_research_results for the full data).\n"
            + (f"Research summary: {summary[:400]}\n" if summary else "")
            + "\nStart by calling get_research_results to access the full research."
        )


# ── Forced synthesis fallback ─────────────────────────────────────────────

def _forced_synthesis(
    tool_results_collected: list[str],
    state: InterviewState,
    agent_type: str,
    tool_call_log: list,
    tokens_used: int,
) -> dict:
    """Synthesise a result when MAX_ITER is hit, using collected tool outputs."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from backend.services.llm import get_strong_llm

    system = _RESEARCH_SYSTEM if agent_type == "research" else _PRD_SYSTEM
    context_text = "\n---\n".join(tool_results_collected[:12])

    prompt = (
        f"Based on the following evidence collected so far, produce your final answer.\n\n"
        f"PM Question: {state.get('current_question', '')}\n\n"
        f"Evidence:\n{context_text}"
    )

    try:
        llm = get_strong_llm()
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=prompt)])
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
        result = _parse_final_result(raw, agent_type)
    except Exception:
        result = _parse_final_result("", agent_type)

    return {"result": result, "tool_call_log": tool_call_log, "tokens_used": tokens_used}


# ── Anthropic-native ReAct loop ───────────────────────────────────────────

def _run_anthropic(state: InterviewState, agent_type: str) -> dict:
    """Full ReAct loop using the Anthropic SDK with extended thinking."""
    import anthropic as ant

    client = ant.Anthropic(api_key=settings.anthropic_api_key)
    tools = _RESEARCH_TOOLS if agent_type == "research" else _PRD_TOOLS
    system_text = _RESEARCH_SYSTEM if agent_type == "research" else _PRD_SYSTEM

    # System message with prompt-cache header
    system_content = [
        {
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    initial_text = _build_initial_message(agent_type, state)
    messages: list[dict] = [{"role": "user", "content": initial_text}]

    tool_call_log: list[dict] = []
    tokens_used = 0
    tool_results_collected: list[str] = []

    for iteration in range(MAX_ITER):
        thinking_budget = 8000 if iteration == 0 else 2000
        try:
            response = client.beta.messages.create(
                model=settings.strong_model,
                max_tokens=16000,
                system=system_content,
                tools=tools,
                thinking={"type": "enabled", "budget_tokens": thinking_budget},
                messages=messages,
                betas=["interleaved-thinking-2025-05-14", "prompt-caching-2024-07-31"],
                temperature=1,  # required for extended thinking
            )
        except Exception:
            # Retry without thinking if beta not available
            try:
                response = client.messages.create(
                    model=settings.strong_model,
                    max_tokens=8192,
                    system=system_content,
                    tools=tools,
                    messages=messages,
                    extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
                )
            except Exception as exc2:
                # Both failed — fall back to LangChain
                return _run_langchain_fallback(state, agent_type)

        tokens_used += response.usage.input_tokens + response.usage.output_tokens

        # Collect tool use blocks
        tool_uses = [
            {"id": b.id, "name": b.name, "input": b.input}
            for b in response.content
            if b.type == "tool_use"
        ]

        if not tool_uses:
            # Final answer — extract text from response
            text_parts = [
                b.text for b in response.content
                if b.type == "text"
            ]
            final_text = "\n".join(text_parts)
            result = _parse_final_result(final_text, agent_type)
            return {
                "result": result,
                "tool_call_log": tool_call_log,
                "tokens_used": tokens_used,
            }

        # Append assistant turn (includes thinking blocks verbatim)
        messages.append({"role": "assistant", "content": response.content})

        # Execute tools in parallel
        tool_result_blocks = _parallel_execute(tool_uses, state, tool_call_log)

        # Collect for forced synthesis fallback
        for block in tool_result_blocks:
            tool_results_collected.append(str(block.get("content", "")))

        messages.append({"role": "user", "content": tool_result_blocks})

    # MAX_ITER hit
    return _forced_synthesis(
        tool_results_collected, state, agent_type, tool_call_log, tokens_used
    )


# ── LangChain fallback loop ───────────────────────────────────────────────

def _run_langchain_fallback(state: InterviewState, agent_type: str) -> dict:
    """Simple single-shot LangChain call for non-Anthropic providers."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from backend.services.llm import get_strong_llm

    system = _RESEARCH_SYSTEM if agent_type == "research" else _PRD_SYSTEM
    initial = _build_initial_message(agent_type, state)

    # For the fallback, execute all default tools upfront and embed in prompt
    if agent_type == "research":
        interviews_info = _tool_list_interviews(state)
        interview_data = state.get("interview_data", [])
        excerpts: list[str] = []
        for doc in interview_data[:4]:
            fname = doc.get("filename", "?")
            content = doc.get("content", "")
            excerpts.append(f"--- {fname} ---\n{content[:3000]}")
        context = (
            f"{initial}\n\n"
            f"Interview list:\n{interviews_info}\n\n"
            f"Interview excerpts:\n{''.join(excerpts)}"
        )
    else:
        research_info = _tool_get_research_results(state)
        memory_info = _tool_get_memory_items(state, {})
        context = (
            f"{initial}\n\n"
            f"Research results:\n{research_info}\n\n"
            f"Memory items:\n{memory_info}"
        )

    llm = get_strong_llm()
    try:
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=context)])
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    except Exception:
        raw = ""

    result = _parse_final_result(raw, agent_type)
    return {"result": result, "tool_call_log": [], "tokens_used": 0}


# ── Public entry point ────────────────────────────────────────────────────

def run(state: InterviewState, agent_type: str) -> dict:
    """Run the ReAct loop for the given agent type.

    Returns:
        {
            "result":       dict  — validated_claims / PRD fields (same shape as before)
            "tool_call_log": list — [{tool, args, result_preview, tokens_used, cached}]
            "tokens_used":  int
        }
    """
    if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        try:
            import anthropic  # noqa: F401 — availability check
            return _run_anthropic(state, agent_type)
        except ImportError:
            pass  # anthropic SDK not installed
        except Exception:
            pass  # unexpected error — fall through

    return _run_langchain_fallback(state, agent_type)
