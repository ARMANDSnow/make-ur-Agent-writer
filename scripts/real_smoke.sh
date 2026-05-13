#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p logs
ts="$(date +%Y%m%d_%H%M%S)"
log_path="logs/real_smoke_${ts}.log"

export PYTHONPYCACHEPREFIX="$ROOT/.pycache"

{
  python3 main.py preflight
  python3 main.py extract --volume longzu_1 --limit 2 --force
  python3 main.py status
  python3 main.py estimate-cost
  python3 main.py preflight
  echo "Real smoke log written: $log_path"
} 2>&1 | tee "$log_path"
