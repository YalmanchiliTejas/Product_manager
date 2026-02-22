from __future__ import annotations

import json
from typing import Any

from ..llm.base import ImageInput
from .base import AgentResult, BaseAgent


class DesignReasoner(BaseAgent):
    """Analyzes design inputs — both text descriptions and visual mockups.

    Reasons through UX flows, information architecture, interaction patterns,
    and accessibility to produce structured design feedback and recommendations.
    """

    name = "design-reasoner"

    SYSTEM = (
        "You are a senior Product Designer and UX strategist. You analyze designs "
        "with a critical eye for usability, accessibility, information hierarchy, "
        "and alignment with product requirements. You think through user flows "
        "step by step and identify friction points, missing states, and edge cases. "
        "Be specific and actionable in your feedback."
    )

    def run(
        self,
        *,
        product_name: str = "",
        context_summary: str = "",
        design_descriptions: list[str] | None = None,
        design_images: list[ImageInput] | None = None,
        prd: dict[str, Any] | None = None,
    ) -> AgentResult:
        design_descriptions = design_descriptions or []
        design_images = design_images or []
        self._trace = []
        self._total_usage = {}

        analyses: list[dict[str, Any]] = []

        # Analyze text-based design descriptions
        if design_descriptions:
            self._record(f"Analyzing {len(design_descriptions)} text design descriptions")
            for i, desc in enumerate(design_descriptions):
                analysis = self._analyze_text_design(product_name, context_summary, desc, prd)
                analyses.append({"type": "text", "index": i, "analysis": analysis})

        # Analyze visual design mockups
        if design_images:
            self._record(f"Analyzing {len(design_images)} design images")
            for i, img in enumerate(design_images):
                analysis = self._analyze_image_design(product_name, context_summary, img, prd)
                analyses.append({"type": "image", "index": i, "analysis": analysis})

        # Synthesize overall design assessment
        self._record("Synthesizing overall design assessment")
        synthesis = self._synthesize(product_name, analyses, prd)

        return AgentResult(
            agent_name=self.name,
            status="completed",
            output={
                "individual_analyses": analyses,
                "synthesis": synthesis,
                "text_designs_reviewed": len(design_descriptions),
                "image_designs_reviewed": len(design_images),
            },
            reasoning_trace=list(self._trace),
            token_usage=dict(self._total_usage),
        )

    def _analyze_text_design(
        self,
        product_name: str,
        context: str,
        description: str,
        prd: dict[str, Any] | None,
    ) -> dict[str, Any]:
        prd_context = ""
        if prd:
            goals = prd.get("goals", [])
            user_stories = prd.get("user_stories", [])
            prd_context = (
                f"\n\nPRD Goals: {json.dumps(goals)}"
                f"\nUser Stories: {json.dumps(user_stories)}"
            )

        raw = self._call_llm(
            f"Analyze this design for '{product_name}':\n\n"
            f"Product Context: {context}\n{prd_context}\n\n"
            f"Design Description:\n{description}\n\n"
            f"Reason through step by step:\n"
            f"1. User Flow Analysis: Walk through the flow as a user. Where is there friction?\n"
            f"2. Information Architecture: Is the hierarchy clear? Is anything buried or missing?\n"
            f"3. Edge Cases: What happens with empty states, errors, long text, many items?\n"
            f"4. Accessibility: Color contrast, keyboard nav, screen reader considerations?\n"
            f"5. PRD Alignment: Does this design address the product requirements?\n\n"
            f"Output as JSON:\n"
            f'{{"flow_analysis": "...", "ia_assessment": "...", '
            f'"edge_cases": ["..."], "accessibility_notes": ["..."], '
            f'"prd_alignment": "...", "recommendations": ["..."], '
            f'"severity": "good|needs_work|significant_issues"}}\n\n'
            f"Output ONLY valid JSON.",
            system=self.SYSTEM,
            max_tokens=1500,
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
            return {"raw_analysis": raw, "parse_error": True}

    def _analyze_image_design(
        self,
        product_name: str,
        context: str,
        image: ImageInput,
        prd: dict[str, Any] | None,
    ) -> dict[str, Any]:
        prd_context = ""
        if prd:
            goals = prd.get("goals", [])
            prd_context = f"\nPRD Goals: {json.dumps(goals)}"

        prompt = (
            f"Analyze this design mockup/screenshot for '{product_name}'.\n\n"
            f"Product Context: {context}\n{prd_context}\n\n"
            f"Examine the image and reason through:\n"
            f"1. Visual Hierarchy: What draws the eye first? Is the layout logical?\n"
            f"2. Component Inventory: What UI elements are present? Anything missing?\n"
            f"3. User Flow: How would a user navigate this? Where might they get stuck?\n"
            f"4. Consistency: Do spacing, typography, and colors feel consistent?\n"
            f"5. Accessibility: Contrast ratios, touch targets, text readability?\n"
            f"6. PRD Alignment: Does this screen support the product goals?\n\n"
            f"Output as JSON:\n"
            f'{{"visual_hierarchy": "...", "components": ["..."], '
            f'"flow_assessment": "...", "consistency_notes": "...", '
            f'"accessibility_issues": ["..."], "prd_alignment": "...", '
            f'"recommendations": ["..."], '
            f'"severity": "good|needs_work|significant_issues"}}\n\n'
            f"Output ONLY valid JSON."
        )
        resp = self._llm.chat_with_images(
            prompt,
            [image],
            system=self.SYSTEM,
            max_tokens=1500,
        )
        self._accumulate_usage(resp.usage)
        raw = resp.text

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
            return {"raw_analysis": raw, "parse_error": True}

    def _synthesize(
        self,
        product_name: str,
        analyses: list[dict[str, Any]],
        prd: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not analyses:
            return {"summary": "No designs provided for analysis."}

        analyses_text = json.dumps(analyses, indent=2)
        raw = self._call_llm(
            f"Synthesize these individual design analyses for '{product_name}' "
            f"into an overall design assessment:\n\n{analyses_text}\n\n"
            f"Provide:\n"
            f"1. Overall design maturity rating (1-5)\n"
            f"2. Top 3 strengths\n"
            f"3. Top 3 areas for improvement (prioritized)\n"
            f"4. Critical issues that block launch\n"
            f"5. Suggested next design iteration focus\n\n"
            f"Output as JSON:\n"
            f'{{"maturity_rating": 3, "strengths": ["..."], '
            f'"improvements": ["..."], "blockers": ["..."], '
            f'"next_iteration_focus": "..."}}\n\n'
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
            return {"raw_synthesis": raw, "parse_error": True}
