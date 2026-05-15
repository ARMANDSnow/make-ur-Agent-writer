#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p logs
ts="$(date +%Y%m%d_%H%M%S)"
log_path="logs/write_smoke_${ts}.log"

export PYTHONPYCACHEPREFIX="$ROOT/.pycache"

{
  python3 main.py preflight
  python3 main.py compress
  python3 main.py debate
  python3 main.py write --chapters 1 --force
  python3 main.py review
  python3 main.py status
  python3 main.py estimate-cost
  python3 main.py preflight
  snap="outputs/drafts/snapshots/${ts}"
  mkdir -p "$snap"
  cp outputs/drafts/chapter_01.md "$snap/" 2>/dev/null || true
  cp outputs/drafts/chapter_01.meta.json "$snap/" 2>/dev/null || true
  cp -r outputs/reviews "$snap/" 2>/dev/null || true
  cp outputs/debate/decisions.json "$snap/debate_decisions.json" 2>/dev/null || true
  cp outputs/debate/outline.md "$snap/debate_outline.md" 2>/dev/null || true
  echo "Snapshot saved: $snap"
  echo "Write smoke log written: $log_path"
} 2>&1 | tee "$log_path"
