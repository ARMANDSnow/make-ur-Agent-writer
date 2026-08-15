"""Read/write ``workspaces/<name>/data/workspace.json``.

Schema v2:

``{"type": "novel" | "drama", "created_at": "<ISO 8601>" | null,
"schema_version": 2, "creation_mode": "greenfield" | "continuation"}``

``creation_mode`` is present only for novel workspaces.  It records how the
workspace was created; it must never be inferred from whether a continuation
start point happens to exist.

Older workspaces may not have this file. In that case
``read()`` returns a schema_version=0 novel default and performs a bounded,
read-only legacy inference: a real ``小说txt/seed.txt`` with no real
``小说txt/upload.txt`` is greenfield; every ambiguous shape fails closed to
continuation.  Reads never migrate or rewrite metadata.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .. import paths


# ``drama`` remains known only so legacy workspaces fail closed instead of
# being reinterpreted as novels.  This branch creates and mutates novels only.
KNOWN_TYPES = frozenset({"novel", "drama"})
SUPPORTED_TYPES = frozenset({"novel"})
VALID_TYPES = KNOWN_TYPES
VALID_CREATION_MODES = frozenset({"greenfield", "continuation"})
SCHEMA_VERSION = 2
_MAX_META_BYTES = 64 * 1024


def _real_regular(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _real_directory(path: Path) -> bool:
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _entry_absent(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def _infer_legacy_creation_mode(name: str) -> str:
    """Infer only the one unambiguous historical greenfield layout.

    The probe is deliberately metadata-only: it never opens either file and it
    rejects symlinked workspace/raw directories or entries.  Anything other
    than the exact historical ``seed.txt``-only layout remains continuation so
    an imported book cannot silently bypass its start-point gate.
    """

    root = paths.WORKSPACE_DIR / name
    raw_dir = root / "小说txt"
    if not _real_directory(root) or not _real_directory(raw_dir):
        return "continuation"
    seed = _real_regular(raw_dir / "seed.txt")
    upload_absent = _entry_absent(raw_dir / "upload.txt")
    return "greenfield" if seed and upload_absent else "continuation"


def _legacy_default(name: str) -> Dict[str, Any]:
    return {
        "type": "novel",
        "created_at": None,
        "schema_version": 0,
        "creation_mode": _infer_legacy_creation_mode(name),
        "_metadata_status": "legacy",
    }


def _conservative_default() -> Dict[str, Any]:
    return {
        "type": "novel",
        "created_at": None,
        "schema_version": 0,
        "creation_mode": "continuation",
        "_metadata_status": "invalid",
    }


def workspace_meta_path(name: str) -> Path:
    return paths.WORKSPACE_DIR / name / "data" / "workspace.json"


def _open_meta_nofollow(name: str) -> Optional[int]:
    """Open metadata through verified directory fds; ``None`` means absent."""

    if not name or Path(name).name != name or name in {".", ".."}:
        raise OSError("invalid workspace name")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_fd = os.open(paths.WORKSPACE_DIR, directory_flags)
    workspace_fd: Optional[int] = None
    data_fd: Optional[int] = None
    try:
        workspace_fd = os.open(name, directory_flags, dir_fd=root_fd)
        try:
            data_fd = os.open("data", directory_flags, dir_fd=workspace_fd)
        except FileNotFoundError:
            return None
        try:
            return os.open(
                "workspace.json",
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=data_fd,
            )
        except FileNotFoundError:
            return None
    finally:
        if data_fd is not None:
            os.close(data_fd)
        if workspace_fd is not None:
            os.close(workspace_fd)
        os.close(root_fd)


def read(name: str) -> Dict[str, Any]:
    """Return workspace metadata, never raising for missing/bad metadata."""

    try:
        fd = _open_meta_nofollow(name)
    except OSError:
        sys.stderr.write("[workspace_meta] event=metadata_open_failed action=fail_closed\n")
        return _conservative_default()
    if fd is None:
        return _legacy_default(name)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_META_BYTES:
            return _conservative_default()
        raw = os.read(fd, _MAX_META_BYTES + 1)
        if len(raw) > _MAX_META_BYTES:
            return _conservative_default()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        sys.stderr.write("[workspace_meta] event=metadata_decode_failed action=fail_closed\n")
        return _conservative_default()
    finally:
        os.close(fd)
    if not isinstance(data, dict):
        return _conservative_default()
    workspace_type = data.get("type")
    type_valid = workspace_type in VALID_TYPES
    if not type_valid:
        workspace_type = "novel"
    try:
        schema_version = int(data.get("schema_version") or 0)
    except (TypeError, ValueError):
        schema_version = 0
    result = {
        "type": workspace_type,
        "created_at": data.get("created_at"),
        "schema_version": schema_version,
        "_metadata_status": "valid" if type_valid else "invalid",
    }
    if workspace_type == "novel":
        creation_mode = data.get("creation_mode")
        if schema_version < SCHEMA_VERSION:
            creation_mode = _infer_legacy_creation_mode(name)
            if type_valid:
                result["_metadata_status"] = "legacy"
        elif creation_mode not in VALID_CREATION_MODES:
            creation_mode = "continuation"
            result["_metadata_status"] = "invalid"
        result["creation_mode"] = creation_mode
    return result


def write(
    name: str,
    *,
    type: str,
    created_at: Optional[str] = None,
    creation_mode: Optional[str] = None,
) -> None:
    """Write ``workspace.json`` for a workspace."""

    if type not in SUPPORTED_TYPES:
        raise ValueError(f"unsupported workspace type: {type!r}")
    if type == "novel":
        creation_mode = creation_mode or "continuation"
        if creation_mode not in VALID_CREATION_MODES:
            raise ValueError(f"invalid creation mode: {creation_mode!r}")
    elif creation_mode is not None:
        raise ValueError("creation_mode only applies to novel workspaces")
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {
        "type": type,
        "created_at": created_at,
        "schema_version": SCHEMA_VERSION,
    }
    if type == "novel":
        payload["creation_mode"] = creation_mode
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
