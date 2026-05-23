#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CHAPTERS="2"
REQUIRE_PLAN="1"
BOOK="${WORKSPACE_NAME:-${BOOK:-}}"
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

{
  for i in $(seq 1 "$CHAPTERS"); do
    chapter_path=$(printf "$DRAFTS_DIR/chapter_%02d.md" "$i")
    if [ -f "$chapter_path" ]; then
      echo "Chapter $i already exists, skipping: $chapter_path"
      continue
    fi

    python3 main.py ${BOOK:+--book $BOOK} preflight
    python3 main.py ${BOOK:+--book $BOOK} write --chapters 1 --resume-from "$i" --force
    python3 main.py ${BOOK:+--book $BOOK} review-chapter "$i"
    python3 main.py ${BOOK:+--book $BOOK} status

    if [ "$i" -lt "$CHAPTERS" ]; then
      proposal_path=$(printf "$DRAFTS_DIR/chapter_%02d.entity_advance_proposals.json" "$i")
      echo ""
      echo "=== Chapter $i done. Check $proposal_path ==="
      echo "=== Dry run: python3 main.py ${BOOK:+--book $BOOK }apply-advance --chapter $i --proposal-idx <comma-list> ==="
      echo "=== Apply:   python3 main.py ${BOOK:+--book $BOOK }apply-advance --chapter $i --proposal-idx <comma-list> --confirm ==="
      echo "=== Then re-run: bash scripts/write_book.sh ${BOOK:+--book $BOOK }$CHAPTERS to continue ==="
      echo "Write book log written: $log_path"
      exit 0
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
