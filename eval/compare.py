"""Run comparison — compare two runs from results.jsonl.

CLI:
    python -m eval compare {run_id_a} {run_id_b}

Prints a table of per-case score deltas and highlights improvements/regressions.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESULTS_FILE = Path(__file__).parent / "results" / "results.jsonl"

_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_RESET = "\033[0m"

IMPROVED_THRESHOLD = 0.02
REGRESSED_THRESHOLD = -0.02


def load_run_records(run_id: str) -> dict[str, dict]:
    """Return {case_id: record} for all records matching run_id."""
    if not RESULTS_FILE.exists():
        return {}
    records: dict[str, dict] = {}
    with RESULTS_FILE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("run_id") == run_id:
                records[rec["case_id"]] = rec
    return records


def compare_runs(run_id_a: str, run_id_b: str) -> None:
    recs_a = load_run_records(run_id_a)
    recs_b = load_run_records(run_id_b)

    if not recs_a:
        print(f"{_RED}No records found for run_id '{run_id_a}'{_RESET}")
        sys.exit(1)
    if not recs_b:
        print(f"{_RED}No records found for run_id '{run_id_b}'{_RESET}")
        sys.exit(1)

    all_case_ids = sorted(set(recs_a) | set(recs_b))

    print(f"\n{_BOLD}Comparing runs:{_RESET}")
    print(f"  A: {run_id_a}")
    print(f"  B: {run_id_b}\n")

    col_w = max(len(cid) for cid in all_case_ids) + 2
    header = (
        f"{'case_id':<{col_w}} {'A':>6}  {'B':>6}  {'delta':>7}  status"
    )
    sep = "─" * len(header)
    print(header)
    print(sep)

    n_improved = n_regressed = n_same = n_missing = 0
    weighted_a = weighted_b = 0.0

    for case_id in all_case_ids:
        rec_a = recs_a.get(case_id)
        rec_b = recs_b.get(case_id)

        if rec_a is None or rec_b is None:
            label = f"{_DIM}MISSING{_RESET}"
            score_a_str = f"{rec_a['overall_score']:.3f}" if rec_a else "  N/A"
            score_b_str = f"{rec_b['overall_score']:.3f}" if rec_b else "  N/A"
            delta_str = "    N/A"
            n_missing += 1
        else:
            sa = rec_a["overall_score"]
            sb = rec_b["overall_score"]
            delta = sb - sa
            score_a_str = f"{sa:.3f}"
            score_b_str = f"{sb:.3f}"
            delta_str = f"{delta:+.3f}"
            weighted_a += sa
            weighted_b += sb

            if delta > IMPROVED_THRESHOLD:
                label = f"{_GREEN}IMPROVED{_RESET}"
                n_improved += 1
            elif delta < REGRESSED_THRESHOLD:
                label = f"{_RED}REGRESSED{_RESET}"
                n_regressed += 1
            else:
                label = f"{_DIM}SAME{_RESET}"
                n_same += 1

        print(f"{case_id:<{col_w}} {score_a_str:>6}  {score_b_str:>6}  {delta_str:>7}  {label}")

    print(sep)
    n_compared = len(all_case_ids) - n_missing
    if n_compared > 0:
        avg_a = weighted_a / n_compared
        avg_b = weighted_b / n_compared
        overall_delta = avg_b - avg_a
        delta_colour = _GREEN if overall_delta > IMPROVED_THRESHOLD else (_RED if overall_delta < REGRESSED_THRESHOLD else _RESET)
        print(
            f"{'overall':<{col_w}} {avg_a:>6.3f}  {avg_b:>6.3f}  "
            f"{delta_colour}{overall_delta:>+7.3f}{_RESET}"
        )

    print(f"\n  {_GREEN}improved{_RESET}: {n_improved}  {_RED}regressed{_RESET}: {n_regressed}  {_DIM}same{_RESET}: {n_same}  missing: {n_missing}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two eval runs")
    parser.add_argument("run_id_a", help="First run ID")
    parser.add_argument("run_id_b", help="Second run ID")
    args = parser.parse_args()
    compare_runs(args.run_id_a, args.run_id_b)


if __name__ == "__main__":
    main()
