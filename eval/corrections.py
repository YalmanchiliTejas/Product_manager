"""Human correction workflow — annotate failed cases and promote to training data.

CLI:
    python -m eval corrections annotate {run_id} {case_id}
    python -m eval corrections promote {case_id}

annotate:
  Shows failed assertions from a run, lets you accept the actual output as
  gold and optionally change the case split to 'train'.

promote:
  Moves a case to the 'train' split without needing a specific run.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

from eval.case import CASES_DIR, load_case_by_id, update_case_gold_outputs

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
RESULTS_FILE = Path(__file__).parent / "results" / "results.jsonl"

_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_RESET = "\033[0m"


# ── Helpers ───────────────────────────────────────────────────────────────


def _load_artifact(run_id: str, case_id: str, name: str) -> dict | list | None:
    path = ARTIFACTS_DIR / run_id / case_id / name
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _prompt(msg: str, choices: list[str]) -> str:
    """Simple interactive prompt. Returns lowercased choice."""
    choices_str = "/".join(choices)
    while True:
        try:
            ans = input(f"{msg} [{choices_str}]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        if ans in choices:
            return ans
        print(f"  Please enter one of: {choices_str}")


def _print_section(title: str, content: str, max_chars: int = 500) -> None:
    print(f"\n{_BOLD}{title}{_RESET}")
    truncated = content[:max_chars]
    if len(content) > max_chars:
        truncated += f"\n  {_DIM}... ({len(content) - max_chars} chars truncated){_RESET}"
    print(textwrap.indent(truncated, "  "))


# ── annotate ─────────────────────────────────────────────────────────────


def annotate(run_id: str, case_id: str) -> None:
    """Interactive annotation for a single case-run."""
    print(f"\n{_BOLD}Annotation:{_RESET} run={run_id}  case={case_id}")

    # Load score
    score = _load_artifact(run_id, case_id, "score.json")
    if score is None:
        print(f"{_RED}No score.json found at eval/artifacts/{run_id}/{case_id}/{_RESET}")
        sys.exit(1)

    overall = score.get("overall", 0)
    colour = _GREEN if overall >= 0.7 else _RED
    print(f"\n{colour}Overall score: {overall:.3f}{_RESET}")

    # Failed assertions
    details = score.get("details", {})
    missed_facts = [d for d in details.get("facts", []) if not d.get("found")]
    failed_prd = [d for d in details.get("prd", []) if not d.get("passed")]
    failed_mem = [d for d in details.get("memory", []) if not d.get("passed")]
    forbidden_found = [d for d in details.get("forbidden", []) if d.get("found")]

    if missed_facts:
        print(f"\n{_YELLOW}Missed expected facts:{_RESET}")
        for d in missed_facts:
            print(f"  - {d['fact']}")

    if failed_prd:
        print(f"\n{_YELLOW}Failed PRD assertions:{_RESET}")
        for d in failed_prd:
            a = d.get("assertion", {})
            print(f"  - [{a.get('type')}] {d.get('reason')}")

    if failed_mem:
        print(f"\n{_YELLOW}Failed memory assertions:{_RESET}")
        for d in failed_mem:
            a = d.get("assertion", {})
            print(f"  - [{a.get('type')}] {d.get('reason')}")

    if forbidden_found:
        print(f"\n{_RED}Forbidden facts that appeared:{_RESET}")
        for d in forbidden_found:
            print(f"  - {d['fact']}  (match: {d.get('text_match', '')})")

    # Show key outputs
    research = _load_artifact(run_id, case_id, "research.json") or {}
    prd = _load_artifact(run_id, case_id, "prd.json") or {}
    tickets = _load_artifact(run_id, case_id, "tickets.json") or []

    summary = research.get("summary", "")
    if summary:
        _print_section("Research Summary", summary)

    prd_md = prd.get("full_markdown", "")
    if prd_md:
        _print_section("PRD (first 800 chars)", prd_md, max_chars=800)

    print(f"\n  Tickets: {len(tickets)} generated")

    # Ask user
    print()
    accept = _prompt("Accept this output as gold for future training?", ["yes", "no", "skip"])

    if accept == "skip":
        print(f"{_DIM}Skipped.{_RESET}")
        return

    if accept == "no":
        print(f"{_DIM}Output not accepted. Case unchanged.{_RESET}")
        return

    # accept == "yes"
    gold_outputs: dict = {}
    if research:
        gold_outputs["research"] = research
    if prd:
        gold_outputs["prd"] = prd
    if tickets:
        gold_outputs["tickets"] = tickets

    # Find case path
    try:
        case = load_case_by_id(case_id)
    except FileNotFoundError:
        print(f"{_RED}Case '{case_id}' not found in eval/cases/{_RESET}")
        sys.exit(1)

    case_path = case._path
    new_split = None

    promote_ans = _prompt("Change split to 'train'?", ["yes", "no"])
    if promote_ans == "yes":
        new_split = "train"

    updated_path = update_case_gold_outputs(case_path, gold_outputs, new_split)
    split_note = f" → split changed to 'train'" if new_split else ""
    print(f"\n{_GREEN}Gold outputs saved to {updated_path.relative_to(CASES_DIR)}{split_note}{_RESET}")


# ── promote ───────────────────────────────────────────────────────────────


def promote(case_id: str) -> None:
    """Change case split to 'train'."""
    try:
        case = load_case_by_id(case_id)
    except FileNotFoundError:
        print(f"{_RED}Case '{case_id}' not found{_RESET}")
        sys.exit(1)

    if case.split == "train":
        print(f"{_DIM}Case '{case_id}' is already in split 'train'{_RESET}")
        return

    updated_path = update_case_gold_outputs(case._path, case.gold_outputs, new_split="train")
    rel_path = updated_path.relative_to(CASES_DIR)
    print(f"{_GREEN}Case '{case_id}' promoted to split 'train' (was '{case.split}') at {rel_path}{_RESET}")


# ── CLI ───────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Human correction workflow for eval cases")
    sub = parser.add_subparsers(dest="command", required=True)

    ann = sub.add_parser("annotate", help="Review a run and optionally save as gold")
    ann.add_argument("run_id", help="Run ID to annotate")
    ann.add_argument("case_id", help="Case ID to annotate")

    prom = sub.add_parser("promote", help="Move a case to train split")
    prom.add_argument("case_id", help="Case ID to promote")

    args = parser.parse_args()

    if args.command == "annotate":
        annotate(args.run_id, args.case_id)
    elif args.command == "promote":
        promote(args.case_id)


if __name__ == "__main__":
    main()
