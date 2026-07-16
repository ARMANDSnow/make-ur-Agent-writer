"""Process-crash driver for iter114 once-only shot-image attempt tests."""

from __future__ import annotations

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
    "AI_DRAW_API_KEY",
    "AI_DRAW_ENDPOINT",
    "AI_DRAW_BASE_URL",
    "OPENAI_BASE_URL",
):
    os.environ.pop(_name, None)

from src import paths
from src import drama_shot_image_attempt_store as store
from src import drama_shot_image_candidate_store
from src.drama_shot_image_attempts import build_shot_image_provider_capability


class _Adapter:
    def __init__(self, counter: Path, payload: bytes) -> None:
        self.counter = counter
        self.payload = payload

    def generate(self, spec, *, prompt, reference_bytes):
        current = int(self.counter.read_text(encoding="utf-8") or "0") if self.counter.exists() else 0
        self.counter.write_text(str(current + 1), encoding="utf-8")
        if MODE == "after_call":
            os._exit(91)
        return self.payload


if len(sys.argv) != 5:
    raise SystemExit("usage: driver WORKSPACE_DIR WORKSPACE MODE COUNTER")

paths.WORKSPACE_DIR = Path(sys.argv[1])
WORKSPACE = sys.argv[2]
MODE = sys.argv[3]
COUNTER = Path(sys.argv[4])
CAPABILITY = build_shot_image_provider_capability(
    backend_id="fake-shot-image",
    capability_version="v1",
    max_reference_images=8,
)
MANIFEST = drama_shot_image_candidate_store.load_fresh_episode_shot_image_candidates(WORKSPACE)
PLAN = store.load_fresh_episode_shot_image_plan(WORKSPACE)
SHOT_ID = PLAN.shot_specs[0].shot_id
PAYLOAD = bytes.fromhex(os.environ["SHOT_IMAGE_ATTEMPT_PNG_HEX"])


original_staging = store._write_staging_create_only
original_persist = store._persist_ledger
original_append = store.append_local_shot_image_candidate


def staging_then_exit(*args, **kwargs):
    if MODE == "after_adapter_return":
        os._exit(96)
    result = original_staging(*args, **kwargs)
    os._exit(92)
    return result


def persist_then_maybe_exit(*args, **kwargs):
    result = original_persist(*args, **kwargs)
    ledger = args[1]
    if MODE == "after_started" and ledger.attempts and ledger.attempts[-1].status == "started":
        os._exit(90)
    if MODE == "after_receipt" and ledger.attempts and ledger.attempts[-1].status == "artifact_received":
        os._exit(93)
    if MODE == "after_succeeded" and ledger.attempts and ledger.attempts[-1].status == "succeeded":
        os._exit(95)
    return result


def append_then_exit(*args, **kwargs):
    result = original_append(*args, **kwargs)
    os._exit(94)
    return result


with (
    patch.object(
        store,
        "_write_staging_create_only",
        staging_then_exit if MODE in {"after_adapter_return", "after_staging"} else original_staging,
    ),
    patch.object(store, "_persist_ledger", persist_then_maybe_exit),
    patch.object(
        store,
        "append_local_shot_image_candidate",
        append_then_exit if MODE in {"after_candidate", "after_candidate_corrupt"} else original_append,
    ),
):
    store.run_shot_image_attempt_with_adapter(
        WORKSPACE,
        shot_id=SHOT_ID,
        capability=CAPABILITY,
        provider_fingerprint="a" * 64,
        adapter=_Adapter(COUNTER, PAYLOAD),
        expected_manifest_fingerprint=MANIFEST.manifest_fingerprint,
    )
