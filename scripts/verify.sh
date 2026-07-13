#!/usr/bin/env bash
set -euo pipefail

# verify.sh is mock-only sanity. Drop real-model env so it never burns tokens.
export OPENAI_MODEL=mock
export LITELLM_LOCAL_MODEL_COST_MAP=true
unset OPENAI_API_KEY OPENAI_BASE_URL OPENAI_STREAM
unset PLANNER_API_KEY PLANNER_BASE_URL PLANNER_MODEL
unset DISABLE_PROMPT_CACHE WRITE_MAX_TOKENS WRITE_PROMPT_PROFILE

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Keep the standard gate on the same dependency set as the project test
# command.  Falling back preserves bootstrap usability before the venv exists.
PYTHON_BIN="$ROOT/.venv/bin/python3"
[[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="python3"

# Iter 096: verify is physically offline, not merely free of billable model
# calls.  Do not source with_proxy.sh here: its localhost probe is itself a
# network attempt and is only relevant to separately-authorized real runs.

export PYTHONPYCACHEPREFIX="$ROOT/.pycache"

# iter 017: accept --book / $WORKSPACE_NAME so verify can target a per-book
# workspace. Default (no flag, no env) is legacy mode = repo-root paths.
BOOK="${WORKSPACE_NAME:-${BOOK:-}}"
while [ $# -gt 0 ]; do
  case "$1" in
    --book) BOOK="$2"; shift 2;;
    --book=*) BOOK="${1#--book=}"; shift;;
    *) shift;;
  esac
done
if [ -n "$BOOK" ]; then
  export WORKSPACE_NAME="$BOOK"
fi
BOOK_ARG=""
if [ -n "$BOOK" ]; then
  BOOK_ARG="--book $BOOK"
fi

"$PYTHON_BIN" -m py_compile main.py src/*.py src/web/*.py tests/*.py
"$PYTHON_BIN" -m unittest discover -s tests -v
"$PYTHON_BIN" main.py $BOOK_ARG normalize
"$PYTHON_BIN" main.py $BOOK_ARG split
# Iter 026: auto-pipeline replaces run-all here. run-all only ran
# 6 steps (normalize→split→extract→compress→debate→write), skipping
# bootstrap-apply and plan-chapters. auto-pipeline runs all 9 SOP
# steps and is the same function the WebUI wizard's worker invokes,
# keeping CLI / GUI on one orchestration code path.
"$PYTHON_BIN" main.py $BOOK_ARG auto-pipeline --extract-limit 2 --chapters 1 --force
"$PYTHON_BIN" main.py $BOOK_ARG status
"$PYTHON_BIN" main.py $BOOK_ARG check-manifest
"$PYTHON_BIN" main.py $BOOK_ARG manifest-report
"$PYTHON_BIN" main.py $BOOK_ARG review-summary
"$PYTHON_BIN" main.py $BOOK_ARG check-reports
"$PYTHON_BIN" main.py $BOOK_ARG estimate-cost
