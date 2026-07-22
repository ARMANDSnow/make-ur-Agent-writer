#!/usr/bin/env python3
"""Run the deterministic loopback short-drama component acceptance.

This harness is intentionally test-scoped: production URL/peer guards remain
unchanged.  Only this process patches them after binding both local servers to
127.0.0.1 random ports.  No external network or real provider is reachable.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Pin offline configuration before importing any project module.
os.environ["DRAGON_RAJA_SKIP_DOTENV"] = "1"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["OPENAI_MODEL"] = "mock"
os.environ["DRAMA_MODEL"] = "mock"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"
for _secret_name in (
    "OPENAI_API_KEY", "PLANNER_API_KEY", "AI_DRAW_API_KEY", "SD_API_KEY",
    "AI_DRAW_ENDPOINT", "AI_DRAW_BASE_URL", "OPENAI_BASE_URL",
    "SD_API_BASE_URL", "SD_ASSET_PUBLIC_BASE_URL",
):
    os.environ.pop(_secret_name, None)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Replace one ordinary, single-link JSON file without following it."""

    parent = path.parent
    if parent.is_symlink():
        raise ValueError("local E2E evidence parent must not be a symlink")
    parent.mkdir(parents=True, exist_ok=True)
    temporary = parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", closefd=True) as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or path.is_symlink():
        raise ValueError("local E2E evidence must be an ordinary single-link file")


def _identity(value: str, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40,64}", value) is None:
        raise ValueError(f"{label} must be a lowercase git object id")
    return value


def _workspace_root(value: str) -> Path:
    root = Path(value)
    marker = root / ".dragon-raja-local-e2e"
    if root.is_symlink() or not root.is_dir():
        raise ValueError("local E2E workspace root must be an existing ordinary directory")
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_nlink != 1:
        raise ValueError("local E2E workspace marker is missing or unsafe")
    return root.resolve(strict=True)


def _permissive_loopback_url(value: str, *, label: str, allow_http: bool = False):
    del label, allow_http
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname != "127.0.0.1"
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("test injection accepts only exact loopback URLs")
    return parsed


def _loopback_peer(host: str | None) -> None:
    if host != "127.0.0.1":
        raise ValueError("test injection rejected a non-loopback peer")


@contextmanager
def _callback_process(workspace_root: Path) -> Iterator[int]:
    ready_file = workspace_root / f".callback-ready-{secrets.token_hex(6)}.json"
    callback = ROOT / "tests" / "support" / "local_drama_callback.py"
    child_env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "DRAGON_RAJA_SKIP_DOTENV": "1",
        "PYTHON_DOTENV_DISABLED": "1",
        "OPENAI_MODEL": "mock",
        "DRAMA_MODEL": "mock",
        "LITELLM_LOCAL_MODEL_COST_MAP": "true",
        "NO_PROXY": "127.0.0.1",
    }
    process = subprocess.Popen(
        [
            sys.executable, str(callback),
            "--workspace-root", str(workspace_root),
            "--ready-file", str(ready_file),
        ],
        cwd=ROOT,
        env=child_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    try:
        deadline = time.monotonic() + 10
        port = 0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("independent callback process exited before readiness")
            try:
                ready = json.loads(ready_file.read_text(encoding="utf-8"))
                port = int(ready.get("port"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                time.sleep(0.02)
                continue
            if 1 <= port <= 65535:
                break
        if not port:
            raise RuntimeError("independent callback process did not become ready")
        yield port
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        ready_file.unlink(missing_ok=True)


def _run_image_chain(provider_base: str) -> dict[str, Any]:
    from src import ai_draw_client
    from src import drama_multimodal_smoke as multimodal
    from src import paths
    from src.drama_schemas import CharacterSheet, character_paths
    from src.utils import read_json_optional

    env = {
        "AI_DRAW_ENDPOINT": "",
        "AI_DRAW_BASE_URL": provider_base + "/v1",
        "AI_DRAW_API_KEY": "local-image-test-token",
        "AI_DRAW_MODEL": "local-openai-image-adapter",
    }
    options = {
        "confirm_real_image": True,
        "image_budget_cny": 10.0,
        "image_estimated_cost_cny": 1.0,
        "image_timeout_seconds": 30.0,
    }
    with (
        patch.dict(os.environ, env, clear=False),
        patch.object(ai_draw_client, "validate_api_base_url", _permissive_loopback_url),
        patch.object(ai_draw_client, "_validate_public_endpoint", _loopback_peer),
        patch.object(multimodal, "validate_api_base_url", _permissive_loopback_url),
        patch.object(multimodal, "_validate_public_endpoint", _loopback_peer),
        patch.object(multimodal.drama_smoke, "real_text_tasks_ready", return_value=True),
    ):
        # Build the five text stations with deterministic mock generators, but
        # stop at the media authorization boundary.  Calling the all-mock
        # multimodal path would also commit mock images and intentionally make
        # a later paid-image upgrade fail closed.
        with patch.dict(os.environ, {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了"}, clear=False):
            prepared = multimodal.run(
                "local-image-e2e",
                real_text=True,
                options={
                    "confirm_real_text": True,
                    "text_budget_cny": 5.0,
                    "text_timeout_seconds": 30.0,
                },
            )
        if prepared.get("status") != "awaiting_image_authorization":
            raise AssertionError("mock text preparation did not stop before media")
        state = multimodal.run(
            "local-image-e2e", real_image=True, options=options
        )
    if state.get("status") != "awaiting_video_authorization":
        raise AssertionError("image runner did not reach the expected durable handoff")
    durable = read_json_optional(multimodal.state_path("local-image-e2e"), None)
    if not isinstance(durable, dict):
        raise AssertionError("image runner durable state is missing")
    rows = durable.get("image_attempts") or {}
    sheet = CharacterSheet(**read_json_optional(character_paths("local-image-e2e").sheet_path, None))
    character_ids = [item.id for item in sheet.characters if 1 in (item.appearances or [1])]
    if not character_ids or set(character_ids) != set(rows):
        raise AssertionError("image attempts do not cover the episode cast")
    character_rows = {
        str(item.get("id") or ""): item
        for item in multimodal.model_to_dict(sheet).get("characters", [])
    }
    for character_id in character_ids:
        attempts = rows[character_id]
        if len(attempts) != 1:
            raise AssertionError("local image provider must be called once per character")
        row = attempts[0]
        required = {
            "status", "staging_path", "artifact_path", "artifact_sha256",
            "artifact_record", "artifact_record_sha256",
        }
        if row.get("status") != "succeeded" or not required.issubset(row):
            raise AssertionError("image staging/receipt/canonical chain is incomplete")
        staging = paths.workspace_root("local-image-e2e") / row["staging_path"]
        canonical = paths.workspace_root("local-image-e2e") / row["artifact_path"]
        if staging.exists() or not canonical.is_file():
            raise AssertionError("image staging was not promoted and cleaned")
        data = canonical.read_bytes()
        ai_draw_client._detect_image_type(data)
        if hashlib.sha256(data).hexdigest() != row["artifact_sha256"]:
            raise AssertionError("canonical image hash differs from its durable receipt")
        if multimodal._canonical_sha256(row["artifact_record"]) != row["artifact_record_sha256"]:
            raise AssertionError("image record hash differs from its durable receipt")
        refs = character_rows.get(character_id, {}).get("reference_images") or []
        if len(refs) != 1 or multimodal._canonical_sha256(refs[0]) != row["artifact_record_sha256"]:
            raise AssertionError("character reference projection differs from the paid receipt")
        if not multimodal._completed_image_is_current(
            "local-image-e2e", character_rows[character_id], attempts
        ):
            raise AssertionError("durable image state is not current after canonical promote")
    return {"character_count": len(character_ids), "canonical_count": len(character_ids)}


def _run_video_chain(
    provider_base: str,
    workspace_root: Path,
    authorize_callback: Any,
) -> dict[str, Any]:
    from src import ai_draw_client, drama_video, drama_video_client, drama_video_smoke
    from src.utils import read_json

    drama_video_smoke._prepare_mock_inputs("local-video-e2e")
    with _callback_process(workspace_root) as callback_port:
        authorize_callback(callback_port)
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_API_BASE_URL": provider_base,
            "SD_API_KEY": "local-video-test-token",
            "SD_VIDEO_ESTIMATED_COST_CNY": "0.25",
            "SD_VIDEO_RESULT_HOSTS": "127.0.0.1",
            "SD_VIDEO_MODEL": drama_video.DEFAULT_VIDEO_MODEL,
            "SD_ASSET_PUBLIC_BASE_URL": f"https://127.0.0.1:{callback_port}",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(ai_draw_client, "_validate_public_endpoint", _loopback_peer),
            patch.object(drama_video_client, "_validate_public_endpoint", _loopback_peer),
            patch.object(drama_video, "_validate_public_endpoint", _loopback_peer),
            patch.object(drama_video_client, "validate_api_base_url", _permissive_loopback_url),
            patch.object(drama_video, "validate_api_base_url", _permissive_loopback_url),
            patch.object(http.client, "HTTPSConnection", http.client.HTTPConnection),
            patch.object(drama_video, "POLL_INTERVAL_SECONDS", 0.0),
        ):
            result = drama_video.run_video_job(
                "local-video-e2e",
                {"confirm_real_video": True, "budget_cny": 1.0, "timeout_minutes": 1.0},
                lambda *_args: None,
                sleep=lambda _seconds: None,
            )
            resumed = drama_video.run_video_job(
                "local-video-e2e",
                {"confirm_real_video": True, "budget_cny": 1.0, "timeout_minutes": 1.0},
                lambda *_args: None,
                sleep=lambda _seconds: None,
            )
    if result.get("status") != "succeeded" or result.get("committed") is not True:
        raise AssertionError("local video chain did not commit")
    if resumed.get("resumed") is not True or resumed.get("network_requests") != 0:
        raise AssertionError("successful video did not resume with zero provider requests")
    data, meta = drama_video.read_video("local-video-e2e")
    spec = drama_video._probe_mp4(data)
    if (spec.duration_seconds, spec.width, spec.height) != (5.0, 720, 1280):
        raise AssertionError("committed video does not match the strict local contract")
    ledger = read_json(drama_video.video_submission_path("local-video-e2e"))
    if ledger.get("status") != "succeeded" or ledger.get("submission_count") != 1:
        raise AssertionError("video durable ledger did not close exactly one submission")
    rendered = json.dumps({"meta": meta, "ledger": ledger}, sort_keys=True).lower()
    if any(token in rendered for token in ("signature=", "authorization:", "bearer ")):
        raise AssertionError("video evidence retained a sensitive transport value")
    return {
        "submission_count": 1,
        "poll_completed": True,
        "callback_process": True,
        "zero_network_resume": True,
    }


def _wait_job(job_id: str) -> dict[str, Any]:
    from src.web import jobs

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        row = jobs.get_job(job_id)
        if row and row.get("status") in jobs.TERMINAL_STATUSES:
            return row
        time.sleep(0.01)
    raise TimeoutError("local route worker did not finish")


def _run_five_station_closure() -> dict[str, Any]:
    from src.web import jobs, routes, static

    stations = {
        "drama-plan": "plan",
        "drama-hooks": "hooks",
        "drama-storyboard": "storyboard",
        "drama-characters": "characters",
        "drama-review-assemble": "review",
    }
    frontend = static.JS_DASHBOARD
    helper_start = frontend.index("async function dramaGenerationPayload(")
    helper_end = frontend.index("\n  async function ", helper_start + 1)
    helper = frontend[helper_start:helper_end]
    frontend_assignments = {
        "confirm_real_text": "out.confirm_real_text = true;",
        "budget_cny": "out.budget_cny = authorization.budget_cny;",
        "timeout_minutes": "out.timeout_minutes = authorization.timeout_minutes;",
        "confirm_text_retry": "out.confirm_text_retry = true;",
        "confirm_upstream_status_and_billing_checked": (
            "out.confirm_upstream_status_and_billing_checked = true;"
        ),
    }
    for field, assignment in frontend_assignments.items():
        if assignment not in helper:
            raise AssertionError(f"emitted frontend helper omits the exact {field} assignment")
    for step in stations:
        if re.search(rf'dramaGenerationPayload\(\s*"{re.escape(step)}"', frontend) is None:
            raise AssertionError(f"frontend does not construct authorization for {step}")
    received: list[tuple[str, dict[str, Any]]] = []
    mutation_headers = {
        "content-type": "application/json",
        "x-drama-mutation-intent": "mutate-v1",
    }

    def real_config(_task: str) -> dict[str, str]:
        return {"model": "local/contract-only"}

    jobs.reset_for_tests()
    original = dict(jobs.STEP_HANDLERS)
    try:
        for step, suffix in stations.items():
            def handler(params: dict[str, Any], _progress: Any, *, expected: str = step):
                received.append((expected, dict(params)))
                return {"status": "succeeded", "step": expected}

            jobs.STEP_HANDLERS[step] = handler
            payload = {
                "episode_no": 1,
                "confirm_real_text": True,
                "budget_cny": 3.0,
                "timeout_minutes": 1.0,
            }
            with patch.object(routes, "get_model_config", side_effect=real_config):
                status, _content_type, body = routes.dispatch(
                    "POST",
                    f"/api/workspace/local-image-e2e/drama/{suffix}",
                    json.dumps(payload).encode("utf-8"),
                    mutation_headers,
                )[:3]
                if status != 202:
                    raise AssertionError(f"route rejected one-shot authorization for {step}")
                terminal = _wait_job(json.loads(body)["job_id"])
                if terminal.get("status") != "succeeded":
                    raise AssertionError(f"worker did not accept normalized params for {step}")
                for projection in (
                    jobs.public_job_view(terminal),
                    jobs.public_job_summary_view(terminal),
                    jobs.public_job_detail_view(terminal),
                ):
                    projected_params = projection.get("params") or {}
                    if any(str(key).startswith("confirm_") for key in projected_params):
                        raise AssertionError("one-shot authorization leaked into a public job view")
                denied = routes.dispatch(
                    "POST",
                    f"/api/workspace/local-image-e2e/drama/{suffix}",
                    b'{"episode_no":1}',
                    mutation_headers,
                )
                if denied[0] != 400:
                    raise AssertionError(f"authorization leaked into the next {step} request")
    finally:
        jobs.STEP_HANDLERS.clear()
        jobs.STEP_HANDLERS.update(original)
        jobs.reset_for_tests()
    if len(received) != len(stations):
        raise AssertionError("not all five station workers received params")
    for _step, params in received:
        if params != {
            "episode_no": 1,
            "confirm_real_text": True,
            "budget_cny": 3.0,
            "timeout_minutes": 1.0,
        }:
            raise AssertionError("route changed the one-shot authorization closure")
    return {"station_count": len(stations), "worker_receive_count": len(received)}


def run(args: argparse.Namespace) -> dict[str, Any]:
    from src import paths
    from tests.support.local_drama_provider import LocalDramaProvider

    root = _workspace_root(args.workspace_root)
    paths.WORKSPACE_DIR = root
    with LocalDramaProvider() as provider:
        image = _run_image_chain(provider.base_url)
        video = _run_video_chain(provider.base_url, root, provider.authorize_callback)
        stations = _run_five_station_closure()
        counts = provider.counters()
    expected = {
        "image_generate": image["character_count"],
        "asset_upload": 2,
        "asset_poll": 2,
        "video_create": 1,
        "video_poll": 2,
        "video_download": 1,
        "callback_fetch": 2,
    }
    if counts != expected:
        raise AssertionError("loopback request counts differ from the deterministic contract")
    return {
        "image_runner": {**image, "request_count": counts["image_generate"]},
        "video_runner": {**video, "request_count": counts["video_create"]},
        "five_station_authorization": stations,
        "provider_request_counts": counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--evidence-path", required=True)
    parser.add_argument("--git-head", required=True)
    parser.add_argument("--git-tree", required=True)
    args = parser.parse_args()
    evidence_path = Path(args.evidence_path)
    base = {
        "schema_version": 1,
        "acceptance_level": "local-e2e",
        "verification_profile": "loopback-fake-provider",
        "acceptance_run_id": str(args.run_id),
        "git_head": _identity(args.git_head, "git_head"),
        "git_tree": _identity(args.git_tree, "git_tree"),
        "provider_validated": False,
    }
    _atomic_json(evidence_path, {**base, "status": "running"})
    try:
        components = run(args)
    except BaseException as exc:
        _atomic_json(evidence_path, {
            **base,
            "status": "failed",
            "error_code": type(exc).__name__,
        })
        return 1
    final = {**base, "status": "passed", "components": components}
    _atomic_json(evidence_path, final)
    print(json.dumps({
        "status": "passed",
        "acceptance_level": "local-e2e",
        "provider_validated": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
