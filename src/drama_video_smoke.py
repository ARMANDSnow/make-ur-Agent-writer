"""Bounded mock/real smoke for the episode-1 video job."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Dict

from . import drama_smoke, drama_store, drama_video, paths
from .drama_schemas import CharacterSheet, character_paths
from .schemas import model_to_dict
from .utils import read_json_optional, write_json
from .web import jobs
from .web.workspace_ctx import use_workspace
from .workspace_lock import acquire_write_lock


REAL_CONFIRMATION = "可以跑真实视频 smoke"
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _wait(job_id: str, timeout_seconds: float) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        record = jobs.get_job(job_id)
        if record and record.get("status") in jobs.TERMINAL_STATUSES:
            return record
        time.sleep(0.05)
    jobs.request_cancel(job_id, "video smoke timeout; no automatic retry")
    raise TimeoutError("video smoke timed out; the paid request was not retried")


def _prepare_mock_inputs(workspace: str) -> None:
    drama_smoke.run_smoke(workspace, real_text=False, real_image=False, timeout_seconds=30)
    with use_workspace(workspace):
        with acquire_write_lock(source="drama-video-smoke-prepare"):
            sheet_path = character_paths(workspace).sheet_path
            raw = read_json_optional(sheet_path, None)
            sheet = CharacterSheet(**raw)
            payload = model_to_dict(sheet)
            root = paths.workspace_root(workspace)
            for character in payload["characters"]:
                cid = character["id"]
                rel = f"data/character_refs/{cid}/portrait_neutral.png"
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(_PNG_1X1)
                character["reference_images"] = [{
                    "path": rel,
                    "generated_by": "mock-video-smoke",
                    "prompt": "原创角色参考图占位",
                    "requested_model": "mock",
                    "requested_size": "1x1",
                    "provider_size": "1x1",
                    "width": 1,
                    "height": 1,
                }]
            drama_store.migrate_fresh_episode_fingerprints_v2(workspace)
            write_json(sheet_path, payload)
            drama_store.assemble_episode(workspace, episode_no=1)


def run_smoke(
    workspace: str,
    *,
    real_video: bool = False,
    confirm_real_video: bool = False,
    budget_cny: float = 0.0,
    timeout_seconds: float = 300.0,
    prepare_inputs: bool = True,
    reset_jobs: bool = True,
) -> Dict[str, Any]:
    if not math.isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 3600:
        raise SystemExit("timeout-seconds must be finite and between 1 and 3600")
    if not math.isfinite(budget_cny) or budget_cny < 0:
        raise SystemExit("budget-cny must be finite and non-negative")
    if real_video:
        if not confirm_real_video or os.getenv("CONFIRM_REAL_VIDEO_SMOKE") != REAL_CONFIRMATION:
            raise SystemExit("refusing real video smoke without CLI and shell confirmation")
        if budget_cny <= 0:
            raise SystemExit("real video smoke requires a finite positive budget")
        os.environ["SD_VIDEO_MODE"] = "real"
        # Do not prepare text/image artifacts: that would expand video consent.
        drama_video.load_video_inputs(workspace, episode_no=1)
    else:
        os.environ["SD_VIDEO_MODE"] = "mock"
        if prepare_inputs:
            _prepare_mock_inputs(workspace)
    if reset_jobs:
        jobs.reset_for_tests()
    params: Dict[str, Any] = {"episode_no": 1}
    if real_video:
        params.update({
            "confirm_real_video": True,
            "budget_cny": budget_cny,
            "timeout_minutes": timeout_seconds / 60.0,
        })
    started_at = time.monotonic()
    started = jobs.start_job(workspace, "drama-video", params)
    terminal = _wait(started["job_id"], timeout_seconds)
    if terminal.get("status") not in {"succeeded", "budget_exceeded"}:
        raise RuntimeError(f"video job did not succeed: {terminal.get('status')}")
    data, meta = drama_video.read_video(workspace, episode_no=1)
    summary = terminal.get("result_summary") or {}
    result = {
        "ok": True,
        "workspace": workspace,
        "real_video": real_video,
        "job_id": started["job_id"],
        "task_id": meta.get("task_id"),
        "status": terminal.get("status"),
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
        "cost_cny": meta.get("cost_cny"),
        "budget_cny": meta.get("budget_cny"),
        "file_size_bytes": len(data),
        "duration_seconds": meta.get("duration_seconds"),
        "ratio": meta.get("ratio"),
        "resolution": meta.get("resolution"),
        "network_requests": summary.get("network_requests", 0 if not real_video else None),
        "automatic_retries": 0,
    }
    log = paths.workspace_root(workspace) / "logs" / f"drama_video_smoke_{int(time.time())}.json"
    write_json(log, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", required=True)
    parser.add_argument("--real-video", action="store_true")
    parser.add_argument("--confirm-real-video", action="store_true")
    parser.add_argument("--budget-cny", type=float, default=0.0)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    args = parser.parse_args()
    try:
        result = run_smoke(
            args.book,
            real_video=args.real_video,
            confirm_real_video=args.confirm_real_video,
            budget_cny=args.budget_cny,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        safe = {
            "ok": False,
            "workspace": args.book,
            "real_video": args.real_video,
            "error_code": "drama_video_timeout" if isinstance(exc, TimeoutError) else "drama_video_smoke_failed",
            "automatic_retries": 0,
        }
        print(json.dumps(safe, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
