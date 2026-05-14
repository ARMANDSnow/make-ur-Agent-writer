#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p logs
ts="$(date +%Y%m%d_%H%M%S)"
log_path="logs/debate_smoke_${ts}.log"

export PYTHONPYCACHEPREFIX="$ROOT/.pycache"

{
  python3 main.py preflight
  python3 main.py debate
  python3 main.py estimate-cost
  python3 main.py preflight
  snap="outputs/debate/snapshots/${ts}"
  mkdir -p "$snap"
  cp outputs/debate/decisions.json "$snap/" 2>/dev/null || true
  cp outputs/debate/debate_log.jsonl "$snap/" 2>/dev/null || true
  cp outputs/debate/outline.md "$snap/" 2>/dev/null || true
  echo "Snapshot saved: $snap"
  echo "Debate smoke log written: $log_path"
} 2>&1 | tee "$log_path"
