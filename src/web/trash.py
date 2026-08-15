"""Soft-delete a workspace by moving it to workspaces/_trash/.

Hard rm is intentionally out of scope. The purge flow is responsible for
removing _trash/ entries on the user's schedule.
"""

from __future__ import annotations

import json
import fcntl
import os
import re
import shutil
import stat
import time
from datetime import datetime
from contextlib import contextmanager
from typing import Any, Dict, List, Tuple

from .. import paths


TRASH_DIR_NAME = "_trash"
_ENTRY_NAME_RE = re.compile(r"^(?P<original>.+)__(?P<ts>[0-9]{8}_[0-9]{6}(?:_\d+)?)$")
_SAFE_ENTRY_RE = re.compile(
    r"^[A-Za-z0-9_一-鿿][A-Za-z0-9_一-鿿-]{0,63}"
    r"__[0-9]{8}_[0-9]{6}(?:_\d+)?$"
)
_RESERVED_ORIGINAL_NAMES = frozenset({"legacy", "_trash", "", ".", ".."})
_MAX_META_BYTES = 64 * 1024


def _entry_supported_novel_identity(entry: str) -> tuple[int, int] | None:
    """Recognize only novel trash entries without following symlinks.

    Missing metadata is the historical novel layout.  Present but malformed,
    unknown, or explicitly unsupported metadata fails closed so the main
    branch cannot enumerate, restore, or delete that data.
    """

    ok, _ = _safe_entry_path(entry)
    if not ok:
        return None
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_fd = entry_fd = data_fd = meta_fd = None
    try:
        root_fd = os.open(paths.WORKSPACE_DIR / TRASH_DIR_NAME, flags)
        entry_fd = os.open(entry, flags, dir_fd=root_fd)
        entry_info = os.fstat(entry_fd)
        try:
            data_fd = os.open("data", flags, dir_fd=entry_fd)
        except FileNotFoundError:
            return entry_info.st_dev, entry_info.st_ino
        try:
            meta_fd = os.open(
                "workspace.json",
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=data_fd,
            )
        except FileNotFoundError:
            return entry_info.st_dev, entry_info.st_ino
        info = os.fstat(meta_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_META_BYTES:
            return None
        raw = os.read(meta_fd, _MAX_META_BYTES + 1)
        if len(raw) > _MAX_META_BYTES:
            return None
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict) and payload.get("type") == "novel":
            return entry_info.st_dev, entry_info.st_ino
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    finally:
        for fd in (meta_fd, data_fd, entry_fd, root_fd):
            if fd is not None:
                os.close(fd)


def _entry_is_supported_novel(entry: str) -> bool:
    return _entry_supported_novel_identity(entry) is not None


@contextmanager
def _locked_trash_root():
    """Serialize checked trash mutations and retain a nofollow parent fd."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(paths.WORKSPACE_DIR / TRASH_DIR_NAME, flags)
    lock_fd = os.open(
        ".novel-only-trash.lock",
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=root_fd,
    )
    try:
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise OSError("trash lock is not a regular file")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield root_fd
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
            os.close(root_fd)


def _entry_identity_matches(root_fd: int, entry: str, identity: tuple[int, int]) -> bool:
    try:
        info = os.stat(entry, dir_fd=root_fd, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == identity


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
    from . import workspace_meta

    metadata = workspace_meta.read(name)
    if (
        metadata.get("type") not in workspace_meta.SUPPORTED_TYPES
        or metadata.get("_metadata_status") == "invalid"
    ):
        return False, "unsupported_workspace_type"
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
        if not _entry_is_supported_novel(name):
            continue
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
    try:
        with _locked_trash_root() as trash_fd:
            identity = _entry_supported_novel_identity(entry)
            if identity is None:
                return False, "unsupported_workspace_type"
            original_name, _ = _split_entry_name(entry)
            if not original_name:
                return False, "malformed_entry"
            target = paths.WORKSPACE_DIR / original_name
            if target.exists():
                return False, "name_collision"
            if not _entry_identity_matches(trash_fd, entry, identity):
                return False, "entry_not_found"
            workspace_fd = os.open(
                paths.WORKSPACE_DIR,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                os.rename(entry, original_name, src_dir_fd=trash_fd, dst_dir_fd=workspace_fd)
            finally:
                os.close(workspace_fd)
    except FileNotFoundError:
        return False, "entry_not_found"
    return True, str(target.relative_to(paths.WORKSPACE_DIR))


def purge_trash_entry(entry: str) -> Tuple[bool, str]:
    """Hard-delete workspaces/_trash/<entry>/ via shutil.rmtree. No undo."""

    ok, reason = _safe_entry_path(entry)
    if not ok:
        return False, reason
    try:
        with _locked_trash_root() as trash_fd:
            identity = _entry_supported_novel_identity(entry)
            if identity is None:
                return False, "unsupported_workspace_type"
            if not _entry_identity_matches(trash_fd, entry, identity):
                return False, "entry_not_found"
            shutil.rmtree(entry, dir_fd=trash_fd)
    except FileNotFoundError:
        return False, "entry_not_found"
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
