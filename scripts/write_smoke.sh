#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Iter 027: adapt HTTP(S)_PROXY for the aetherheartpool tunnel.
# shellcheck source=with_proxy.sh
source "$ROOT/scripts/with_proxy.sh"

# iter 017: accept --book / $WORKSPACE_NAME so smoke can target a per-book workspace.
BOOK="${WORKSPACE_NAME:-${BOOK:-}}"
while [ $# -gt 0 ]; do
  case "$1" in
    --book) BOOK="$2"; shift 2;;
    --book=*) BOOK="${1#--book=}"; shift;;
    *) shift;;
  esac
done
[ -n "$BOOK" ] && export WORKSPACE_NAME="$BOOK"
BOOK_ARG=""
[ -n "$BOOK" ] && BOOK_ARG="--book $BOOK"

PATH_QUERY='import sys; from src import paths; sys.stdout.write(str(getattr(paths, sys.argv[1])()))'
DEBATE_DIR="$(python3 -c "$PATH_QUERY" debate_dir)"
DRAFTS_DIR="$(python3 -c "$PATH_QUERY" drafts_dir)"
REVIEWS_DIR="$(python3 -c "$PATH_QUERY" reviews_dir)"
LOGS_DIR="$(python3 -c "$PATH_QUERY" logs_dir)"

mkdir -p "$LOGS_DIR"
ts="$(date +%Y%m%d_%H%M%S)"
log_path="$LOGS_DIR/write_smoke_${ts}.log"

export PYTHONPYCACHEPREFIX="$ROOT/.pycache"

{
  python3 main.py $BOOK_ARG preflight
  python3 main.py $BOOK_ARG compress
  python3 main.py $BOOK_ARG debate
  python3 main.py $BOOK_ARG write --chapters 1 --force
  python3 main.py $BOOK_ARG review
  python3 main.py $BOOK_ARG status
  python3 main.py $BOOK_ARG estimate-cost
  python3 main.py $BOOK_ARG preflight
  snap="$DRAFTS_DIR/snapshots/${ts}"
  mkdir -p "$snap"
  cp "$DRAFTS_DIR/chapter_01.md" "$snap/" 2>/dev/null || true
  cp "$DRAFTS_DIR/chapter_01.meta.json" "$snap/" 2>/dev/null || true
  cp -r "$REVIEWS_DIR" "$snap/" 2>/dev/null || true
  cp "$DEBATE_DIR/decisions.json" "$snap/debate_decisions.json" 2>/dev/null || true
  cp "$DEBATE_DIR/outline.md" "$snap/debate_outline.md" 2>/dev/null || true
  echo "Snapshot saved: $snap"
  echo "Write smoke log written: $log_path"
} 2>&1 | tee "$log_path"
