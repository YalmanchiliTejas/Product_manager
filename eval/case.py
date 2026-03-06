"""EvalCase dataclass and YAML loader/writer.

Case files live in eval/cases/{split}/*.yaml.
Use load_case() to parse one file, load_cases_for_split() to load a whole split,
and update_case_gold_outputs() to write corrections back.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


CASES_DIR = Path(__file__).parent / "cases"


# ── Sub-structures ────────────────────────────────────────────────────────


@dataclass
class InterviewSpec:
    filename: str
    content: str


@dataclass
class PriorMemoryItem:
    type: str          # decision | constraint | metric | persona
    title: str
    content: str
    confidence: str = "medium"


@dataclass
class PrdAssertion:
    type: str          # field_nonempty | field_contains | min_list_length | min_citations
    field: str = ""
    substring: str = ""
    count: int = 0


@dataclass
class MemoryAssertion:
    type: str          # min_recalled | decision_stored
    count: int = 0
    item_type: str = ""   # for decision_stored


# ── Main case dataclass ───────────────────────────────────────────────────


@dataclass
class EvalCase:
    id: str
    name: str
    description: str
    split: str                                    # train | dev | test
    market_context: str
    question: str
    auto_confirm: bool
    interviews: list[InterviewSpec]
    prior_memory: list[PriorMemoryItem]
    expected_facts: list[str]
    forbidden_facts: list[str]
    expected_prd_assertions: list[PrdAssertion]
    expected_memory_assertions: list[MemoryAssertion]
    gold_outputs: dict[str, Any] = field(default_factory=dict)

    # Path is set by loader so corrections can rewrite the file
    _path: Path | None = field(default=None, repr=False, compare=False)


# ── YAML helpers ─────────────────────────────────────────────────────────


def _req(d: dict, key: str, path: Path) -> Any:
    if key not in d:
        raise ValueError(f"Missing required field '{key}' in {path}")
    return d[key]


def load_case(path: Path) -> EvalCase:
    """Parse a single YAML case file into an EvalCase."""
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Case file {path} must be a YAML mapping")

    interviews = [
        InterviewSpec(
            filename=iv["filename"],
            content=textwrap.dedent(iv.get("content", "")),
        )
        for iv in raw.get("interviews", [])
    ]

    prior_memory = [
        PriorMemoryItem(
            type=pm["type"],
            title=pm["title"],
            content=textwrap.dedent(pm.get("content", "")),
            confidence=pm.get("confidence", "medium"),
        )
        for pm in raw.get("prior_memory", [])
    ]

    prd_assertions = [
        PrdAssertion(
            type=a["type"],
            field=a.get("field", ""),
            substring=a.get("substring", ""),
            count=int(a.get("count", 0)),
        )
        for a in raw.get("expected_prd_assertions", [])
    ]

    memory_assertions = [
        MemoryAssertion(
            type=a["type"],
            count=int(a.get("count", 0)),
            item_type=a.get("item_type", ""),
        )
        for a in raw.get("expected_memory_assertions", [])
    ]

    case = EvalCase(
        id=str(_req(raw, "id", path)),
        name=str(_req(raw, "name", path)),
        description=str(raw.get("description", "")),
        split=str(_req(raw, "split", path)),
        market_context=str(raw.get("market_context", "")),
        question=str(_req(raw, "question", path)),
        auto_confirm=bool(raw.get("auto_confirm", True)),
        interviews=interviews,
        prior_memory=prior_memory,
        expected_facts=list(raw.get("expected_facts", [])),
        forbidden_facts=list(raw.get("forbidden_facts", [])),
        expected_prd_assertions=prd_assertions,
        expected_memory_assertions=memory_assertions,
        gold_outputs=raw.get("gold_outputs") or {},
    )
    case._path = path
    return case


def load_cases_for_split(split: str, cases_dir: Path = CASES_DIR) -> list[EvalCase]:
    """Load all YAML files from cases/{split}/."""
    split_dir = cases_dir / split
    if not split_dir.exists():
        raise FileNotFoundError(f"Split directory not found: {split_dir}")
    cases = []
    for p in sorted(split_dir.glob("*.yaml")):
        cases.append(load_case(p))
    return cases


def load_case_by_id(case_id: str, cases_dir: Path = CASES_DIR) -> EvalCase:
    """Search all splits for a case with the given id."""
    for split_dir in sorted(cases_dir.iterdir()):
        if not split_dir.is_dir():
            continue
        for p in split_dir.glob("*.yaml"):
            try:
                case = load_case(p)
                if case.id == case_id:
                    return case
            except Exception:
                continue
    raise FileNotFoundError(f"No case with id '{case_id}' found in {cases_dir}")


def update_case_gold_outputs(
    case_path: Path,
    gold_outputs: dict,
    new_split: str | None = None,
) -> Path:
    """Rewrite a case YAML file in-place with updated gold_outputs (and optional split change).

    Uses PyYAML round-trip to preserve structure. Comments are not preserved
    (PyYAML limitation), but all data fields are kept exactly.
    """
    with case_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    raw["gold_outputs"] = gold_outputs

    # Keep split label and filesystem location aligned.
    destination_path = case_path
    if new_split is not None:
        raw["split"] = new_split
        destination_dir = case_path.parent.parent / new_split
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination_path = destination_dir / case_path.name

    tmp = destination_path.with_suffix(".yaml.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    tmp.replace(destination_path)
    if destination_path != case_path and case_path.exists():
        case_path.unlink()

    return destination_path
