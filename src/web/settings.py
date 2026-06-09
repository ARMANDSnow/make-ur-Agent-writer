"""iter 026: model-switch panel.

The dashboard / wizard are useless if the user can't change which LLM is
called. ``.env`` at the project root is the single source of truth (see
``src/config.py:31`` ``load_dotenv``). This module exposes:

* ``GET /api/settings`` — read the current values with the API key
  middle masked so a screenshot or curl never leaks it.
* ``PUT /api/settings`` — atomic write of a hand-edited subset.

We do NOT hot-reload the running process — ``load_dotenv`` happens at
import time and the LLMClient caches its config — so the UI shows a
"restart required" banner after every successful PUT. iter 027+ may
revisit hot-reload via ``importlib.reload(src.config)``.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..config import ROOT


_ENV_PATH = ROOT / ".env"

# Hard-coded whitelist of keys the WebUI is allowed to read or write.
# Adding a key = a code review event. ``MODEL_PROFILE`` is included
# because some iter 023+ deploys override per-task models via it.
ALLOWED_KEYS = (
    "OPENAI_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "MODEL_PROFILE",
    "PLANNER_MODEL",
    "PLANNER_API_KEY",
    "PLANNER_BASE_URL",
    "OPENAI_STREAM",
    "DISABLE_PROMPT_CACHE",
    "WRITE_MAX_TOKENS",
    "WRITE_PROMPT_PROFILE",
)
SECRET_KEYS = frozenset({"OPENAI_API_KEY", "PLANNER_API_KEY"})

MAX_VALUE_LEN = 512


def get_settings() -> Tuple[int, str, bytes]:
    """GET handler — returns a JSON object with API key middle masked."""
    raw = _read_env(_ENV_PATH)
    out: Dict[str, str] = {}
    for key in ALLOWED_KEYS:
        val = raw.get(key, "")
        if key in SECRET_KEYS:
            out[key] = _mask(val)
        else:
            out[key] = val
    return _json(200, {"settings": out, "restart_required": False})


def put_settings(body: bytes) -> Tuple[int, str, bytes]:
    """PUT handler — atomically update whitelisted keys.

    Body: ``{"OPENAI_MODEL": "...", ...}``. Keys outside the whitelist
    are rejected with 400 rather than silently dropped — the user
    should know if the UI sent something we won't persist.
    """

    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})

    updates: Dict[str, str] = {}
    for key, val in payload.items():
        if key not in ALLOWED_KEYS:
            return _json(400, {"error": f"unknown key: {key}"})
        if not isinstance(val, str):
            return _json(400, {"error": f"value for {key} must be a string"})
        if len(val) > MAX_VALUE_LEN:
            return _json(400, {"error": f"value for {key} exceeds {MAX_VALUE_LEN} chars"})
        if re.search(r"[\n\r\x00]", val):
            return _json(400, {"error": f"value for {key} contains control characters"})
        if key in SECRET_KEYS and _is_masked(val):
            continue
        updates[key] = val

    # Merge: keep existing keys we didn't touch, replace the ones in
    # ``updates``.
    existing = _read_env(_ENV_PATH)
    merged = dict(existing)
    merged.update(updates)

    try:
        _write_env_atomic(_ENV_PATH, merged)
    except OSError as exc:
        return _json(500, {"error": f"failed to write .env: {exc}"})

    return _json(200, {"saved": True, "restart_required": True, "updated_keys": sorted(updates.keys())})


# ---- helpers ---------------------------------------------------------------


def _mask(secret: str) -> str:
    """Show first 3 + last 4 of a long secret; ``***`` for short ones."""
    if not secret:
        return ""
    if len(secret) <= 7:
        return "***"
    return f"{secret[:3]}***{secret[-4:]}"


def _is_masked(value: str) -> bool:
    return "***" in value


def _read_env(path: Path) -> Dict[str, str]:
    """Parse ``KEY=VALUE`` lines from .env. Ignores comments and blanks.

    Does NOT support quoted values or backslash escapes — the .env files
    the project ships are simple ASCII key=value pairs.
    """
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip()
    return out


def _write_env_atomic(path: Path, env: Dict[str, str]) -> None:
    """Write a .env file in deterministic key order via a temp file +
    os.replace so a crash mid-write doesn't leave a half-written .env."""

    # Whitelisted keys first (in our canonical order), then any others
    # that were already in the file (preserved as-is).
    ordered_keys = list(ALLOWED_KEYS) + sorted(set(env.keys()) - set(ALLOWED_KEYS))
    lines = []
    for key in ordered_keys:
        if key in env:
            lines.append(f"{key}={env[key]}")
    text = "\n".join(lines) + "\n"
    # iter 048d (A5): same per-writer tmp suffix as state.write_text_atomic
    # so concurrent PUT /settings calls (and tests that race them) can't
    # corrupt each other's tmp mid-write.
    tmp_path = path.with_suffix(
        path.suffix + f".tmp.{os.getpid()}.{threading.get_ident()}"
    )
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def _json(status: int, payload: Dict[str, Any]) -> Tuple[int, str, bytes]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return status, "application/json; charset=utf-8", body
