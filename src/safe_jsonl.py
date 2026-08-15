"""Bounded, no-follow JSONL tail reads for untrusted workspace logs."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any


DEFAULT_MAX_TOTAL_BYTES = 512 * 1024
DEFAULT_MAX_LINE_BYTES = 64 * 1024
DEFAULT_MAX_JSON_DEPTH = 64


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _safe_relative_parts(relative: str) -> tuple[str, ...]:
    value = PurePosixPath(str(relative))
    parts = value.parts
    if value.is_absolute() or not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("relative JSONL path required")
    if any("/" in part or "\x00" in part for part in parts):
        raise ValueError("invalid JSONL path component")
    return tuple(parts)


def _json_depth_within(raw: bytes, maximum: int) -> bool:
    """Lexically bound JSON nesting before handing bytes to ``json.loads``."""

    depth = 0
    quoted = False
    escaped = False
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # quote
                quoted = False
            continue
        if byte == 0x22:
            quoted = True
        elif byte in (0x7B, 0x5B):  # { [
            depth += 1
            if depth > maximum:
                return False
        elif byte in (0x7D, 0x5D):  # } ]
            depth -= 1
            if depth < 0:
                return False
    return not quoted and depth == 0


def tail_jsonl(
    root: Path,
    relative: str,
    limit: int,
    *,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
    max_json_depth: int = DEFAULT_MAX_JSON_DEPTH,
) -> list[dict[str, Any]]:
    """Return a fail-closed tail of dict rows beneath ``root``.

    Every path component is opened relative to a no-follow directory fd.  A
    source that is missing, non-regular, replaced while reading, over a byte or
    nesting limit, malformed, or contains a non-object row degrades to ``[]``.
    """

    try:
        count = int(limit)
    except (TypeError, ValueError, OverflowError):
        return []
    if count <= 0 or max_total_bytes <= 0 or max_line_bytes <= 0 or max_json_depth <= 0:
        return []
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        return []
    try:
        parts = _safe_relative_parts(relative)
    except ValueError:
        return []

    root_fd = current_fd = file_fd = None
    opened_directory_identities: list[tuple[int, int]] = []
    try:
        root_path = Path(root)
        root_lstat = root_path.lstat()
        if stat.S_ISLNK(root_lstat.st_mode) or not stat.S_ISDIR(root_lstat.st_mode):
            return []
        root_fd = os.open(root_path, _directory_flags())
        opened_root = os.fstat(root_fd)
        if (opened_root.st_dev, opened_root.st_ino) != (root_lstat.st_dev, root_lstat.st_ino):
            return []
        opened_directory_identities.append((opened_root.st_dev, opened_root.st_ino))
        current_fd = root_fd
        for part in parts[:-1]:
            next_fd = os.open(part, _directory_flags(), dir_fd=current_fd)
            next_stat = os.fstat(next_fd)
            opened_directory_identities.append((next_stat.st_dev, next_stat.st_ino))
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd

        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        file_fd = os.open(parts[-1], flags, dir_fd=current_fd)
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            return []

        position = before.st_size
        raw_tail = b""
        chunk_size = 8192
        while position > 0 and raw_tail.count(b"\n") <= count:
            remaining = max_total_bytes - len(raw_tail)
            if remaining <= 0:
                return []
            read_size = min(chunk_size, position, remaining)
            position -= read_size
            chunk = os.pread(file_fd, read_size, position)
            if len(chunk) != read_size:
                return []
            raw_tail = chunk + raw_tail

        after = os.fstat(file_fd)
        before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if before_identity != after_identity:
            return []

        # Re-resolve the complete pathname after the read.  Re-checking only
        # the already-open file descriptor would accept a detached inode when
        # an attacker renames the original file and replaces its pathname.
        verify_root_fd = verify_current_fd = verify_file_fd = None
        try:
            verify_root_lstat = root_path.lstat()
            if stat.S_ISLNK(verify_root_lstat.st_mode) or not stat.S_ISDIR(verify_root_lstat.st_mode):
                return []
            verify_root_fd = os.open(root_path, _directory_flags())
            verify_root_stat = os.fstat(verify_root_fd)
            if (verify_root_stat.st_dev, verify_root_stat.st_ino) != opened_directory_identities[0]:
                return []
            verify_current_fd = verify_root_fd
            for index, part in enumerate(parts[:-1], start=1):
                next_fd = os.open(part, _directory_flags(), dir_fd=verify_current_fd)
                next_stat = os.fstat(next_fd)
                if (next_stat.st_dev, next_stat.st_ino) != opened_directory_identities[index]:
                    os.close(next_fd)
                    return []
                if verify_current_fd != verify_root_fd:
                    os.close(verify_current_fd)
                verify_current_fd = next_fd
            verify_file_fd = os.open(parts[-1], flags, dir_fd=verify_current_fd)
            final_stat = os.fstat(verify_file_fd)
            final_identity = (
                final_stat.st_dev,
                final_stat.st_ino,
                final_stat.st_size,
                final_stat.st_mtime_ns,
            )
            if not stat.S_ISREG(final_stat.st_mode) or final_identity != after_identity:
                return []
        finally:
            if verify_file_fd is not None:
                os.close(verify_file_fd)
            if verify_current_fd is not None and verify_current_fd != verify_root_fd:
                os.close(verify_current_fd)
            if verify_root_fd is not None:
                os.close(verify_root_fd)

        lines = raw_tail.splitlines()
        if position > 0:
            if not lines:
                return []
            lines = lines[1:]
        if len(lines) > count:
            lines = lines[-count:]

        rows: list[dict[str, Any]] = []
        for raw in lines:
            if len(raw) > max_line_bytes:
                return []
            raw = raw.strip()
            if not raw:
                continue
            if not _json_depth_within(raw, max_json_depth):
                return []
            try:
                text = raw.decode("utf-8")
                value = json.loads(text)
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, MemoryError):
                return []
            if not isinstance(value, dict):
                return []
            rows.append(value)
        return rows
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError):
        return []
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass
        if current_fd is not None and current_fd != root_fd:
            try:
                os.close(current_fd)
            except OSError:
                pass
        if root_fd is not None:
            try:
                os.close(root_fd)
            except OSError:
                pass
