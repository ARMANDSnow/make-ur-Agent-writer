#!/usr/bin/env bash
# Iter 027 P3: watchdog for capstone real-model runs.
#
# Watches the mtime of workspaces/<book>/logs/llm_calls.jsonl as a
# heartbeat. If the file hasn't been written to within --warn-after
# seconds we print a stderr WARN; if it crosses --abort-after we send
# SIGTERM to --pid so write_book.sh can save partial progress before
# dying.
#
# Default behavior: warn-only. Kill is opt-in via --pid so a fat-
# fingered run on a healthy long-running pipeline doesn't murder it.
#
# Usage:
#   bash scripts/watchdog.sh --book longzu [--warn-after 300] [--abort-after 360] [--pid <PID>]
#
# Example (3-terminal capstone setup):
#   # terminal A — kick off the writer
#   bash scripts/write_book.sh --book longzu 30 --replan-every 5 --budget-cny 60 &
#   WRITER=$!
#   # terminal B — watchdog
#   bash scripts/watchdog.sh --book longzu --pid $WRITER
#   # terminal C — dashboard
#   /usr/bin/python3 main.py web --port 8765

set -u

BOOK=""
WARN_AFTER=300
ABORT_AFTER=360
PID=""
INTERVAL=30

while [ $# -gt 0 ]; do
  case "$1" in
    --book) BOOK="$2"; shift 2 ;;
    --book=*) BOOK="${1#--book=}"; shift ;;
    --warn-after) WARN_AFTER="$2"; shift 2 ;;
    --warn-after=*) WARN_AFTER="${1#--warn-after=}"; shift ;;
    --abort-after) ABORT_AFTER="$2"; shift 2 ;;
    --abort-after=*) ABORT_AFTER="${1#--abort-after=}"; shift ;;
    --pid) PID="$2"; shift 2 ;;
    --pid=*) PID="${1#--pid=}"; shift ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --interval=*) INTERVAL="${1#--interval=}"; shift ;;
    -h|--help)
      sed -n '2,25p' "$0"
      exit 0
      ;;
    *)
      echo "[watchdog] unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

if [ -z "$BOOK" ]; then
  echo "[watchdog] --book required" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Iter 027: watchdog itself does not call LLMs, but we source the proxy
# adapter so the stderr "[with_proxy] mode=…" line lands in the same log
# as the writer — makes post-mortem easy when something does go wrong.
# shellcheck source=with_proxy.sh
source "$ROOT/scripts/with_proxy.sh"
LOG_PATH="$ROOT/workspaces/$BOOK/logs/llm_calls.jsonl"

# Portable mtime: stat -f %m on macOS, stat -c %Y on linux.
if stat -f %m "$LOG_PATH" >/dev/null 2>&1; then
  STAT_FMT='stat -f %m'
else
  STAT_FMT='stat -c %Y'
fi

echo "[watchdog] book=$BOOK log=$LOG_PATH" >&2
echo "[watchdog] warn_after=${WARN_AFTER}s abort_after=${ABORT_AFTER}s interval=${INTERVAL}s pid=${PID:-(warn-only)}" >&2

warned=0
while true; do
  if [ ! -f "$LOG_PATH" ]; then
    echo "[watchdog] $(date '+%H:%M:%S') log file missing — pipeline may not have started yet" >&2
    sleep "$INTERVAL"
    continue
  fi

  mtime=$($STAT_FMT "$LOG_PATH" 2>/dev/null || echo 0)
  now=$(date +%s)
  age=$((now - mtime))

  if [ "$age" -ge "$ABORT_AFTER" ]; then
    if [ -n "$PID" ]; then
      if kill -0 "$PID" 2>/dev/null; then
        echo "" >&2
        echo "================================================================" >&2
        echo "[watchdog] ABORT: no LLM call for ${age}s (>= ${ABORT_AFTER}s)" >&2
        echo "[watchdog] sending SIGTERM to PID $PID" >&2
        echo "================================================================" >&2
        kill -TERM "$PID"
        exit 2
      else
        echo "[watchdog] PID $PID already gone; exiting" >&2
        exit 0
      fi
    else
      echo "[watchdog] ABORT threshold hit (${age}s) but --pid not set; would have killed" >&2
      exit 2
    fi
  elif [ "$age" -ge "$WARN_AFTER" ]; then
    if [ "$warned" = "0" ]; then
      echo "" >&2
      echo "[watchdog] $(date '+%H:%M:%S') WARN: no LLM call for ${age}s (>= ${WARN_AFTER}s, < ${ABORT_AFTER}s abort)" >&2
      warned=1
    fi
  else
    if [ "$warned" = "1" ]; then
      echo "[watchdog] $(date '+%H:%M:%S') recovered (mtime fresh, age=${age}s)" >&2
      warned=0
    fi
  fi

  sleep "$INTERVAL"
done
