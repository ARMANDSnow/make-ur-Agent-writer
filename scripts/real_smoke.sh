#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# iter 017: accept --book / $WORKSPACE_NAME so smoke can target a per-book workspace.
BOOK="${WORKSPACE_NAME:-${BOOK:-}}"
VOLUME="longzu_1"
LIMIT="2"
while [ $# -gt 0 ]; do
  case "$1" in
    --book) BOOK="$2"; shift 2;;
    --book=*) BOOK="${1#--book=}"; shift;;
    --volume) VOLUME="$2"; shift 2;;
    --limit) LIMIT="$2"; shift 2;;
    *) shift;;
  esac
done
[ -n "$BOOK" ] && export WORKSPACE_NAME="$BOOK"
BOOK_ARG=""
[ -n "$BOOK" ] && BOOK_ARG="--book $BOOK"

PATH_QUERY='import sys; from src import paths; sys.stdout.write(str(getattr(paths, sys.argv[1])()))'
LOGS_DIR="$(python3 -c "$PATH_QUERY" logs_dir)"

mkdir -p "$LOGS_DIR"
ts="$(date +%Y%m%d_%H%M%S)"
log_path="$LOGS_DIR/real_smoke_${ts}.log"

export PYTHONPYCACHEPREFIX="$ROOT/.pycache"

{
  python3 main.py $BOOK_ARG preflight
  python3 main.py $BOOK_ARG extract --volume "$VOLUME" --limit "$LIMIT" --force
  python3 main.py $BOOK_ARG status
  python3 main.py $BOOK_ARG estimate-cost
  python3 main.py $BOOK_ARG preflight
  echo "Real smoke log written: $log_path"
} 2>&1 | tee "$log_path"
