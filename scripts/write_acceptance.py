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
LOCAL_E2E_FILENAME = "local_drama_e2e.json"
LOCAL_E2E_SCHEMA_VERSION = 1
LOCAL_E2E_PROFILE = "loopback-fake-provider"


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


def _read_json_record(harness_fd: int, filename: str) -> dict[str, Any]:
    """Read one fixed harness record without following links or path changes."""
    nofollow = getattr(os, "O_NOFOLLOW")
    fd = os.open(filename, os.O_RDONLY | nofollow, dir_fd=harness_fd)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError(f"{filename} must be a single-link regular file")
        chunks: list[bytes] = []
        remaining = MAX_RECORD_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError(f"{filename} changed while it was read")
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) > MAX_RECORD_BYTES:
        raise ValueError(f"{filename} exceeds the size limit")
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{filename} must be a JSON object")
    return value


def _validate_local_e2e_evidence(
    harness_fd: int,
    *,
    run_id: str,
    git_head: str,
    git_tree: str,
) -> None:
    component = _read_json_record(harness_fd, LOCAL_E2E_FILENAME)
    expected = {
        "schema_version": LOCAL_E2E_SCHEMA_VERSION,
        "status": "passed",
        "acceptance_level": "local-e2e",
        "verification_profile": LOCAL_E2E_PROFILE,
        "acceptance_run_id": run_id,
        "git_head": git_head,
        "git_tree": git_tree,
        "provider_validated": False,
    }
    for key, wanted in expected.items():
        if component.get(key) != wanted:
            raise ValueError(
                f"{LOCAL_E2E_FILENAME} has invalid {key}: expected {wanted!r}"
            )
    # Local fake-provider evidence cannot upgrade or imply real-provider
    # validation through an alternate or nested field.
    def claims_provider_validation(value: Any) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = "".join(
                    char for char in str(key).lower() if char.isalnum()
                )
                if (
                    "provider" in normalized_key
                    and "validat" in normalized_key
                    and child not in (
                    False,
                    None,
                    "",
                    )
                ):
                    return True
                if claims_provider_validation(child):
                    return True
            return False
        if isinstance(value, list):
            return any(claims_provider_validation(child) for child in value)
        if isinstance(value, str):
            normalized = "".join(char for char in value.lower() if char.isalnum())
            return "provider" in normalized and "validat" in normalized
        return False

    if claims_provider_validation(component):
        raise ValueError(f"{LOCAL_E2E_FILENAME} claims provider validation")
    components = component.get("components")
    if set(component) != set(expected) | {"components"}:
        raise ValueError(f"{LOCAL_E2E_FILENAME} has unexpected fields")
    if not isinstance(components, dict):
        raise ValueError(f"{LOCAL_E2E_FILENAME} is missing component results")
    required_components = {
        "image_runner", "video_runner", "five_station_authorization",
        "provider_request_counts",
    }
    if set(components) != required_components:
        raise ValueError(f"{LOCAL_E2E_FILENAME} has incomplete component results")
    image = components.get("image_runner")
    video = components.get("video_runner")
    stations = components.get("five_station_authorization")
    counts = components.get("provider_request_counts")
    if not all(isinstance(value, dict) for value in (image, video, stations, counts)):
        raise ValueError(f"{LOCAL_E2E_FILENAME} component results must be objects")
    if set(image) != {"character_count", "canonical_count", "request_count"}:
        raise ValueError(f"{LOCAL_E2E_FILENAME} image component has unexpected fields")
    if set(video) != {
        "submission_count", "request_count", "poll_completed",
        "callback_process", "zero_network_resume",
    }:
        raise ValueError(f"{LOCAL_E2E_FILENAME} video component has unexpected fields")
    if set(stations) != {"station_count", "worker_receive_count"}:
        raise ValueError(f"{LOCAL_E2E_FILENAME} station component has unexpected fields")
    image_count = image.get("character_count")
    if (
        type(image_count) is not int
        or image_count <= 0
        or image.get("canonical_count") != image_count
        or image.get("request_count") != image_count
    ):
        raise ValueError(f"{LOCAL_E2E_FILENAME} image component is incomplete")
    if (
        video.get("submission_count") != 1
        or video.get("request_count") != 1
        or video.get("poll_completed") is not True
        or video.get("callback_process") is not True
        or video.get("zero_network_resume") is not True
    ):
        raise ValueError(f"{LOCAL_E2E_FILENAME} video component is incomplete")
    if (
        stations.get("station_count") != 5
        or stations.get("worker_receive_count") != 5
    ):
        raise ValueError(f"{LOCAL_E2E_FILENAME} station component is incomplete")
    expected_counts = {
        "image_generate": image_count,
        "asset_upload": 2,
        "asset_poll": 2,
        "video_create": 1,
        "video_poll": 2,
        "video_download": 1,
        "callback_fetch": 2,
    }
    if counts != expected_counts:
        raise ValueError(f"{LOCAL_E2E_FILENAME} request counts differ from the contract")


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
            steps = [step for step in completed_steps.splitlines() if step]
            if status == "passed" and "local_drama_e2e" not in steps:
                raise ValueError("passed canonical acceptance requires local_drama_e2e")
            if status == "passed":
                _validate_local_e2e_evidence(
                    harness_fd,
                    run_id=run_id,
                    git_head=payload["git_head"],
                    git_tree=payload["git_tree"],
                )
            payload.update(
                {
                    "status": status,
                    "exit_code": exit_code,
                    "test_count": test_count,
                    "completed_at": _utc_now(),
                    "duration_seconds": max(0, duration_seconds),
                    "completed_steps": steps,
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
