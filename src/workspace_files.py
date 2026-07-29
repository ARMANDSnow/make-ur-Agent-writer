"""Bounded, no-follow file access beneath a named workspace.

This module is intentionally narrow: it backs the Web KB/draft surfaces that
must tolerate partially initialized workspaces without trusting descendant
``Path`` objects.  Every directory component is opened relative to an already
opened directory descriptor, and final entries must be regular files.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import PurePosixPath
from typing import Any, Callable, Iterable

from . import paths


class WorkspaceFileError(OSError):
    """A workspace entry is unsafe, malformed, or exceeds its bound."""


def _directory_flags() -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise WorkspaceFileError("secure workspace file access unavailable")
    return os.O_RDONLY | directory | nofollow | getattr(os, "O_CLOEXEC", 0)


def _parts(relative: str) -> tuple[str, ...]:
    value = PurePosixPath(relative)
    parts = value.parts
    if (
        not relative
        or value.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise WorkspaceFileError("invalid workspace-relative path")
    return parts


def _open_dir(workspace: str, parts: Iterable[str], *, create: bool = False) -> int:
    try:
        current = os.open(paths.workspace_root(workspace), _directory_flags())
    except (OSError, TypeError, ValueError) as exc:
        raise WorkspaceFileError("unsafe workspace root") from exc
    try:
        for part in parts:
            try:
                child = os.open(part, _directory_flags(), dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current)
                    child = os.open(part, _directory_flags(), dir_fd=current)
                except OSError as exc:
                    raise WorkspaceFileError("cannot create workspace directory") from exc
            except OSError as exc:
                raise WorkspaceFileError("unsafe workspace directory") from exc
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def _open_parent(workspace: str, relative: str, *, create: bool = False) -> tuple[int, str]:
    parts = _parts(relative)
    return _open_dir(workspace, parts[:-1], create=create), parts[-1]


def _require_regular(file_fd: int, *, max_bytes: int) -> os.stat_result:
    info = os.fstat(file_fd)
    if not stat.S_ISREG(info.st_mode):
        raise WorkspaceFileError("workspace entry is not a regular file")
    if info.st_size < 0 or info.st_size > max_bytes:
        raise WorkspaceFileError("workspace file exceeds size limit")
    return info


def read_bytes(workspace: str, relative: str, *, max_bytes: int) -> bytes:
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    parent_fd, leaf = _open_parent(workspace, relative)
    file_fd = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            file_fd = os.open(leaf, flags, dir_fd=parent_fd)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise WorkspaceFileError("unsafe workspace file") from exc
        before = _require_regular(file_fd, max_bytes=max_bytes)
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(file_fd)
        identity = lambda value: (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
        )
        if (
            len(payload) > max_bytes
            or len(payload) != before.st_size
            or identity(before) != identity(after)
        ):
            raise WorkspaceFileError("workspace file changed during read")
        return payload
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        os.close(parent_fd)


def read_text(
    workspace: str,
    relative: str,
    *,
    max_bytes: int,
    errors: str = "replace",
) -> str:
    return read_bytes(workspace, relative, max_bytes=max_bytes).decode("utf-8", errors=errors)


def read_json_optional(
    workspace: str,
    relative: str,
    default: Any,
    *,
    max_bytes: int,
) -> Any:
    try:
        return json.loads(read_text(workspace, relative, max_bytes=max_bytes))
    except FileNotFoundError:
        return default
    except (UnicodeDecodeError, json.JSONDecodeError):
        return default


def _reject_existing_nonregular(parent_fd: int, leaf: str) -> None:
    try:
        info = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise WorkspaceFileError("cannot inspect workspace target") from exc
    if not stat.S_ISREG(info.st_mode):
        raise WorkspaceFileError("workspace target is not a regular file")


def write_bytes_atomic(workspace: str, relative: str, payload: bytes, *, max_bytes: int) -> None:
    if len(payload) > max_bytes:
        raise WorkspaceFileError("workspace file exceeds size limit")
    parent_fd, leaf = _open_parent(workspace, relative, create=True)
    temp_name = f".{leaf}.tmp.{secrets.token_hex(12)}"
    temp_fd = -1
    created = False
    try:
        _reject_existing_nonregular(parent_fd, leaf)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        temp_fd = os.open(temp_name, flags, 0o600, dir_fd=parent_fd)
        created = True
        offset = 0
        while offset < len(payload):
            written = os.write(temp_fd, payload[offset:])
            if written <= 0:
                raise WorkspaceFileError("short workspace file write")
            offset += written
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = -1
        _reject_existing_nonregular(parent_fd, leaf)
        os.replace(temp_name, leaf, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        created = False
        os.fsync(parent_fd)
    except OSError as exc:
        if isinstance(exc, WorkspaceFileError):
            raise
        raise WorkspaceFileError("workspace atomic write failed") from exc
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        if created:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except OSError:
                pass
        os.close(parent_fd)


def write_text_atomic(workspace: str, relative: str, text: str, *, max_bytes: int) -> None:
    write_bytes_atomic(workspace, relative, text.encode("utf-8"), max_bytes=max_bytes)


def write_json_atomic(workspace: str, relative: str, value: Any, *, max_bytes: int) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    write_text_atomic(workspace, relative, payload, max_bytes=max_bytes)


def list_regular_names(
    workspace: str,
    relative_dir: str,
    *,
    accept: Callable[[str], bool],
    max_entries: int = 10_000,
) -> list[str]:
    parts = _parts(relative_dir)
    try:
        directory_fd = _open_dir(workspace, parts)
    except FileNotFoundError:
        return []
    try:
        names = os.listdir(directory_fd)
        if len(names) > max_entries:
            raise WorkspaceFileError("workspace directory exceeds entry limit")
        result: list[str] = []
        for name in names:
            if not accept(name):
                continue
            try:
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as exc:
                raise WorkspaceFileError("cannot inspect workspace entry") from exc
            if not stat.S_ISREG(info.st_mode):
                raise WorkspaceFileError("workspace entry is not a regular file")
            result.append(name)
        return sorted(result)
    finally:
        os.close(directory_fd)
