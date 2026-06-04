"""Soft-delete a workspace by moving it to workspaces/_trash/.

Hard rm is intentionally out of scope. The purge flow is responsible for
removing _trash/ entries on the user's schedule.
"""

from __future__ import annotations

import re
import shutil
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

from .. import paths


TRASH_DIR_NAME = "_trash"
_ENTRY_NAME_RE = re.compile(r"^(?P<original>.+)__(?P<ts>[0-9]{8}_[0-9]{6}(?:_\d+)?)$")
_SAFE_ENTRY_RE = re.compile(
    r"^[A-Za-z0-9_一-鿿][A-Za-z0-9_一-鿿-]{0,63}"
    r"__[0-9]{8}_[0-9]{6}(?:_\d+)?$"
)
_RESERVED_ORIGINAL_NAMES = frozenset({"legacy", "_trash", "", ".", ".."})


def soft_delete_workspace(name: str) -> Tuple[bool, str]:
    """Move workspaces/<name>/ to workspaces/_trash/<name>__<ts>/.

    Returns (ok, message). On success ``message`` is the new path
    relative to ``paths.WORKSPACE_DIR``. On failure ``ok=False`` and
    ``message`` is a human-readable reason.

    Idempotency note: a second delete returns ok=False with
    ``workspace_not_found`` because the source directory is already
    gone — caller should map this to HTTP 404.
    """

    src = paths.WORKSPACE_DIR / name
    if not src.is_dir():
        return False, "workspace_not_found"
    trash_root = paths.WORKSPACE_DIR / TRASH_DIR_NAME
    trash_root.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    target = trash_root / f"{name}__{ts}"
    # If a same-second delete collides, append a counter; keeps the
    # rename atomic and avoids overwriting an existing trash entry.
    counter = 1
    while target.exists():
        counter += 1
        target = trash_root / f"{name}__{ts}_{counter}"
    src.rename(target)
    return True, str(target.relative_to(paths.WORKSPACE_DIR))


def list_trash_entries() -> List[Dict[str, Any]]:
    """Scan workspaces/_trash/* and return per-entry metadata."""

    root = paths.WORKSPACE_DIR / TRASH_DIR_NAME
    if not root.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        original_name, ts = _split_entry_name(name)
        deleted_at = ""
        if ts:
            base = ts.split("_")[0] + ts.split("_")[1] if "_" in ts else ts
            try:
                dt = datetime.strptime(base[:14], "%Y%m%d%H%M%S")
                deleted_at = dt.isoformat(timespec="seconds")
            except (ValueError, IndexError):
                deleted_at = ts
        size_bytes = 0
        file_count = 0
        for path in entry.rglob("*"):
            if path.is_file():
                file_count += 1
                try:
                    size_bytes += path.stat().st_size
                except OSError:
                    continue
        out.append(
            {
                "entry": name,
                "original_name": original_name,
                "deleted_at": deleted_at,
                "size_mb": round(size_bytes / (1024 * 1024), 2),
                "file_count": file_count,
            }
        )
    return out


def restore_trash_entry(entry: str) -> Tuple[bool, str]:
    """Move workspaces/_trash/<entry>/ back to workspaces/<original_name>/."""

    ok, reason = _safe_entry_path(entry)
    if not ok:
        return False, reason
    src = paths.WORKSPACE_DIR / TRASH_DIR_NAME / entry
    if not src.is_dir():
        return False, "entry_not_found"
    original_name, _ = _split_entry_name(entry)
    if not original_name:
        return False, "malformed_entry"
    target = paths.WORKSPACE_DIR / original_name
    if target.exists():
        return False, "name_collision"
    src.rename(target)
    return True, str(target.relative_to(paths.WORKSPACE_DIR))


def purge_trash_entry(entry: str) -> Tuple[bool, str]:
    """Hard-delete workspaces/_trash/<entry>/ via shutil.rmtree. No undo."""

    ok, reason = _safe_entry_path(entry)
    if not ok:
        return False, reason
    src = paths.WORKSPACE_DIR / TRASH_DIR_NAME / entry
    if not src.is_dir():
        return False, "entry_not_found"
    shutil.rmtree(src)
    return True, "purged"


def _split_entry_name(entry: str) -> Tuple[str, str]:
    match = _ENTRY_NAME_RE.fullmatch(entry)
    if not match:
        return entry, ""
    return match.group("original"), match.group("ts")


def _safe_entry_path(entry: str) -> Tuple[bool, str]:
    """Validate a trash entry name before resolving it under ``_trash``.

    The route layer performs the edge check too; keeping this local guard
    prevents future callers from bypassing path-traversal and sentinel
    protections at the filesystem boundary.
    """

    if not entry or "/" in entry or "\\" in entry or ".." in entry.split("__")[0]:
        return False, "malformed_entry"
    if not _SAFE_ENTRY_RE.fullmatch(entry):
        return False, "malformed_entry"
    match = _ENTRY_NAME_RE.fullmatch(entry)
    original = match.group("original") if match else ""
    if original in _RESERVED_ORIGINAL_NAMES:
        return False, "reserved_name"
    return True, ""
