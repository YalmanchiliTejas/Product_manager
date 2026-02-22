from __future__ import annotations

import json
from typing import Any

from .base import AgentResult, BaseAgent


class DeliveryPlanner(BaseAgent):
    """Converts a PRD into execution-ready tickets and plans distribution
    across project management tools (Jira, Slack, Confluence)."""

    name = "delivery-planner"

    SYSTEM = (
        "You are a delivery planning specialist who converts PRDs into actionable, "
        "well-scoped engineering tickets. Each ticket should have clear acceptance "
        "criteria, dependencies, and an appropriate owner role. Think about execution "
        "order, parallelization opportunities, and risk sequencing."
    )

    SUPPORTED_INTEGRATIONS = ("jira", "confluence", "slack", "teams")

    def run(
        self,
        *,
        product_name: str = "",
        prd: dict[str, Any] | None = None,
        target_integrations: list[str] | None = None,
    ) -> AgentResult:
        prd = prd or {}
        target_integrations = target_integrations or ["jira", "slack"]
        self._trace = []
        self._total_usage = {}

        # Step 1: Generate tickets from PRD
        self._record("Generating tickets from PRD requirements")
        tickets = self._generate_tickets(product_name, prd)

        # Step 2: Determine execution order
        self._record("Planning execution order and dependencies")
        execution_plan = self._plan_execution(tickets)

        # Step 3: Plan distribution across tools
        self._record("Planning ticket distribution across integrations")
        distribution = self._plan_distribution(target_integrations, tickets)

        return AgentResult(
            agent_name=self.name,
            status="completed",
            output={
                "tickets": tickets,
                "execution_plan": execution_plan,
                "distribution": distribution,
                "total_tickets": len(tickets),
            },
            reasoning_trace=list(self._trace),
            token_usage=dict(self._total_usage),
        )

    def _generate_tickets(self, product_name: str, prd: dict[str, Any]) -> list[dict[str, Any]]:
        prd_text = json.dumps(prd, indent=2)
        key_prefix = (product_name or "PRD")[:3].upper()

        raw = self._call_llm(
            f"Convert this PRD into engineering tickets:\n\n{prd_text}\n\n"
            f"For each requirement and milestone, create specific tickets.\n"
            f"Each ticket must have:\n"
            f'- "id": "{key_prefix}-NNN" (sequential numbering starting at 101)\n'
            f'- "title": concise actionable title\n'
            f'- "description": what needs to be done\n'
            f'- "acceptance_criteria": list of testable criteria\n'
            f'- "owner_role": who should work on this (Engineer, Designer, PM, etc.)\n'
            f'- "priority": "P0" (must have) | "P1" (should have) | "P2" (nice to have)\n'
            f'- "estimated_points": 1, 2, 3, 5, 8, or 13\n'
            f'- "dependencies": list of ticket IDs this depends on (can be empty)\n'
            f'- "labels": relevant labels\n\n'
            f"Output as JSON array. Output ONLY valid JSON.",
            system=self.SYSTEM,
            max_tokens=3000,
        )
        try:
            result = json.loads(raw)
            if isinstance(result, list):
                return result
            if isinstance(result, dict) and "tickets" in result:
                return result["tickets"]
            return [result]
        except json.JSONDecodeError:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(raw[start:end])
                except json.JSONDecodeError:
                    pass
            self._record("Warning: Ticket JSON parse failed, using fallback")
            return [
                {
                    "id": f"{key_prefix}-101",
                    "title": f"Implement {product_name} core functionality",
                    "owner_role": "Engineer",
                    "priority": "P0",
                    "raw_content": raw,
                    "parse_error": True,
                }
            ]

    def _plan_execution(self, tickets: list[dict[str, Any]]) -> dict[str, Any]:
        ticket_summary = json.dumps(
            [{"id": t.get("id"), "title": t.get("title"), "priority": t.get("priority"),
              "dependencies": t.get("dependencies", [])} for t in tickets],
            indent=2,
        )
        raw = self._call_llm(
            f"Given these tickets:\n{ticket_summary}\n\n"
            f"Create an execution plan:\n"
            f"1. Group tickets into phases/sprints based on dependencies\n"
            f"2. Identify which tickets can be parallelized\n"
            f"3. Flag the critical path\n\n"
            f"Output as JSON:\n"
            f'{{"phases": [{{"name": "...", "tickets": ["ID1", "ID2"], "parallel": true|false}}], '
            f'"critical_path": ["ID1", "ID2", ...], '
            f'"total_estimated_points": N}}\n\n'
            f"Output ONLY valid JSON.",
            system=self.SYSTEM,
            max_tokens=800,
        )
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
            return {"raw_plan": raw, "parse_error": True}

    def _plan_distribution(
        self,
        integrations: list[str],
        tickets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        enabled = [i for i in integrations if i in self.SUPPORTED_INTEGRATIONS] or ["jira"]
        distribution = []
        for integration in enabled:
            if integration == "jira":
                distribution.append({
                    "integration": "jira",
                    "action": "create_issues",
                    "ticket_count": len(tickets),
                    "status": "queued",
                })
            elif integration == "confluence":
                distribution.append({
                    "integration": "confluence",
                    "action": "create_prd_page",
                    "ticket_count": 1,
                    "status": "queued",
                })
            elif integration == "slack":
                distribution.append({
                    "integration": "slack",
                    "action": "post_summary",
                    "ticket_count": 1,
                    "status": "queued",
                })
            elif integration == "teams":
                distribution.append({
                    "integration": "teams",
                    "action": "post_summary",
                    "ticket_count": 1,
                    "status": "queued",
                })
        return distribution
