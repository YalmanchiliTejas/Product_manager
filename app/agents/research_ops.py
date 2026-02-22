from __future__ import annotations

import json
from typing import Any

from .base import AgentResult, BaseAgent


class ResearchOps(BaseAgent):
    """Plans interview outreach, generates targeted questions,
    and synthesizes collected feedback into actionable insights."""

    name = "research-ops"

    SYSTEM = (
        "You are a user research operations specialist for a Product Management team. "
        "You design interview guides, generate targeted questions based on product context, "
        "and synthesize qualitative feedback into structured insights. "
        "Be specific, avoid generic questions, and always tie questions back to the product context."
    )

    def run(
        self,
        *,
        product_name: str = "",
        context_summary: str = "",
        existing_feedback: list[str] | None = None,
        stakeholder_roles: list[str] | None = None,
    ) -> AgentResult:
        existing_feedback = existing_feedback or []
        stakeholder_roles = stakeholder_roles or [
            "End User",
            "Engineering Lead",
            "Product Manager",
            "Designer",
            "Customer Success",
        ]
        self._trace = []
        self._total_usage = {}

        # Step 1: Generate role-specific interview questions
        self._record("Generating targeted interview questions from context")
        questions = self._generate_questions(product_name, context_summary, stakeholder_roles)

        # Step 2: Identify research gaps
        self._record("Analyzing existing feedback for gaps")
        gap_analysis = self._analyze_gaps(context_summary, existing_feedback)

        # Step 3: Create interview plan
        self._record("Building interview outreach plan")
        interview_plan = self._build_plan(product_name, stakeholder_roles, questions)

        return AgentResult(
            agent_name=self.name,
            status="completed",
            output={
                "interview_plan": interview_plan,
                "role_questions": questions,
                "gap_analysis": gap_analysis,
                "channels": ["email", "slack_dm", "calendar_link"],
                "recommended_sample_size": max(5, len(stakeholder_roles) * 2),
            },
            reasoning_trace=list(self._trace),
            token_usage=dict(self._total_usage),
        )

    def _generate_questions(
        self,
        product_name: str,
        context: str,
        roles: list[str],
    ) -> dict[str, list[str]]:
        prompt = (
            f"You are planning user research for '{product_name}'.\n\n"
            f"Context:\n{context}\n\n"
            f"Generate 3-4 specific, open-ended interview questions for each of these roles: "
            f"{', '.join(roles)}.\n\n"
            f"Questions should uncover pain points, workflow gaps, and success criteria "
            f"specific to the product context above.\n\n"
            f"Output as JSON: {{\"role_name\": [\"question1\", \"question2\", ...], ...}}\n"
            f"Output ONLY valid JSON, no other text."
        )
        raw = self._call_llm(prompt, system=self.SYSTEM, max_tokens=1500)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # If LLM didn't return clean JSON, extract it
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
            self._record("Warning: Could not parse question JSON, using fallback")
            return {role: [f"What is your biggest challenge with {product_name}?"] for role in roles}

    def _analyze_gaps(self, context: str, feedback: list[str]) -> str:
        if not feedback:
            return "No existing feedback to analyze. Full research needed."
        joined = "\n- ".join(feedback)
        return self._call_llm(
            f"Given this product context:\n{context}\n\n"
            f"And this existing feedback:\n- {joined}\n\n"
            f"What research gaps remain? What questions are still unanswered? "
            f"What stakeholder perspectives are missing?",
            system=self.SYSTEM,
            max_tokens=600,
        )

    def _build_plan(
        self,
        product_name: str,
        roles: list[str],
        questions: dict[str, list[str]],
    ) -> dict[str, Any]:
        return {
            "product": product_name,
            "target_roles": roles,
            "questions_per_role": {role: len(qs) for role, qs in questions.items()},
            "outreach_channels": ["email", "slack_dm", "calendar_link"],
            "suggested_format": "30-minute semi-structured interview",
            "follow_up": "Summarize key themes within 24h of each interview",
        }
