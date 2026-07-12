#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="$ROOT/.venv/bin/python3"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

REAL=0
CONFIRMED=0
for arg in "$@"; do
  [[ "$arg" == "--real-video" ]] && REAL=1
  [[ "$arg" == "--confirm-real-video" ]] && CONFIRMED=1
done

if [[ "$REAL" -eq 1 ]]; then
  if [[ "$CONFIRMED" -ne 1 || "${CONFIRM_REAL_VIDEO_SMOKE:-}" != "可以跑真实视频 smoke" ]]; then
    echo '{"ok":false,"error_code":"real_video_confirmation_required"}'
    exit 64
  fi
else
  export SD_VIDEO_MODE=mock
  unset SD_API_KEY SD_API_BASE_URL SD_ASSET_PUBLIC_BASE_URL SD_VIDEO_RESULT_HOSTS SD_VIDEO_ESTIMATED_COST_CNY
fi

exec "$PYTHON_BIN" -m src.drama_video_smoke "$@"
