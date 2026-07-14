#!/usr/bin/env python3
"""Test-only cross-process crash/restart driver for paid drama recovery.

The parent test launches this file with a minimal environment.  Crash modes
persist a marker and then call ``os._exit(86)`` so no Python exception handler,
``finally`` block, or in-memory module state can participate in recovery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# This nonce is deliberately created at module import.  Different values in
# crash and resume markers prove that a fresh interpreter imported the driver.
IMPORT_NONCE = secrets.token_hex(16)
CRASH_EXIT = 86
PROVIDER_FINGERPRINT = "f" * 64
WORKSPACE = "crash-matrix"

os.environ["DRAGON_RAJA_SKIP_DOTENV"] = "1"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["OPENAI_MODEL"] = "mock"
os.environ["DRAMA_MODEL"] = "mock"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"
for _name in (
    "OPENAI_API_KEY", "PLANNER_API_KEY", "AI_DRAW_API_KEY", "AI_DRAW_ENDPOINT",
    "AI_DRAW_BASE_URL", "OPENAI_BASE_URL", "SD_API_KEY", "SD_API_BASE_URL",
    "SD_ASSET_PUBLIC_BASE_URL",
):
    os.environ.pop(_name, None)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)


def _marker(path: Path, scenario: str, **facts: Any) -> None:
    _atomic_json(path, {
        "scenario": scenario,
        "pid": os.getpid(),
        "import_nonce": IMPORT_NONCE,
        **facts,
    })


def _event(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (name + "\n").encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)


def _event_count(path: Path, name: str) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="ascii").splitlines() if line == name)


def _configure_root(value: str) -> Path:
    from src import paths

    root = Path(value).resolve(strict=True)
    marker = root / ".dragon-raja-crash-matrix"
    if root.is_symlink() or not root.is_dir() or marker.is_symlink() or not marker.is_file():
        raise ValueError("unsafe crash-matrix workspace root")
    paths.WORKSPACE_DIR = root
    return root


def _prepare_image(workspace: str = WORKSPACE) -> None:
    from src import drama_multimodal_smoke as multi
    from src import drama_video_smoke
    from src.drama_schemas import CharacterSheet, character_paths
    from src.schemas import model_to_dict
    from src.utils import read_json, write_json

    drama_video_smoke._prepare_mock_inputs(workspace)
    sheet_path = character_paths(workspace).sheet_path
    payload = model_to_dict(CharacterSheet(**read_json(sheet_path)))
    payload["characters"] = payload["characters"][:1]
    payload["characters"][0]["reference_images"] = []
    payload["characters"][0]["visual_contrast_with"] = {}
    write_json(sheet_path, payload)
    state = multi._new_state(workspace)
    multi._save(state)


def _image_options() -> dict[str, Any]:
    return {
        "confirm_real_image": True,
        "image_budget_cny": 10.0,
        "image_estimated_cost_cny": 1.0,
        "image_timeout_seconds": 30.0,
    }


def _successful_image_draw(events: Path):
    def draw(workspace: str, _character: Any, **kwargs: Any) -> dict[str, Any]:
        from src import drama_multimodal_smoke as multi

        _event(events, "image_generate")
        target = kwargs["output_path"]
        multi._atomic_write_bytes(target, multi._PNG_1X1)
        return {
            "path": str(target.relative_to(multi.paths.workspace_root(workspace))),
            "generated_by": "local-crash-matrix",
            "prompt": "<local-test>",
            "requested_model": "local-test-image",
            "requested_size": multi.DEFAULT_IMAGE_SIZE,
            "width": 1,
            "height": 1,
        }

    return draw


def _crash_image(marker_path: Path, events: Path) -> None:
    from src import drama_multimodal_smoke as multi

    state = multi.load_state(WORKSPACE)
    if state is None:
        raise AssertionError("image state is missing")
    original = multi._replace_character_reference

    def die_after_projection(workspace: str, character_id: str, generated: dict[str, Any]) -> None:
        original(workspace, character_id, generated)
        durable = multi.load_state(workspace)
        _cid, rows = next(iter(durable["image_attempts"].items()))
        attempt = rows[-1]
        canonical = multi.paths.workspace_root(workspace) / str(attempt["artifact_path"])
        _marker(
            marker_path,
            "image-crash-after-canonical-projection",
            durable_status=attempt["status"],
            canonical_exists=canonical.is_file(),
            staging_exists=(multi.paths.workspace_root(workspace) / attempt["staging_path"]).is_file(),
        )
        os._exit(CRASH_EXIT)

    with (
        patch.object(multi, "_image_provider_fingerprint", return_value=PROVIDER_FINGERPRINT),
        patch.object(multi, "redraw_character_reference", _successful_image_draw(events)),
        patch.object(multi, "_replace_character_reference", die_after_projection),
    ):
        multi._run_images(WORKSPACE, state, _image_options(), real_image=True)
    raise AssertionError("image crash seam did not exit")


def _resume_image(marker_path: Path, events: Path) -> None:
    from src import drama_multimodal_smoke as multi
    from src.drama_schemas import character_paths
    from src.utils import read_json

    state = multi.load_state(WORKSPACE)
    if state is None:
        raise AssertionError("image state is missing")

    def forbidden_provider(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        _event(events, "image_generate")
        raise AssertionError("paid image provider was called during receipt recovery")

    with (
        patch.object(multi, "_image_provider_fingerprint", return_value=PROVIDER_FINGERPRINT),
        patch.object(multi, "redraw_character_reference", forbidden_provider),
    ):
        completed = multi._run_images(WORKSPACE, state, _image_options(), real_image=True)
    if not completed:
        raise AssertionError("image receipt recovery did not complete")
    persisted = multi.load_state(WORKSPACE)
    cid, rows = next(iter(persisted["image_attempts"].items()))
    attempt = rows[-1]
    root = multi.paths.workspace_root(WORKSPACE)
    sheet = read_json(character_paths(WORKSPACE).sheet_path)
    reference = sheet["characters"][0]["reference_images"][0]
    canonical = root / attempt["artifact_path"]
    _marker(
        marker_path,
        "image-resume",
        durable_status=attempt["status"],
        phase_status=persisted["phases"]["all_character_images"]["status"],
        canonical_sha256=hashlib.sha256(canonical.read_bytes()).hexdigest(),
        receipt_sha256=attempt["artifact_sha256"],
        projection_sha256=multi._canonical_sha256(reference),
        record_sha256=attempt["artifact_record_sha256"],
        staging_exists=(root / attempt["staging_path"]).exists(),
        character_id=cid,
    )


IMAGE_STAGES = (
    "not_sent",
    "submission_unknown",
    "response_received",
    "staging_written",
    "receipt_written",
    "canonical_promoted",
)


class _ImageCrashSeam(BaseException):
    """Leave the audit written by _run_images without local exception recovery."""


def _seed_started_image(
    workspace: str,
    events: Path,
    *,
    write_staging: bool,
    response_received: bool = False,
) -> None:
    from src import drama_multimodal_smoke as multi

    state = multi.load_state(workspace)
    if state is None:
        raise AssertionError("image state is missing")

    def stop_after_request(_workspace: str, _character: Any, **kwargs: Any) -> dict[str, Any]:
        _event(events, "image_generate")
        if response_received:
            _event(events, "image_response_received")
        if write_staging:
            multi._atomic_write_bytes(kwargs["output_path"], multi._PNG_1X1)
        raise _ImageCrashSeam()

    try:
        with (
            patch.object(multi, "_image_provider_fingerprint", return_value=PROVIDER_FINGERPRINT),
            patch.object(multi, "redraw_character_reference", stop_after_request),
        ):
            multi._run_images(workspace, state, _image_options(), real_image=True)
    except _ImageCrashSeam:
        pass
    else:
        raise AssertionError("image crash seam did not interrupt the production entry")


def _advance_image_seed(workspace: str, stage: str, events: Path) -> None:
    from src import drama_multimodal_smoke as multi
    from src.drama_schemas import CharacterSheet, character_paths
    from src.utils import read_json

    if stage in {"submission_unknown", "response_received"}:
        _seed_started_image(
            workspace,
            events,
            write_staging=False,
            response_received=stage == "response_received",
        )
        return
    _seed_started_image(workspace, events, write_staging=True)
    if stage == "staging_written":
        return
    state = multi.load_state(workspace)
    sheet = CharacterSheet(**read_json(character_paths(workspace).sheet_path))
    character = multi._appearing_characters(sheet)[0]
    cid = str(character["id"])
    attempt = state["image_attempts"][cid][-1]
    if not multi._recover_started_image_receipt(workspace, character, attempt):
        raise AssertionError("production receipt recovery rejected the staged fixture")
    multi._save(state)
    if stage == "receipt_written":
        return
    root = multi.paths.workspace_root(workspace)
    staging = root / attempt["staging_path"]
    multi._atomic_write_bytes(root / attempt["artifact_path"], staging.read_bytes())
    multi._replace_character_reference(workspace, cid, attempt["artifact_record"])
    staging.unlink()


def _run_image_stage(stage: str, workspace: str, events: Path) -> dict[str, Any]:
    from src import drama_multimodal_smoke as multi
    from src.drama_schemas import character_paths
    from src.secure_http import RequestNotSentError
    from src.utils import read_json

    stage_calls_start = _event_count(events, "image_generate")
    stage_responses_start = _event_count(events, "image_response_received")
    _prepare_image(workspace)
    if stage == "not_sent":
        state = multi.load_state(workspace)

        def not_sent(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RequestNotSentError("local matrix proved request was not sent")

        with (
            patch.object(multi, "_image_provider_fingerprint", return_value=PROVIDER_FINGERPRINT),
            patch.object(multi, "redraw_character_reference", not_sent),
        ):
            if multi._run_images(workspace, state, _image_options(), real_image=True):
                raise AssertionError("not-sent attempt unexpectedly completed")
    else:
        _advance_image_seed(workspace, stage, events)

    seeded = multi.load_state(workspace)
    seeded_attempts = [
        row
        for rows in seeded["image_attempts"].values()
        for row in rows
    ]
    seeded_attempt = seeded_attempts[-1] if seeded_attempts else None
    root = multi.paths.workspace_root(workspace)
    pre_recovery_status = seeded_attempt.get("status") if seeded_attempt else None
    pre_recovery_staging_exists = bool(
        seeded_attempt
        and seeded_attempt.get("staging_path")
        and (root / seeded_attempt["staging_path"]).exists()
    )
    pre_recovery_canonical_exists = bool(
        seeded_attempt
        and seeded_attempt.get("artifact_path")
        and (root / seeded_attempt["artifact_path"]).exists()
    )
    calls_before = _event_count(events, "image_generate")

    def forbidden_provider(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        _event(events, "image_generate")
        raise AssertionError("image recovery repeated a paid request")

    draw = _successful_image_draw(events) if stage == "not_sent" else forbidden_provider
    state = multi.load_state(workspace)
    with (
        patch.object(multi, "_image_provider_fingerprint", return_value=PROVIDER_FINGERPRINT),
        patch.object(multi, "redraw_character_reference", draw),
    ):
        completed = multi._run_images(workspace, state, _image_options(), real_image=True)
    call_delta = _event_count(events, "image_generate") - calls_before
    persisted = multi.load_state(workspace)
    cid, attempts = next(iter(persisted["image_attempts"].items()))
    attempt = attempts[-1]
    row: dict[str, Any] = {
        "stage": stage,
        "generate_total": _event_count(events, "image_generate") - stage_calls_start,
        "response_received_total": (
            _event_count(events, "image_response_received") - stage_responses_start
        ),
        "generate_delta": call_delta,
        "completed": completed,
        "durable_status": attempt["status"],
        "phase_status": persisted["phases"]["all_character_images"]["status"],
        "pre_recovery_status": pre_recovery_status,
        "pre_recovery_staging_exists": pre_recovery_staging_exists,
        "pre_recovery_canonical_exists": pre_recovery_canonical_exists,
    }
    if completed:
        root = multi.paths.workspace_root(workspace)
        sheet = read_json(character_paths(workspace).sheet_path)
        reference = sheet["characters"][0]["reference_images"][0]
        canonical = root / attempt["artifact_path"]
        row.update({
            "canonical_sha256": hashlib.sha256(canonical.read_bytes()).hexdigest(),
            "receipt_sha256": attempt["artifact_sha256"],
            "projection_sha256": multi._canonical_sha256(reference),
            "record_sha256": attempt["artifact_record_sha256"],
            "staging_exists": (root / attempt["staging_path"]).exists(),
        })
    return row


def _image_matrix(marker_path: Path, events: Path) -> None:
    results = [
        _run_image_stage(stage, f"image-matrix-{index}", events)
        for index, stage in enumerate(IMAGE_STAGES)
    ]
    _marker(marker_path, "image-matrix", results=results)


TEXT_STATIONS = (
    "drama-plan",
    "drama-hooks",
    "drama-storyboard",
    "drama-characters",
    "drama-review-assemble",
)
TEXT_CASES = (
    "submitting",
    "response_missing",
    "response_canonical",
    "failed_after_submission",
    "budget_exceeded",
    "succeeded_canonical",
    "model_drift",
    "endpoint_drift",
    "input_drift",
)


def _text_artifact(workspace: str, station: str) -> dict[str, Any]:
    from src.drama_schemas import character_paths, episode_paths
    from src.utils import read_json, read_json_optional, write_json

    ep = episode_paths(workspace)
    if station == "drama-plan":
        return {key: value for key, value in read_json(ep.setup_path).items() if key != "hook"}
    if station == "drama-hooks":
        candidates = read_json_optional(ep.hook_candidates_path, None)
        if not isinstance(candidates, dict):
            hook = read_json(ep.setup_path).get("hook")
            candidates = {"hooks": [hook]}
            write_json(ep.hook_candidates_path, candidates)
        return candidates
    if station == "drama-storyboard":
        return read_json(ep.storyboard_path)
    if station == "drama-characters":
        return read_json(character_paths(workspace).sheet_path)
    if station == "drama-review-assemble":
        return read_json(ep.review_path)
    raise AssertionError("unknown text station")


def _text_config(*, drift: str | None = None) -> dict[str, Any]:
    config = {
        "model": "local/text-matrix",
        "base_url": "https://text.example.test/v1",
        "api_key": "local-test-only",
    }
    if drift == "model":
        config["model"] = "local/text-other-model"
    elif drift == "endpoint":
        config["base_url"] = "https://other-text.example.test/v1"
    return config


def _run_text_case(workspace: str, station: str, case: str, events: Path) -> dict[str, Any]:
    from src import paths
    from src.utils import read_json, write_json
    from src.web import jobs
    from src.web.workspace_ctx import use_workspace

    artifact = _text_artifact(workspace, station)
    params = {"confirm_real_text": True, "budget_cny": 3.0, "timeout_minutes": 1.0}
    event_name = f"text_call_{station}"
    calls_before = _event_count(events, event_name)

    def operation() -> dict[str, Any]:
        _event(events, event_name)
        return artifact

    with use_workspace(workspace), patch("src.config.get_model_config", return_value=_text_config()):
        token = jobs._begin_drama_text_attempt(station, params, 1)
        if case in {"response_canonical", "succeeded_canonical", "model_drift", "endpoint_drift", "input_drift"}:
            candidates = artifact.get("hooks") if station == "drama-hooks" else None
            jobs._bind_drama_text_artifact(
                token,
                artifact,
                candidates=candidates if isinstance(candidates, list) else None,
            )
        if case in {"response_missing", "response_canonical", "model_drift", "endpoint_drift", "input_drift"}:
            jobs._mark_drama_text_attempt(token, "response_received")
        elif case == "failed_after_submission":
            jobs._mark_drama_text_attempt(token, "failed_after_submission")
        elif case == "budget_exceeded":
            jobs._mark_drama_text_attempt(token, "budget_exceeded")
        elif case == "succeeded_canonical":
            jobs._mark_drama_text_attempt(token, "succeeded")

        if case == "input_drift":
            wizard = paths.workspace_root(workspace) / "data" / "wizard_input.json"
            changed = read_json(wizard)
            changed["topic"] = "changed-after-paid-attempt"
            write_json(wizard, changed)

        try:
            if case in {"model_drift", "endpoint_drift"}:
                drift = "model" if case == "model_drift" else "endpoint"
                with patch("src.config.get_model_config", return_value=_text_config(drift=drift)):
                    returned, _recovery = jobs._call_drama_text_model(
                        station, params, 1, operation
                    )
            else:
                returned, _recovery = jobs._call_drama_text_model(
                    station, params, 1, operation
                )
        except ValueError as exc:
            outcome = "blocked"
            error = str(exc)
            returned = None
        else:
            outcome = "recovered" if returned == artifact else "called"
            error = ""

    calls = _event_count(events, event_name) - calls_before
    return {
        "station": station,
        "case": case,
        "outcome": outcome,
        "paid_calls": calls,
        "error": error[:120],
    }


def _text_matrix(marker_path: Path, events: Path) -> None:
    from src import drama_video_smoke, paths

    base = "text-matrix-base"
    drama_video_smoke._prepare_mock_inputs(base)
    results: list[dict[str, Any]] = []
    for station_index, station in enumerate(TEXT_STATIONS):
        for case_index, case in enumerate(TEXT_CASES):
            workspace = f"text-{station_index}-{case_index}"
            shutil.copytree(paths.workspace_root(base), paths.workspace_root(workspace))
            results.append(_run_text_case(workspace, station, case, events))
    _marker(marker_path, "text-matrix", results=results)


class _ResumeVideoClient:
    base_url = "https://video.example.test"
    api_key = "local-video-matrix-token"

    def __init__(self, events: Path) -> None:
        self.events = events
        self.request_timeout_seconds = 30.0
        self.asset_number = 0

    def upload_asset(self, **_kwargs: Any) -> dict[str, Any]:
        _event(self.events, "asset_upload")
        self.asset_number += 1
        return {"asset": {"id": f"asset-{self.asset_number}"}}

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        _event(self.events, "asset_poll")
        return {"asset": {"id": asset_id, "status": "ready"}}

    def create_video_task(self, **_kwargs: Any) -> dict[str, Any]:
        _event(self.events, "video_create")
        return {"task": {"id": "task-matrix-1", "status": "pending"}}

    def get_task(self, task_id: str) -> dict[str, Any]:
        _event(self.events, "video_poll")
        return {"task": {
            "id": task_id,
            "status": "completed",
            "video_url": "https://result.example.test/result.mp4?signature=local",
            "cost_cny": 1.25,
        }}


class _CrashAfterCreateVideoClient(_ResumeVideoClient):
    def __init__(self, events: Path, marker_path: Path) -> None:
        super().__init__(events)
        self.marker_path = marker_path

    def create_video_task(self, **_kwargs: Any) -> dict[str, Any]:
        from src import drama_video

        _event(self.events, "video_create")
        ledger = drama_video.read_video_submission(WORKSPACE)
        _marker(
            self.marker_path,
            "video-crash-after-create-before-task-id",
            ledger_status=ledger["status"],
            create_count=_event_count(self.events, "video_create"),
        )
        os._exit(CRASH_EXIT)


def _prepare_video(events: Path, workspace: str = WORKSPACE) -> None:
    del events
    from src import drama_video_smoke

    drama_video_smoke._prepare_mock_inputs(workspace)


def _crash_video_submitting(marker_path: Path, events: Path) -> None:
    from src import drama_video

    client = _CrashAfterCreateVideoClient(events, marker_path)
    with patch.dict(os.environ, _video_environment(drama_video), clear=False):
        drama_video.run_video_job(
            WORKSPACE,
            {"confirm_real_video": True, "budget_cny": 3.0, "timeout_minutes": 1.0},
            lambda *_args: None,
            client=client,
            sleep=lambda _seconds: None,
        )
    raise AssertionError("video submitting crash seam did not exit")


def _resume_video_submitting(marker_path: Path, events: Path) -> None:
    from src import drama_video

    client = _ResumeVideoClient(events)
    error = ""
    try:
        with patch.dict(os.environ, _video_environment(drama_video), clear=False):
            drama_video.run_video_job(
                WORKSPACE,
                {"confirm_real_video": True, "budget_cny": 3.0, "timeout_minutes": 1.0},
                lambda *_args: None,
                client=client,
                sleep=lambda _seconds: None,
            )
    except drama_video.DramaVideoSubmissionUnknown as exc:
        error = str(exc)
    if not error:
        raise AssertionError("submitting video did not fail closed after restart")
    ledger = drama_video.read_video_submission(WORKSPACE)
    _marker(
        marker_path,
        "video-resume-submitting",
        ledger_status=ledger["status"],
        create_count=_event_count(events, "video_create"),
        poll_count=_event_count(events, "video_poll"),
        download_count=_event_count(events, "video_download"),
        blocked=True,
    )


def _video_meta(workspace: str = WORKSPACE) -> tuple[bytes, dict[str, Any]]:
    from src import drama_video
    from tests.support.local_drama_provider import strict_mp4_fixture

    inputs = drama_video.load_video_inputs(workspace)
    client = _ResumeVideoClient(Path(os.devnull))
    provider = drama_video._video_provider_fingerprint(client, drama_video.DEFAULT_VIDEO_MODEL)
    data = strict_mp4_fixture()
    return data, {
        "schema_version": 1,
        "episode_no": 1,
        "status": "succeeded",
        "provider": "video.example.test",
        "provider_model": drama_video.DEFAULT_VIDEO_MODEL,
        "provider_fingerprint": provider,
        "task_id": "task-matrix-1",
        "input_fingerprint": inputs.fingerprint,
        "duration_seconds": 5.0,
        "ratio": "9:16",
        "resolution": "720x1280px",
        "content_type": "video/mp4",
        "file_size_bytes": len(data),
        "video_sha256": hashlib.sha256(data).hexdigest(),
        "cost_cny": 1.25,
        "cost_unreported": False,
        "budget_cny": 3.0,
        "estimated_cost_cny": 2.0,
    }


def _video_environment(drama_video: Any) -> dict[str, str]:
    return {
        "SD_VIDEO_MODE": "real",
        "SD_VIDEO_ESTIMATED_COST_CNY": "2",
        "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        "SD_VIDEO_MODEL": drama_video.DEFAULT_VIDEO_MODEL,
        "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
    }


def _crash_video(marker_path: Path, events: Path) -> None:
    from src import drama_video
    from tests.support.local_drama_provider import strict_mp4_fixture

    out = drama_video.video_paths(WORKSPACE)
    original_write_json = drama_video.write_json

    def die_before_meta(path: Path, value: Any) -> None:
        if path == out.meta_path:
            _marker(
                marker_path,
                "video-crash-after-media-before-meta",
                media_exists=out.video_path.is_file(),
                meta_exists=out.meta_path.is_file(),
                ledger_status=drama_video.read_video_submission(WORKSPACE)["status"],
            )
            os._exit(CRASH_EXIT)
        original_write_json(path, value)

    client = _ResumeVideoClient(events)

    def local_download(*_args: Any, **_kwargs: Any) -> tuple[bytes, str]:
        _event(events, "video_download")
        return strict_mp4_fixture(), "video/mp4"

    with (
        patch.dict(os.environ, _video_environment(drama_video), clear=False),
        patch.object(drama_video, "download_video", local_download),
        patch.object(drama_video, "write_json", die_before_meta),
    ):
        drama_video.run_video_job(
            WORKSPACE,
            {"confirm_real_video": True, "budget_cny": 3.0, "timeout_minutes": 1.0},
            lambda *_args: None,
            client=client,
            sleep=lambda _seconds: None,
        )
    raise AssertionError("video crash seam did not exit")


def _resume_video(marker_path: Path, events: Path) -> None:
    from src import drama_video
    from src.utils import read_json
    from tests.support.local_drama_provider import strict_mp4_fixture

    client = _ResumeVideoClient(events)

    def local_download(*_args: Any, **_kwargs: Any) -> tuple[bytes, str]:
        _event(events, "video_download")
        return strict_mp4_fixture(), "video/mp4"

    with (
        patch.dict(os.environ, _video_environment(drama_video), clear=False),
        patch.object(drama_video, "download_video", local_download),
    ):
        result = drama_video.run_video_job(
            WORKSPACE,
            {"resume_submitted": True},
            lambda *_args: None,
            client=client,
            sleep=lambda _seconds: None,
        )
    data, meta = drama_video.read_video(WORKSPACE)
    raw_meta = read_json(drama_video.video_paths(WORKSPACE).meta_path)
    ledger = drama_video.read_video_submission(WORKSPACE)
    _marker(
        marker_path,
        "video-resume",
        result_status=result["status"],
        ledger_status=ledger["status"],
        task_id=ledger["task_id"],
        media_sha256=hashlib.sha256(data).hexdigest(),
        meta_sha256=raw_meta["video_sha256"],
        network_requests=result.get("network_requests"),
    )


VIDEO_STAGES = (
    "pre_submit",
    "submitting",
    "submitted",
    "media_written",
    "meta_written",
    "succeeded",
)
VIDEO_EVENTS = ("asset_upload", "asset_poll", "video_create", "video_poll", "video_download")


def _seed_video_ledger(workspace: str, status: str, client: _ResumeVideoClient) -> None:
    from src import drama_video
    from src.utils import sha256_data

    inputs = drama_video.load_video_inputs(workspace)
    authorization = drama_video._video_authorization(3.0, 1.0, 2.0)
    payload: dict[str, Any] = {
        "status": status,
        "input_fingerprint": inputs.fingerprint,
        "provider_fingerprint": drama_video._video_provider_fingerprint(
            client, drama_video.DEFAULT_VIDEO_MODEL
        ),
        "result_hosts_fingerprint": sha256_data(["result.example.test"]),
        "submission_count": 1,
        **authorization,
        "updated_at": 1,
    }
    if status in {"submitted", "succeeded"}:
        payload["task_id"] = "task-matrix-1"
    if status == "succeeded":
        payload.update({"cost_cny": 1.25, "cost_unreported": False})
    drama_video._write_video_submission(workspace, payload)


def _run_video_stage(stage: str, workspace: str, events: Path) -> dict[str, Any]:
    from src import drama_video
    from tests.support.local_drama_provider import strict_mp4_fixture

    _prepare_video(events, workspace)
    client = _ResumeVideoClient(events)
    if stage != "pre_submit":
        ledger_status = "succeeded" if stage == "succeeded" else stage
        if stage in {"media_written", "meta_written"}:
            ledger_status = "submitted"
        _seed_video_ledger(workspace, ledger_status, client)
    if stage in {"media_written", "meta_written", "succeeded"}:
        data, meta = _video_meta(workspace)
        out = drama_video.video_paths(workspace)
        if stage == "media_written":
            drama_video._atomic_write(out.video_path, data)
        else:
            drama_video._commit_video_pair(out, data, meta)

    status_before = drama_video.video_status(workspace)
    counts_before = {name: _event_count(events, name) for name in VIDEO_EVENTS}

    def local_download(*_args: Any, **_kwargs: Any) -> tuple[bytes, str]:
        _event(events, "video_download")
        return strict_mp4_fixture(), "video/mp4"

    params = (
        {"resume_submitted": True}
        if stage in {"submitted", "media_written", "meta_written"}
        else {"confirm_real_video": True, "budget_cny": 3.0, "timeout_minutes": 1.0}
    )
    try:
        with (
            patch.dict(os.environ, _video_environment(drama_video), clear=False),
            patch.object(drama_video, "download_video", local_download),
        ):
            result = drama_video.run_video_job(
                workspace,
                params,
                lambda *_args: None,
                client=client,
                sleep=lambda _seconds: None,
            )
    except drama_video.DramaVideoSubmissionUnknown as exc:
        outcome = "blocked"
        result = {"error": str(exc)}
    else:
        outcome = "succeeded"

    deltas = {
        name: _event_count(events, name) - counts_before[name]
        for name in VIDEO_EVENTS
    }
    ledger = drama_video.read_video_submission(workspace)
    status_after = drama_video.video_status(workspace)
    row: dict[str, Any] = {
        "stage": stage,
        "outcome": outcome,
        "ledger_status": ledger["status"],
        "status_before": status_before["state"],
        "status_after": status_after["state"],
        "deltas": deltas,
    }
    if outcome == "succeeded":
        data, _safe_meta = drama_video.read_video(workspace)
        raw_meta = json.loads(drama_video.video_paths(workspace).meta_path.read_text(encoding="utf-8"))
        row.update({
            "media_sha256": hashlib.sha256(data).hexdigest(),
            "meta_sha256": raw_meta["video_sha256"],
            "task_id": ledger["task_id"],
            "network_requests": result.get("network_requests"),
        })
    return row


def _video_matrix(marker_path: Path, events: Path) -> None:
    results = [
        _run_video_stage(stage, f"video-matrix-{index}", events)
        for index, stage in enumerate(VIDEO_STAGES)
    ]
    _marker(marker_path, "video-matrix", results=results)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=(
        "text-matrix", "image-matrix", "video-matrix",
        "prepare-image", "crash-image", "resume-image",
        "crash-video-submitting", "resume-video-submitting",
        "prepare-video", "crash-video", "resume-video",
    ))
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--marker", type=Path)
    parser.add_argument("--events", type=Path)
    args = parser.parse_args()
    _configure_root(args.workspace_root)
    marker = args.marker
    events = args.events
    if args.scenario == "text-matrix":
        _text_matrix(marker, events)
    elif args.scenario == "image-matrix":
        _image_matrix(marker, events)
    elif args.scenario == "video-matrix":
        _video_matrix(marker, events)
    elif args.scenario == "prepare-image":
        _prepare_image()
    elif args.scenario == "crash-image":
        _crash_image(marker, events)
    elif args.scenario == "resume-image":
        _resume_image(marker, events)
    elif args.scenario == "prepare-video":
        _prepare_video(events)
    elif args.scenario == "crash-video-submitting":
        _crash_video_submitting(marker, events)
    elif args.scenario == "resume-video-submitting":
        _resume_video_submitting(marker, events)
    elif args.scenario == "crash-video":
        _crash_video(marker, events)
    elif args.scenario == "resume-video":
        _resume_video(marker, events)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
