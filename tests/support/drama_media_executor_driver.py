"""Fresh-interpreter crash driver for iter137 generic media execution."""

from __future__ import annotations

import json
import os
import socket
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

from src import (
    drama_media_executor as executor,
    drama_media_tasks,
    drama_media_worker,
    paths,
)


if len(sys.argv) != 9:
    raise SystemExit(
        "usage: driver WORKSPACE_DIR WORKSPACE TASK WORKER TOKEN "
        "MODE COUNTER NOW_MS"
    )

paths.WORKSPACE_DIR = Path(sys.argv[1])
WORKSPACE = sys.argv[2]
TASK_ID = sys.argv[3]
WORKER = sys.argv[4]
TOKEN = sys.argv[5]
MODE = sys.argv[6]
COUNTER = Path(sys.argv[7])
NOW_MS = int(sys.argv[8])


def read_counter() -> dict[str, object]:
    return json.loads(COUNTER.read_text(encoding="utf-8"))


def update_counter(field: str, value: object | None = None) -> None:
    payload = read_counter()
    if value is None:
        payload[field] = int(payload[field]) + 1
    else:
        payload[field] = value
    COUNTER.write_text(
        json.dumps(payload, sort_keys=True), encoding="utf-8"
    )


ledger = drama_media_tasks.load_media_task_ledger(WORKSPACE, episode_no=1)
task = next(item for item in ledger.tasks if item.task_id == TASK_ID)
binding = next(
    item for item in ledger.backend_bindings if item.task_id == TASK_ID
)
identity = executor.DramaMediaExecutionIdentity(
    bridge_id=binding.backend_id,
    backend_id=binding.backend_id,
    provider_fingerprint=task.provider_fingerprint,
    model_fingerprint=task.model_fingerprint,
    account_fingerprint=task.account_fingerprint,
    endpoint_fingerprint=task.endpoint_fingerprint,
    source_capability_fingerprint=binding.source_capability_fingerprint,
)


class DurableSyntheticPaidBridge(executor.DramaMediaPaidEvidenceBridge):
    @property
    def identity(self):
        return identity

    def submit(self, context):
        payload = read_counter()
        if not payload["paid_submitted"]:
            if MODE == "crash_before_paid_submit":
                os._exit(90)
            update_counter("submit")
            update_counter("paid_submitted", True)
            if MODE == "crash_after_paid_submit":
                os._exit(91)
        return executor.build_media_execution_observation(
            context=context,
            phase="submit",
            outcome="submitted",
            paid_evidence_fingerprint="a" * 64,
        )

    def poll(self, context):
        update_counter("poll")
        return executor.build_media_execution_observation(
            context=context,
            phase="poll",
            outcome="ready",
            paid_evidence_fingerprint="b" * 64,
        )

    def download(self, context):
        update_counter("download")
        return executor.build_media_execution_observation(
            context=context,
            phase="download",
            outcome="ready",
            paid_evidence_fingerprint="c" * 64,
        )

    def validate(self, context):
        update_counter("validate")
        return executor.build_media_execution_observation(
            context=context,
            phase="validate",
            outcome="succeeded",
            paid_evidence_fingerprint="d" * 64,
            artifact_evidence_fingerprint="e" * 64,
        )


original_transition = executor._transition


def transition_then_maybe_exit(*args, **kwargs):
    result = original_transition(*args, **kwargs)
    if (
        MODE == "crash_after_generic_submitted"
        and kwargs.get("target_state") == "submitted"
    ):
        os._exit(92)
    return result


with (
    patch.object(
        socket, "socket", side_effect=AssertionError("network forbidden")
    ),
    patch.object(drama_media_tasks, "_clock_ms", return_value=NOW_MS),
    patch.object(drama_media_worker, "_clock_ms", return_value=NOW_MS),
    patch.object(executor, "_transition", transition_then_maybe_exit),
):
    result = executor.run_media_task(
        WORKSPACE,
        episode_no=1,
        task_id=TASK_ID,
        worker_fingerprint=WORKER,
        lease_token_fingerprint=TOKEN,
        bridge=DurableSyntheticPaidBridge(),
        lease_duration_ms=60_000,
        timeout_ms=30_000,
    )
if result["state"] != "succeeded":
    raise SystemExit("media executor did not reach succeeded")
