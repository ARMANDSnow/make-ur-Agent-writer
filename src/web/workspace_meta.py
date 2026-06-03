"""Read/write ``workspaces/<name>/data/workspace.json``.

Schema v1:

``{"type": "novel" | "drama", "created_at": "<ISO 8601>" | null,
"schema_version": 1}``

Workspaces created before iter 036 do not have this file.  In that case
``read()`` returns a schema_version=0 novel default so all existing novel
workspaces keep working.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .. import paths


VALID_TYPES = frozenset({"novel", "drama"})
SCHEMA_VERSION = 1

_LEGACY_DEFAULT = {"type": "novel", "created_at": None, "schema_version": 0}


def workspace_meta_path(name: str) -> Path:
    return paths.WORKSPACE_DIR / name / "data" / "workspace.json"


def read(name: str) -> Dict[str, Any]:
    """Return workspace metadata, never raising for missing/bad metadata."""

    path = workspace_meta_path(name)
    if not path.exists():
        return dict(_LEGACY_DEFAULT)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        sys.stderr.write(
            f"[workspace_meta] read {name!r} failed: {exc}; falling back to novel\n"
        )
        return dict(_LEGACY_DEFAULT)
    if not isinstance(data, dict):
        return dict(_LEGACY_DEFAULT)
    workspace_type = data.get("type")
    if workspace_type not in VALID_TYPES:
        workspace_type = "novel"
    try:
        schema_version = int(data.get("schema_version") or 0)
    except (TypeError, ValueError):
        schema_version = 0
    return {
        "type": workspace_type,
        "created_at": data.get("created_at"),
        "schema_version": schema_version,
    }


def write(name: str, *, type: str, created_at: Optional[str] = None) -> None:
    """Write ``workspace.json`` for a workspace."""

    if type not in VALID_TYPES:
        raise ValueError(f"invalid type: {type!r}")
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {
        "type": type,
        "created_at": created_at,
        "schema_version": SCHEMA_VERSION,
    }
    path = workspace_meta_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as fh:
        tmp_path = Path(fh.name)
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    try:
        tmp_path.replace(path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
