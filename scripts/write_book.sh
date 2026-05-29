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
# Iter 024 P2c/P3c/P4b flags
REPLAN_EVERY="0"   # 0 = disabled (default backward-compat with iter 023)
BUDGET_CNY="0"     # 0 = no ceiling (default)
REQUIRE_START_POINT="1"
START_POINT=""
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
    --replan-every)
      REPLAN_EVERY="$2"
      shift 2
      ;;
    --replan-every=*)
      REPLAN_EVERY="${1#--replan-every=}"
      shift
      ;;
    --budget-cny)
      BUDGET_CNY="$2"
      shift 2
      ;;
    --budget-cny=*)
      BUDGET_CNY="${1#--budget-cny=}"
      shift
      ;;
    --start-point)
      START_POINT="$2"
      shift 2
      ;;
    --start-point=*)
      START_POINT="${1#--start-point=}"
      shift
      ;;
    --require-start-point)
      REQUIRE_START_POINT="1"
      shift
      ;;
    --allow-missing-start-point)
      REQUIRE_START_POINT="0"
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

if [ -n "$START_POINT" ]; then
  if [ -n "$BOOK" ]; then
    python3 main.py --book "$BOOK" set-start-point "$START_POINT"
  else
    python3 main.py set-start-point "$START_POINT"
  fi
fi

# Resolve per-workspace output paths via paths.py (legacy mode returns repo
# root). All file system operations below go through these vars.
PATH_QUERY='import sys; from src import paths; sys.stdout.write(str(getattr(paths, sys.argv[1])()))'
DEBATE_DIR="$(python3 -c "$PATH_QUERY" debate_dir)"
DRAFTS_DIR="$(python3 -c "$PATH_QUERY" drafts_dir)"
REVIEWS_DIR="$(python3 -c "$PATH_QUERY" reviews_dir)"
LOGS_DIR="$(python3 -c "$PATH_QUERY" logs_dir)"
CHAPTER_PLAN="$DEBATE_DIR/chapter_plan.json"

START_CHAPTER_ID="$(python3 -c 'from src import start_point; print(start_point.get_start_chapter_id() or "")')"
if [ "$REQUIRE_START_POINT" = "1" ] && [ -z "$START_CHAPTER_ID" ]; then
  echo "ERROR: no start point set for write_book.sh."
  echo "Set one explicitly before long generation:"
  echo "  python3 main.py ${BOOK:+--book $BOOK }set-start-point <chapter_id_or_volume_id>"
  echo "or pass it in this run:"
  echo "  bash scripts/write_book.sh ${BOOK:+--book $BOOK }$CHAPTERS --start-point <chapter_id_or_volume_id>"
  echo "For intentional from-beginning tests only, use: --allow-missing-start-point"
  exit 1
fi

if [ "$REQUIRE_PLAN" = "1" ] && [ ! -f "$CHAPTER_PLAN" ]; then
  echo "ERROR: chapter_plan.json not found at: $CHAPTER_PLAN"
  echo "Run: python3 main.py ${BOOK:+--book $BOOK }plan-chapters --chapters $CHAPTERS --require-start-point"
  echo "Or bypass intentionally with: bash scripts/write_book.sh ${BOOK:+--book $BOOK }$CHAPTERS --no-plan"
  exit 1
fi

if [ "$REQUIRE_PLAN" = "1" ] && [ "$REQUIRE_START_POINT" = "1" ]; then
  PLAN_START_CHAPTER_ID="$(python3 -c "
from src.utils import read_json
from pathlib import Path
data = read_json(Path('$CHAPTER_PLAN'), {})
print(data.get('start_chapter_id') or '')
" 2>/dev/null || true)"
  if [ -z "$PLAN_START_CHAPTER_ID" ]; then
    echo "ERROR: chapter_plan.json has no start_chapter_id metadata."
    echo "This plan may have been generated from the wrong beginning anchor."
    echo "Re-run: python3 main.py ${BOOK:+--book $BOOK }plan-chapters --chapters $CHAPTERS --force --require-start-point"
    exit 1
  fi
  if [ "$PLAN_START_CHAPTER_ID" != "$START_CHAPTER_ID" ]; then
    echo "ERROR: chapter_plan.json start point mismatch."
    echo "Current start point: $START_CHAPTER_ID"
    echo "Plan start point:    $PLAN_START_CHAPTER_ID"
    echo "Re-run plan-chapters with --force after setting the desired start point."
    exit 1
  fi
fi

mkdir -p "$LOGS_DIR" "$DRAFTS_DIR/snapshots"
ts="$(date +%Y%m%d_%H%M%S)"
log_path="$LOGS_DIR/write_book_${ts}.log"

export PYTHONPYCACHEPREFIX="$ROOT/.pycache"

# Iter 024 P3c: record llm_calls.jsonl line count at run start for per-chapter
# and cumulative budget computation. Tracks delta since this invocation began
# (independent of all prior runs' history).
INITIAL_LLM_LINES="$(wc -l < "$LOGS_DIR/llm_calls.jsonl" 2>/dev/null || echo 0)"
INITIAL_LLM_LINES="${INITIAL_LLM_LINES//[[:space:]]/}"

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
  local attempt="${2:-0}"
  local prefix
  prefix=$(printf "%s/chapter_%02d" "$DRAFTS_DIR" "$i")
  # Iter 019: drop the .md, .meta.json, and .failure.json so the writer
  # produces a clean re-run without inheriting stale lint / verdict state.
  # Keep entity_advance_proposals.json so apply-advance can be re-run if
  # needed; the writer overwrites it on the next attempt anyway.
  #
  # Debug fix (post iter 019): instead of `rm -f`, MOVE the files to
  # `chapter_NN.last_failure_attemptN.{ext}`. Pre-fix, after 3 retries all
  # rejected, the meta.json was deleted before the user could see WHICH
  # reviewer agent flagged the chapter or with what issue. Now diagnostics
  # are preserved for post-mortem. Successful chapters keep the rm
  # behavior implicitly: clean filenames only exist for the current
  # successful draft, while last_failure_* records the rejected attempts.
  local suffix="last_failure_attempt${attempt}"
  for ext in md meta.json failure.json; do
    if [ -f "${prefix}.${ext}" ]; then
      mv -f "${prefix}.${ext}" "${prefix}.${suffix}.${ext}"
    fi
  done
  # Iter 027 capstone hardening: rejected drafts can already have appended a
  # rolling summary before the outer retry loop runs. Rewind the rolling
  # context at the same chapter boundary so the retry is not prompted with
  # its own failed attempt, and later chapters do not inherit rejected state.
  # Iter 027 bug-sweep F2: prune failure must abort the retry. Silently
  # warning and continuing leaves the failed draft's rolling summary in
  # place, so the retry inherits the polluted context — exactly the
  # regression prune_from_chapter was added to prevent.
  if ! python3 -c "from src.chapter_summary import prune_from_chapter; prune_from_chapter($i)"; then
    echo "ERROR: failed to prune rolling summary for retry of chapter $i" >&2
    echo "Aborting to avoid polluting the next retry with the failed draft's context." >&2
    exit 1
  fi
}

# Iter 019 audit fix: snapshot helper called by BOTH the success and the
# retry-exhausted exit paths. Pre-fix the snapshot block lived after the
# main loop, so an `exit 2` for retry exhaustion skipped it and the user
# lost diagnostics for the partial run.
take_snapshot() {
  local suffix="${1:-}"
  local snap="$DRAFTS_DIR/snapshots/${ts}${suffix}"
  mkdir -p "$snap"
  cp "$DRAFTS_DIR"/chapter_*.md "$snap/" 2>/dev/null || true
  cp "$DRAFTS_DIR"/chapter_*.meta.json "$snap/" 2>/dev/null || true
  cp "$DRAFTS_DIR"/chapter_*.failure.json "$snap/" 2>/dev/null || true
  # Debug fix: also snapshot the preserved last_failure_attempt* files so
  # the post-mortem evidence (which reviewer agent rejected, with what
  # issue) is captured even when a chapter eventually succeeded.
  cp "$DRAFTS_DIR"/chapter_*.last_failure_attempt*.* "$snap/" 2>/dev/null || true
  cp "$DRAFTS_DIR"/chapter_*.entity_advance_proposals.json "$snap/" 2>/dev/null || true
  cp "$DRAFTS_DIR/rolling_chapter_summary.json" "$snap/" 2>/dev/null || true
  cp -r "$REVIEWS_DIR" "$snap/" 2>/dev/null || true
  cp "$DEBATE_DIR/decisions.json" "$snap/debate_decisions.json" 2>/dev/null || true
  cp "$DEBATE_DIR/outline.md" "$snap/debate_outline.md" 2>/dev/null || true
  echo "Snapshot saved: $snap"
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
        clear_chapter_state "$i" "$attempted"
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
      # Iter 019 audit fix: snapshot partial progress BEFORE exit 2 so the
      # user keeps diagnostics from the failed run.
      take_snapshot "_aborted_ch$(printf '%02d' "$i")"
      echo "Write book log: $log_path"
      exit 2
    fi

    if [ "$AUTO_ADVANCE" = "1" ]; then
      # Iter 024 P4b: dry-run proposal-vs-plan conflict check BEFORE
      # auto-applying. Hard-conflict proposals (e.g. would set X↔Y as
      # 已死/敌对 but next chapter plan expects active interaction)
      # are SKIPPED — operator can apply manually after review.
      conflict_check=$(python3 -c "
import json
from src import paths, proposal_validator
from src.utils import read_json
drafts = paths.drafts_dir()
proposals = read_json(drafts / 'chapter_$(printf '%02d' "$i").entity_advance_proposals.json', {})
prop_list = proposals.get('proposals', []) if isinstance(proposals, dict) else (proposals if isinstance(proposals, list) else [])
plan = read_json(paths.chapter_plan_path(), {})
graph = read_json(paths.entity_graph_path(), {})
conflicts = proposal_validator.validate_proposals_against_plan(prop_list, $i, plan, graph)
if conflicts:
    print('CONFLICT:' + '; '.join(c['reason'][:120] for c in conflicts[:2]))
else:
    print('SAFE')
" 2>/dev/null || echo "SAFE")
      if [[ "$conflict_check" == CONFLICT:* ]]; then
        echo "=== [BLOCKED] apply-advance for ch$i conflicts with next chapter plan: ${conflict_check#CONFLICT: } ==="
        echo "=== [BLOCKED] Skipping auto-apply; review proposals manually in chapter_$(printf '%02d' "$i").entity_advance_proposals.json ==="
      else
        # Iter 019: auto-apply high-confidence entity-advance proposals between
        # chapters. --allow-empty turns "no proposals matched threshold" into a
        # no-op exit 0 so the loop doesn't break on quiet chapters.
        python3 main.py ${BOOK:+--book $BOOK} apply-advance \
          --chapter "$i" \
          --auto-apply \
          --min-confidence "$MIN_CONFIDENCE" \
          --allow-empty \
          --confirm
      fi
    else
      echo "=== auto-advance disabled (--no-auto-advance); skipping apply-advance for chapter $i ==="
    fi

    # Iter 024 P3c: per-chapter cost report + cumulative budget check.
    # Always print since users want visibility; only enforce ceiling
    # when --budget-cny was passed.
    chapter_cost_info=$(python3 -c "
from src.cost_estimator import estimate_cost_since
delta = estimate_cost_since($INITIAL_LLM_LINES)
print(f\"{delta['cost_cny']:.4f}|{delta['calls']}|{delta['prompt_tokens']}|{delta['response_tokens']}\")
" 2>/dev/null || echo "0.0|0|0|0")
    IFS='|' read -r cum_cost cum_calls cum_prompt cum_resp <<< "$chapter_cost_info"
    echo "[cost] after ch$i: cumulative ¥${cum_cost} | calls=${cum_calls} | prompt_tok=${cum_prompt} | resp_tok=${cum_resp}"
    if [ "$BUDGET_CNY" != "0" ]; then
      over_budget=$(python3 -c "print(1 if float('$cum_cost') > float('$BUDGET_CNY') else 0)")
      if [ "$over_budget" = "1" ]; then
        echo ""
        echo "[BUDGET] cumulative cost ¥${cum_cost} exceeded ceiling ¥${BUDGET_CNY} after ch$i"
        echo "[BUDGET] stopping write_book.sh; partial progress preserved (ch1..ch$i written)"
        take_snapshot "_budget_exit_ch$(printf '%02d' "$i")"
        echo "Write book log: $log_path"
        exit 3
      fi
    fi

    # Iter 024 P2c: every REPLAN_EVERY chapters, trigger plot_planner
    # --append to add K fresh chapters that continue from what's been
    # written. Skip on the very last chapter (no next batch to plan).
    if [ "$REPLAN_EVERY" != "0" ] && [ "$i" -lt "$CHAPTERS" ] && [ "$((i % REPLAN_EVERY))" -eq 0 ]; then
      echo ""
      echo "=== Auto re-plan: appending $REPLAN_EVERY chapters after ch$i ==="
      python3 main.py ${BOOK:+--book $BOOK} plan-chapters \
        --append "$REPLAN_EVERY" --from-chapter "$i" --force \
        || echo "[WARN] auto re-plan failed; continuing with existing plan"
    fi
  done

  # Iter 019 audit fix: success-path snapshot delegated to take_snapshot
  # (no suffix). The retry-exhausted path above takes its own snapshot
  # with `_aborted_chNN` suffix before exit 2.
  take_snapshot ""
  echo "Write book log written: $log_path"
} 2>&1 | tee "$log_path"

# Iter 022 B6: pipefail alone is not enough — `exit 2` from inside the
# braced block + tee on the right side of the pipe still gave exit code
# 0 in iter 020/021 tests (depends on bash version + how `exit` interacts
# with subshell pipe stages). Explicitly capture the left pipe stage exit
# code via PIPESTATUS[0] and re-exit with it. PIPESTATUS is bash-only, but
# the shebang on line 1 already forces /usr/bin/env bash.
exit "${PIPESTATUS[0]}"
