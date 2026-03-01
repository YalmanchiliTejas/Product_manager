#!/usr/bin/env python3
"""Beacon Interview Agent — CLI with REPL loop.

Usage:
    python -m backend.agents.cli ./interviews/
    python -m backend.agents.cli ./interviews/ --provider openai --model gpt-4o
    python -m backend.agents.cli ./interviews/ --market "B2B SaaS, $50B TAM"

The CLI:
  1. Parses all interview files in the given folder
  2. Starts an interactive REPL session
  3. You ask questions, confirm tasks, review PRDs
  4. Agent runs research → PRD → tickets pipeline

Commands inside the REPL:
  /tasks     — show current task list
  /prd       — show generated PRD
  /tickets   — show generated tickets
  /export    — export PRD + tickets to files
  /phase     — show current agent phase
  /help      — show available commands
  /quit      — exit
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _setup_python_path():
    """Ensure the project root is on sys.path."""
    project_root = Path(__file__).resolve().parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


_setup_python_path()


def _configure_provider(args):
    """Set LLM provider env vars before importing anything else."""
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["STRONG_MODEL"] = args.model
    if args.fast_model:
        os.environ["FAST_MODEL"] = args.fast_model
    if args.api_key:
        # Set the appropriate key based on provider
        provider = (args.provider or os.environ.get("LLM_PROVIDER", "anthropic")).lower()
        key_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "groq": "GROQ_API_KEY",
            "azure_openai": "AZURE_OPENAI_API_KEY",
        }
        env_key = key_map.get(provider)
        if env_key:
            os.environ[env_key] = args.api_key


# ── ANSI colours ─────────────────────────────────────────────────────────

class _C:
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"
    RESET = "\033[0m"


def _print_header():
    print(f"""
{_C.CYAN}{_C.BOLD}╔══════════════════════════════════════════════════════╗
║          Beacon — Interview Agent CLI               ║
║       AI Product Discovery from Interviews          ║
╚══════════════════════════════════════════════════════╝{_C.RESET}
""")


def _print_agent(text: str):
    """Print agent message."""
    print(f"\n{_C.GREEN}{_C.BOLD}Agent:{_C.RESET} {text}")


def _print_system(text: str):
    """Print system message."""
    print(f"{_C.DIM}{text}{_C.RESET}")


def _print_error(text: str):
    print(f"{_C.RED}Error: {text}{_C.RESET}")


def _print_tasks(tasks: list[dict]):
    """Pretty-print the task list."""
    if not tasks:
        print(f"\n{_C.DIM}No tasks yet.{_C.RESET}")
        return

    status_icons = {
        "proposed": f"{_C.YELLOW}○{_C.RESET}",
        "confirmed": f"{_C.CYAN}◉{_C.RESET}",
        "in_progress": f"{_C.MAGENTA}►{_C.RESET}",
        "completed": f"{_C.GREEN}✓{_C.RESET}",
        "rejected": f"{_C.RED}✗{_C.RESET}",
    }

    print(f"\n{_C.BOLD}Task List:{_C.RESET}")
    for i, task in enumerate(tasks, 1):
        icon = status_icons.get(task.get("status", ""), "?")
        agent = f"[{task.get('agent', '?')}]"
        print(f"  {icon} {i}. {task.get('title', '')} {_C.DIM}{agent}{_C.RESET}")


def _export_outputs(session, export_dir: str):
    """Export PRD and tickets to files."""
    out = Path(export_dir)
    out.mkdir(parents=True, exist_ok=True)

    prd = session.get_prd()
    if prd:
        prd_path = out / "prd.md"
        prd_path.write_text(prd.get("full_markdown", ""), encoding="utf-8")
        print(f"  PRD exported to: {prd_path}")

        prd_json_path = out / "prd.json"
        # Remove full_markdown for the JSON export to avoid duplication
        prd_json = {k: v for k, v in prd.items() if k != "full_markdown"}
        prd_json_path.write_text(json.dumps(prd_json, indent=2), encoding="utf-8")
        print(f"  PRD data exported to: {prd_json_path}")

    tickets = session.get_tickets()
    if tickets:
        tickets_path = out / "tickets.json"
        tickets_path.write_text(json.dumps(tickets, indent=2), encoding="utf-8")
        print(f"  Tickets exported to: {tickets_path}")

        # Also export as readable text
        from backend.agents.ticket_agent import render_tickets
        tickets_txt_path = out / "tickets.txt"
        tickets_txt_path.write_text(render_tickets(tickets), encoding="utf-8")
        print(f"  Tickets (text) exported to: {tickets_txt_path}")

    if not prd and not tickets:
        print("  Nothing to export yet. Run the agent first.")


def _run_repl(session):
    """Main REPL loop."""
    from backend.agents.ticket_agent import render_tickets

    phase = session.get_phase()

    print(f"\n{_C.DIM}Type your question, or use /help for commands.{_C.RESET}")
    print(f"{_C.DIM}Current phase: {phase}{_C.RESET}\n")

    while True:
        try:
            user_input = input(f"{_C.BOLD}You:{_C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            _print_system("\nSaving session to memory...")
            try:
                session.end()
            except Exception:
                pass
            print(f"{_C.DIM}Goodbye!{_C.RESET}")
            break

        if not user_input:
            continue

        # ── Slash commands ────────────────────────────────────────────
        if user_input.startswith("/"):
            cmd = user_input.lower().split()[0]

            if cmd in ("/quit", "/exit", "/q"):
                _print_system("Saving session to memory...")
                try:
                    stats = session.end()
                    _print_system(
                        f"Saved: {stats.get('mem0_stored', 0)} mem0 memories, "
                        f"{stats.get('decision_log_items', 0)} decisions logged."
                    )
                except Exception as e:
                    _print_system(f"Memory save skipped: {e}")
                print(f"\n{_C.DIM}Goodbye!{_C.RESET}")
                break

            elif cmd == "/help":
                print(f"""
{_C.BOLD}Commands:{_C.RESET}
  /tasks     — show current task list
  /prd       — show generated PRD (markdown)
  /tickets   — show generated tickets
  /decisions — show decisions/constraints extracted this session
  /export    — export PRD + tickets to ./output/
  /phase     — show current agent phase
  /auto      — ask with auto-confirm (no task confirmation step)
  /save      — persist session to longitudinal memory now
  /help      — this help message
  /quit      — exit (auto-saves to memory)
""")

            elif cmd == "/tasks":
                _print_tasks(session.get_tasks())

            elif cmd == "/prd":
                prd = session.get_prd()
                if prd:
                    print(f"\n{prd.get('full_markdown', 'No PRD content.')}")
                else:
                    print(f"\n{_C.DIM}No PRD generated yet.{_C.RESET}")

            elif cmd == "/tickets":
                tickets = session.get_tickets()
                if tickets:
                    print(render_tickets(tickets))
                else:
                    print(f"\n{_C.DIM}No tickets generated yet.{_C.RESET}")

            elif cmd == "/export":
                parts = user_input.split(maxsplit=1)
                export_dir = parts[1] if len(parts) > 1 else "./output"
                _export_outputs(session, export_dir)

            elif cmd == "/phase":
                print(f"\n{_C.DIM}Phase: {session.get_phase()}{_C.RESET}")

            elif cmd == "/decisions":
                decisions = session.get_decision_log()
                if not decisions:
                    print(f"\n{_C.DIM}No decisions extracted yet.{_C.RESET}")
                else:
                    print(f"\n{_C.BOLD}Decision Log ({len(decisions)} items):{_C.RESET}")
                    type_icons = {
                        "decision": f"{_C.CYAN}D{_C.RESET}",
                        "constraint": f"{_C.RED}C{_C.RESET}",
                        "metric": f"{_C.GREEN}M{_C.RESET}",
                        "persona": f"{_C.MAGENTA}P{_C.RESET}",
                    }
                    for i, item in enumerate(decisions, 1):
                        icon = type_icons.get(item.get("type", ""), "?")
                        conf = item.get("confidence", "?")
                        print(
                            f"  {icon} {i}. {item.get('title', '?')} "
                            f"{_C.DIM}[{conf}]{_C.RESET}"
                        )
                        print(f"     {item.get('content', '')[:120]}")

            elif cmd == "/save":
                _print_system("Saving session to memory...")
                try:
                    stats = session.end()
                    _print_agent(
                        f"Saved: {stats.get('mem0_stored', 0)} mem0 memories, "
                        f"{stats.get('decision_log_items', 0)} decisions logged."
                        + (" Index rebuilt." if stats.get("index_rebuilt") else "")
                    )
                except Exception as e:
                    _print_error(str(e))

            elif cmd == "/auto":
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2:
                    print(f"{_C.DIM}Usage: /auto <your question>{_C.RESET}")
                    continue
                question = parts[1]
                _print_system("Running with auto-confirm...")
                try:
                    msgs = session.ask(question, auto_confirm=True)
                    for msg in msgs:
                        _print_agent(msg.get("content", ""))
                except Exception as e:
                    _print_error(str(e))

            else:
                print(f"{_C.DIM}Unknown command: {cmd}. Type /help for options.{_C.RESET}")

            continue

        # ── Regular input — route based on phase ──────────────────────
        phase = session.get_phase()

        if phase == "planning" and session.state.get("tasks_pending_confirmation"):
            # We're waiting for task confirmation
            _print_system("Processing task confirmation...")
            try:
                msgs = session.confirm(user_input)
                for msg in msgs:
                    _print_agent(msg.get("content", ""))
            except Exception as e:
                _print_error(str(e))

        elif phase == "generating":
            # We're waiting for PRD review
            _print_system("Processing PRD review...")
            try:
                msgs = session.review_prd(user_input)
                for msg in msgs:
                    _print_agent(msg.get("content", ""))
            except Exception as e:
                _print_error(str(e))

        else:
            # New question
            _print_system("Analysing question and planning tasks...")
            try:
                msgs = session.ask(user_input)
                for msg in msgs:
                    _print_agent(msg.get("content", ""))

                # Show task list if pending confirmation
                if session.state.get("tasks_pending_confirmation"):
                    _print_tasks(session.get_tasks())
                    print(f"\n{_C.DIM}Confirm tasks? (yes/no/modify){_C.RESET}")

            except Exception as e:
                _print_error(str(e))


def main():
    parser = argparse.ArgumentParser(
        description="Beacon Interview Agent — analyse customer interviews with AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m backend.agents.cli ./interviews/
  python -m backend.agents.cli ./interviews/ --provider openai --model gpt-4o
  python -m backend.agents.cli ./interviews/ --provider ollama --model llama3
  python -m backend.agents.cli ./interviews/ --market "B2B SaaS targeting SMBs"
  python -m backend.agents.cli ./interviews/ --auto "What are the top pain points?"
        """,
    )
    parser.add_argument(
        "folder",
        help="Path to folder containing interview files (.txt, .md, .csv, .pdf, .json)",
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic", "openai", "ollama", "groq", "azure_openai"],
        default=None,
        help="LLM provider (default: from LLM_PROVIDER env var or 'anthropic')",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Strong model name (default: from STRONG_MODEL env var)",
    )
    parser.add_argument(
        "--fast-model",
        default=None,
        help="Fast model name (default: from FAST_MODEL env var)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for the chosen provider",
    )
    parser.add_argument(
        "--market",
        default="",
        help="Market context string (e.g. 'B2B SaaS, $50B TAM')",
    )
    parser.add_argument(
        "--project-id",
        default="",
        help="Existing project UUID (optional, for DB-backed context)",
    )
    parser.add_argument(
        "--auto",
        metavar="QUESTION",
        default=None,
        help="Run a single question with auto-confirm and exit (non-interactive)",
    )

    args = parser.parse_args()

    # Configure provider before any imports
    _configure_provider(args)

    from backend.agents.doc_parser import parse_interview_folder, summarize_parsed_interviews
    from backend.agents.orchestrator import InterviewSession

    _print_header()

    # Parse interviews
    folder = args.folder
    _print_system(f"Parsing interviews from: {folder}")

    try:
        interviews = parse_interview_folder(folder)
    except (FileNotFoundError, ValueError) as e:
        _print_error(str(e))
        sys.exit(1)

    print(summarize_parsed_interviews(interviews))

    provider = os.environ.get("LLM_PROVIDER", "anthropic")
    model = os.environ.get("STRONG_MODEL", "default")
    _print_system(f"LLM provider: {provider} | model: {model}")

    # Create session
    session = InterviewSession(
        interview_data=interviews,
        market_context=args.market,
        project_id=args.project_id,
    )

    # Run intake
    msgs = session.start()
    for msg in msgs:
        _print_agent(msg.get("content", ""))

    # Non-interactive mode
    if args.auto:
        _print_system(f"Auto mode: {args.auto}")
        try:
            msgs = session.ask(args.auto, auto_confirm=True)
            for msg in msgs:
                _print_agent(msg.get("content", ""))

            # Export results
            _export_outputs(session, "./output")
        except Exception as e:
            _print_error(str(e))
            sys.exit(1)
        return

    # Interactive REPL
    _run_repl(session)


if __name__ == "__main__":
    main()
