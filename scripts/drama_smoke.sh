#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BOOK="iter090_drama_smoke_$(date +%Y%m%d_%H%M%S)"
ARGS=()
REAL_TEXT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --book) BOOK="$2"; shift 2 ;;
    --real-text) REAL_TEXT=1; ARGS+=("--real-text"); shift ;;
    --real-image)
      echo "Legacy --real-image is disabled; use scripts/drama_multimodal_smoke.sh for budgeted all-character image testing" >&2
      exit 64
      ;;
    --confirm-real-smoke) export CONFIRM_REAL_MODEL_SMOKE="可以跑了"; shift ;;
    --confirm-real-image-smoke)
      echo "Legacy image confirmation is disabled; use scripts/drama_multimodal_smoke.sh" >&2
      exit 64
      ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

if [[ "$REAL_TEXT" == "1" && "${CONFIRM_REAL_MODEL_SMOKE:-}" != "可以跑了" ]]; then
  echo "Refusing real drama text smoke without --confirm-real-smoke" >&2
  exit 64
fi
if [[ "$REAL_TEXT" == "0" ]]; then
  export OPENAI_MODEL=mock
  export DRAMA_MODEL=mock
  export LITELLM_LOCAL_MODEL_COST_MAP=true
fi

cd "$ROOT"
if [[ ${#ARGS[@]} -gt 0 ]]; then
  exec "$ROOT/.venv/bin/python3" -m src.drama_smoke --book "$BOOK" "${ARGS[@]}"
fi
exec "$ROOT/.venv/bin/python3" -m src.drama_smoke --book "$BOOK"
