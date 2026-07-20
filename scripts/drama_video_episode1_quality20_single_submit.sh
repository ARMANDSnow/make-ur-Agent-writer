#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BOOK=""
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --book)
      if [[ "$#" -lt 2 || -z "$2" || -n "$BOOK" ]]; then
        echo '{"ok":false,"error_code":"quality20_book_required"}'
        exit 64
      fi
      BOOK="$2"
      shift 2
      ;;
    *)
      echo '{"ok":false,"error_code":"quality20_arguments_rejected"}'
      exit 64
      ;;
  esac
done

if [[ "$BOOK" != "iter124_real_sop_v2" ]]; then
  echo '{"ok":false,"error_code":"quality20_workspace_rejected"}'
  exit 64
fi

export SD_VIDEO_ESTIMATED_COST_CNY=80

exec bash "$ROOT/scripts/drama_video_smoke.sh" \
  --book "$BOOK" \
  --real-video \
  --confirm-real-video \
  --budget-cny 80 \
  --timeout-seconds 1800 \
  --authorization-profile iter143-iter124-real-sop-v2-quality20-single-submit-v1
