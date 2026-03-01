"""PRD Generator sub-agent.

Takes research results + assembled context + user question and produces
a structured, evidence-backed PRD with KPIs and next actions.
"""

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.state import InterviewState
from backend.services.llm import get_strong_llm


_PRD_GENERATION_PROMPT = """\
You are a senior product manager generating a Product Requirements Document.

Given research findings, customer interview context, and a product question,
write a comprehensive PRD.  Every claim MUST cite its source.

Output a JSON object with this exact structure:

{
  "title": "PRD title",
  "problem_statement": "Evidence-backed problem description citing interviews",
  "user_stories": [
    "As a [persona], I want [feature] so that [benefit]"
  ],
  "proposed_solution": "Solution description",
  "kpis": [
    {
      "metric": "Metric name",
      "target": "Target value (quantified)",
      "measurement_method": "How to measure"
    }
  ],
  "technical_requirements": [
    "Requirement 1",
    "Requirement 2"
  ],
  "constraints_and_risks": [
    "Constraint or risk 1"
  ],
  "next_actions": [
    {
      "action": "Action description",
      "owner": "Role responsible",
      "timeline": "Suggested timeline"
    }
  ],
  "success_metrics": [
    "Metric description with target"
  ],
  "evidence_citations": [
    "Source: filename or reference — supporting quote"
  ]
}

Guidelines:
- KPIs must be quantified with specific targets derived from research.
- User stories must map to real interview findings, not hypothetical personas.
- Constraints should include any contradictions found in research.
- Next actions should be concrete, assignable, and time-bound.
- At least 3 KPIs, 3 user stories, and 3 next actions."""


def _build_prd_prompt(
    question: str,
    research: dict,
    context: dict,
    tasks: list[dict],
) -> str:
    """Assemble the full prompt for PRD generation."""
    parts: list[str] = [f"Product Question: {question}\n"]

    # Research findings
    summary = research.get("summary", "")
    if summary:
        parts.append(f"Research Summary:\n{summary}\n")

    validated = research.get("validated_claims", [])
    if validated:
        claim_lines = "\n".join(
            f"- [{c.get('confidence', '?')}] {c.get('claim', '')} "
            f"(source: {c.get('source', '?')})"
            for c in validated
        )
        parts.append(f"Validated Claims:\n{claim_lines}\n")

    contradictions = research.get("contradictions", [])
    if contradictions:
        contra_lines = "\n".join(
            f"- {c.get('claim_a', '')} vs {c.get('claim_b', '')}"
            for c in contradictions
        )
        parts.append(f"Contradictions Found:\n{contra_lines}\n")

    metrics = research.get("quantified_metrics", [])
    if metrics:
        metric_lines = "\n".join(
            f"- {m.get('metric', '')}: {m.get('value', '')} ({m.get('source', '')})"
            for m in metrics
        )
        parts.append(f"Quantified Metrics:\n{metric_lines}\n")

    themes = research.get("key_themes", [])
    if themes:
        parts.append(f"Key Themes: {', '.join(themes)}\n")

    gaps = research.get("gaps", [])
    if gaps:
        parts.append(f"Data Gaps: {', '.join(gaps)}\n")

    # Context from interviews
    interview_ctx = context.get("interview_context", {})
    relevant_chunks = interview_ctx.get("relevant_chunks", [])
    if relevant_chunks:
        chunk_lines = "\n".join(
            f"- [{c.get('source', '?')}] {c.get('content', '')[:300]}"
            for c in relevant_chunks[:6]
        )
        parts.append(f"Relevant Interview Excerpts:\n{chunk_lines}\n")

    # Memory / DB context
    db_ctx = context.get("db_context", {})
    memory_items = db_ctx.get("memory_items", [])
    if memory_items:
        mem_lines = "\n".join(
            f"- [{m.get('type', '?')}] {m.get('title', '')}: {m.get('content', '')[:200]}"
            for m in memory_items[:5]
        )
        parts.append(f"Project Memory:\n{mem_lines}\n")

    # Recalled memories from past sessions (longitudinal context)
    memory_text = context.get("memory_context_text", "")
    if memory_text:
        parts.append(f"{memory_text}\n")

    # Confirmed tasks
    confirmed_tasks = [t for t in tasks if t.get("status") == "confirmed"]
    if confirmed_tasks:
        task_lines = "\n".join(f"- {t.get('title', '')}" for t in confirmed_tasks)
        parts.append(f"Confirmed Tasks:\n{task_lines}\n")

    return "\n".join(parts)


def _parse_prd_response(content: str) -> dict:
    """Parse the LLM response into a structured PRD dict."""
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        pass

    # Try extracting JSON from markdown code block
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            pass

    # Fallback: return raw content as the PRD
    return {
        "title": "Generated PRD",
        "problem_statement": content,
        "user_stories": [],
        "proposed_solution": "",
        "kpis": [],
        "technical_requirements": [],
        "constraints_and_risks": [],
        "next_actions": [],
        "success_metrics": [],
        "evidence_citations": [],
    }


def _render_prd_markdown(prd: dict) -> str:
    """Render the PRD dict as clean markdown."""
    sections: list[str] = []

    sections.append(f"# {prd.get('title', 'Product Requirements Document')}\n")

    if prd.get("problem_statement"):
        sections.append(f"## Problem Statement\n\n{prd['problem_statement']}\n")

    stories = prd.get("user_stories", [])
    if stories:
        story_lines = "\n".join(f"- {s}" for s in stories)
        sections.append(f"## User Stories\n\n{story_lines}\n")

    if prd.get("proposed_solution"):
        sections.append(f"## Proposed Solution\n\n{prd['proposed_solution']}\n")

    kpis = prd.get("kpis", [])
    if kpis:
        kpi_lines: list[str] = []
        for k in kpis:
            kpi_lines.append(
                f"| {k.get('metric', '')} | {k.get('target', '')} "
                f"| {k.get('measurement_method', '')} |"
            )
        table = "| Metric | Target | Measurement |\n|--------|--------|-------------|\n"
        table += "\n".join(kpi_lines)
        sections.append(f"## KPIs & Success Metrics\n\n{table}\n")

    reqs = prd.get("technical_requirements", [])
    if reqs:
        req_lines = "\n".join(f"- {r}" for r in reqs)
        sections.append(f"## Technical Requirements\n\n{req_lines}\n")

    risks = prd.get("constraints_and_risks", [])
    if risks:
        risk_lines = "\n".join(f"- {r}" for r in risks)
        sections.append(f"## Constraints & Risks\n\n{risk_lines}\n")

    actions = prd.get("next_actions", [])
    if actions:
        action_lines: list[str] = []
        for a in actions:
            action_lines.append(
                f"| {a.get('action', '')} | {a.get('owner', '')} "
                f"| {a.get('timeline', '')} |"
            )
        table = "| Action | Owner | Timeline |\n|--------|-------|----------|\n"
        table += "\n".join(action_lines)
        sections.append(f"## Next Actions\n\n{table}\n")

    citations = prd.get("evidence_citations", [])
    if citations:
        cite_lines = "\n".join(f"- {c}" for c in citations)
        sections.append(f"## Evidence Citations\n\n{cite_lines}\n")

    return "\n".join(sections)


def run_prd_agent(state: InterviewState) -> dict:
    """Entry point called by the orchestrator.

    Delegates to the ReAct loop engine (react_loop.run) which gathers
    evidence via tools before writing the PRD.

    Returns a PRD dict with all structured fields + full_markdown.
    """
    from backend.agents import react_loop

    loop_result = react_loop.run(state, "prd")
    prd = loop_result["result"]

    # Merge tool_call_log into state
    log = state.get("tool_call_log")
    if isinstance(log, list):
        log.extend(loop_result.get("tool_call_log", []))

    # Render markdown and set defaults
    prd["full_markdown"] = _render_prd_markdown(prd)
    prd.setdefault("cited_chunk_ids", [])
    prd.setdefault("cited_memory_ids", [])

    return prd
