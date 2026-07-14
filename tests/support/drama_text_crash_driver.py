#!/usr/bin/env python3
"""Test-only text-station fixtures and a real ``os._exit`` crash driver."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CRASH_EXIT = 86
IMPORT_NONCE = secrets.token_hex(16)
TEXT_STATIONS = (
    "drama-plan",
    "drama-hooks",
    "drama-storyboard",
    "drama-characters",
    "drama-review-assemble",
)
MODEL_CONFIG = {
    "model": "test-provider/text-model",
    "base_url": "https://text-provider.invalid/v1",
    "api_key": "synthetic-test-token",
}


def configure_workspace_root(root: Path) -> Path:
    from src import paths

    resolved = root.resolve(strict=True)
    paths.WORKSPACE_DIR = resolved
    return resolved


def prepare_workspace(root: Path, workspace: str) -> None:
    from src import paths
    from src.drama_schemas import character_paths, episode_paths
    from src.utils import write_json

    configure_workspace_root(root)
    workspace_root = paths.workspace_root(workspace)
    data = workspace_root / "data"
    data.mkdir(parents=True, exist_ok=True)
    write_json(data / "wizard_input.json", {
        "workspace": workspace,
        "topic": "synthetic crash matrix",
        "track": "test",
        "episode_count": 1,
        "episode_duration_seconds": 60,
        "schema_version": 1,
    })
    (data / "creation_standard.snapshot.md").write_text(
        "synthetic matrix standard\n", encoding="utf-8"
    )
    episode = episode_paths(workspace, episode_no=1)
    write_json(episode.setup_path, {
        "episode_no": 1,
        "title": "synthetic setup",
        "hook": {"type": "test", "content": "synthetic hook"},
    })
    write_json(episode.storyboard_path, {
        "episode_no": 1,
        "shots": [{"shot_id": "s001", "content": "synthetic shot"}],
    })
    write_json(character_paths(workspace).sheet_path, {
        "schema_version": 1,
        "characters": [{"id": "c001", "name": "synthetic character"}],
    })


def station_result(step: str) -> dict[str, Any]:
    results: dict[str, dict[str, Any]] = {
        "drama-plan": {"episode_no": 1, "title": "matrix plan"},
        "drama-hooks": {
            "hooks": [{"type": "test", "content": "matrix candidate"}],
        },
        "drama-storyboard": {
            "episode_no": 1,
            "shots": [{"shot_id": "s001", "content": "matrix board"}],
        },
        "drama-characters": {
            "schema_version": 1,
            "characters": [{"id": "c001", "name": "matrix character"}],
        },
        "drama-review-assemble": {
            "approved": True,
            "issues": [],
            "summary": "matrix review",
        },
    }
    return json.loads(json.dumps(results[step]))


def bind_and_write_canonical(
    workspace: str,
    step: str,
    token: tuple[str, dict[str, Any]],
    result: dict[str, Any],
) -> None:
    from src.drama_schemas import character_paths, episode_paths
    from src.utils import write_json
    from src.web import jobs

    candidates = result["hooks"] if step == "drama-hooks" else None
    jobs._bind_drama_text_artifact(token, result, candidates=candidates)
    episode = episode_paths(workspace, episode_no=1)
    paths = {
        "drama-plan": episode.setup_path,
        "drama-hooks": episode.hook_candidates_path,
        "drama-storyboard": episode.storyboard_path,
        "drama-characters": character_paths(workspace).sheet_path,
        "drama-review-assemble": episode.review_path,
    }
    write_json(paths[step], result)


def mutate_station_input(workspace: str, step: str) -> None:
    from src import paths
    from src.drama_schemas import episode_paths
    from src.utils import read_json, write_json

    if step == "drama-plan":
        path = paths.workspace_root(workspace) / "data" / "wizard_input.json"
        payload = read_json(path)
        payload["topic"] = "drifted synthetic topic"
    else:
        path = episode_paths(workspace, episode_no=1).setup_path
        payload = read_json(path)
        payload["title"] = "drifted synthetic setup"
    write_json(path, payload)


def _write_marker(path: Path, **payload: Any) -> None:
    from src.utils import write_json

    write_json(path, {
        "pid": os.getpid(),
        "import_nonce": IMPORT_NONCE,
        **payload,
    })


def _provider_nonce(path: Path) -> dict[str, Any]:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, (IMPORT_NONCE + "\n").encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return {"unexpected": "provider called"}


def _crash(args: argparse.Namespace) -> None:
    from src.web import jobs
    from src.web.workspace_ctx import use_workspace

    prepare_workspace(args.workspace_root, args.workspace)
    with use_workspace(args.workspace), patch(
        "src.config.get_model_config", return_value=MODEL_CONFIG
    ):
        token = jobs._begin_drama_text_attempt(args.step, {}, 1)
        if token is None:
            raise AssertionError("real-text attempt was not created")
        ledger = jobs._load_drama_text_attempts(args.workspace)
        status = ledger["attempts"][f"{args.step}:1"]["status"]
        if status != "submitting":
            raise AssertionError("submitting state was not durable before crash")
        _write_marker(args.marker, step=args.step, durable_status=status)
        os._exit(CRASH_EXIT)


def _resume(args: argparse.Namespace) -> None:
    from src.web import jobs
    from src.web.workspace_ctx import use_workspace

    configure_workspace_root(args.workspace_root)
    error = None
    with use_workspace(args.workspace), patch(
        "src.config.get_model_config", return_value=MODEL_CONFIG
    ):
        try:
            jobs._call_drama_text_model(
                args.step,
                {},
                1,
                lambda: _provider_nonce(args.provider_nonce),
            )
        except ValueError as exc:
            error = str(exc)
        ledger = jobs._load_drama_text_attempts(args.workspace)
    if error is None or "reconciliation" not in error:
        raise AssertionError("fresh process did not fail closed on submitting state")
    _write_marker(
        args.marker,
        step=args.step,
        durable_status=ledger["attempts"][f"{args.step}:1"]["status"],
        provider_called=args.provider_nonce.exists(),
        reconciliation_required=True,
    )


def main() -> int:
    os.environ["DRAGON_RAJA_SKIP_DOTENV"] = "1"
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["OPENAI_MODEL"] = "mock"
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("crash", "resume"))
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--step", choices=TEXT_STATIONS, required=True)
    parser.add_argument("--marker", type=Path, required=True)
    parser.add_argument("--provider-nonce", type=Path, required=True)
    args = parser.parse_args()
    root_marker = args.workspace_root / ".dragon-raja-text-crash-matrix"
    if not root_marker.is_file() or root_marker.is_symlink():
        raise ValueError("unsafe text crash-matrix workspace root")
    if args.mode == "crash":
        _crash(args)
    else:
        _resume(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
