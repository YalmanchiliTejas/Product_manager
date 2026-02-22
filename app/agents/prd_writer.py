from __future__ import annotations

import json
from typing import Any

from .base import AgentResult, BaseAgent


class PRDWriter(BaseAgent):
    """Generates a structured PRD from compressed context and research insights.

    Uses chain-of-thought reasoning to work through product decisions,
    trade-offs, and scope before producing the final document.
    """

    name = "prd-writer"

    SYSTEM = (
        "You are a senior Product Manager writing a Product Requirements Document (PRD). "
        "You think through problems methodically: first understand the user pain, then "
        "reason about solutions, consider trade-offs, and only then write clear requirements. "
        "Your PRDs are specific, actionable, and avoid vague language. "
        "Every requirement should be testable and tied to a user outcome."
    )

    def run(
        self,
        *,
        product_name: str = "",
        context_summary: str = "",
        feedback_summary: str = "",
        research_insights: dict[str, Any] | None = None,
        design_analysis: dict[str, Any] | None = None,
    ) -> AgentResult:
        self._trace = []
        self._total_usage = {}

        # Step 1: Reason through the problem space
        self._record("Reasoning through problem space and user needs")
        reasoning = self._reason_through_problem(
            product_name, context_summary, feedback_summary
        )

        # Step 2: Generate the PRD
        self._record("Generating structured PRD")
        prd = self._generate_prd(
            product_name,
            context_summary,
            feedback_summary,
            reasoning,
            research_insights,
            design_analysis,
        )

        # Step 3: Self-review for gaps
        self._record("Self-reviewing PRD for completeness and gaps")
        review = self._self_review(prd)

        return AgentResult(
            agent_name=self.name,
            status="completed",
            output={
                "prd": prd,
                "reasoning": reasoning,
                "self_review": review,
            },
            reasoning_trace=list(self._trace),
            token_usage=dict(self._total_usage),
        )

    def _reason_through_problem(
        self,
        product_name: str,
        context: str,
        feedback: str,
    ) -> str:
        prompt = (
            f"Before writing a PRD for '{product_name}', think step by step:\n\n"
            f"## Context\n{context}\n\n"
            f"## Stakeholder Feedback\n{feedback}\n\n"
            f"Work through these questions:\n"
            f"1. What is the core user problem? Who experiences it most acutely?\n"
            f"2. What existing solutions do they use today? Why are those insufficient?\n"
            f"3. What are the key constraints (technical, business, timeline)?\n"
            f"4. What trade-offs should we make? (scope vs speed, flexibility vs simplicity)\n"
            f"5. What would success look like in 3 months? 6 months?\n"
            f"6. What are the biggest risks and how do we mitigate them?\n\n"
            f"Think through each carefully."
        )
        return self._call_llm(prompt, system=self.SYSTEM, max_tokens=1500, temperature=0.4)

    def _generate_prd(
        self,
        product_name: str,
        context: str,
        feedback: str,
        reasoning: str,
        research: dict[str, Any] | None,
        design: dict[str, Any] | None,
    ) -> dict[str, Any]:
        research_section = ""
        if research:
            gap = research.get("gap_analysis", "")
            research_section = f"\n## Research Insights\nGap Analysis: {gap}\n"

        design_section = ""
        if design:
            design_section = f"\n## Design Analysis\n{json.dumps(design, indent=2)}\n"

        prompt = (
            f"Write a complete PRD for '{product_name}'.\n\n"
            f"## Your Reasoning\n{reasoning}\n\n"
            f"## Compressed Context\n{context}\n\n"
            f"## Stakeholder Feedback\n{feedback}\n"
            f"{research_section}{design_section}\n"
            f"Output the PRD as JSON with these exact keys:\n"
            f'{{"title": "...", "problem_statement": "...", '
            f'"goals": ["..."], "non_goals": ["..."], '
            f'"user_stories": [{{"persona": "...", "story": "...", "acceptance_criteria": ["..."]}}], '
            f'"requirements": [{{"id": "R1", "description": "...", "priority": "P0|P1|P2", "rationale": "..."}}], '
            f'"success_metrics": [{{"metric": "...", "target": "...", "measurement": "..."}}], '
            f'"risks": [{{"risk": "...", "impact": "High|Med|Low", "mitigation": "..."}}], '
            f'"milestones": [{{"name": "...", "scope": "...", "dependencies": ["..."]}}], '
            f'"open_questions": ["..."], '
            f'"source_context": "..."}}\n\n'
            f"Output ONLY valid JSON."
        )
        raw = self._call_llm(prompt, system=self.SYSTEM, max_tokens=3000, temperature=0.3)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(raw[start:end])
                except json.JSONDecodeError:
                    pass
            self._record("Warning: PRD JSON parse failed, returning raw text")
            return {
                "title": f"PRD: {product_name}",
                "raw_content": raw,
                "parse_error": True,
            }

    def _self_review(self, prd: dict[str, Any]) -> str:
        prd_text = json.dumps(prd, indent=2)
        return self._call_llm(
            f"Review this PRD for completeness and quality:\n\n{prd_text}\n\n"
            f"Check for:\n"
            f"1. Are requirements specific and testable?\n"
            f"2. Are success metrics measurable?\n"
            f"3. Are risks realistic with actionable mitigations?\n"
            f"4. Are there gaps between user stories and requirements?\n"
            f"5. Any contradictions or unclear priorities?\n\n"
            f"Provide a brief assessment and list any issues found.",
            system=self.SYSTEM,
            max_tokens=600,
        )
