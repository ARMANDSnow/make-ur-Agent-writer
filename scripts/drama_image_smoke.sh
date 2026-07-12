#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONFIRM_REAL_IMAGE_SMOKE="${CONFIRM_REAL_IMAGE_SMOKE:-}"
for arg in "$@"; do
  case "$arg" in
    --confirm-real-image-smoke) CONFIRM_REAL_IMAGE_SMOKE="可以跑生图" ;;
  esac
done
if [ "$CONFIRM_REAL_IMAGE_SMOKE" != "可以跑生图" ]; then
  echo "Refusing real image smoke without --confirm-real-image-smoke" >&2
  exit 64
fi
export CONFIRM_REAL_IMAGE_SMOKE

# Reuse the same proxy adaptation as the existing AetherHeart model path.
# shellcheck source=with_proxy.sh
source "$ROOT/scripts/with_proxy.sh"
export PYTHONPYCACHEPREFIX="$ROOT/.pycache"

"$ROOT/.venv/bin/python3" -m src.drama_image_smoke
