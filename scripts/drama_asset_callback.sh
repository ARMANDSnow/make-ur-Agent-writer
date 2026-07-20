#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="$ROOT/.venv/bin/python3"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

export DRAGON_RAJA_SKIP_DOTENV=1
export PYTHON_DOTENV_DISABLED=1
export OPENAI_MODEL=mock
export DRAMA_MODEL=mock
export LITELLM_LOCAL_MODEL_COST_MAP=true
unset OPENAI_API_KEY PLANNER_API_KEY AI_DRAW_API_KEY SD_API_KEY

exec "$PYTHON_BIN" -m src.drama_asset_callback_server "$@"
