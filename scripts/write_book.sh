#!/usr/bin/env bash
# Iter 029: production writing is owned by `python3 main.py write-book`.
# This script remains only as a compatibility wrapper for users and old
# smoke commands that prefer `bash scripts/write_book.sh`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=with_proxy.sh
source "$ROOT/scripts/with_proxy.sh"

CHAPTERS="2"
RESUME_FROM="1"
BOOK="${WORKSPACE_NAME:-${BOOK:-}}"
MAX_RETRIES="2"
MIN_CONFIDENCE="0.7"
REPLAN_EVERY="0"
BUDGET_CNY="0"
AUTO_ADVANCE="1"
REQUIRE_PLAN="1"
REQUIRE_START_POINT="1"
REQUIRE_EXTERNAL_REVIEW="1"
FORCE="0"
START_POINT=""

need_value() {
  if [ $# -lt 2 ] || [ -z "$2" ]; then
    echo "$1 requires a value" >&2
    exit 64
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --book)
      need_value "$1" "${2-}"
      BOOK="$2"
      shift 2
      ;;
    --book=*)
      BOOK="${1#--book=}"
      shift
      ;;
    --chapters)
      need_value "$1" "${2-}"
      CHAPTERS="$2"
      shift 2
      ;;
    --chapters=*)
      CHAPTERS="${1#--chapters=}"
      shift
      ;;
    --resume-from)
      need_value "$1" "${2-}"
      RESUME_FROM="$2"
      shift 2
      ;;
    --resume-from=*)
      RESUME_FROM="${1#--resume-from=}"
      shift
      ;;
    --force)
      FORCE="1"
      shift
      ;;
    --max-retries)
      need_value "$1" "${2-}"
      MAX_RETRIES="$2"
      shift 2
      ;;
    --max-retries=*)
      MAX_RETRIES="${1#--max-retries=}"
      shift
      ;;
    --min-confidence)
      need_value "$1" "${2-}"
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
      need_value "$1" "${2-}"
      REPLAN_EVERY="$2"
      shift 2
      ;;
    --replan-every=*)
      REPLAN_EVERY="${1#--replan-every=}"
      shift
      ;;
    --budget-cny)
      need_value "$1" "${2-}"
      BUDGET_CNY="$2"
      shift 2
      ;;
    --budget-cny=*)
      BUDGET_CNY="${1#--budget-cny=}"
      shift
      ;;
    --no-plan|--allow-missing-plan)
      REQUIRE_PLAN="0"
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
    --skip-external-review)
      REQUIRE_EXTERNAL_REVIEW="0"
      shift
      ;;
    --start-point)
      need_value "$1" "${2-}"
      START_POINT="$2"
      shift 2
      ;;
    --start-point=*)
      START_POINT="${1#--start-point=}"
      shift
      ;;
    [0-9]*)
      CHAPTERS="$1"
      shift
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 64
      ;;
  esac
done

if [ -n "$START_POINT" ]; then
  start_cmd=(python3 main.py)
  if [ -n "$BOOK" ]; then
    start_cmd+=(--book "$BOOK")
  fi
  start_cmd+=(set-start-point "$START_POINT")
  "${start_cmd[@]}"
fi

cmd=(python3 main.py)
if [ -n "$BOOK" ]; then
  cmd+=(--book "$BOOK")
fi
cmd+=(write-book --chapters "$CHAPTERS" --resume-from "$RESUME_FROM")
cmd+=(--max-retries "$MAX_RETRIES" --min-confidence "$MIN_CONFIDENCE")
cmd+=(--replan-every "$REPLAN_EVERY" --budget-cny "$BUDGET_CNY")

if [ "$FORCE" = "1" ]; then
  cmd+=(--force)
fi
if [ "$AUTO_ADVANCE" = "0" ]; then
  cmd+=(--no-auto-advance)
fi
if [ "$REQUIRE_PLAN" = "0" ]; then
  cmd+=(--allow-missing-plan)
fi
if [ "$REQUIRE_START_POINT" = "0" ]; then
  cmd+=(--allow-missing-start-point)
fi
if [ "$REQUIRE_EXTERNAL_REVIEW" = "0" ]; then
  cmd+=(--skip-external-review)
fi

exec "${cmd[@]}"
