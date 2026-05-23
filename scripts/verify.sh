#!/usr/bin/env bash
set -euo pipefail

# verify.sh is mock-only sanity. Drop real-model env so it never burns tokens.
export OPENAI_MODEL=mock
unset OPENAI_API_KEY OPENAI_BASE_URL

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

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

python3 -m py_compile main.py src/*.py tests/*.py
python3 -m unittest discover -s tests -v
python3 main.py $BOOK_ARG normalize
python3 main.py $BOOK_ARG split
python3 main.py $BOOK_ARG run-all --extract-limit 2 --chapters 1 --force
python3 main.py $BOOK_ARG status
python3 main.py $BOOK_ARG check-manifest
python3 main.py $BOOK_ARG manifest-report
python3 main.py $BOOK_ARG review-summary
python3 main.py $BOOK_ARG check-reports
python3 main.py $BOOK_ARG estimate-cost
