#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <project_id> [run_type]"
  exit 1
fi

PROJECT_ID="$1"
RUN_TYPE="${2:-manual_rebuild}"

python -m backend.graphs.memory_update_graph "$PROJECT_ID" --run-type "$RUN_TYPE"
