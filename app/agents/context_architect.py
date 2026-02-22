from __future__ import annotations

import json
from typing import Any

from .base import AgentResult, BaseAgent


class ContextArchitect(BaseAgent):
    """Recursive document chunking and LLM-powered summarization (RLMS).

    Takes raw documents and feedback, produces a hierarchical compressed
    context that downstream agents can consume within token budgets.
    """

    name = "context-architect"

    CHUNK_SIZE = 2000  # chars per chunk
    MAX_L1 = 32
    MAX_L2 = 12

    SYSTEM = (
        "You are a context compression specialist for a Product Management AI system. "
        "Your job is to distill raw text into concise, information-dense summaries that "
        "preserve all product requirements, user pain points, metrics, and decisions. "
        "Never invent information — only compress what is given."
    )

    def run(
        self,
        *,
        documents: list[str] | None = None,
        feedback: list[str] | None = None,
    ) -> AgentResult:
        documents = documents or []
        feedback = feedback or []
        self._trace = []
        self._total_usage = {}

        # Step 1: Chunk documents
        chunks = self._chunk(documents)
        self._record(f"Chunked {len(documents)} documents into {len(chunks)} chunks")

        # Step 2: Level-1 summaries (per-chunk)
        lvl1 = []
        for i, chunk in enumerate(chunks[: self.MAX_L1]):
            summary = self._summarize_chunk(chunk, level=1)
            lvl1.append(summary)
            if i < 3 or i == len(chunks) - 1:
                self._record(f"L1 summary {i+1}: {summary[:80]}...")

        # Step 3: Level-2 summaries (group L1s)
        lvl2 = []
        for i in range(0, len(lvl1), 4):
            group = lvl1[i : i + 4]
            combined = "\n\n".join(group)
            summary = self._summarize_group(combined, level=2)
            lvl2.append(summary)
        lvl2 = lvl2[: self.MAX_L2]
        self._record(f"Produced {len(lvl2)} L2 group summaries")

        # Step 4: Integrate feedback
        feedback_summary = ""
        if feedback:
            feedback_summary = self._summarize_feedback(feedback)
            self._record(f"Feedback synthesis: {feedback_summary[:80]}...")

        # Step 5: Global synthesis
        global_summary = self._global_synthesis(lvl2, feedback_summary)
        self._record(f"Global summary produced ({len(global_summary)} chars)")

        return AgentResult(
            agent_name=self.name,
            status="completed",
            output={
                "documents_ingested": len(documents),
                "feedback_items": len(feedback),
                "chunk_count": len(chunks),
                "level_1_summaries": lvl1,
                "level_2_summaries": lvl2,
                "feedback_summary": feedback_summary,
                "global_summary": global_summary,
                "token_policy": {
                    "chunk_size_chars": self.CHUNK_SIZE,
                    "recursion_levels": 2,
                    "max_level_1_summaries": self.MAX_L1,
                    "max_level_2_summaries": self.MAX_L2,
                },
            },
            reasoning_trace=list(self._trace),
            token_usage=dict(self._total_usage),
        )

    def _chunk(self, documents: list[str]) -> list[str]:
        chunks: list[str] = []
        for doc in documents:
            for i in range(0, len(doc), self.CHUNK_SIZE):
                chunk = doc[i : i + self.CHUNK_SIZE].strip()
                if chunk:
                    chunks.append(chunk)
        return chunks

    def _summarize_chunk(self, chunk: str, level: int) -> str:
        return self._call_llm(
            f"Summarize the following text in 2-3 concise sentences. "
            f"Preserve all product requirements, user problems, metrics, and decisions.\n\n"
            f"---\n{chunk}\n---",
            system=self.SYSTEM,
            max_tokens=300,
        )

    def _summarize_group(self, combined: str, level: int) -> str:
        return self._call_llm(
            f"You are given several summaries from a product document. "
            f"Merge them into a single coherent paragraph that captures all key points. "
            f"Do not repeat information.\n\n---\n{combined}\n---",
            system=self.SYSTEM,
            max_tokens=400,
        )

    def _summarize_feedback(self, feedback: list[str]) -> str:
        joined = "\n- ".join(feedback)
        return self._call_llm(
            f"Synthesize the following user/stakeholder feedback into a structured summary. "
            f"Group by theme (pain points, feature requests, success metrics).\n\n"
            f"Feedback items:\n- {joined}",
            system=self.SYSTEM,
            max_tokens=500,
        )

    def _global_synthesis(self, lvl2: list[str], feedback_summary: str) -> str:
        parts = "\n\n".join(lvl2)
        prompt = (
            f"Create a comprehensive context briefing for a Product Manager by combining "
            f"these document summaries and stakeholder feedback.\n\n"
            f"## Document Summaries\n{parts}\n\n"
        )
        if feedback_summary:
            prompt += f"## Stakeholder Feedback\n{feedback_summary}\n\n"
        prompt += (
            "Output a structured briefing with sections: Key Findings, User Pain Points, "
            "Requirements, Success Metrics, Open Questions."
        )
        return self._call_llm(prompt, system=self.SYSTEM, max_tokens=1000)
