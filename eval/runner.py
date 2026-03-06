"""Evaluation runner — executes the real InterviewSession end-to-end.

CLI:
    python -m eval runner --split dev
    python -m eval runner --case case_001
    python -m eval runner --split dev --model claude-sonnet-4-6 --provider anthropic --tag v2

For each case the runner:
  1. Builds interview_data from inline YAML content (via temp files)
  2. Creates an InterviewSession, seeds prior_memory into the decision_log
  3. Runs start() → ask(auto_confirm=True) which internally does the full pipeline
  4. Captures all artifacts and scores them
  5. Saves artifacts to eval/artifacts/{run_id}/{case_id}/
  6. Appends a result record to eval/results/results.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.case import EvalCase, PriorMemoryItem, load_case_by_id, load_cases_for_split
from eval.scorer import ScoreResult, score_case

CASE_TIMEOUT = 120  # seconds per case
ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
RESULTS_FILE = Path(__file__).parent / "results" / "results.jsonl"

# ── ANSI colours ──────────────────────────────────────────────────────────

_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_RESET = "\033[0m"


# ── RunOutputs dataclass ──────────────────────────────────────────────────


@dataclass
class RunOutputs:
    case_id: str
    run_id: str
    research_results: dict = field(default_factory=dict)
    prd_document: dict = field(default_factory=dict)
    tickets: list[dict] = field(default_factory=list)
    tool_call_log: list[dict] = field(default_factory=list)
    cache_stats: dict = field(default_factory=dict)
    decision_log: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    recalled_memories: list[dict] = field(default_factory=list)
    phase_snapshots: dict[str, dict] = field(default_factory=dict)
    error: str | None = None
    duration_seconds: float = 0.0


# ── Prior memory seeding ──────────────────────────────────────────────────


def _seed_prior_memory(session: Any, prior_memory: list[PriorMemoryItem]) -> None:
    """Inject prior_memory items into the session's DecisionLog BEFORE session.start().

    recall_memories() inside ask() calls decision_log.search(question, limit=5)
    which finds these items via keyword overlap — no Supabase needed.
    """
    for spec in prior_memory:
        session.decision_log.add({
            "type": spec.type,
            "title": spec.title,
            "content": spec.content,
            "confidence": spec.confidence,
            "phase": "eval_seed",
            "session_id": session.state.get("session_id", ""),
        })


# ── Interview data builder ────────────────────────────────────────────────


def _build_interview_data(case: EvalCase) -> list[dict]:
    """Write each inline interview to a temp .txt file, parse it, then unlink."""
    from backend.agents.doc_parser import parse_interview_file

    interview_data: list[dict] = []
    for spec in case.interviews:
        with tempfile.NamedTemporaryFile(
            suffix=".txt", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write(spec.content)
            tmp_path = f.name
        try:
            parsed = parse_interview_file(tmp_path)
            parsed["filename"] = spec.filename  # restore logical filename
            interview_data.append(parsed)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return interview_data


# ── Core single-case runner ───────────────────────────────────────────────


def _run_single_case_inner(case: EvalCase, run_id: str) -> RunOutputs:
    """Execute one case against the real orchestrator. Called inside a timeout thread."""
    from backend.agents.orchestrator import InterviewSession

    outputs = RunOutputs(case_id=case.id, run_id=run_id)
    t0 = time.monotonic()

    interview_data = _build_interview_data(case)

    session = InterviewSession(
        interview_data=interview_data,
        market_context=case.market_context,
        project_id="",   # no-DB mode
        user_id="eval-runner",
    )

    # Seed prior memory into decision_log BEFORE start()
    _seed_prior_memory(session, case.prior_memory)

    # Run the full pipeline
    session.start()
    outputs.phase_snapshots["after_start"] = {
        "phase": session.get_phase(),
        "task_count": len(session.get_tasks()),
    }

    session.ask(case.question, auto_confirm=True)
    # auto_confirm=True runs: confirm → research → prd → review → tickets internally

    outputs.phase_snapshots["after_ask"] = {
        "phase": session.get_phase(),
        "task_count": len(session.get_tasks()),
        "has_research": bool(session.state.get("research_results")),
        "has_prd": bool(session.state.get("prd_document")),
        "ticket_count": len(session.state.get("tickets", [])),
    }

    # Collect all outputs from state
    outputs.research_results = session.state.get("research_results") or {}
    outputs.prd_document = session.state.get("prd_document") or {}
    outputs.tickets = session.state.get("tickets") or []
    outputs.tool_call_log = session.state.get("tool_call_log") or []
    outputs.cache_stats = session.state.get("cache_stats") or {}
    outputs.messages = session.state.get("messages") or []
    outputs.recalled_memories = session.state.get("recalled_memories") or []
    outputs.decision_log = session.decision_log.get_all()
    outputs.duration_seconds = round(time.monotonic() - t0, 2)

    return outputs


def _run_single_case(case: EvalCase, run_id: str) -> RunOutputs:
    """Run one case with a timeout, returning partial outputs on timeout."""
    outputs_ref: list[RunOutputs] = []
    error_ref: list[str] = []

    def _worker():
        try:
            result = _run_single_case_inner(case, run_id)
            outputs_ref.append(result)
        except Exception as exc:
            error_ref.append(str(exc))
            # Return partial state if session was partially constructed
            outputs_ref.append(RunOutputs(case_id=case.id, run_id=run_id, error=str(exc)))

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_worker)
        try:
            future.result(timeout=CASE_TIMEOUT)
        except FuturesTimeout:
            outputs = outputs_ref[0] if outputs_ref else RunOutputs(case_id=case.id, run_id=run_id)
            outputs.error = f"Timeout after {CASE_TIMEOUT}s"
            outputs.duration_seconds = CASE_TIMEOUT
            return outputs

    if error_ref and not outputs_ref:
        return RunOutputs(case_id=case.id, run_id=run_id, error=error_ref[0])

    outputs = outputs_ref[0]
    if error_ref:
        outputs.error = error_ref[0]
    return outputs


# ── Artifact saving ───────────────────────────────────────────────────────


def _save_artifacts(outputs: RunOutputs, score: ScoreResult) -> Path:
    """Write all artifacts for one case-run."""
    artifact_dir = ARTIFACTS_DIR / outputs.run_id / outputs.case_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    def _dump(name: str, data: Any) -> None:
        with (artifact_dir / name).open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    _dump("research.json", outputs.research_results)
    _dump("prd.json", outputs.prd_document)
    _dump("tickets.json", outputs.tickets)
    _dump("tool_call_log.json", outputs.tool_call_log)
    _dump("messages.json", outputs.messages)
    _dump("phase_snapshots.json", outputs.phase_snapshots)
    _dump("decision_log.json", outputs.decision_log)
    _dump("score.json", score.as_dict())

    return artifact_dir


# ── Results persistence ───────────────────────────────────────────────────


def _append_result(record: dict) -> None:
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _make_record(
    run_id: str,
    case: EvalCase,
    outputs: RunOutputs,
    score: ScoreResult,
    artifact_dir: Path,
    tag: str,
    model: str,
    provider: str,
) -> dict:
    return {
        "run_id": run_id,
        "case_id": case.id,
        "case_name": case.name,
        "split": case.split,
        "tag": tag,
        "model": model,
        "provider": provider,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": outputs.duration_seconds,
        "overall_score": score.overall,
        "scores": {
            "fact_coverage": score.fact_coverage,
            "forbidden_miss_rate": score.forbidden_miss_rate,
            "prd_assertion_pass_rate": score.prd_assertion_pass_rate,
            "memory_assertion_pass_rate": score.memory_assertion_pass_rate,
        },
        "error": outputs.error,
        "artifact_dir": str(artifact_dir),
    }


# ── Per-case execution + printing ─────────────────────────────────────────


def _execute_case(
    case: EvalCase,
    run_id: str,
    tag: str,
    model: str,
    provider: str,
) -> tuple[RunOutputs, ScoreResult]:
    print(f"  {_DIM}[{case.id}]{_RESET} {case.name} ", end="", flush=True)

    outputs = _run_single_case(case, run_id)

    score = score_case(case, outputs)
    artifact_dir = _save_artifacts(outputs, score)
    record = _make_record(run_id, case, outputs, score, artifact_dir, tag, model, provider)
    _append_result(record)

    status = _GREEN + "PASS" + _RESET if score.overall >= 0.7 else _RED + "FAIL" + _RESET
    err_note = f" {_RED}[{outputs.error[:40]}]{_RESET}" if outputs.error else ""
    print(f"→ {status} {score.overall:.2f}{err_note}")

    return outputs, score


# ── Run split / single case ───────────────────────────────────────────────


def run_split(split: str, tag: str, model: str, provider: str) -> None:
    from eval.case import load_cases_for_split

    cases = load_cases_for_split(split)
    if not cases:
        print(f"No cases found for split '{split}'")
        return

    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    print(f"\n{_BOLD}Run ID:{_RESET} {run_id}")
    print(f"{_BOLD}Split: {_RESET}{split} ({len(cases)} cases)  tag={tag}  model={model}\n")

    scores: list[float] = []
    for case in cases:
        _, score = _execute_case(case, run_id, tag, model, provider)
        scores.append(score.overall)

    avg = sum(scores) / len(scores) if scores else 0.0
    print(f"\n{_BOLD}Overall: {avg:.3f}{_RESET}  ({len(scores)} cases)  run_id={run_id}")
    print(f"Artifacts: {ARTIFACTS_DIR / run_id}")
    print(f"Results:   {RESULTS_FILE}")


def run_case(case_id: str, tag: str, model: str, provider: str) -> None:
    case = load_case_by_id(case_id)
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    print(f"\n{_BOLD}Run ID:{_RESET} {run_id}")
    print(f"{_BOLD}Case:{_RESET} {case.id} — {case.name}\n")

    outputs, score = _execute_case(case, run_id, tag, model, provider)

    # Detailed score breakdown
    print(f"\n{_BOLD}Score Breakdown:{_RESET}")
    print(f"  fact_coverage:              {score.fact_coverage:.3f}")
    print(f"  forbidden_miss_rate:        {score.forbidden_miss_rate:.3f}")
    print(f"  prd_assertion_pass_rate:    {score.prd_assertion_pass_rate:.3f}")
    print(f"  memory_assertion_pass_rate: {score.memory_assertion_pass_rate:.3f}")
    print(f"  {_BOLD}overall: {score.overall:.3f}{_RESET}")

    # Failed assertions
    failed_prd = [d for d in score.details.get("prd", []) if not d.get("passed")]
    failed_mem = [d for d in score.details.get("memory", []) if not d.get("passed")]
    missed_facts = [d for d in score.details.get("facts", []) if not d.get("found")]

    if missed_facts:
        print(f"\n{_YELLOW}Missed facts:{_RESET}")
        for d in missed_facts:
            print(f"  - {d['fact']}")
    if failed_prd:
        print(f"\n{_YELLOW}Failed PRD assertions:{_RESET}")
        for d in failed_prd:
            print(f"  - {d.get('assertion', {}).get('type')} → {d.get('reason')}")
    if failed_mem:
        print(f"\n{_YELLOW}Failed memory assertions:{_RESET}")
        for d in failed_mem:
            print(f"  - {d.get('assertion', {}).get('type')} → {d.get('reason')}")

    print(f"\nArtifacts: {ARTIFACTS_DIR / run_id / case_id}")


# ── CLI ───────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Eval runner for the PM interview agent")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--split", help="Run all cases in this split (dev/test/train)")
    group.add_argument("--case", metavar="CASE_ID", help="Run a single case by id")
    parser.add_argument("--tag", default="untagged", help="Label for this run (e.g. v2-prompt)")
    parser.add_argument("--model", default=None, help="Override STRONG_MODEL")
    parser.add_argument("--provider", default=None, help="Override LLM_PROVIDER")

    args = parser.parse_args()

    # Set env vars BEFORE importing InterviewSession (lru_cache workaround)
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["STRONG_MODEL"] = args.model

    # Resolve model/provider for record-keeping
    model = os.environ.get("STRONG_MODEL", "claude-sonnet-4-6")
    provider = os.environ.get("LLM_PROVIDER", "anthropic")

    if args.split:
        run_split(args.split, args.tag, model, provider)
    else:
        run_case(args.case, args.tag, model, provider)


if __name__ == "__main__":
    main()
