#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON_BIN="$ROOT/.venv/bin/python3"
[[ -x "$PYTHON_BIN" ]] || PYTHON_BIN="python3"

REAL_TEXT=0
REAL_IMAGE=0
REAL_VIDEO=0
CONFIRM_TEXT=0
CONFIRM_IMAGE=0
CONFIRM_VIDEO=0
for arg in "$@"; do
  [[ "$arg" == "--real-text" ]] && REAL_TEXT=1
  [[ "$arg" == "--real-image" ]] && REAL_IMAGE=1
  [[ "$arg" == "--real-video" ]] && REAL_VIDEO=1
  [[ "$arg" == "--confirm-real-text" ]] && CONFIRM_TEXT=1
  [[ "$arg" == "--confirm-real-image" ]] && CONFIRM_IMAGE=1
  [[ "$arg" == "--confirm-real-video" ]] && CONFIRM_VIDEO=1
done

if [[ "$REAL_TEXT" -eq 1 && "$CONFIRM_TEXT" -ne 1 ]]; then
  echo '{"ok":false,"error_code":"real_text_confirmation_required"}'
  exit 64
fi
if [[ "$REAL_IMAGE" -eq 1 && "$CONFIRM_IMAGE" -ne 1 ]]; then
  echo '{"ok":false,"error_code":"real_image_confirmation_required"}'
  exit 64
fi
if [[ "$REAL_VIDEO" -eq 1 && "$CONFIRM_VIDEO" -ne 1 ]]; then
  echo '{"ok":false,"error_code":"real_video_confirmation_required"}'
  exit 64
fi

# The existing video smoke keeps its second, shell-level confirmation layer.
if [[ "$REAL_VIDEO" -eq 1 ]]; then
  export CONFIRM_REAL_VIDEO_SMOKE="可以跑真实视频 smoke"
fi
if [[ "$REAL_TEXT" -eq 1 ]]; then
  export CONFIRM_REAL_MODEL_SMOKE="可以跑了"
fi
if [[ "$REAL_IMAGE" -eq 1 ]]; then
  export CONFIRM_REAL_IMAGE_SMOKE="可以跑生图"
fi
exec "$PYTHON_BIN" -m src.drama_multimodal_smoke "$@"
