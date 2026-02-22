from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from ..llm.base import LLMProvider


@dataclass
class AgentResult:
    """Standardized result returned by every agent."""

    agent_name: str
    status: str = "completed"  # completed | failed | partial
    output: dict[str, Any] = field(default_factory=dict)
    reasoning_trace: list[str] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent_name,
            "status": self.status,
            "output": self.output,
            "reasoning_trace": self.reasoning_trace,
            "token_usage": self.token_usage,
        }


class BaseAgent(abc.ABC):
    """Base class for all PM pipeline agents."""

    name: str = "base"

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm
        self._trace: list[str] = []
        self._total_usage: dict[str, int] = {}

    def _record(self, step: str) -> None:
        self._trace.append(step)

    def _accumulate_usage(self, usage: dict[str, int]) -> None:
        for k, v in usage.items():
            self._total_usage[k] = self._total_usage.get(k, 0) + v

    def _call_llm(self, prompt: str, *, system: str = "", **kwargs: Any) -> str:
        resp = self._llm.complete(prompt, system=system, **kwargs)
        self._accumulate_usage(resp.usage)
        return resp.text

    def _call_llm_chat(self, messages: list[dict[str, Any]], *, system: str = "", **kwargs: Any) -> str:
        resp = self._llm.chat(messages, system=system, **kwargs)
        self._accumulate_usage(resp.usage)
        return resp.text

    @abc.abstractmethod
    def run(self, **kwargs: Any) -> AgentResult:
        """Execute the agent's task and return a result."""
