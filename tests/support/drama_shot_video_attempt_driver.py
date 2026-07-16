"""Process-crash driver for iter117 once-only shot-video attempt tests."""

from __future__ import annotations

import json
import hashlib
import os
import sys
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ["DRAGON_RAJA_SKIP_DOTENV"] = "1"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["OPENAI_MODEL"] = "mock"
for _name in (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "AI_DRAW_API_KEY",
    "AI_DRAW_ENDPOINT",
    "AI_DRAW_BASE_URL",
):
    os.environ.pop(_name, None)

from src import paths
from src import drama_shot_video_attempt_store as store
from src import drama_shot_video_candidate_store
from src.drama_shot_video_attempts import (
    build_shot_video_provider_capability,
    build_shot_video_submission_gate,
)
from tests._drama_shot_video_attempt_base import DramaShotVideoAttemptFixture


if len(sys.argv) != 5:
    raise SystemExit("usage: driver WORKSPACE_DIR WORKSPACE MODE COUNTER")

paths.WORKSPACE_DIR = Path(sys.argv[1])
WORKSPACE = sys.argv[2]
MODE = sys.argv[3]
COUNTER = Path(sys.argv[4])
PLAN = store.load_fresh_episode_shot_video_plan(WORKSPACE)
MANIFEST = drama_shot_video_candidate_store.load_fresh_episode_shot_video_candidates(
    WORKSPACE
)
SHOT_ID = PLAN.shot_specs[0].shot_id
CAPABILITY = build_shot_video_provider_capability(
    backend_id="fake-shot-video",
    capability_version="v1",
    supported_modes=["image_to_video", "reference_to_video"],
    supports_tail_frame=True,
    max_reference_images=25,
    supported_durations_seconds=sorted(
        {item.target_duration_seconds for item in PLAN.shot_specs}
    ),
    supported_resolutions=[(16, 16)],
)
GATE = build_shot_video_submission_gate(
    backend_id="fake-shot-video",
    authorization_id="svauth_" + hashlib.sha256(
        f"{PLAN.episode_no}:{SHOT_ID}:{PLAN.shot_specs[0].spec_fingerprint}:default".encode()
    ).hexdigest()[:24],
    authorized_episode_no=PLAN.episode_no,
    authorized_shot_id=SHOT_ID,
    authorized_request_fingerprint=PLAN.shot_specs[0].spec_fingerprint,
    provider_fingerprint="a" * 64,
    model_fingerprint="e" * 64,
    account_fingerprint="b" * 64,
    endpoint_fingerprint="c" * 64,
    auth_fingerprint="d" * 64,
    estimated_cost_microunits=0,
    authorized_budget_microunits=1000,
)


def bump(field: str) -> None:
    value = json.loads(COUNTER.read_text(encoding="utf-8"))
    value[field] += 1
    COUNTER.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


class _Adapter:
    identity = store.shot_video_adapter_identity_from_gate(GATE)

    def submit(self, spec, *, prompt, frame_bytes, reference_bytes):
        bump("submit")
        if MODE == "after_submit":
            os._exit(91)
        return "task-1"

    def poll(self, spec, submission):
        bump("poll")
        return store.ShotVideoPollResult(
            "succeeded",
            result_token="result-1",
            cost_reported=False,
            actual_cost_microunits=None,
        )

    def download(self, spec, submission, terminal):
        bump("download")
        payload = DramaShotVideoAttemptFixture._mp4_for_duration(
            spec.target_duration_seconds
        )
        if MODE == "after_download":
            os._exit(94)
        return payload


original_persist = store._persist_ledger
original_staging = store._write_staging_create_only
original_append = store.append_local_shot_video_candidate


def persist_then_exit(*args, **kwargs):
    result = original_persist(*args, **kwargs)
    ledger = args[1]
    if ledger.attempts:
        status = ledger.attempts[-1].status
        if MODE == "after_started" and status == "started":
            os._exit(90)
        if MODE == "after_submitted" and status == "submitted":
            os._exit(92)
        if MODE == "after_terminal" and status == "provider_succeeded":
            os._exit(93)
        if MODE == "after_artifact" and status == "artifact_received":
            os._exit(96)
        if MODE == "after_succeeded" and status == "succeeded":
            os._exit(98)
    return result


def staging_then_exit(*args, **kwargs):
    result = original_staging(*args, **kwargs)
    os._exit(95)
    return result


def append_then_exit(*args, **kwargs):
    result = original_append(*args, **kwargs)
    os._exit(97)
    return result


with (
    patch.object(store, "_persist_ledger", persist_then_exit),
    patch.object(
        store,
        "_write_staging_create_only",
        staging_then_exit if MODE == "after_staging" else original_staging,
    ),
    patch.object(
        store,
        "append_local_shot_video_candidate",
        append_then_exit if MODE == "after_candidate" else original_append,
    ),
):
    store.run_shot_video_attempt_with_adapter(
        WORKSPACE,
        shot_id=SHOT_ID,
        capability=CAPABILITY,
        submission_gate=GATE,
        mode="reference_to_video",
        output_width=16,
        output_height=16,
        adapter=_Adapter(),
        expected_manifest_fingerprint=MANIFEST.manifest_fingerprint,
    )
