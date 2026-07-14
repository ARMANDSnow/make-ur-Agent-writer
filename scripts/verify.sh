#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/verify.sh

Runs the single canonical mock/offline acceptance in an isolated synthetic
workspace. Named/private workspaces are intentionally unsupported.
EOF
}

if [[ $# -gt 0 ]]; then
  if [[ $# -eq 1 && "$1" == "--help" ]]; then
    usage
    exit 0
  fi
  echo "[FATAL] verify.sh accepts no workspace or other arguments" >&2
  usage >&2
  exit 64
fi

# verify.sh is the single canonical mock/offline acceptance entry. Pin every
# provider surface before any Python process can load the user's .env.
unset WORKSPACE_NAME BOOK
export OPENAI_MODEL=mock
export DRAMA_MODEL=mock
export PLANNER_MODEL=mock
export SD_VIDEO_MODE=mock
export LITELLM_LOCAL_MODEL_COST_MAP=true
export DRAGON_RAJA_SKIP_DOTENV=1
export PYTHON_DOTENV_DISABLED=1
unset OPENAI_API_KEY OPENAI_BASE_URL OPENAI_STREAM
unset PLANNER_API_KEY PLANNER_BASE_URL
unset AI_DRAW_ENDPOINT AI_DRAW_BASE_URL AI_DRAW_MODEL AI_DRAW_API_KEY AI_DRAW_RESULT_HOSTS
unset SD_API_BASE_URL SD_API_KEY SD_VIDEO_MODEL SD_ASSET_PUBLIC_BASE_URL
unset SD_VIDEO_RESULT_HOSTS SD_VIDEO_ESTIMATED_COST_CNY
unset CONFIRM_REAL_MODEL_SMOKE CONFIRM_REAL_VIDEO_SMOKE
unset DISABLE_PROMPT_CACHE WRITE_MAX_TOKENS WRITE_PROMPT_PROFILE

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="$ROOT/.venv/bin/python3"
EVIDENCE_PYTHON="$PYTHON_BIN"
PYTHON_RUNTIME="project_venv"
if [[ ! -x "$EVIDENCE_PYTHON" ]]; then
  EVIDENCE_PYTHON="$(command -v python3 || true)"
  PYTHON_RUNTIME="missing_project_venv"
fi
if [[ -z "$EVIDENCE_PYTHON" ]]; then
  echo "[FATAL] no Python interpreter is available to initialize acceptance evidence" >&2
  exit 2
fi

# Iter 096: verify is physically offline, not merely free of billable model
# calls.  Do not source with_proxy.sh here: its localhost probe is itself a
# network attempt and is only relevant to separately-authorized real runs.

export PYTHONPYCACHEPREFIX="$ROOT/.pycache"
umask 077

START_EPOCH="$(date +%s)"
CURRENT_STEP="initialization"
TEST_COUNT=0
COMPLETED_STEPS=""
RUN_DIR=""
COUNT_FILE=""
RUN_ID="$("$EVIDENCE_PYTHON" scripts/write_acceptance.py start --root "$ROOT" --python-runtime "$PYTHON_RUNTIME")"

on_exit() {
  local exit_code="$?"
  local end_epoch duration evidence_status failed_step evidence_ok
  trap - EXIT
  end_epoch="$(date +%s)"
  duration=$((end_epoch - START_EPOCH))
  evidence_status="failed"
  failed_step="$CURRENT_STEP"
  if [[ "$exit_code" -eq 0 ]]; then
    evidence_status="passed"
    failed_step=""
  fi
  evidence_ok=1
  if ! "$EVIDENCE_PYTHON" scripts/write_acceptance.py finish \
    --root "$ROOT" \
    --run-id "$RUN_ID" \
    --status "$evidence_status" \
    --exit-code "$exit_code" \
    --test-count "$TEST_COUNT" \
    --duration-seconds "$duration" \
    --completed-steps "$COMPLETED_STEPS" \
    --failed-step "$failed_step"; then
    evidence_ok=0
    echo "[FATAL] failed to finalize outputs/harness/acceptance.json" >&2
    [[ "$exit_code" -ne 0 ]] || exit_code=1
  fi
  if [[ -n "$COUNT_FILE" ]]; then
    rm -f "$COUNT_FILE"
  fi
  if [[ -n "$RUN_DIR" ]]; then
    if [[ ! -L "$RUN_DIR" && ! -L "$RUN_DIR/.dragon-raja-verify-owned" \
      && -f "$RUN_DIR/.dragon-raja-verify-owned" ]]; then
      rm -rf -- "$RUN_DIR"
    fi
  fi
  if [[ "$evidence_ok" -eq 1 && "$exit_code" -eq 0 ]]; then
    echo "Acceptance evidence: $ROOT/outputs/harness/acceptance.json"
  fi
  exit "$exit_code"
}
trap on_exit EXIT

if [[ ! -x "$PYTHON_BIN" ]]; then
  CURRENT_STEP="project_interpreter"
  echo "[FATAL] missing project interpreter: $PYTHON_BIN" >&2
  echo "Create .venv and install requirements before running acceptance." >&2
  exit 2
fi

RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/dragon-raja-verify.XXXXXX")"
chmod 700 "$RUN_DIR"
touch "$RUN_DIR/.dragon-raja-verify-owned"
chmod 600 "$RUN_DIR/.dragon-raja-verify-owned"
COUNT_FILE="$RUN_DIR/unittest-count"
VERIFY_WORKSPACE_ROOT="$RUN_DIR/workspaces"
VERIFY_BOOK_ROOT="$VERIFY_WORKSPACE_ROOT/verify"
VERIFY_DRAMA_ROOT="$RUN_DIR/drama-e2e"
mkdir -p "$VERIFY_BOOK_ROOT/小说txt"
mkdir -p "$VERIFY_DRAMA_ROOT"
touch "$VERIFY_DRAMA_ROOT/.dragon-raja-local-e2e"
chmod 600 "$VERIFY_DRAMA_ROOT/.dragon-raja-local-e2e"
touch "$VERIFY_WORKSPACE_ROOT/.dragon-raja-verify-owned"
chmod 600 "$VERIFY_WORKSPACE_ROOT/.dragon-raja-verify-owned"
cat > "$VERIFY_BOOK_ROOT/小说txt/verify-placeholder.txt" <<'EOF'
第一章 离线验收占位

<用户填写正文>
EOF

complete_step() {
  if [[ -n "$COMPLETED_STEPS" ]]; then
    COMPLETED_STEPS+=$'\n'
  fi
  COMPLETED_STEPS+="$CURRENT_STEP"
}

pin_empty_runtime_env() {
  # unittest expects credential variables to be absent. After it completes,
  # pin empty values so later CLI processes cannot reload local .env values.
  export OPENAI_API_KEY="" OPENAI_BASE_URL="" OPENAI_STREAM=""
  export PLANNER_API_KEY="" PLANNER_BASE_URL=""
  export AI_DRAW_ENDPOINT="" AI_DRAW_BASE_URL="" AI_DRAW_MODEL="" AI_DRAW_API_KEY="" AI_DRAW_RESULT_HOSTS=""
  export SD_API_BASE_URL="" SD_API_KEY="" SD_VIDEO_MODEL="" SD_ASSET_PUBLIC_BASE_URL=""
  export SD_VIDEO_RESULT_HOSTS="" SD_VIDEO_ESTIMATED_COST_CNY=""
  export CONFIRM_REAL_MODEL_SMOKE="" CONFIRM_REAL_VIDEO_SMOKE=""
  export DISABLE_PROMPT_CACHE="" WRITE_MAX_TOKENS="" WRITE_PROMPT_PROFILE=""
}

run_step() {
  CURRENT_STEP="$1"
  shift
  "$@"
  complete_step
}

run_main_step() {
  local step="$1"
  shift
  run_step "$step" "$PYTHON_BIN" scripts/run_isolated_cli.py \
    --workspace-root "$VERIFY_WORKSPACE_ROOT" "$@"
}
run_step repository_state "$PYTHON_BIN" scripts/write_acceptance.py check-repository --root "$ROOT"
run_step harness_check "$PYTHON_BIN" scripts/check_agent_harness.py
run_step py_compile "$PYTHON_BIN" -m py_compile main.py src/*.py src/web/*.py tests/*.py scripts/run_isolated_cli.py

CURRENT_STEP="unittest"
set +e
"$PYTHON_BIN" -m unittest discover -s tests -v 2>&1 | awk -v count_file="$COUNT_FILE" '
  { print }
  $1 == "Ran" && $2 ~ /^[0-9]+$/ && $3 ~ /^tests?$/ { print $2 > count_file }
'
TEST_STATUS="${PIPESTATUS[0]}"
set -e
if [[ "$TEST_STATUS" -ne 0 ]]; then
  exit "$TEST_STATUS"
fi
if [[ ! -f "$COUNT_FILE" ]]; then
  echo "[FATAL] unittest summary was not produced" >&2
  exit 1
fi
TEST_COUNT="$(sed -n '1p' "$COUNT_FILE")"
if [[ ! "$TEST_COUNT" =~ ^[1-9][0-9]*$ ]]; then
  echo "[FATAL] unittest discovered no tests or produced an invalid count" >&2
  exit 1
fi
complete_step
pin_empty_runtime_env

# Iter 103: this is a mandatory loopback fake-provider component test.  It
# shares the canonical run/git identity, writes separate local-e2e evidence,
# and may never be treated as an optional skip.
run_step local_drama_e2e "$PYTHON_BIN" scripts/run_local_drama_e2e.py \
  --workspace-root "$VERIFY_DRAMA_ROOT" \
  --run-id "$RUN_ID" \
  --evidence-path "$ROOT/outputs/harness/local_drama_e2e.json" \
  --git-head "$(git rev-parse HEAD)" \
  --git-tree "$(git rev-parse 'HEAD^{tree}')"

run_main_step normalize normalize
run_main_step split split
# Iter 026: auto-pipeline replaces run-all here. run-all only ran
# 6 steps (normalize→split→extract→compress→debate→write), skipping
# bootstrap-apply and plan-chapters. auto-pipeline runs all 9 SOP
# steps and is the same function the WebUI wizard's worker invokes,
# keeping CLI / GUI on one orchestration code path.
run_main_step auto_pipeline auto-pipeline --extract-limit 2 --chapters 1 --force
run_main_step status status
run_main_step check_manifest check-manifest
run_main_step manifest_report manifest-report
run_main_step review_summary review-summary
run_main_step check_reports check-reports
run_main_step estimate_cost estimate-cost
run_main_step preflight preflight
