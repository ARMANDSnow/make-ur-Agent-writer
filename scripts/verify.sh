#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONPYCACHEPREFIX="$ROOT/.pycache"

python3 -m py_compile main.py src/*.py tests/*.py
python3 -m unittest discover -s tests -v
python3 main.py normalize
python3 main.py split
python3 main.py run-all --extract-limit 2 --chapters 1 --force
python3 main.py status
python3 main.py check-manifest
python3 main.py manifest-report
python3 main.py review-summary
python3 main.py check-reports
python3 main.py estimate-cost
