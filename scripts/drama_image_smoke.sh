#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "Legacy drama_image_smoke is disabled; use scripts/drama_multimodal_smoke.sh for budgeted all-character image testing" >&2
exit 64
