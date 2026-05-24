#!/usr/bin/env bash
# Iter 019: fully unattended chapter-writing loop. The pre-iter-019 version
# printed manual "apply-advance" instructions after every chapter and
# exited 0, requiring a human to re-run the script for each batch. iter
# 019 auto-applies high-confidence entity-advance proposals between
# chapters and detects failure markers (failure.json /
# needs_human_review meta) to retry instead of silently skipping.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CHAPTERS="2"
REQUIRE_PLAN="1"
BOOK="${WORKSPACE_NAME:-${BOOK:-}}"
MAX_RETRIES="2"
MIN_CONFIDENCE="0.7"
AUTO_ADVANCE="1"
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --no-plan)
      REQUIRE_PLAN="0"
      shift
      ;;
    --book)
      BOOK="$2"
      shift 2
      ;;
    --book=*)
      BOOK="${1#--book=}"
      shift
      ;;
    --max-retries)
      MAX_RETRIES="$2"
      shift 2
      ;;
    --max-retries=*)
      MAX_RETRIES="${1#--max-retries=}"
      shift
      ;;
    --min-confidence)
      MIN_CONFIDENCE="$2"
      shift 2
      ;;
    --min-confidence=*)
      MIN_CONFIDENCE="${1#--min-confidence=}"
      shift
      ;;
    --no-auto-advance)
      AUTO_ADVANCE="0"
      shift
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done
if [ "${#ARGS[@]}" -gt 0 ]; then
  CHAPTERS="${ARGS[0]}"
fi

# iter 017: when --book is set, export WORKSPACE_NAME so every python
# subcommand picks up the per-book workspace via src/paths.py.
if [ -n "$BOOK" ]; then
  export WORKSPACE_NAME="$BOOK"
fi

# Resolve per-workspace output paths via paths.py (legacy mode returns repo
# root). All file system operations below go through these vars.
PATH_QUERY='import sys; from src import paths; sys.stdout.write(str(getattr(paths, sys.argv[1])()))'
DEBATE_DIR="$(python3 -c "$PATH_QUERY" debate_dir)"
DRAFTS_DIR="$(python3 -c "$PATH_QUERY" drafts_dir)"
REVIEWS_DIR="$(python3 -c "$PATH_QUERY" reviews_dir)"
LOGS_DIR="$(python3 -c "$PATH_QUERY" logs_dir)"
CHAPTER_PLAN="$DEBATE_DIR/chapter_plan.json"

if [ "$REQUIRE_PLAN" = "1" ] && [ ! -f "$CHAPTER_PLAN" ]; then
  echo "ERROR: chapter_plan.json not found at: $CHAPTER_PLAN"
  echo "Run: python3 main.py ${BOOK:+--book $BOOK }plan-chapters --chapters $CHAPTERS"
  echo "Or bypass intentionally with: bash scripts/write_book.sh ${BOOK:+--book $BOOK }$CHAPTERS --no-plan"
  exit 1
fi

mkdir -p "$LOGS_DIR" "$DRAFTS_DIR/snapshots"
ts="$(date +%Y%m%d_%H%M%S)"
log_path="$LOGS_DIR/write_book_${ts}.log"

export PYTHONPYCACHEPREFIX="$ROOT/.pycache"

# Iter 019 helpers ------------------------------------------------------------
# chapter_approved <i> -> 0 if approved, 1 otherwise. Uses the chapter-status
# subcommand so the criteria stay in one Python place (verdict==Approve AND
# no failure.json AND no needs_human_review).
chapter_approved() {
  local i="$1"
  local out
  out="$(python3 main.py ${BOOK:+--book $BOOK} chapter-status "$i" 2>/dev/null || true)"
  python3 -c '
import json, sys
try:
    data = json.loads(sys.argv[1] or "{}")
except Exception:
    sys.exit(1)
sys.exit(0 if data.get("approved") else 1)
' "$out"
}

clear_chapter_state() {
  local i="$1"
  local prefix
  prefix=$(printf "%s/chapter_%02d" "$DRAFTS_DIR" "$i")
  # Iter 019: drop the .md, .meta.json, and .failure.json so the writer
  # produces a clean re-run without inheriting stale lint / verdict state.
  # Keep entity_advance_proposals.json so apply-advance can be re-run if
  # needed; the writer overwrites it on the next attempt anyway.
  rm -f "${prefix}.md" "${prefix}.meta.json" "${prefix}.failure.json"
}

{
  for i in $(seq 1 "$CHAPTERS"); do
    if chapter_approved "$i"; then
      echo "Chapter $i already approved, skipping."
      continue
    fi

    attempted=0
    success=0
    while [ "$attempted" -le "$MAX_RETRIES" ]; do
      if [ "$attempted" -gt 0 ]; then
        echo "=== Retry $attempted/$MAX_RETRIES for chapter $i ==="
        clear_chapter_state "$i"
      fi
      attempted=$((attempted + 1))

      python3 main.py ${BOOK:+--book $BOOK} preflight
      python3 main.py ${BOOK:+--book $BOOK} write --chapters 1 --resume-from "$i" --force
      python3 main.py ${BOOK:+--book $BOOK} review-chapter "$i"
      python3 main.py ${BOOK:+--book $BOOK} status

      if chapter_approved "$i"; then
        success=1
        break
      fi
    done

    if [ "$success" = "0" ]; then
      echo ""
      echo "GAVE UP on chapter $i after $attempted attempts."
      echo "See: $(printf "%s/chapter_%02d.failure.json" "$DRAFTS_DIR" "$i")"
      echo "And: $(printf "%s/chapter_%02d.meta.json" "$DRAFTS_DIR" "$i")"
      echo "Re-run with a higher --max-retries or inspect by hand."
      echo "Write book log: $log_path"
      exit 2
    fi

    if [ "$AUTO_ADVANCE" = "1" ]; then
      # Iter 019: auto-apply high-confidence entity-advance proposals between
      # chapters. --allow-empty turns "no proposals matched threshold" into a
      # no-op exit 0 so the loop doesn't break on quiet chapters.
      python3 main.py ${BOOK:+--book $BOOK} apply-advance \
        --chapter "$i" \
        --auto-apply \
        --min-confidence "$MIN_CONFIDENCE" \
        --allow-empty \
        --confirm
    else
      echo "=== auto-advance disabled (--no-auto-advance); skipping apply-advance for chapter $i ==="
    fi
  done

  snap="$DRAFTS_DIR/snapshots/${ts}"
  mkdir -p "$snap"
  cp "$DRAFTS_DIR"/chapter_*.md "$snap/" 2>/dev/null || true
  cp "$DRAFTS_DIR"/chapter_*.meta.json "$snap/" 2>/dev/null || true
  cp "$DRAFTS_DIR"/chapter_*.entity_advance_proposals.json "$snap/" 2>/dev/null || true
  cp "$DRAFTS_DIR/rolling_chapter_summary.json" "$snap/" 2>/dev/null || true
  cp -r "$REVIEWS_DIR" "$snap/" 2>/dev/null || true
  cp "$DEBATE_DIR/decisions.json" "$snap/debate_decisions.json" 2>/dev/null || true
  cp "$DEBATE_DIR/outline.md" "$snap/debate_outline.md" 2>/dev/null || true
  echo "Snapshot saved: $snap"
  echo "Write book log written: $log_path"
} 2>&1 | tee "$log_path"
