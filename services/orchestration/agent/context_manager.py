"""
Token-budget-aware context assembly.

Uses a 4-chars-per-token approximation — accurate enough for English prose
without the overhead of running a real tokenizer at runtime.
"""

from dataclasses import dataclass, field
from typing import Any

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


@dataclass
class ContextItem:
    text: str
    label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PackedContext:
    items: list[ContextItem]
    estimated_tokens: int
    truncated: bool


def pack_into_context(
    items: list[ContextItem],
    budget: int,
    reserve: int = 0,
) -> PackedContext:
    """
    Greedily pack items into a token budget.

    Args:
        items:   Content items to pack (taken in order provided).
        budget:  Total token budget.
        reserve: Tokens reserved for system prompt + expected response.
                 Subtracted from budget before packing.
    """
    effective = max(budget - reserve, 0)
    result: list[ContextItem] = []
    used = 0

    for item in items:
        tokens = estimate_tokens(item.text + item.label)
        if used + tokens > effective:
            return PackedContext(items=result, estimated_tokens=used, truncated=True)
        result.append(item)
        used += tokens

    return PackedContext(items=result, estimated_tokens=used, truncated=False)


def render_context(packed: PackedContext, separator: str = "\n\n---\n\n") -> str:
    """Render packed items into a single prompt string."""
    parts = []
    for item in packed.items:
        if item.label:
            parts.append(f"### {item.label}\n{item.text}")
        else:
            parts.append(item.text)
    return separator.join(parts)


def batch_by_token_budget(
    items: list[ContextItem],
    budget_per_batch: int,
) -> list[list[ContextItem]]:
    """
    Split a large item list into batches where each batch fits within a budget.
    Used in the MapReduce pipeline to handle very large source corpora.
    """
    batches: list[list[ContextItem]] = []
    current: list[ContextItem] = []
    current_tokens = 0

    for item in items:
        tokens = estimate_tokens(item.text + item.label)
        if current_tokens + tokens > budget_per_batch and current:
            batches.append(current)
            current = []
            current_tokens = 0
        current.append(item)
        current_tokens += tokens

    if current:
        batches.append(current)

    return batches
