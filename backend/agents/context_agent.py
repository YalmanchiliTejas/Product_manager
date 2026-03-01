"""Context Fetcher sub-agent.

Dynamically discovers and assembles the right context for the current task,
inspired by the Claude Code pattern — progressive context building rather
than dumping everything upfront.

Runs as a standalone callable, invoked by the orchestrator.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.state import InterviewState
from backend.services.llm import get_fast_llm


_CONTEXT_ASSESSMENT_PROMPT = """\
You are a context assessment specialist for a product management AI system.

Given a user's question and available interview data, determine what additional
context is needed to answer well.  Return a JSON object:

{
  "needs_memory": true/false,
  "memory_queries": ["query1", "query2"],
  "needs_evidence": true/false,
  "evidence_queries": ["query1", "query2"],
  "needs_project_index": true/false,
  "reasoning": "brief explanation"
}

Be selective — only request what is genuinely needed.  Prefer fewer, more
targeted queries over broad sweeps."""


def _assess_context_needs(question: str, interview_summary: str) -> dict:
    """Use the fast LLM to decide what context the orchestrator needs."""
    llm = get_fast_llm()
    response = llm.invoke([
        SystemMessage(content=_CONTEXT_ASSESSMENT_PROMPT),
        HumanMessage(content=(
            f"User question: {question}\n\n"
            f"Available interview data summary:\n{interview_summary}"
        )),
    ])

    import json
    try:
        return json.loads(response.content)
    except (json.JSONDecodeError, TypeError):
        # Fallback: fetch everything conservatively
        return {
            "needs_memory": True,
            "memory_queries": [question],
            "needs_evidence": True,
            "evidence_queries": [question],
            "needs_project_index": True,
            "reasoning": "Could not parse assessment; fetching broadly.",
        }


def _build_interview_context(interview_data: list[dict], question: str) -> dict:
    """Build context from the locally-loaded interview data (no DB needed).

    Searches interview chunks for relevance to the question using simple
    keyword overlap scoring.
    """
    question_words = set(question.lower().split())
    scored_chunks: list[tuple[float, str, str]] = []

    for doc in interview_data:
        filename = doc.get("filename", "unknown")
        for chunk in doc.get("chunks", []):
            chunk_words = set(chunk.lower().split())
            overlap = len(question_words & chunk_words) / max(len(question_words), 1)
            scored_chunks.append((overlap, filename, chunk))

    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    top_chunks = scored_chunks[:10]

    return {
        "relevant_chunks": [
            {"source": fname, "content": content, "relevance": round(score, 3)}
            for score, fname, content in top_chunks
        ],
        "total_sources_searched": len(interview_data),
        "total_chunks_searched": sum(len(d.get("chunks", [])) for d in interview_data),
    }


def _fetch_db_context(project_id: str, question: str, needs: dict) -> dict:
    """Fetch context from the database layer — memory items, chunks, index.

    Gracefully degrades if the DB is unavailable (CLI-only mode).
    """
    result: dict = {
        "memory_items": [],
        "evidence_chunks": [],
        "project_index": "",
        "citations": {"memory_item_ids": [], "chunk_ids": []},
    }

    try:
        if needs.get("needs_project_index"):
            from backend.services.context_pack import get_context_pack
            pack = get_context_pack(
                project_id=project_id,
                task_type="interview_analysis",
                query=question,
                budget_tokens=3000,
            )
            result["project_index"] = pack.get("index", "")
            result["memory_items"] = pack.get("memory_items", [])
            result["evidence_chunks"] = pack.get("evidence_chunks", [])
            result["citations"] = pack.get("citations", {})
            return result

        if needs.get("needs_memory"):
            from backend.services.hybrid_search import hybrid_search_memory_items
            for query in needs.get("memory_queries", [question]):
                items = hybrid_search_memory_items(
                    project_id=project_id, query=query, match_count=6,
                )
                for item in items:
                    if item["id"] not in {m["id"] for m in result["memory_items"]}:
                        result["memory_items"].append(item)

        if needs.get("needs_evidence"):
            from backend.services.hybrid_search import hybrid_search_chunks
            for query in needs.get("evidence_queries", [question]):
                chunks = hybrid_search_chunks(
                    project_id=project_id, query=query, match_count=8,
                )
                for chunk in chunks:
                    cid = chunk.get("chunk_id")
                    if cid not in {c.get("chunk_id") for c in result["evidence_chunks"]}:
                        result["evidence_chunks"].append(chunk)

        result["citations"] = {
            "memory_item_ids": [m["id"] for m in result["memory_items"]],
            "chunk_ids": [c.get("chunk_id") for c in result["evidence_chunks"]],
        }
    except Exception:
        # DB not available (CLI-only mode) — that's fine, interview data is primary
        pass

    return result


def run_context_agent(state: InterviewState) -> dict:
    """Entry point called by the orchestrator.

    Returns a context_pack dict with:
      - interview_context: relevant chunks from loaded interviews
      - db_context: memory items + evidence chunks from DB (if available)
      - recalled_memories: past session memories injected by the orchestrator
      - memory_context_text: formatted text block for sub-agent prompt injection
      - assessment: what the LLM decided was needed
    """
    question = state["current_question"]
    interview_data = state.get("interview_data", [])
    project_id = state.get("project_id", "")
    recalled = state.get("recalled_memories", [])

    # Summarise available interviews for the assessment
    summaries = []
    for doc in interview_data:
        meta = doc.get("metadata", {})
        summaries.append(
            f"- {doc.get('filename', '?')}: {meta.get('word_count', 0)} words, "
            f"{meta.get('speaker_count', 0)} speakers"
        )
    interview_summary = "\n".join(summaries) if summaries else "No interviews loaded."

    # 1. Assess what context is needed
    needs = _assess_context_needs(question, interview_summary)

    # 2. Build interview-local context (always available, no DB needed)
    interview_context = _build_interview_context(interview_data, question)

    # 3. Fetch DB context if a project is loaded
    db_context: dict = {"memory_items": [], "evidence_chunks": [], "project_index": "", "citations": {}}
    if project_id:
        db_context = _fetch_db_context(project_id, question, needs)

    # 4. Build formatted memory context for prompt injection
    memory_context_text = ""
    if recalled:
        mem_lines = []
        for mem in recalled:
            mtype = mem.get("type", "memory")
            title = mem.get("title", "")
            content = mem.get("content", "")
            if title:
                mem_lines.append(f"- [{mtype}] {title}: {content[:200]}")
            else:
                mem_lines.append(f"- [{mtype}] {content[:250]}")
        memory_context_text = (
            "Relevant knowledge from past sessions:\n"
            + "\n".join(mem_lines)
        )

    return {
        "assessment": needs,
        "interview_context": interview_context,
        "db_context": db_context,
        "recalled_memories": recalled,
        "memory_context_text": memory_context_text,
    }
