"""Pure-Python scorer — zero LLM calls, zero Supabase imports.

score_case(case, outputs) -> ScoreResult

Weights:
  0.40 * fact_coverage
  0.10 * forbidden_miss_rate
  0.30 * prd_assertion_pass_rate
  0.20 * memory_assertion_pass_rate
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from eval.case import EvalCase, MemoryAssertion, PrdAssertion

if TYPE_CHECKING:
    from eval.runner import RunOutputs

FACT_WEIGHT = 0.40
FORBIDDEN_WEIGHT = 0.10
PRD_WEIGHT = 0.30
MEMORY_WEIGHT = 0.20


# ── Result dataclass ──────────────────────────────────────────────────────


@dataclass
class ScoreResult:
    fact_coverage: float            # 0-1, fraction of expected_facts found
    forbidden_miss_rate: float      # 0-1, fraction of forbidden_facts NOT found
    prd_assertion_pass_rate: float  # 0-1
    memory_assertion_pass_rate: float  # 0-1
    overall: float                  # weighted composite
    details: dict[str, list[dict]] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "fact_coverage": self.fact_coverage,
            "forbidden_miss_rate": self.forbidden_miss_rate,
            "prd_assertion_pass_rate": self.prd_assertion_pass_rate,
            "memory_assertion_pass_rate": self.memory_assertion_pass_rate,
            "overall": self.overall,
            "details": self.details,
        }


# ── Corpus builder ────────────────────────────────────────────────────────


def _build_corpus(research_results: dict, prd_document: dict) -> str:
    """Concatenate all text output into a single lowercase search corpus."""
    parts: list[str] = []

    # Research summary
    parts.append(research_results.get("summary", ""))

    # All claim text
    for claim in research_results.get("validated_claims", []):
        parts.append(claim.get("claim", ""))
        parts.append(claim.get("evidence", ""))

    # Key themes
    parts.extend(research_results.get("key_themes", []))

    # Quantified metrics
    for m in research_results.get("quantified_metrics", []):
        parts.append(f"{m.get('metric','')} {m.get('value','')} {m.get('notes','')}")

    # PRD full text
    parts.append(prd_document.get("full_markdown", ""))
    parts.append(prd_document.get("problem_statement", ""))
    parts.append(prd_document.get("proposed_solution", ""))
    parts.extend(prd_document.get("user_stories", []))
    parts.extend(prd_document.get("technical_requirements", []))
    parts.extend(prd_document.get("constraints_and_risks", []))

    return " ".join(parts).lower()


# ── Fact checking ─────────────────────────────────────────────────────────


def _check_fact(fact: str, corpus: str) -> dict[str, Any]:
    needle = fact.lower()
    idx = corpus.find(needle)
    if idx == -1:
        return {"fact": fact, "found": False, "text_match": None}
    # Return up to 80 chars of surrounding context
    start = max(0, idx - 20)
    end = min(len(corpus), idx + len(needle) + 60)
    snippet = corpus[start:end].replace("\n", " ").strip()
    return {"fact": fact, "found": True, "text_match": f"...{snippet}..."}


# ── PRD assertion checker ─────────────────────────────────────────────────


def _check_prd_assertion(assertion: PrdAssertion, prd: dict) -> dict[str, Any]:
    t = assertion.type
    result: dict[str, Any] = {"assertion": vars(assertion), "passed": False, "reason": ""}

    if t == "field_nonempty":
        val = prd.get(assertion.field)
        result["passed"] = bool(val)
        result["reason"] = (
            f"prd['{assertion.field}'] = {repr(str(val)[:60])}"
            if val
            else f"prd['{assertion.field}'] is empty or missing"
        )

    elif t == "field_contains":
        haystack = str(prd.get(assertion.field, "")).lower()
        needle = assertion.substring.lower()
        result["passed"] = needle in haystack
        result["reason"] = (
            f"Found '{assertion.substring}' in prd['{assertion.field}']"
            if result["passed"]
            else f"'{assertion.substring}' not found in prd['{assertion.field}']"
        )

    elif t == "min_list_length":
        lst = prd.get(assertion.field, [])
        actual = len(lst) if isinstance(lst, list) else 0
        result["passed"] = actual >= assertion.count
        result["reason"] = f"prd['{assertion.field}'] has {actual} items (need ≥{assertion.count})"

    elif t == "min_citations":
        chunk_ids = prd.get("cited_chunk_ids", []) or []
        mem_ids = prd.get("cited_memory_ids", []) or []
        total = len(chunk_ids) + len(mem_ids)
        result["passed"] = total >= assertion.count
        result["reason"] = f"Total citations: {total} (need ≥{assertion.count})"

    else:
        result["reason"] = f"Unknown assertion type: {t}"

    return result


# ── Memory assertion checker ──────────────────────────────────────────────


def _check_memory_assertion(
    assertion: MemoryAssertion,
    recalled_memories: list[dict],
    decision_log: list[dict],
) -> dict[str, Any]:
    t = assertion.type
    result: dict[str, Any] = {"assertion": vars(assertion), "passed": False, "reason": ""}

    if t == "min_recalled":
        actual = len(recalled_memories)
        result["passed"] = actual >= assertion.count
        result["reason"] = f"recalled_memories has {actual} items (need ≥{assertion.count})"

    elif t == "decision_stored":
        matching = [
            item for item in decision_log
            if item.get("type") == assertion.item_type
        ]
        result["passed"] = len(matching) > 0
        result["reason"] = (
            f"Found {len(matching)} '{assertion.item_type}' item(s) in decision_log"
            if result["passed"]
            else f"No '{assertion.item_type}' items found in decision_log"
        )

    else:
        result["reason"] = f"Unknown memory assertion type: {t}"

    return result


# ── Master scorer ─────────────────────────────────────────────────────────


def score_case(case: EvalCase, outputs: "RunOutputs") -> ScoreResult:
    """Score a completed run against a case's assertions."""
    research = outputs.research_results or {}
    prd = outputs.prd_document or {}
    recalled = outputs.recalled_memories or []
    dec_log = outputs.decision_log or []

    corpus = _build_corpus(research, prd)

    # ── Fact coverage ──────────────────────────────────────────────────
    fact_details: list[dict] = []
    if case.expected_facts:
        for fact in case.expected_facts:
            fact_details.append(_check_fact(fact, corpus))
        fact_coverage = sum(1 for d in fact_details if d["found"]) / len(fact_details)
    else:
        fact_coverage = 1.0

    # ── Forbidden facts ────────────────────────────────────────────────
    forbidden_details: list[dict] = []
    if case.forbidden_facts:
        for fact in case.forbidden_facts:
            d = _check_fact(fact, corpus)
            forbidden_details.append(d)
        # Higher = better: fraction of forbidden facts NOT found
        forbidden_miss_rate = sum(1 for d in forbidden_details if not d["found"]) / len(
            forbidden_details
        )
    else:
        forbidden_miss_rate = 1.0

    # ── PRD assertions ─────────────────────────────────────────────────
    prd_details: list[dict] = []
    if case.expected_prd_assertions:
        for assertion in case.expected_prd_assertions:
            prd_details.append(_check_prd_assertion(assertion, prd))
        prd_pass_rate = sum(1 for d in prd_details if d["passed"]) / len(prd_details)
    else:
        prd_pass_rate = 1.0

    # ── Memory assertions ──────────────────────────────────────────────
    mem_details: list[dict] = []
    if case.expected_memory_assertions:
        for assertion in case.expected_memory_assertions:
            mem_details.append(_check_memory_assertion(assertion, recalled, dec_log))
        mem_pass_rate = sum(1 for d in mem_details if d["passed"]) / len(mem_details)
    else:
        mem_pass_rate = 1.0

    overall = (
        FACT_WEIGHT * fact_coverage
        + FORBIDDEN_WEIGHT * forbidden_miss_rate
        + PRD_WEIGHT * prd_pass_rate
        + MEMORY_WEIGHT * mem_pass_rate
    )

    return ScoreResult(
        fact_coverage=round(fact_coverage, 4),
        forbidden_miss_rate=round(forbidden_miss_rate, 4),
        prd_assertion_pass_rate=round(prd_pass_rate, 4),
        memory_assertion_pass_rate=round(mem_pass_rate, 4),
        overall=round(overall, 4),
        details={
            "facts": fact_details,
            "forbidden": forbidden_details,
            "prd": prd_details,
            "memory": mem_details,
        },
    )
