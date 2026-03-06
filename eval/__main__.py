"""Route: python -m eval {runner|compare|corrections} ...

Examples:
    python -m eval runner --split dev
    python -m eval runner --case case_001 --tag v2
    python -m eval compare <run_id_a> <run_id_b>
    python -m eval corrections annotate <run_id> <case_id>
    python -m eval corrections promote <case_id>
"""

import sys


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    sub = sys.argv[1]
    sys.argv = [f"eval.{sub}"] + sys.argv[2:]

    if sub == "runner":
        from eval.runner import main as _main
    elif sub == "compare":
        from eval.compare import main as _main
    elif sub == "corrections":
        from eval.corrections import main as _main
    else:
        print(f"Unknown subcommand: '{sub}'. Choose from: runner, compare, corrections")
        sys.exit(1)

    _main()


main()
