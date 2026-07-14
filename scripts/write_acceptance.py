#!/usr/bin/env python3
"""Write small acceptance records through a symlink-safe, atomic path."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
MAX_RECORD_BYTES = 64 * 1024
ACCEPTANCE_LEVEL = "mock-functional"
VERIFICATION_PROFILE = "canonical-mock-offline"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _git_paths(root: Path, *args: str) -> tuple[int, list[str]]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, []
    paths = [os.fsdecode(value) for value in result.stdout.split(b"\0") if value]
    return result.returncode, paths


def _git_identity(root: Path) -> dict[str, Any]:
    head_result = _git(root, "rev-parse", "HEAD")
    tree_result = _git(root, "rev-parse", "HEAD^{tree}")
    head = head_result.stdout.strip() if head_result and head_result.returncode == 0 else None
    tree = tree_result.stdout.strip() if tree_result and tree_result.returncode == 0 else None
    clean = bool(head and len(head) == 40 and tree and len(tree) == 40)
    protected_paths: list[str] = []
    worktree_rc, worktree_paths = _git_paths(root, "diff", "--name-only", "-z", "--")
    index_rc, index_paths = _git_paths(root, "diff", "--cached", "--name-only", "-z", "--")
    untracked_rc, untracked_paths = _git_paths(
        root, "ls-files", "--others", "--exclude-standard", "-z"
    )
    if worktree_rc or index_rc or untracked_rc:
        clean = False
    else:
        protected_paths.extend(worktree_paths)
        protected_paths.extend(index_paths)
        protected_paths.extend(path for path in untracked_paths if not path.startswith("docs/"))
        if protected_paths:
            clean = False
    return {
        "git_head": head if head and len(head) == 40 else None,
        "git_tree": tree if tree and len(tree) == 40 else None,
        "tracked_scope_clean": clean,
        "protected_paths": sorted(set(protected_paths)),
    }


def _open_child_dir(parent_fd: int, name: str) -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise RuntimeError("secure acceptance writes require O_NOFOLLOW and O_DIRECTORY")
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    return os.open(name, os.O_RDONLY | directory | nofollow, dir_fd=parent_fd)


def _open_harness_dir(root: Path) -> int:
    directory = getattr(os, "O_DIRECTORY", None)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if directory is None or nofollow is None:
        raise RuntimeError("secure acceptance writes are unsupported on this platform")
    root_fd = os.open(str(root.resolve()), os.O_RDONLY | directory | nofollow)
    try:
        outputs_fd = _open_child_dir(root_fd, "outputs")
        try:
            return _open_child_dir(outputs_fd, "harness")
        finally:
            os.close(outputs_fd)
    finally:
        os.close(root_fd)


def _read_current(harness_fd: int) -> dict[str, Any]:
    nofollow = getattr(os, "O_NOFOLLOW")
    fd = os.open("acceptance.json", os.O_RDONLY | nofollow, dir_fd=harness_fd)
    try:
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            text = handle.read(MAX_RECORD_BYTES + 1)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    if len(text.encode("utf-8")) > MAX_RECORD_BYTES:
        raise ValueError("existing acceptance record exceeds the size limit")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("existing acceptance record must be a JSON object")
    return value


@contextmanager
def _acceptance_lock(harness_fd: int):
    nofollow = getattr(os, "O_NOFOLLOW")
    lock_fd = os.open(
        "acceptance.lock",
        os.O_RDWR | os.O_CREAT | nofollow,
        0o600,
        dir_fd=harness_fd,
    )
    try:
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise RuntimeError("acceptance lock must be a regular file")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def _atomic_write(harness_fd: int, payload: dict[str, Any]) -> None:
    nofollow = getattr(os, "O_NOFOLLOW")
    temporary = f".acceptance.{uuid.uuid4().hex}.tmp"
    fd = -1
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=harness_fd,
        )
        data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        if len(data) > MAX_RECORD_BYTES:
            raise ValueError("acceptance record exceeds the size limit")
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(
            temporary,
            "acceptance.json",
            src_dir_fd=harness_fd,
            dst_dir_fd=harness_fd,
        )
        os.fsync(harness_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=harness_fd)
        except FileNotFoundError:
            pass


def start_record(root: Path, python_runtime: str) -> str:
    run_id = uuid.uuid4().hex
    identity = _git_identity(root)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": "running",
        "exit_code": None,
        "mock_offline": True,
        "acceptance_level": ACCEPTANCE_LEVEL,
        "verification_profile": VERIFICATION_PROFILE,
        "workspace_scope": {"mode": "isolated-mock"},
        "python_runtime": python_runtime,
        "test_count": None,
        "started_at": _utc_now(),
        "completed_at": None,
        "duration_seconds": None,
        "git_head": identity["git_head"],
        "git_tree": identity["git_tree"],
        "tracked_scope_clean": identity["tracked_scope_clean"],
        "completed_steps": [],
        "failed_step": None,
    }
    harness_fd = _open_harness_dir(root)
    try:
        with _acceptance_lock(harness_fd):
            _atomic_write(harness_fd, payload)
    finally:
        os.close(harness_fd)
    return run_id


def finish_record(
    root: Path,
    run_id: str,
    status: str,
    exit_code: int,
    test_count: int,
    duration_seconds: int,
    completed_steps: str,
    failed_step: str | None,
) -> None:
    if status == "passed" and test_count <= 0:
        raise ValueError("a passed acceptance record requires a positive test count")
    harness_fd = _open_harness_dir(root)
    try:
        with _acceptance_lock(harness_fd):
            payload = _read_current(harness_fd)
            if payload.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("acceptance schema version changed during the run")
            if payload.get("run_id") != run_id or payload.get("status") != "running":
                raise ValueError("acceptance run identity changed during the run")
            identity = _git_identity(root)
            if identity["git_head"] != payload.get("git_head"):
                raise ValueError("git HEAD changed during acceptance")
            if identity["git_tree"] != payload.get("git_tree"):
                raise ValueError("git tree changed during acceptance")
            if payload.get("tracked_scope_clean") and not identity["tracked_scope_clean"]:
                raise ValueError("repository scope became dirty during acceptance")
            if status == "passed" and (
                not payload.get("tracked_scope_clean")
                or not identity["tracked_scope_clean"]
                or not payload.get("git_head")
                or not payload.get("git_tree")
            ):
                raise ValueError("passed acceptance requires a clean, committed git identity")
            payload.update(
                {
                    "status": status,
                    "exit_code": exit_code,
                    "test_count": test_count,
                    "completed_at": _utc_now(),
                    "duration_seconds": max(0, duration_seconds),
                    "completed_steps": [
                        step for step in completed_steps.splitlines() if step
                    ],
                    "failed_step": failed_step or None,
                }
            )
            _atomic_write(harness_fd, payload)
    finally:
        os.close(harness_fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--root", type=Path, required=True)
    start.add_argument("--python-runtime", required=True)

    check_repository = subparsers.add_parser("check-repository")
    check_repository.add_argument("--root", type=Path, required=True)

    finish = subparsers.add_parser("finish")
    finish.add_argument("--root", type=Path, required=True)
    finish.add_argument("--run-id", required=True)
    finish.add_argument("--status", choices=("passed", "failed"), required=True)
    finish.add_argument("--exit-code", type=int, required=True)
    finish.add_argument("--test-count", type=int, required=True)
    finish.add_argument("--duration-seconds", type=int, required=True)
    finish.add_argument("--completed-steps", default="")
    finish.add_argument("--failed-step")
    args = parser.parse_args()

    try:
        if args.command == "start":
            print(start_record(args.root, args.python_runtime))
        elif args.command == "check-repository":
            identity = _git_identity(args.root)
            if not identity["tracked_scope_clean"]:
                paths = ", ".join(identity["protected_paths"][:10]) or "git metadata unavailable"
                raise ValueError(f"repository scope is not clean: {paths}")
        else:
            finish_record(
                args.root,
                args.run_id,
                args.status,
                args.exit_code,
                args.test_count,
                args.duration_seconds,
                args.completed_steps,
                args.failed_step,
            )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ACCEPTANCE EVIDENCE ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
