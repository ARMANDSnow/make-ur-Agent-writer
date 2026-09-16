#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for the Dragon Raja AI Continuer repo.
# Safe to run repeatedly and against a cached/partially-prepared VM.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# The base image ships Python 3.12 but not the stdlib venv module that this
# project's canonical acceptance (scripts/verify.sh) hard-requires at
# .venv/bin/python3. Install it only when it is actually missing.
if ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3-venv
fi

# Create the project virtualenv once; reuse it on later runs.
if [ ! -x .venv/bin/python3 ]; then
  python3 -m venv .venv
fi

.venv/bin/python3 -m pip install --upgrade pip
.venv/bin/python3 -m pip install -r requirements.txt
