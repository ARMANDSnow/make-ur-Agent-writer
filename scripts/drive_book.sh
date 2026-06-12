#!/usr/bin/env bash
set -euo pipefail

# iter 052: thin wrapper around `main.py drive-book` (src/book_driver.py).
# The driver itself refuses non-mock models without --confirm-real-run;
# this wrapper adds the same CONFIRM_REAL_MODEL_SMOKE=可以跑了 gate the
# other real-model scripts use, and maps it onto --confirm-real-run so
# both conventions stay in sync.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=with_proxy.sh
source "$ROOT/scripts/with_proxy.sh"

# iter 017: accept --book / $WORKSPACE_NAME so the driver targets a per-book workspace.
BOOK="${WORKSPACE_NAME:-${BOOK:-}}"
CONFIRM_REAL_MODEL_SMOKE="${CONFIRM_REAL_MODEL_SMOKE:-}"
ACTION=""
PASS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --confirm-real-smoke) CONFIRM_REAL_MODEL_SMOKE="可以跑了"; shift;;
    --book) BOOK="$2"; shift 2;;
    --book=*) BOOK="${1#--book=}"; shift;;
    start|resume|status|stop|report)
      ACTION="$1"; PASS+=("$1"); shift;;
    *) PASS+=("$1"); shift;;
  esac
done
[ -n "$BOOK" ] && export WORKSPACE_NAME="$BOOK"
BOOK_ARG=""
[ -n "$BOOK" ] && BOOK_ARG="--book $BOOK"

# Real-model gate: only start/resume can spend money; status/stop/report are free.
MODEL="${OPENAI_MODEL:-}"
if [ "$ACTION" = "start" ] || [ "$ACTION" = "resume" ]; then
  if [ "$MODEL" != "mock" ]; then
    if [ "$CONFIRM_REAL_MODEL_SMOKE" != "可以跑了" ]; then
      echo "Refusing to drive a real model without CONFIRM_REAL_MODEL_SMOKE=可以跑了 or --confirm-real-smoke" >&2
      exit 64
    fi
    PASS+=("--confirm-real-run")
  fi
fi

export PYTHONPYCACHEPREFIX="$ROOT/.pycache"

exec python3 main.py $BOOK_ARG drive-book ${PASS[@]+"${PASS[@]}"}
