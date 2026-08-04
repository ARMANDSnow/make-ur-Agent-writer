"""Recoverable, consent-scoped short-drama multimodal smoke orchestration."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import math
import os
import secrets
import stat
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Mapping

# As with drama_smoke, direct module execution defaults to mock text.  This
# must happen before any transitive LLM import; programmatic run() repeats the
# pin after it receives the explicit real_text flag.
if __name__ == "__main__" and "--real-text" not in sys.argv[1:]:
    os.environ["OPENAI_MODEL"] = "mock"
    os.environ["DRAMA_MODEL"] = "mock"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"

from . import ai_draw_client, drama_smoke, drama_store, drama_video, paths
from .ai_draw_client import (
    AIDrawNetworkError,
    AIDrawProviderError,
    AIDrawTimeout,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_IMAGE_SIZE,
    _atomic_write_bytes,
    _detect_image_type,
    _image_dimensions,
    _images_generation_url,
    _resolve_openai_draw_credentials,
    _validate_public_endpoint,
    redraw_character_reference,
    validate_api_base_url,
)
from .drama_schemas import CharacterSheet, ReferenceImage, character_paths, episode_paths
from .config import get_model_config, load_dotenv_if_available
from .paid_recovery_states import (
    IMAGE_ATTEMPT_STATUSES,
    IMAGE_RECEIPT_STATUSES,
    TEXT_CANONICAL_RECOVERY_STATUSES,
    VIDEO_NON_RESUMABLE_STATUSES,
    VIDEO_PAID_SUBMISSION_STATUSES,
    VIDEO_UNKNOWN_SUBMISSION_STATUSES,
)
from .schemas import model_to_dict
from .secure_http import RequestNotSentError
from .utils import read_json, read_json_optional, write_json
from .web.drama_insights import collect_drama_insights
from .web.workspace_ctx import use_workspace
from .workspace_lock import acquire_write_lock


PHASES = ("real_text", "all_character_images", "reassemble", "video_readiness", "real_video")
PHASE_STATUSES = {
    "pending", "running", "succeeded", "failed", "blocked",
    "budget_exceeded",
    "awaiting_retry_authorization", "awaiting_real_video_authorization",
    "awaiting_text_retry_authorization",
    "submission_consumed", "failed_after_submission",
}
RUN_STATUSES = {
    "pending", "running", "succeeded", "failed", "blocked",
    "budget_exceeded",
    "awaiting_retry_authorization", "awaiting_text_authorization",
    "awaiting_text_retry_authorization",
    "awaiting_image_authorization", "awaiting_video_authorization",
    "failed_after_video_submission", "video_submission_already_consumed",
}


def _video_submission_view(
    workspace: str,
) -> tuple[Dict[str, Any] | None, Dict[str, Any], bool]:
    """Return the raw private ledger plus its reconciliation-aware safe state."""

    submission = drama_video.read_video_submission(workspace)
    public_state = drama_video.video_status(workspace) if submission is not None else {}
    return submission, public_state, public_state.get("state") == "submitted"


def _video_submission_accounting(
    workspace: str,
    video_phase: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return one reconciliation-aware accounting view for a video attempt.

    A durable submission ledger is authoritative whenever it exists. Its raw
    status remains visible as ``source_submission_status`` for audit, while
    ``submission_status`` follows the safe reconciliation projection. Only a
    genuinely absent ledger may fall back to the legacy phase counters.
    """

    try:
        submission = drama_video.read_video_submission(workspace)
    except (OSError, TypeError, ValueError):
        # A damaged durable marker cannot safely be treated as no submission.
        # It is an unresolved exposure until an operator repairs/reconciles it.
        return {
            "_source_submission": None,
            "source_ledger_present": True,
            "source_submission_status": "invalid",
            "submission_status": "blocked",
            "request_count": 0,
            "submission_unknown_count": 1,
            "submission_consumed": True,
        }

    if submission is None:
        request_count = min(1, _safe_count(video_phase.get("paid_submission_count")))
        unknown_count = min(
            1,
            _safe_count(video_phase.get("submission_unknown_count")),
        )
        # The pre-split one-shot marker was written before the external request,
        # so it proves a consumed opportunity but not a sent request. Preserve
        # it as unknown unless a newer split counter says otherwise.
        legacy_consumed = (
            "submission_unknown_count" not in video_phase
            and video_phase.get("submission_consumed") is True
            and video_phase.get("attempt") == 1
            and (
                "paid_submission_count" not in video_phase
                or (
                    type(video_phase.get("paid_submission_count")) is int
                    and video_phase.get("paid_submission_count") == 1
                )
            )
        )
        if legacy_consumed:
            request_count, unknown_count = 0, 1
        return {
            "_source_submission": None,
            "source_ledger_present": False,
            "source_submission_status": None,
            "submission_status": "still_unknown" if unknown_count else None,
            "request_count": request_count,
            "submission_unknown_count": unknown_count,
            "submission_consumed": bool(request_count or unknown_count),
        }

    source_status = submission.get("status")
    try:
        public_state = drama_video.video_status(workspace)
    except (OSError, TypeError, ValueError):
        public_state = {"state": "blocked"}
    projected_state = public_state.get("state")

    if source_status == "request_not_sent":
        effective_status = "request_not_sent"
        request_count, unknown_count, consumed = 0, 0, False
    elif source_status in VIDEO_PAID_SUBMISSION_STATUSES:
        # These durable source outcomes are already known. Public artifact or
        # authorization readiness may still be blocked without changing their
        # paid-submission classification.
        effective_status = str(source_status)
        request_count, unknown_count, consumed = 1, 0, True
    elif source_status in VIDEO_UNKNOWN_SUBMISSION_STATUSES and projected_state in {
        "submitted",
        "provider_rejected",
    }:
        effective_status = str(projected_state)
        request_count, unknown_count, consumed = 1, 0, True
    elif source_status in VIDEO_UNKNOWN_SUBMISSION_STATUSES:
        # ``still_unknown`` is the accounting outcome; the public video status
        # intentionally retains its older ``submission_unknown`` vocabulary.
        effective_status = "still_unknown"
        request_count, unknown_count, consumed = 0, 1, True
    else:
        # A durable but unclassifiable marker is fail-closed, never legacy.
        effective_status = "blocked"
        request_count, unknown_count, consumed = 0, 1, True

    return {
        "_source_submission": submission,
        "source_ledger_present": True,
        "source_submission_status": source_status,
        "submission_status": effective_status,
        "request_count": request_count,
        "submission_unknown_count": unknown_count,
        "submission_consumed": consumed,
    }


RETRY_TIMEOUT_SECONDS = 180.0
MAX_IMAGE_ATTEMPTS_PER_CHARACTER = 3
STATE_SCHEMA_VERSION = 1
CALIBRATION_REPORT_SCHEMA_VERSION = 2
TEXT_STEP_TASKS = {
    "drama-plan": "drama_plan",
    "drama-hooks": "drama_hooks",
    "drama-storyboard": "drama_storyboard",
    "drama-characters": "drama_character",
    "drama-review-assemble": "drama_review",
}
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class MultimodalAuthorizationError(PermissionError):
    pass


def run_video_smoke(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    # drama_video_smoke imports web.jobs (and therefore the LLM stack).  Keep
    # the public wrapper patchable for tests while deferring that import until
    # run() has pinned mock or validated real-text authorization.
    from .drama_video_smoke import run_smoke

    return run_smoke(*args, **kwargs)


def _positive(value: Any, label: str, *, maximum: float = 1_000_000.0) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be finite and positive")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be finite and positive") from exc
    if not math.isfinite(number) or number <= 0 or number > maximum:
        raise ValueError(f"{label} must be finite and positive")
    return number


def _safe_non_negative(value: Any) -> float | None:
    """Return a finite non-negative metric without trusting provider payloads."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _safe_short_text(value: Any, *, maximum: int = 80) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (
        not value
        or len(value) > maximum
        or "://" in value
        or "\\" in value
        or value.startswith("/")
        or ".." in value
    ):
        return None
    return value


def _safe_count(value: Any, *, maximum: int = 1_000_000) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        return 0
    return value


def _model_sha256(model: str) -> str:
    return hashlib.sha256(model.strip().encode("utf-8")).hexdigest()


def _text_model_fingerprints() -> Dict[str, str]:
    return {
        step: _model_sha256(str(get_model_config(task).get("model") or "mock"))
        for step, task in TEXT_STEP_TASKS.items()
    }


def _text_provider_fingerprints() -> Dict[str, str]:
    """Hash non-public provider routing/account identity without persisting secrets."""

    result: Dict[str, str] = {}
    for step, task in TEXT_STEP_TASKS.items():
        config = get_model_config(task)
        payload = {
            "model": str(config.get("model") or "mock").strip(),
            "base_url": str(config.get("base_url") or "").strip().rstrip("/"),
            "base_url_env": str(config.get("base_url_env") or ""),
            "api_key_env": str(config.get("api_key_env") or ""),
            # API keys are expected to be high-entropy.  Only their SHA-256
            # contribution survives, binding a resume to the same account.
            "api_key": str(config.get("api_key") or ""),
        }
        result[step] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    return result


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _text_artifact_fingerprint(workspace: str, step: str) -> str:
    """Hash the stable canonical output of one text station."""

    ep = episode_paths(workspace, episode_no=1)
    if step == "drama-plan":
        raw = read_json_optional(ep.setup_path, None)
        if not isinstance(raw, dict):
            raise ValueError("drama plan artifact is missing")
        payload = {key: value for key, value in raw.items() if key != "hook"}
    elif step == "drama-hooks":
        raw = read_json_optional(ep.setup_path, None)
        if not isinstance(raw, dict) or not isinstance(raw.get("hook"), dict):
            raise ValueError("selected drama hook artifact is missing")
        payload = raw["hook"]
    elif step == "drama-storyboard":
        payload = read_json_optional(ep.storyboard_path, None)
    elif step == "drama-characters":
        raw = read_json_optional(character_paths(workspace).sheet_path, None)
        if not isinstance(raw, dict):
            raise ValueError("drama character artifact is missing")
        payload = dict(raw)
        characters = []
        for item in raw.get("characters") or []:
            if isinstance(item, dict):
                characters.append({key: value for key, value in item.items() if key != "reference_images"})
        payload["characters"] = characters
    elif step == "drama-review-assemble":
        review = read_json_optional(ep.review_path, None)
        episode = read_json_optional(ep.episode_path, None)
        meta = read_json_optional(ep.meta_path, None)
        if not isinstance(review, dict) or not isinstance(episode, dict) or not isinstance(meta, dict):
            raise ValueError("assembled drama station artifacts are missing")
        # Image-reference reassembly intentionally refreshes the input
        # fingerprint.  Everything else is stable evidence produced by the
        # text station and must remain bound to it.
        stable_meta = {
            key: value for key, value in meta.items()
            if key not in {"input_fingerprint", "episode_sha256"}
        }
        stable_episode = {
            key: value for key, value in episode.items()
            if key != "ai_friendly_constraints"
        }
        payload = {"review": review, "episode": stable_episode, "meta": stable_meta}
    else:
        raise ValueError("unknown drama text artifact step")
    if not isinstance(payload, (dict, list)):
        raise ValueError("drama text station artifact is missing or invalid")
    return _canonical_sha256(payload)


def _text_artifacts_current(workspace: str, phase: Mapping[str, Any]) -> bool:
    completed = phase.get("completed_steps")
    frozen = phase.get("artifact_fingerprints")
    if not isinstance(completed, list) or not isinstance(frozen, dict):
        return False
    try:
        return all(
            isinstance(frozen.get(step), str)
            and frozen[step] == _text_artifact_fingerprint(workspace, step)
            for step in completed
        )
    except (OSError, TypeError, ValueError):
        return False


def _adopt_durable_text_station(workspace: str, phase: Dict[str, Any], step: str) -> bool:
    """Adopt a paid Web station committed before the smoke callback ran."""
    from .web import jobs as web_jobs

    if step not in TEXT_STEP_TASKS:
        return False
    with use_workspace(workspace):
        try:
            ledger = web_jobs._load_drama_text_attempts(workspace)
            row = ledger["attempts"].get(f"{step}:1")
            if (
                not isinstance(row, dict)
                or row.get("status") not in TEXT_CANONICAL_RECOVERY_STATUSES
            ):
                return False
        except (OSError, TypeError, ValueError):
            return False
        task = TEXT_STEP_TASKS[step]
        current_provider = web_jobs._drama_text_provider_fingerprint(task)
        pinned_provider = (phase.get("provider_fingerprints") or {}).get(step)
        if (
            row.get("provider_fingerprint") != current_provider
            or not web_jobs._drama_text_recovery_fingerprint_matches(
                step, workspace, 1, row
            )
            or (pinned_provider is not None and row.get("provider_fingerprint") != pinned_provider)
        ):
            raise ValueError("durable drama text attempt identity changed before recovery")
        try:
            if web_jobs._canonical_drama_text_result(
                step, workspace, 1, row, allow_selected_hook=True
            ) is None:
                return False
            phase.setdefault("artifact_fingerprints", {})[step] = _text_artifact_fingerprint(workspace, step)
        except (OSError, TypeError, ValueError):
            return False
    completed = phase.setdefault("completed_steps", [])
    if step not in completed:
        completed.append(step)
    phase.setdefault("station_evidence", {})[step] = {
        "status": "succeeded",
        "recovered_from_durable_attempt": True,
        "call_count": int(row.get("attempt_count") or 1),
        "non_mock_call_count": int(row.get("attempt_count") or 1),
        "pinned_model_call_count": int(row.get("attempt_count") or 1),
        "model_sha256": (phase.get("model_fingerprints") or {}).get(step),
        "elapsed_seconds": 0.0,
    }
    phase.pop("active_step", None)
    phase.pop("active_step_started_at", None)
    phase.pop("retry_required_step", None)
    return True


def _drama_call_counts(workspace: str) -> Dict[str, Dict[str, Any]]:
    """Count only safe task/model facts from the local LLM audit ledger."""
    result = {
        task: {"calls": 0, "non_mock_calls": 0, "model_calls": {}}
        for task in TEXT_STEP_TASKS.values()
    }
    path = paths.workspace_root(workspace) / "logs" / "llm_calls.jsonl"
    if not path.is_file():
        return result
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                try:
                    row = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(row, dict):
                    continue
                final_of_attempts = row.get("final_of_attempts")
                if type(final_of_attempts) is int and final_of_attempts > 0:
                    continue
                task = row.get("task")
                model = row.get("model")
                if task not in result or not isinstance(model, str):
                    continue
                result[task]["calls"] += 1
                digest = _model_sha256(model)
                result[task]["model_calls"][digest] = result[task]["model_calls"].get(digest, 0) + 1
                if model.strip() and model.strip() != "mock":
                    result[task]["non_mock_calls"] += 1
    except OSError:
        return result
    return result


def _call_count_delta(
    current: Mapping[str, Mapping[str, Any]], baseline: Mapping[str, Mapping[str, Any]], task: str, key: str
) -> int:
    return max(0, _safe_count((current.get(task) or {}).get(key)) - _safe_count((baseline.get(task) or {}).get(key)))


def _model_call_delta(
    current: Mapping[str, Mapping[str, Any]], baseline: Mapping[str, Mapping[str, Any]], task: str, model_sha256: str
) -> int:
    current_models = (current.get(task) or {}).get("model_calls")
    baseline_models = (baseline.get(task) or {}).get("model_calls")
    return max(
        0,
        _safe_count(current_models.get(model_sha256) if isinstance(current_models, dict) else None)
        - _safe_count(baseline_models.get(model_sha256) if isinstance(baseline_models, dict) else None),
    )


def _reconcile_failed_text_station(workspace: str, phase: Dict[str, Any], *, real_text: bool) -> None:
    """Refresh cumulative evidence for a failed or crash-interrupted station."""
    step = phase.get("active_step")
    if step not in TEXT_STEP_TASKS:
        return
    evidence = phase.setdefault("station_evidence", {})
    previous = evidence.get(step) if isinstance(evidence.get(step), dict) else {}
    if previous.get("status") == "succeeded":
        phase.pop("active_step", None)
        phase.pop("active_step_started_at", None)
        return
    current_calls = _drama_call_counts(workspace)
    baseline = phase.get("call_baseline") if isinstance(phase.get("call_baseline"), dict) else {}
    task = TEXT_STEP_TASKS[step]
    started_at = _safe_non_negative(phase.get("active_step_started_at"))
    attempt_elapsed = max(0.0, time.time() - started_at) if started_at is not None else 0.0
    previous_elapsed = _safe_non_negative(previous.get("elapsed_seconds")) or 0.0
    pinned = (phase.get("model_fingerprints") or {}).get(step, "")
    evidence[step] = {
        "status": "failed",
        "call_count": _call_count_delta(current_calls, baseline, task, "calls"),
        "non_mock_call_count": _call_count_delta(current_calls, baseline, task, "non_mock_calls"),
        "pinned_model_call_count": _model_call_delta(current_calls, baseline, task, pinned) if real_text else 0,
        "elapsed_seconds": round(previous_elapsed + attempt_elapsed, 3),
        "cumulative_cost_cny": round(float(phase.get("spent_cost_cny") or 0.0), 6),
        "model_sha256": pinned or None,
    }
    phase["llm_calls"] = sum(
        _call_count_delta(current_calls, baseline, task_name, "calls")
        for task_name in TEXT_STEP_TASKS.values()
    )
    phase.pop("active_step", None)
    phase.pop("active_step_started_at", None)


def state_path(workspace: str) -> Path:
    return paths.workspace_root(workspace) / "logs" / "drama_multimodal_smoke_state.json"


def _valid_image_staging_path(cid: str, row: Mapping[str, Any]) -> bool:
    value = row.get("staging_path")
    attempt = row.get("attempt")
    if not isinstance(value, str) or type(attempt) is not int:
        return False
    path = Path(value)
    if path.is_absolute() or path.parts[:3] != ("logs", "drama_multimodal_images", cid):
        return False
    if len(path.parts) != 4:
        return False
    prefix = f"attempt_{attempt}_"
    filename = path.name
    if not filename.startswith(prefix) or not filename.endswith(".png"):
        return False
    token = filename[len(prefix):-4]
    return len(token) == 16 and all(
        ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for ch in token
    )


def load_state(workspace: str) -> Dict[str, Any] | None:
    path = state_path(workspace)
    try:
        stat_result = path.lstat()
    except FileNotFoundError:
        return None
    _assert_relative_path_components_safe(
        paths.workspace_root(workspace),
        Path("logs") / "drama_multimodal_smoke_state.json",
        require_file=True,
    )
    if path.is_symlink() or not path.is_file() or stat_result.st_nlink < 1:
        raise ValueError("multimodal smoke state must be a regular non-symlink file")
    # Paid orchestration state is not optional data: corrupt/unreadable state
    # must fail closed, never look like a fresh run.
    raw = read_json(path)
    if not isinstance(raw, dict) or raw.get("schema_version") != STATE_SCHEMA_VERSION or raw.get("workspace") != workspace:
        raise ValueError("multimodal smoke state is invalid")
    phases = raw.get("phases")
    if not isinstance(phases, dict) or tuple(phases) != PHASES:
        raise ValueError("multimodal smoke phase order is invalid")
    if not all(isinstance(row, dict) for row in phases.values()):
        raise ValueError("multimodal smoke phase state is invalid")
    if any(row.get("status") not in PHASE_STATUSES for row in phases.values()):
        raise ValueError("multimodal smoke phase status is invalid")
    if raw.get("status") not in RUN_STATUSES:
        raise ValueError("multimodal smoke run status is invalid")
    spend = raw.get("image_estimated_spend_cny")
    if isinstance(spend, bool) or not isinstance(spend, (int, float)) or not math.isfinite(float(spend)) or spend < 0:
        raise ValueError("multimodal smoke image spend state is invalid")
    attempts = raw.get("image_attempts")
    if not isinstance(attempts, dict):
        raise ValueError("multimodal smoke image attempt state is invalid")
    estimated_sum = 0.0
    for cid, rows in attempts.items():
        if not isinstance(cid, str) or not isinstance(rows, list) or len(rows) > MAX_IMAGE_ATTEMPTS_PER_CHARACTER:
            raise ValueError("multimodal smoke image attempt state is invalid")
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict) or type(row.get("attempt")) is not int or row["attempt"] != index:
                raise ValueError("multimodal smoke image attempt sequence is invalid")
            timeout = row.get("timeout_seconds")
            estimate = row.get("estimated_cost_cny")
            if (
                isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(float(timeout)) or timeout <= 0
                or isinstance(estimate, bool) or not isinstance(estimate, (int, float)) or not math.isfinite(float(estimate)) or estimate < 0
                or row.get("status") not in IMAGE_ATTEMPT_STATUSES
            ):
                raise ValueError("multimodal smoke image attempt billing state is invalid")
            provider_fingerprint = row.get("provider_fingerprint")
            if provider_fingerprint is not None and (
                not isinstance(provider_fingerprint, str)
                or len(provider_fingerprint) != 64
                or any(ch not in "0123456789abcdef" for ch in provider_fingerprint)
            ):
                raise ValueError("multimodal smoke image provider state is invalid")
            if row.get("staging_path") is not None and not _valid_image_staging_path(cid, row):
                raise ValueError("multimodal smoke image staging state is invalid")
            if row.get("status") in IMAGE_RECEIPT_STATUSES:
                artifact_path = row.get("artifact_path")
                artifact_sha256 = row.get("artifact_sha256")
                artifact_record = row.get("artifact_record")
                artifact_record_sha256 = row.get("artifact_record_sha256")
                try:
                    normalized_record = model_to_dict(ReferenceImage(**artifact_record)) if isinstance(artifact_record, dict) else None
                except Exception as exc:
                    raise ValueError("multimodal smoke image artifact state is invalid") from exc
                if (
                    not isinstance(artifact_path, str)
                    or not artifact_path
                    or Path(artifact_path).is_absolute()
                    or ".." in Path(artifact_path).parts
                    or Path(artifact_path).parts[:3] != ("data", "character_refs", cid)
                    or not isinstance(artifact_sha256, str)
                    or len(artifact_sha256) != 64
                    or any(ch not in "0123456789abcdef" for ch in artifact_sha256)
                    or not isinstance(artifact_record, dict)
                    or artifact_record.get("path") != artifact_path
                    or (
                        artifact_record_sha256 is not None
                        and (
                            not isinstance(artifact_record_sha256, str)
                            or artifact_record_sha256 != _canonical_sha256(normalized_record)
                        )
                    )
                ):
                    raise ValueError("multimodal smoke image artifact state is invalid")
            estimated_sum += float(estimate)
    if not math.isclose(estimated_sum, float(spend), rel_tol=0.0, abs_tol=1e-6):
        raise ValueError("multimodal smoke image spend does not match attempt ledger")
    video = phases["real_video"]
    image_phase = phases["all_character_images"]
    if "cast_ids" in image_phase and (
        not isinstance(image_phase["cast_ids"], list)
        or image_phase["cast_ids"] != sorted(image_phase["cast_ids"])
        or any(not isinstance(cid, str) or not cid for cid in image_phase["cast_ids"])
    ):
        raise ValueError("multimodal smoke image cast state is invalid")
    for key in ("cast_fingerprint", "provider_fingerprint"):
        value = image_phase.get(key)
        if value is not None and (
            not isinstance(value, str) or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)
        ):
            raise ValueError("multimodal smoke image provenance state is invalid")
    if "submission_consumed" in video and type(video["submission_consumed"]) is not bool:
        raise ValueError("multimodal smoke video consumed state is invalid")
    if video.get("submission_consumed") is True and video.get("attempt") != 1:
        raise ValueError("multimodal smoke video attempt ledger is invalid")
    has_paid_counter = "paid_submission_count" in video
    has_unknown_counter = "submission_unknown_count" in video
    if has_unknown_counter and not has_paid_counter:
        raise ValueError("multimodal smoke video split accounting is incomplete")
    if has_paid_counter:
        paid = video["paid_submission_count"]
        if type(paid) is not int or paid not in {0, 1}:
            raise ValueError("multimodal smoke video paid submission ledger is invalid")
    else:
        paid = 0
    unknown = video.get("submission_unknown_count", 0)
    if type(unknown) is not int or unknown not in {0, 1}:
        raise ValueError("multimodal smoke video unknown submission ledger is invalid")
    legacy_consumed = (
        not has_unknown_counter
        and video.get("submission_consumed") is True
        and video.get("attempt") == 1
        and (not has_paid_counter or paid == 1)
    )
    if not legacy_consumed and paid + unknown != int(video.get("submission_consumed") is True):
        raise ValueError("multimodal smoke video submission accounting is inconsistent")
    for phase_name in ("real_text", "all_character_images", "real_video"):
        real = phases[phase_name].get("real")
        if real is not None and type(real) is not bool:
            raise ValueError("multimodal smoke real-mode state is invalid")
    text = phases["real_text"]
    for key in ("spent_cost_cny", "total_budget_cny", "deadline_epoch", "cost_baseline_cny"):
        if key in text:
            value = text[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
                raise ValueError("multimodal smoke text billing state is invalid")
    if "dirty_line_baseline" in text and (
        type(text["dirty_line_baseline"]) is not int or text["dirty_line_baseline"] < 0
    ):
        raise ValueError("multimodal smoke text billing state is invalid")
    completed_steps = text.get("completed_steps")
    if completed_steps is not None and (
        not isinstance(completed_steps, list)
        or any(not isinstance(step, str) for step in completed_steps)
        or completed_steps != list(TEXT_STEP_TASKS)[:len(completed_steps)]
    ):
        raise ValueError("multimodal smoke text station state is invalid")
    if "elapsed_seconds" in text and _safe_non_negative(text["elapsed_seconds"]) is None:
        raise ValueError("multimodal smoke text elapsed state is invalid")
    if "llm_calls" in text and (
        type(text["llm_calls"]) is not int or _safe_count(text["llm_calls"]) != text["llm_calls"]
    ):
        raise ValueError("multimodal smoke text call state is invalid")
    model_fingerprints = text.get("model_fingerprints")
    if model_fingerprints is not None and (
        not isinstance(model_fingerprints, dict)
        or tuple(model_fingerprints) != tuple(TEXT_STEP_TASKS)
        or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)
            for value in model_fingerprints.values()
        )
    ):
        raise ValueError("multimodal smoke text model identity state is invalid")
    provider_fingerprints = text.get("provider_fingerprints")
    if provider_fingerprints is not None and (
        not isinstance(provider_fingerprints, dict)
        or tuple(provider_fingerprints) != tuple(TEXT_STEP_TASKS)
        or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)
            for value in provider_fingerprints.values()
        )
    ):
        raise ValueError("multimodal smoke text provider identity state is invalid")
    return raw


def _new_state(workspace: str) -> Dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "workspace": workspace,
        "phases": {phase: {"status": "pending"} for phase in PHASES},
        "image_attempts": {},
        "image_estimated_spend_cny": 0.0,
        "status": "pending",
        "updated_at": int(time.time()),
    }


def _adopt_existing_workspace_text(workspace: str, state: Dict[str, Any]) -> None:
    """Freeze an existing Web drama's approved episode-1 text artifacts.

    This is a non-destructive media handoff, not a claim that the text was
    generated by this calibration runner.  The phase is therefore marked
    ``real=False`` while its exact artifacts are pinned for drift detection.
    """

    from .web import workspace_meta

    root = paths.workspace_root(workspace)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("existing multimodal workspace must be a regular directory")
    if workspace_meta.read(workspace).get("type") != "drama":
        raise ValueError("existing multimodal workspace must be a drama workspace")
    _assert_media_workspace_paths_safe(workspace)
    completed = list(TEXT_STEP_TASKS)
    try:
        fingerprints = {
            step: _text_artifact_fingerprint(workspace, step)
            for step in completed
        }
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError(
            "existing drama workspace requires one fresh approved episode before media generation"
        ) from exc
    state["phases"]["real_text"] = {
        "status": "succeeded",
        "real": False,
        "completed_steps": completed,
        "artifact_fingerprints": fingerprints,
        "station_evidence": {},
        "call_baseline": {},
        "spent_cost_cny": 0.0,
        "elapsed_seconds": 0.0,
        "llm_calls": 0,
        "imported_existing_workspace": True,
    }


def _assert_relative_path_components_safe(
    root: Path, relative: Path, *, require_file: bool = False
) -> None:
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("existing multimodal workspace contains an unsafe path")
    cursor = root
    for index, part in enumerate(relative.parts):
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            if require_file:
                raise ValueError("existing multimodal workspace artifact is missing")
            return
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("existing multimodal workspace path must be non-symlink")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ValueError("existing multimodal workspace path component is not a directory")
        if index == len(relative.parts) - 1 and require_file and not stat.S_ISREG(info.st_mode):
            raise ValueError("existing multimodal workspace artifact is not a regular file")


def _assert_media_workspace_paths_safe(workspace: str) -> None:
    """Reject nested symlinks before reading or writing adopted media state."""

    root = paths.workspace_root(workspace)
    try:
        root_info = root.lstat()
    except FileNotFoundError as exc:
        raise ValueError("existing multimodal workspace is missing") from exc
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise ValueError("existing multimodal workspace must be a regular directory")
    ep = episode_paths(workspace, episode_no=1)
    cp = character_paths(workspace)
    required = (
        ep.setup_path, ep.storyboard_path, ep.review_path,
        ep.episode_path, ep.meta_path, cp.sheet_path,
    )
    for target in required:
        _assert_relative_path_components_safe(
            root, target.relative_to(root), require_file=True
        )
    for relative in (
        Path("logs"), Path("data"), Path("data/character_refs"),
    ):
        _assert_relative_path_components_safe(root, relative)


def _ensure_media_text_ready(workspace: str) -> Dict[str, str]:
    """Validate/migrate a fresh approved assembly before any image request."""

    _assert_media_workspace_paths_safe(workspace)
    drama_store.assemble_episode(workspace, episode_no=1)
    if drama_store.is_episode_stale(workspace, episode_no=1):
        raise ValueError("existing drama workspace requires one fresh approved episode")
    return {
        step: _text_artifact_fingerprint(workspace, step)
        for step in TEXT_STEP_TASKS
    }


@contextmanager
def _orchestrator_lock(workspace: str):
    """Cross-process claim spanning state read/claim and all paid attempts."""
    root = paths.workspace_root(workspace)
    lock = root.parent / f".{root.name}.drama_multimodal_smoke.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(lock), flags, 0o600)
    except OSError as exc:
        raise ValueError("multimodal smoke lock must be a safe regular file") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise ValueError("multimodal smoke lock must be a safe regular file")
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("multimodal_smoke_busy") from exc
        yield
    finally:
        os.close(fd)


@contextmanager
def _direct_workspace_guard(workspace: str, phase: str):
    """Make direct image/assembly phases visible to standard Web/job writers."""
    with use_workspace(workspace):
        with acquire_write_lock(source=f"drama-multimodal-{phase}"):
            yield


def _save(state: Dict[str, Any]) -> None:
    state["updated_at"] = int(time.time())
    payload = (
        json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    ai_draw_client._atomic_write_bytes(state_path(str(state["workspace"])), payload)


def _profile_prompt(character: Mapping[str, Any], *, simplified: bool) -> tuple[str, str, str]:
    name = str(character.get("name") or "原创角色")[:80]
    render_view = _character_render_view(character)
    signature = json.dumps(render_view, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if simplified:
        profile = "retry_simplified_v1"
        prompt = f"原创角色{name}，{signature[:240]}，单人全身立绘，纯净背景，无文字无水印。"
    else:
        profile = "initial_complete_v1"
        prompt = (
            f"原创角色{name}。主体与服装：{signature[:700]}。构图：单人全身立绘，正面自然站姿；"
            "背景：简洁中性影棚背景；画面不得出现文字、标志或水印。"
        )
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return prompt, profile, digest


def _character_render_view(character: Mapping[str, Any]) -> Dict[str, Any]:
    """Canonical visual inputs; references/appearances are provenance, not prompt."""

    def bounded(value: Any, limit: int) -> Any:
        if isinstance(value, str):
            return value[:limit]
        if isinstance(value, list):
            return [bounded(item, limit) for item in value[:20]]
        if isinstance(value, dict):
            return {
                str(key)[:80]: bounded(item, limit)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))[:40]
            }
        if value is None or type(value) in {bool, int, float}:
            return value
        return str(value)[:limit]

    return {
        key: bounded(character.get(key), 800)
        for key in (
            "id", "name", "role", "age_range", "gender", "lora_token",
            "visual_features", "wardrobe_default", "expression_keywords",
            "visual_signature", "prompt_template_sd", "visual_contrast_with",
        )
    }


def _image_cast_fingerprint(characters: list[Dict[str, Any]]) -> str:
    payload = [
        _character_render_view(item)
        for item in sorted(characters, key=lambda row: str(row.get("id") or ""))
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _image_provider_fingerprint() -> str:
    if str(os.getenv("AI_DRAW_ENDPOINT") or "").strip():
        raise ValueError("multimodal image smoke requires the bounded OpenAI-compatible image API")
    base_url, api_key = _resolve_openai_draw_credentials()
    if not base_url or not api_key:
        raise ValueError("AI draw requires a base URL and API key")
    endpoint = _images_generation_url(base_url)
    parsed = validate_api_base_url(endpoint, label="AI draw base URL")
    _validate_public_endpoint(parsed.hostname)
    model = str(os.getenv("AI_DRAW_MODEL") or DEFAULT_IMAGE_MODEL).strip()
    if not model or len(model) > 80 or any(char in model for char in "\r\n\x00"):
        raise ValueError("AI_DRAW_MODEL must be 1-80 characters without controls")
    if any(char in api_key for char in "\r\n\x00"):
        raise ValueError("AI draw API key contains control characters")
    payload = {
        "endpoint": endpoint.rstrip("/"),
        "model": model,
        "account_sha256": hashlib.sha256(api_key.encode("utf-8")).hexdigest(),
        "result_hosts": sorted(
            item.strip().rstrip(".").lower()
            for item in str(os.getenv("AI_DRAW_RESULT_HOSTS") or "").split(",")
            if item.strip()
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _appearing_characters(sheet: CharacterSheet) -> list[Dict[str, Any]]:
    return [
        item for item in model_to_dict(sheet).get("characters", [])
        if 1 in (item.get("appearances") or [1])
    ]


def _replace_character_reference(workspace: str, character_id: str, generated: Dict[str, Any]) -> None:
    cp = character_paths(workspace)
    raw = read_json_optional(cp.sheet_path, None)
    sheet = CharacterSheet(**raw)
    payload = model_to_dict(sheet)
    found = False
    for item in payload["characters"]:
        if item.get("id") == character_id:
            item["reference_images"] = [generated]
            found = True
            break
    if not found:
        raise ValueError("character disappeared before image commit")
    drama_store.migrate_fresh_episode_fingerprints_v2(workspace)
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    ai_draw_client._atomic_write_bytes(cp.sheet_path, encoded)


def _workspace_path_uses_symlink(root: Path, relative_path: str) -> bool:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        return True
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return True
    return False


def _read_attempt_image(workspace: str, relative_path: str) -> bytes:
    root = paths.workspace_root(workspace).resolve()
    if not relative_path or _workspace_path_uses_symlink(root, relative_path):
        raise ValueError("image attempt path is unsafe")
    target = root / relative_path
    resolved = target.resolve(strict=True)
    resolved.relative_to(root)
    if target.is_symlink() or not resolved.is_file():
        raise ValueError("image attempt artifact is not a regular workspace file")
    data = target.read_bytes()
    _detect_image_type(data)
    return data


def _recover_started_image_receipt(
    workspace: str,
    character: Mapping[str, Any],
    audit: Dict[str, Any],
) -> bool:
    staging_rel = audit.get("staging_path")
    cid = str(character.get("id") or "")
    if (
        audit.get("status") != "started"
        or not _valid_image_staging_path(cid, audit)
        or not isinstance(staging_rel, str)
    ):
        return False
    try:
        data = _read_attempt_image(workspace, staging_rel)
    except (OSError, ValueError):
        return False
    canonical_rel = f"data/character_refs/{cid}/portrait_neutral.png"
    requested_model = _safe_short_text(audit.get("requested_model")) or DEFAULT_IMAGE_MODEL
    prompt_profile = str(audit.get("prompt_profile") or "full")[:40]
    prompt_sha = str(audit.get("prompt_sha256") or "")
    width, height = _image_dimensions(data, "image/png")
    record = model_to_dict(ReferenceImage(**{
        "path": canonical_rel,
        "generated_by": requested_model,
        "prompt": f"<{prompt_profile}:{prompt_sha[:16]}>",
        "requested_model": requested_model,
        "requested_size": DEFAULT_IMAGE_SIZE,
        "width": width,
        "height": height,
    }))
    audit.update({
        "artifact_path": canonical_rel,
        "artifact_sha256": hashlib.sha256(data).hexdigest(),
        "artifact_record": record,
        "artifact_record_sha256": _canonical_sha256(record),
        "file_size_bytes": len(data),
        "width": width,
        "height": height,
        "status": "artifact_received",
        "recovered_from_staging": True,
    })
    return True


def _commit_received_image_attempt(
    workspace: str,
    character_id: str,
    audit: Dict[str, Any],
    *,
    provider_fingerprint: str,
) -> None:
    artifact_record = audit.get("artifact_record")
    canonical_rel = audit.get("artifact_path")
    staging_rel = audit.get("staging_path")
    if not isinstance(artifact_record, dict) or not isinstance(canonical_rel, str):
        raise ValueError("received image attempt is missing recoverable artifact state")
    if audit.get("provider_fingerprint") != provider_fingerprint:
        raise ValueError("received image artifact provider identity changed before commit")
    if isinstance(staging_rel, str) and not _valid_image_staging_path(character_id, audit):
        raise ValueError("received image artifact staging identity changed before commit")
    normalized = model_to_dict(ReferenceImage(**artifact_record))
    if audit.get("artifact_record_sha256") != _canonical_sha256(normalized):
        raise ValueError("received image artifact metadata changed before commit")
    source_rel = staging_rel if isinstance(staging_rel, str) else canonical_rel
    try:
        data = _read_attempt_image(workspace, source_rel)
    except (OSError, ValueError):
        if source_rel == canonical_rel:
            raise
        data = _read_attempt_image(workspace, canonical_rel)
    if hashlib.sha256(data).hexdigest() != audit.get("artifact_sha256"):
        raise ValueError("received image artifact hash changed before commit")
    root = paths.workspace_root(workspace)
    canonical_path = root / canonical_rel
    if source_rel != canonical_rel:
        _atomic_write_bytes(canonical_path, data)
    _replace_character_reference(workspace, character_id, normalized)
    audit["status"] = "succeeded"
    if isinstance(staging_rel, str) and staging_rel != canonical_rel:
        (root / staging_rel).unlink(missing_ok=True)


def _completed_image_is_current(
    workspace: str,
    character: Mapping[str, Any],
    records: list[Dict[str, Any]],
    *,
    provider_fingerprint: str | None = None,
) -> bool:
    succeeded = next((row for row in reversed(records) if row.get("status") == "succeeded"), None)
    if succeeded is None:
        return False
    refs = character.get("reference_images")
    if not isinstance(refs, list) or len(refs) != 1 or not isinstance(refs[0], dict):
        return False
    rel = str(succeeded.get("artifact_path") or "")
    try:
        current_record = model_to_dict(ReferenceImage(**refs[0]))
        paid_record = model_to_dict(ReferenceImage(**succeeded.get("artifact_record")))
    except Exception:
        return False
    if (
        current_record.get("path") != rel
        or not rel
        or _canonical_sha256(current_record) != succeeded.get("artifact_record_sha256")
        or _canonical_sha256(paid_record) != succeeded.get("artifact_record_sha256")
        or (provider_fingerprint is not None and succeeded.get("provider_fingerprint") != provider_fingerprint)
    ):
        return False
    root = paths.workspace_root(workspace).resolve()
    try:
        if _workspace_path_uses_symlink(root, rel):
            return False
        target = (root / rel).resolve()
        target.relative_to(root)
        if not target.is_file():
            return False
        data = target.read_bytes()
        _detect_image_type(data)
        digest = hashlib.sha256(data).hexdigest()
    except (OSError, ValueError):
        return False
    return digest == succeeded.get("artifact_sha256")


def _all_completed_images_are_current(workspace: str, state: Mapping[str, Any]) -> bool:
    raw = read_json_optional(character_paths(workspace).sheet_path, None)
    sheet = CharacterSheet(**raw)
    characters = _appearing_characters(sheet)
    phase = (state.get("phases") or {}).get("all_character_images") or {}
    current_ids = sorted(str(item.get("id") or "") for item in characters)
    if phase.get("cast_ids") != current_ids:
        return False
    if phase.get("cast_fingerprint") != _image_cast_fingerprint(characters):
        return False
    attempts = state.get("image_attempts") or {}
    for character in characters:
        records = attempts.get(str(character["id"]))
        if not isinstance(records, list) or not _completed_image_is_current(
            workspace,
            character,
            records,
            provider_fingerprint=phase.get("provider_fingerprint"),
        ):
            return False
        succeeded = next(row for row in reversed(records) if row.get("status") == "succeeded")
        _prompt, _profile, current_hash = _profile_prompt(character, simplified=int(succeeded["attempt"]) > 1)
        if succeeded.get("prompt_sha256") != current_hash:
            return False
    return True


def _insight_billing(workspace: str) -> tuple[float, int]:
    ledger = collect_drama_insights(workspace).get("llm_cost", {})
    value = ledger.get("cost_cny", 0.0)
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("drama text cost ledger is invalid") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError("drama text cost ledger is invalid")
    dirty = ledger.get("dirty_lines", 0)
    if type(dirty) is not int or dirty < 0:
        raise ValueError("drama text cost ledger is invalid")
    return number, dirty


def _run_images(workspace: str, state: Dict[str, Any], options: Mapping[str, Any], *, real_image: bool) -> bool:
    phase = state["phases"]["all_character_images"]
    if "real" in phase and phase.get("real") is not real_image:
        raise ValueError("image resume mode differs from the original image-stage authorization")
    phase["real"] = real_image
    raw = read_json_optional(character_paths(workspace).sheet_path, None)
    sheet = CharacterSheet(**raw)
    characters = _appearing_characters(sheet)
    if not characters:
        raise ValueError("episode 1 has no appearing characters")
    root = paths.workspace_root(workspace)
    for character in characters:
        cid = str(character.get("id") or "")
        _assert_relative_path_components_safe(
            root, Path("data") / "character_refs" / cid
        )
        _assert_relative_path_components_safe(
            root, Path("logs") / "drama_multimodal_images" / cid
        )
    if real_image:
        if options.get("confirm_real_image") is not True:
            raise MultimodalAuthorizationError("confirm_real_image=true is required for this invocation")
        image_budget = _positive(options.get("image_budget_cny"), "image_budget_cny")
        estimate = _positive(options.get("image_estimated_cost_cny"), "image_estimated_cost_cny")
        initial_timeout = _positive(options.get("image_timeout_seconds"), "image_timeout_seconds", maximum=3600)
        provider_fingerprint = _image_provider_fingerprint()
        if "total_budget_cny" not in phase:
            phase["total_budget_cny"] = image_budget
            phase["estimated_cost_per_attempt_cny"] = estimate
        elif image_budget != float(phase["total_budget_cny"]) or estimate != float(phase["estimated_cost_per_attempt_cny"]):
            raise ValueError("image resume budget and estimate must match the original image-stage authorization")
    else:
        image_budget, estimate, initial_timeout = 0.0, 0.0, 30.0
        provider_fingerprint = _model_sha256("mock")

    cast_ids = sorted(str(item.get("id") or "") for item in characters)
    cast_fingerprint = _image_cast_fingerprint(characters)
    if "cast_ids" not in phase:
        phase["cast_ids"] = cast_ids
        phase["cast_fingerprint"] = cast_fingerprint
        phase["provider_fingerprint"] = provider_fingerprint
    elif (
        phase.get("cast_ids") != cast_ids
        or phase.get("cast_fingerprint") != cast_fingerprint
        or phase.get("provider_fingerprint") != provider_fingerprint
    ):
        raise ValueError("image resume cast, rendering inputs, or provider identity changed")
    _save(state)

    attempts = state.setdefault("image_attempts", {})
    for character in characters:
        cid = str(character["id"])
        records = attempts.setdefault(cid, [])
        if any(
            row.get("status") in IMAGE_RECEIPT_STATUSES
            and not isinstance(row.get("artifact_record_sha256"), str)
            for row in records
            if isinstance(row, dict)
        ):
            phase.update({
                "status": "blocked",
                "error_code": "image_provenance_upgrade_required",
                "character_id": cid,
            })
            state["status"] = "blocked"
            _save(state)
            return False
        if real_image and phase.get("provider_fingerprint") != _image_provider_fingerprint():
            raise ValueError("image provider identity changed during the authorized run")
        if records and real_image and _recover_started_image_receipt(
            workspace, character, records[-1]
        ):
            _save(state)
        if records and records[-1].get("status") == "artifact_received":
            pending = records[-1]
            try:
                _commit_received_image_attempt(
                    workspace, cid, pending, provider_fingerprint=provider_fingerprint
                )
            except (OSError, ValueError) as exc:
                raise ValueError("received image artifact is missing") from exc
            _save(state)
        current = next((item for item in _appearing_characters(CharacterSheet(**read_json_optional(character_paths(workspace).sheet_path, None))) if item["id"] == cid), character)
        if _completed_image_is_current(
            workspace, current, records, provider_fingerprint=provider_fingerprint
        ):
            continue
        attempt_no = len(records) + 1
        if attempt_no > MAX_IMAGE_ATTEMPTS_PER_CHARACTER:
            phase.update({"status": "failed", "error_code": "image_attempt_limit_exhausted", "character_id": cid})
            state["status"] = "failed"
            _save(state)
            return False
        is_retry = attempt_no > 1
        if is_retry and (options.get("confirm_image_retry") is not True or options.get("confirm_upstream_status_and_billing_checked") is not True):
            phase.update({"status": "awaiting_retry_authorization", "character_id": cid, "next_attempt": attempt_no})
            state["status"] = "awaiting_retry_authorization"
            _save(state)
            return False
        if real_image and state["image_estimated_spend_cny"] + estimate > float(phase["total_budget_cny"]):
            phase.update({"status": "blocked", "error_code": "image_budget_exhausted", "character_id": cid})
            state["status"] = "blocked"
            _save(state)
            return False
        prompt, profile, prompt_hash = _profile_prompt(character, simplified=is_retry)
        timeout = RETRY_TIMEOUT_SECONDS if is_retry else initial_timeout
        audit = {
            "attempt": attempt_no,
            "timeout_seconds": timeout,
            "prompt_profile": profile,
            "prompt_sha256": prompt_hash,
            "estimated_cost_cny": estimate if real_image else 0.0,
            "provider_fingerprint": provider_fingerprint,
            "status": "started",
        }
        if real_image:
            staging_rel = (
                f"logs/drama_multimodal_images/{cid}/"
                f"attempt_{attempt_no}_{secrets.token_urlsafe(12)}.png"
            )
            audit.update({
                "staging_path": staging_rel,
                "requested_model": str(os.getenv("AI_DRAW_MODEL") or DEFAULT_IMAGE_MODEL),
                "requested_size": DEFAULT_IMAGE_SIZE,
            })
        records.append(audit)
        if real_image:
            state["image_estimated_spend_cny"] = round(float(state["image_estimated_spend_cny"]) + estimate, 6)
        _save(state)  # audit before any possibly billable request
        attempt_started = time.monotonic()
        try:
            if real_image:
                generated = redraw_character_reference(
                    workspace,
                    character,
                    mock=False,
                    prompt_override=prompt,
                    timeout_seconds=timeout,
                    output_path=paths.workspace_root(workspace) / audit["staging_path"],
                )
            else:
                rel = f"data/character_refs/{cid}/portrait_neutral.png"
                _atomic_write_bytes(paths.workspace_root(workspace) / rel, _PNG_1X1)
                generated = {
                    "path": rel, "generated_by": "mock-multimodal-smoke",
                    "prompt": "<mock>", "requested_model": "mock",
                    "requested_size": "1x1", "provider_size": "1x1",
                    "width": 1, "height": 1,
                }
            # Keep request prompts out of the public character projection. The
            # canonical source prompt remains untouched on the character itself.
            source_rel = str(generated["path"])
            if real_image and source_rel != audit.get("staging_path"):
                raise ValueError("AI draw provider did not use the authorized staging path")
            source_data = _read_attempt_image(workspace, source_rel)
            generated["prompt"] = f"<{profile}:{prompt_hash[:16]}>"
            generated["path"] = f"data/character_refs/{cid}/portrait_neutral.png"
            audit["artifact_path"] = generated["path"]
            audit["artifact_sha256"] = hashlib.sha256(source_data).hexdigest()
            for source, target in (
                ("generated_by", "generated_by"),
                ("requested_model", "requested_model"),
                ("provider_model", "provider_model"),
                ("requested_size", "requested_size"),
                ("provider_size", "provider_size"),
            ):
                safe_value = _safe_short_text(generated.get(source))
                if safe_value is not None:
                    audit[target] = safe_value
            for source, target in (("width", "width"), ("height", "height")):
                value = generated.get(source)
                if type(value) is int and 0 < value <= 100_000:
                    audit[target] = value
            try:
                audit["file_size_bytes"] = len(source_data)
            except OSError:
                pass
            audit["artifact_record"] = model_to_dict(ReferenceImage(**{
                key: generated[key]
                for key in (
                    "path", "generated_by", "prompt", "seed", "requested_model",
                    "provider_model", "requested_size", "provider_size", "width", "height",
                )
                if key in generated
            }))
            audit["artifact_record_sha256"] = _canonical_sha256(audit["artifact_record"])
            audit["status"] = "artifact_received"
            _save(state)
        except AIDrawTimeout:
            audit["status"] = "timeout"
        except AIDrawNetworkError:
            audit["status"] = "network_error"
        except AIDrawProviderError:
            audit["status"] = "provider_error"
        except RequestNotSentError:
            records.pop()
            if real_image:
                state["image_estimated_spend_cny"] = round(
                    max(0.0, float(state["image_estimated_spend_cny"]) - estimate), 6
                )
            phase.update({"status": "blocked", "error_code": "image_request_not_sent", "character_id": cid})
            state["status"] = "blocked"
            _save(state)
            return False
        except Exception:
            audit["status"] = "local_error"
        if audit["status"] == "artifact_received":
            try:
                _commit_received_image_attempt(
                    workspace, cid, audit, provider_fingerprint=provider_fingerprint
                )
            except Exception:
                audit["elapsed_seconds"] = round(max(0.0, time.monotonic() - attempt_started), 3)
                _save(state)
                raise
        audit["elapsed_seconds"] = round(max(0.0, time.monotonic() - attempt_started), 3)
        _save(state)
        if audit["status"] != "succeeded":
            if attempt_no < MAX_IMAGE_ATTEMPTS_PER_CHARACTER:
                phase.update({"status": "awaiting_retry_authorization", "character_id": cid, "next_attempt": attempt_no + 1})
                state["status"] = "awaiting_retry_authorization"
            else:
                phase.update({"status": "failed", "error_code": "image_attempt_limit_exhausted", "character_id": cid})
                state["status"] = "failed"
            _save(state)
            return False
    phase.update({
        "status": "succeeded", "real": real_image, "character_count": len(characters),
        "cast_ids": cast_ids, "cast_fingerprint": cast_fingerprint,
        "provider_fingerprint": provider_fingerprint,
    })
    state["status"] = "running"
    _save(state)
    return True


def _video_readiness(workspace: str, options: Mapping[str, Any], *, real_video: bool) -> Dict[str, Any]:
    inputs = drama_video.load_video_inputs(workspace, episode_no=1)
    result: Dict[str, Any] = {"input_fingerprint": inputs.fingerprint, "reference_count": len(inputs.references)}
    if real_video:
        if options.get("confirm_real_video") is not True:
            raise MultimodalAuthorizationError("confirm_real_video=true is required for this invocation")
        os.environ["SD_VIDEO_MODE"] = "real"
        submission, public_video_state, resuming_submitted = (
            _video_submission_view(workspace)
        )
        needs_new_submission = (
            submission is None or submission.get("status") == "request_not_sent"
        )
        if resuming_submitted:
            try:
                budget = float(submission["authorized_budget_cny"])
                timeout = float(submission["authorized_timeout_minutes"]) * 60.0
                estimate = float(submission["estimated_cost_cny"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    "submitted video task requires authorization reconciliation"
                ) from exc
        else:
            budget = _positive(options.get("video_budget_cny"), "video_budget_cny")
            timeout = _positive(
                options.get("video_timeout_seconds"),
                "video_timeout_seconds", maximum=3600,
            )
        callback_confirmed = (
            options.get("confirm_asset_callback_reachable") is True
            or options.get("confirm_asset_callback_same_process") is True
        )
        if needs_new_submission and not callback_confirmed:
            raise MultimodalAuthorizationError(
                "operator must confirm the provider callback URL reaches the shared asset service"
            )
        if not resuming_submitted:
            _, _, estimate = drama_video.validate_real_video_gate({
                "confirm_real_video": True,
                "budget_cny": budget,
                "timeout_minutes": timeout / 60.0,
            })
        if needs_new_submission:
            public_base = str(os.getenv("SD_ASSET_PUBLIC_BASE_URL") or "").strip()
            validate_api_base_url(public_base, label="SD_ASSET_PUBLIC_BASE_URL")
        hosts = [item.strip() for item in str(os.getenv("SD_VIDEO_RESULT_HOSTS") or "").split(",") if item.strip()]
        if not hosts:
            raise ValueError("SD_VIDEO_RESULT_HOSTS must contain an exact provider result host")
        result.update({
            "estimated_cost_cny": estimate,
            "budget_cny": budget,
            "callback_reachability_confirmed": callback_confirmed,
            "resuming_submitted_task": resuming_submitted,
        })
    return result


def _validate_invocation(
    real_text: bool,
    real_image: bool,
    real_video: bool,
    opts: Mapping[str, Any],
    *,
    resuming_submitted_video: bool = False,
) -> None:
    """Validate only the paid stages explicitly requested in this invocation."""
    if real_text:
        if opts.get("confirm_real_text") is not True:
            raise MultimodalAuthorizationError("confirm_real_text=true is required for this invocation")
        _positive(opts.get("text_budget_cny"), "text_budget_cny")
        _positive(opts.get("text_timeout_seconds"), "text_timeout_seconds", maximum=86400)
    if real_image:
        if opts.get("confirm_real_image") is not True:
            raise MultimodalAuthorizationError("confirm_real_image=true is required for this invocation")
        _positive(opts.get("image_budget_cny"), "image_budget_cny")
        _positive(opts.get("image_estimated_cost_cny"), "image_estimated_cost_cny")
        _positive(opts.get("image_timeout_seconds"), "image_timeout_seconds", maximum=3600)
    if real_video:
        if opts.get("confirm_real_video") is not True:
            raise MultimodalAuthorizationError("confirm_real_video=true is required for this invocation")
        if not resuming_submitted_video:
            _positive(opts.get("video_budget_cny"), "video_budget_cny")
            _positive(opts.get("video_timeout_seconds"), "video_timeout_seconds", maximum=3600)


def run(
    workspace: str,
    *,
    real_text: bool = False,
    real_image: bool = False,
    real_video: bool = False,
    options: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    if not real_text:
        os.environ["OPENAI_MODEL"] = "mock"
        os.environ["DRAMA_MODEL"] = "mock"
        os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"
    opts = dict(options or {})
    _existing_submission, _existing_video_status, resuming_submitted_video = (
        _video_submission_view(workspace) if real_video else (None, {}, False)
    )
    _validate_invocation(
        real_text, real_image, real_video, opts,
        resuming_submitted_video=resuming_submitted_video,
    )
    if real_text and not drama_smoke.real_text_tasks_ready():
        if any(
            error.endswith(":model_mock")
            for error in drama_smoke.real_text_readiness_errors()
        ):
            raise RuntimeError("real_text_tasks_still_mock")
        drama_smoke.validate_real_text_tasks_ready()
    # Authorization is validated above, so it is now safe to merge .env. Do
    # this even with an ambient key/base: policy-critical non-secret values
    # (result-host allowlists, callback base, model and cost estimate) may live
    # only in .env. python-dotenv preserves explicit ambient values, while
    # canonical/tests can still forbid all dotenv reads with the skip flag.
    if real_image or real_video:
        load_dotenv_if_available()
    with _orchestrator_lock(workspace):
        return _run_claimed(
            workspace, real_text=real_text, real_image=real_image,
            real_video=real_video, options=opts,
        )


def _run_claimed(
    workspace: str,
    *,
    real_text: bool,
    real_image: bool,
    real_video: bool,
    options: Mapping[str, Any],
) -> Dict[str, Any]:
    opts = dict(options)
    mock_all = not (real_text or real_image or real_video)
    existing = load_state(workspace)
    if existing is None:
        if paths.workspace_root(workspace).exists():
            if real_text or not (real_image or real_video):
                raise ValueError("fresh multimodal smoke requires a new workspace name")
            state = _new_state(workspace)
            # Compatibility migration and artifact pinning happen under the
            # standard workspace lock before the first durable runner state is
            # written. A crash can therefore restart adoption cleanly instead
            # of leaving old hashes pinned to upgraded review artifacts.
            with _direct_workspace_guard(workspace, "adopt-text"):
                _ensure_media_text_ready(workspace)
                _adopt_existing_workspace_text(workspace, state)
        else:
            drama_smoke._create_workspace(workspace, "推理")
            state = _new_state(workspace)
    else:
        state = existing
    for requested, phase_name in (
        (real_text, "real_text"), (real_image, "all_character_images"), (real_video, "real_video")
    ):
        phase_row = state["phases"][phase_name]
        if requested and phase_row.get("status") == "succeeded" and phase_row.get("real") is False:
            raise ValueError(f"cannot upgrade completed mock phase {phase_name} to a real paid phase")
    state["status"] = "running"
    _save(state)

    completed_text = state["phases"]["real_text"]
    if (
        completed_text.get("status") == "succeeded"
        and not _text_artifacts_current(workspace, completed_text)
    ):
        completed_text.update({"status": "blocked", "error_code": "text_artifact_drift"})
        state["status"] = "blocked"
        _save(state)
        return state

    if state["phases"]["real_text"]["status"] != "succeeded":
        if not (real_text or mock_all):
            state["status"] = "awaiting_text_authorization"
            _save(state)
            return state
        if real_text:
            requested_budget = _positive(opts.get("text_budget_cny"), "text_budget_cny")
            requested_timeout = _positive(opts.get("text_timeout_seconds"), "text_timeout_seconds", maximum=86400)
        else:
            requested_budget, requested_timeout = 0.0, 60.0
        phase = state["phases"]["real_text"]
        phase.setdefault("completed_steps", [])
        phase.setdefault("spent_cost_cny", 0.0)
        phase.setdefault("elapsed_seconds", 0.0)
        phase.setdefault("station_evidence", {})
        phase.setdefault("call_baseline", _drama_call_counts(workspace))
        phase.setdefault("artifact_fingerprints", {})
        if phase["completed_steps"] and not _text_artifacts_current(workspace, phase):
            phase.update({"status": "blocked", "error_code": "text_artifact_drift"})
            state["status"] = "blocked"
            _save(state)
            return state
        if real_text:
            current_fingerprints = _text_model_fingerprints()
            if "model_fingerprints" not in phase:
                phase["model_fingerprints"] = current_fingerprints
            elif phase["model_fingerprints"] != current_fingerprints:
                raise ValueError("text resume model identity differs from the original authorization")
            current_provider_fingerprints = _text_provider_fingerprints()
            if "provider_fingerprints" not in phase:
                phase["provider_fingerprints"] = current_provider_fingerprints
            elif phase["provider_fingerprints"] != current_provider_fingerprints:
                raise ValueError("text resume provider identity differs from the original authorization")
        if "cost_baseline_cny" not in phase:
            baseline_cost, baseline_dirty = _insight_billing(workspace)
            phase["cost_baseline_cny"] = baseline_cost
            phase["dirty_line_baseline"] = baseline_dirty
        else:
            phase.setdefault("dirty_line_baseline", 0)
        # Crash recovery reconciliation must happen before calculating a
        # remaining budget or starting the next station. LLM logs are durable
        # even if the previous process died before its exception handler.
        current_cost, current_dirty = _insight_billing(workspace)
        if current_dirty != int(phase["dirty_line_baseline"]):
            raise ValueError("drama text billing evidence became dirty during the paid run")
        cost_baseline = float(phase["cost_baseline_cny"])
        if current_cost < cost_baseline:
            raise ValueError("drama text cost ledger regressed below the run baseline")
        phase["spent_cost_cny"] = round(
            max(float(phase["spent_cost_cny"]), current_cost - cost_baseline), 6
        )
        # A previous process may have died after persisting active_step and
        # making a provider call.  Unlike an exception handled in this process,
        # that submission outcome is ambiguous: never clear/retry it from state
        # alone.  Require an explicit operator reconciliation on the resume.
        retry_step = (
            phase.get("active_step")
            if phase.get("active_step") in TEXT_STEP_TASKS
            else phase.get("retry_required_step")
        )
        if real_text and retry_step in TEXT_STEP_TASKS and _adopt_durable_text_station(workspace, phase, retry_step):
            retry_step = None
            _save(state)
        if real_text and retry_step in TEXT_STEP_TASKS and not (
            opts.get("confirm_text_retry") is True
            and opts.get("confirm_upstream_status_and_billing_checked") is True
        ):
            phase["status"] = "awaiting_text_retry_authorization"
            state["status"] = "awaiting_text_retry_authorization"
            _save(state)
            return state
        _reconcile_failed_text_station(workspace, phase, real_text=real_text)
        if retry_step in TEXT_STEP_TASKS:
            phase.pop("retry_required_step", None)
        _save(state)
        if real_text:
            if "total_budget_cny" not in phase:
                phase["total_budget_cny"] = requested_budget
                phase["deadline_epoch"] = time.time() + requested_timeout
            elif requested_budget != float(phase["total_budget_cny"]):
                raise ValueError("text resume budget must match the original whole-smoke budget")
            text_budget = max(0.0, float(phase["total_budget_cny"]) - float(phase["spent_cost_cny"]))
            text_timeout = min(requested_timeout, float(phase["deadline_epoch"]) - time.time())
            if text_budget <= 0:
                raise RuntimeError("drama text smoke total budget exhausted")
            if text_timeout <= 0:
                raise drama_smoke.DramaSmokeTimeout("text")
        else:
            text_budget, text_timeout = 0.0, requested_timeout
        phase.update({"status": "running", "real": real_text})
        _save(state)

        def settle_text_spend() -> float:
            current, dirty = _insight_billing(workspace)
            if dirty != int(phase["dirty_line_baseline"]):
                raise ValueError("drama text billing evidence became dirty during the paid run")
            baseline = float(phase["cost_baseline_cny"])
            if current < baseline:
                raise ValueError("drama text cost ledger regressed below the run baseline")
            total = max(float(phase.get("spent_cost_cny") or 0.0), current - baseline)
            phase["spent_cost_cny"] = round(total, 6)
            return total

        def text_step_started(step: str) -> None:
            if step not in TEXT_STEP_TASKS:
                raise ValueError("drama text smoke reported an unknown station")
            phase["active_step"] = step
            phase["active_step_started_at"] = time.time()
            _save(state)  # persist the paid-station claim before its provider call

        def text_step_done(step: str, _result: Dict[str, Any]) -> None:
            current_calls = _drama_call_counts(workspace)
            task = TEXT_STEP_TASKS.get(step)
            if task is None:
                raise ValueError("drama text smoke reported an unknown station")
            if real_text and phase.get("model_fingerprints") != _text_model_fingerprints():
                raise ValueError("text model identity changed during the authorized run")
            if real_text and phase.get("provider_fingerprints") != _text_provider_fingerprints():
                raise ValueError("text provider identity changed during the authorized run")
            spent = settle_text_spend()
            previous = phase["station_evidence"].get(step)
            previous_elapsed = (
                _safe_non_negative(previous.get("elapsed_seconds")) or 0.0
                if isinstance(previous, dict) and previous.get("status") == "failed"
                else 0.0
            )
            phase["station_evidence"][step] = {
                "status": "succeeded",
                "call_count": _call_count_delta(current_calls, phase["call_baseline"], task, "calls"),
                "non_mock_call_count": _call_count_delta(
                    current_calls, phase["call_baseline"], task, "non_mock_calls"
                ),
                "pinned_model_call_count": _model_call_delta(
                    current_calls,
                    phase["call_baseline"],
                    task,
                    (phase.get("model_fingerprints") or {}).get(step, ""),
                ) if real_text else 0,
                "elapsed_seconds": round(
                    previous_elapsed + float(_result.get("elapsed_seconds") or 0.0), 3
                ),
                "cumulative_cost_cny": round(spent, 6),
                "model_sha256": (phase.get("model_fingerprints") or {}).get(step),
            }
            phase["artifact_fingerprints"][step] = _text_artifact_fingerprint(workspace, step)
            phase.pop("active_step", None)
            phase.pop("active_step_started_at", None)
            if step not in phase["completed_steps"]:
                phase["completed_steps"].append(step)
            _save(state)

        invocation_started = time.monotonic()

        def settle_text_runtime() -> None:
            phase["elapsed_seconds"] = round(
                float(phase.get("elapsed_seconds") or 0.0)
                + max(0.0, time.monotonic() - invocation_started),
                3,
            )
            current_calls = _drama_call_counts(workspace)
            phase["llm_calls"] = sum(
                _call_count_delta(current_calls, phase["call_baseline"], task, "calls")
                for task in TEXT_STEP_TASKS.values()
            )

        try:
            result = drama_smoke.run_smoke(
                workspace, real_text=real_text, real_image=False,
                budget_cny=text_budget, timeout_seconds=text_timeout, reset_jobs=False,
                completed_steps=phase["completed_steps"], on_step_start=text_step_started,
                on_step_complete=text_step_done,
                create_workspace=False,
                confirm_text_retry=opts.get("confirm_text_retry") is True,
                confirm_upstream_status_and_billing_checked=(
                    opts.get("confirm_upstream_status_and_billing_checked") is True
                ),
            )
        except Exception as exc:
            settle_text_spend()
            settle_text_runtime()
            failed_step = phase.get("active_step")
            _reconcile_failed_text_station(workspace, phase, real_text=real_text)
            if real_text and failed_step in TEXT_STEP_TASKS:
                phase["retry_required_step"] = failed_step
            phase["status"] = "failed"
            phase["error_code"] = type(exc).__name__
            state["status"] = "failed"
            _save(state)
            raise
        total_spent = settle_text_spend()
        settle_text_runtime()
        state["phases"]["real_text"] = {
            "status": "succeeded", "real": real_text,
            "completed_steps": list(phase["completed_steps"]),
            "spent_cost_cny": round(total_spent, 6),
            "actual_cost_cny": round(total_spent, 6),
            "remaining_budget_cny": round(max(0.0, requested_budget - total_spent), 6),
            "remaining_seconds": round(max(0.0, (float(phase.get("deadline_epoch") or time.time()) - time.time()) if real_text else float(result.get("remaining_seconds") or 0.0)), 3),
            "elapsed_seconds": phase["elapsed_seconds"],
            "llm_calls": phase["llm_calls"],
            "station_evidence": phase["station_evidence"],
            "call_baseline": phase["call_baseline"],
            "artifact_fingerprints": phase["artifact_fingerprints"],
            "budget_semantics": "single_station_may_overshoot_before_settlement",
        }
        if real_text:
            state["phases"]["real_text"].update({
                "total_budget_cny": phase["total_budget_cny"],
                "deadline_epoch": phase["deadline_epoch"],
                "cost_baseline_cny": phase["cost_baseline_cny"],
                "dirty_line_baseline": phase["dirty_line_baseline"],
                "model_fingerprints": phase["model_fingerprints"],
                "provider_fingerprints": phase.get("provider_fingerprints", {}),
            })
        _save(state)

    if real_text and not (real_image or real_video):
        state["status"] = "awaiting_image_authorization"
        _save(state)
        return state

    if state["phases"]["all_character_images"]["status"] != "succeeded":
        if not (real_image or mock_all):
            state["status"] = "awaiting_image_authorization"
            _save(state)
            return state
        with _direct_workspace_guard(workspace, "images"):
            state["phases"]["real_text"]["artifact_fingerprints"] = (
                _ensure_media_text_ready(workspace)
            )
            _save(state)
            if not _run_images(workspace, state, opts, real_image=real_image):
                return state

    if not _all_completed_images_are_current(workspace, state):
        raise ValueError("completed character image provenance no longer matches current artifacts/prompts")

    if state["phases"]["reassemble"]["status"] != "succeeded":
        with _direct_workspace_guard(workspace, "reassemble"):
            drama_store.assemble_episode(workspace, episode_no=1)
        state["phases"]["reassemble"] = {"status": "succeeded"}
        _save(state)

    # Input readiness is useful after images, but all real-provider/callback
    # checks are deliberately repeated in the exact video-submit invocation.
    if not real_video and not mock_all:
        with _direct_workspace_guard(workspace, "readiness"):
            readiness = _video_readiness(workspace, {}, real_video=False)
        state["phases"]["video_readiness"] = {"status": "awaiting_real_video_authorization", **readiness}
        state["status"] = "awaiting_video_authorization"
        _save(state)
        return state

    with _direct_workspace_guard(workspace, "readiness"):
        readiness = _video_readiness(workspace, opts, real_video=real_video)
    state["phases"]["video_readiness"] = {"status": "succeeded", **readiness}
    _save(state)

    if state["phases"]["real_video"]["status"] != "succeeded":
        video_phase = state["phases"]["real_video"]
        if real_video:
            submission, reconciled_status, resume_submitted = (
                _video_submission_view(workspace)
            )
        else:
            submission, reconciled_status, resume_submitted = None, {}, False
        if real_video and video_phase.get("submission_consumed") is True:
            # A durable task id is resumable without another paid POST.  An old
            # state with no ledger, an ambiguous POST, or a terminal provider
            # failure remains fail-closed.
            if (
                submission is None
                or (
                    submission.get("status") in VIDEO_NON_RESUMABLE_STATUSES
                    and reconciled_status.get("state") != "submitted"
                )
            ):
                state["status"] = "video_submission_already_consumed"
                _save(state)
                return state
        video_started = time.monotonic()
        try:
            if resume_submitted:
                video_budget = 0.0
                video_timeout = float(submission["authorized_timeout_minutes"]) * 60.0
            else:
                video_budget = (
                    _positive(opts.get("video_budget_cny"), "video_budget_cny")
                    if real_video else 0.0
                )
                video_timeout = (
                    _positive(
                        opts.get("video_timeout_seconds"),
                        "video_timeout_seconds", maximum=3600,
                    )
                    if real_video else 30.0
                )
            result = run_video_smoke(
                workspace,
                real_video=real_video,
                confirm_real_video=opts.get("confirm_real_video") is True,
                budget_cny=video_budget,
                timeout_seconds=video_timeout,
                prepare_inputs=False,
                reset_jobs=False,
                resume_submitted=resume_submitted,
            )
        except Exception as exc:
            accounting = (
                _video_submission_accounting(workspace, video_phase)
                if real_video
                else {
                    "submission_consumed": False,
                    "request_count": 0,
                    "submission_unknown_count": 0,
                }
            )
            consumed = accounting["submission_consumed"]
            paid = accounting["request_count"]
            unknown = accounting["submission_unknown_count"]
            video_phase.update({
                "status": "failed_after_submission" if consumed else "failed",
                "error_code": type(exc).__name__,
                "elapsed_seconds": round(max(0.0, time.monotonic() - video_started), 3),
                "submission_consumed": consumed,
                "attempt": 1 if consumed else 0,
                "paid_submission_count": paid,
                "submission_unknown_count": unknown,
                "automatic_retries": 0,
            })
            state["status"] = "failed_after_video_submission" if consumed else "failed"
            _save(state)
            raise
        accounting = (
            _video_submission_accounting(workspace, video_phase)
            if real_video
            else {
                "source_submission_status": None,
                "submission_status": None,
                "submission_consumed": False,
                "request_count": 0,
                "submission_unknown_count": 0,
            }
        )
        submitted = (
            accounting["source_submission_status"] == "succeeded"
            and accounting["submission_status"] == "succeeded"
        )
        if real_video and not submitted:
            raise RuntimeError("real video job returned without a succeeded durable submission ledger")
        result_status = str(result.get("status") or "")
        if real_video and result_status not in {"succeeded", "budget_exceeded"}:
            raise RuntimeError("real video job returned an unsupported terminal status")
        phase_status = "budget_exceeded" if result_status == "budget_exceeded" else "succeeded"
        state["phases"]["real_video"] = {
            "status": phase_status, "real": real_video,
            "submission_consumed": accounting["submission_consumed"],
            "attempt": 1 if accounting["submission_consumed"] else 0,
            "automatic_retries": 0, "network_requests": result.get("network_requests", 0),
            "paid_submission_count": accounting["request_count"],
            "submission_unknown_count": accounting["submission_unknown_count"],
            "elapsed_seconds": result.get("elapsed_seconds"),
            "cost_cny": result.get("cost_cny"),
            "cost_unreported": result.get("cost_unreported") is True,
            "budget_cny": result.get("budget_cny"),
            "file_size_bytes": result.get("file_size_bytes"),
            "duration_seconds": result.get("duration_seconds"),
            "ratio": result.get("ratio"),
            "resolution": result.get("resolution"),
        }
        state["status"] = phase_status
        _save(state)
        if phase_status == "budget_exceeded":
            return state
    if all(state["phases"][phase].get("status") == "succeeded" for phase in PHASES):
        state["status"] = "succeeded"
        _save(state)
    return state


def _evidence_level(row: Mapping[str, Any], *, real_provider_observed: bool = False) -> str:
    status = row.get("status")
    if status == "succeeded":
        if row.get("real") is True and real_provider_observed:
            return "real_execution_recorded_unverified"
        return "engineering_mock_verified" if row.get("real") is not True else "real_mode_without_provider_evidence"
    if status in {"pending", None}:
        return "not_started"
    return "incomplete"


def calibration_report(workspace: str) -> Dict[str, Any]:
    """Build a prompt/path/credential-free, read-only calibration summary.

    This function never creates a workspace and never invokes a provider.  It
    intentionally separates engineering evidence from real-sample evidence so
    a successful mock run cannot be presented as real multimodal calibration.
    """
    state = load_state(workspace)
    if state is None:
        return {
            "schema_version": CALIBRATION_REPORT_SCHEMA_VERSION,
            "workspace": workspace,
            "status": "not_started",
            "real_execution_recorded": False,
            "real_sample_complete": False,
            "evidence_integrity": "local_records_unverified",
            "stages": {
                name: {"status": "not_started", "evidence_level": "not_started"}
                for name in ("text", "images", "video")
            },
        }

    text = state["phases"]["real_text"]
    images = state["phases"]["all_character_images"]
    video = state["phases"]["real_video"]
    image_attempts = [
        row
        for rows in state.get("image_attempts", {}).values()
        if isinstance(rows, list)
        for row in rows
        if isinstance(row, dict)
    ]
    successful_images: list[Dict[str, Any]] = []
    frozen_cast = images.get("cast_ids") if isinstance(images.get("cast_ids"), list) else []
    for cid in frozen_cast:
        rows = state.get("image_attempts", {}).get(cid)
        if not isinstance(rows, list):
            continue
        latest = next(
            (row for row in reversed(rows) if isinstance(row, dict) and row.get("status") == "succeeded"),
            None,
        )
        if latest is not None:
            successful_images.append(latest)
    try:
        image_artifacts_current = _all_completed_images_are_current(workspace, state)
    except (OSError, TypeError, ValueError):
        image_artifacts_current = False
    try:
        _video_bytes, validated_video_meta = drama_video.read_video(workspace, episode_no=1)
        video_artifact_current = True
    except (FileNotFoundError, OSError, TypeError, ValueError):
        validated_video_meta = {}
        video_artifact_current = False

    text_request_count = _safe_count(text.get("llm_calls"))
    text_unknown_count = 0
    if text.get("real") is True:
        from .web import jobs as web_jobs
        with use_workspace(workspace):
            text_ledger = web_jobs._load_drama_text_attempts(workspace)
        ledger_attempts = list(text_ledger.get("attempts", {}).values())
        ledger_exposure = sum(_safe_count(row.get("attempt_count")) for row in ledger_attempts if isinstance(row, dict))
        text_unknown_count = sum(
            1 for row in ledger_attempts
            if isinstance(row, dict) and row.get("status") == "submitting"
        )
        # Do not add the LLM audit count to the attempt ledger: they normally
        # describe the same requests.  Max is conservative without double count.
        text_request_count = max(text_request_count, ledger_exposure)
    video_accounting = _video_submission_accounting(workspace, video)
    video_request_count = video_accounting["request_count"]
    video_unknown_count = video_accounting["submission_unknown_count"]
    completed_steps = text.get("completed_steps")
    text_metrics: Dict[str, Any] = {
        "request_count": text_request_count,
        "submission_unknown_count": text_unknown_count,
        "request_semantics": "durable_attempt_exposure_deduplicated_with_llm_audit",
        "completed_station_count": len(completed_steps) if isinstance(completed_steps, list) else 0,
        "stations": {},
    }
    image_metrics: Dict[str, Any] = {
        "request_count": len(image_attempts) if images.get("real") is True else 0,
        "submission_unknown_count": sum(1 for row in image_attempts if row.get("status") == "started") if images.get("real") is True else 0,
        "request_semantics": "attempt_exposure_including_pre_request_unknown",
        "successful_character_count": len(successful_images),
        "character_count": _safe_count(images.get("character_count")),
        "estimated_cost_cny": round(float(state.get("image_estimated_spend_cny") or 0.0), 6),
        "cost_semantics": "pre_request_estimate_not_provider_settlement",
        "attempts": [],
    }
    video_metrics: Dict[str, Any] = {
        "request_count": video_request_count,
        "request_semantics": "paid_submission_count",
        "submission_unknown_count": video_unknown_count,
        "automatic_retries": _safe_count(video.get("automatic_retries")),
    }
    if video_accounting["submission_status"] is not None:
        video_metrics["submission_status"] = video_accounting["submission_status"]
    if video_accounting["source_submission_status"] is not None:
        video_metrics["source_submission_status"] = video_accounting["source_submission_status"]
    if video_accounting["source_ledger_present"]:
        video_submission = video_accounting["_source_submission"]
        ledger_cost = _safe_non_negative(
            video_submission.get("cost_cny") if video_submission is not None else None
        )
        if video_submission is not None and video_submission.get("cost_unreported") is True:
            video_metrics["cost_status"] = "unreported"
            video_metrics["cost_cny"] = None
        elif ledger_cost is not None:
            video_metrics["cost_cny"] = round(ledger_cost, 6)
    for source, target in (
        (text.get("actual_cost_cny", text.get("spent_cost_cny")), "actual_cost_cny"),
        (text.get("elapsed_seconds"), "elapsed_seconds"),
    ):
        value = _safe_non_negative(source)
        if value is not None:
            text_metrics[target] = round(value, 6 if "cost" in target else 3)
    station_evidence = text.get("station_evidence")
    if isinstance(station_evidence, dict):
        for step in TEXT_STEP_TASKS:
            raw = station_evidence.get(step)
            if not isinstance(raw, dict):
                continue
            station_status = raw.get("status")
            station: Dict[str, Any] = {
                "status": station_status if station_status in {"succeeded", "failed"} else "incomplete",
                "call_count": _safe_count(raw.get("call_count")),
                "non_mock_call_count": _safe_count(raw.get("non_mock_call_count")),
                "pinned_model_call_count": _safe_count(raw.get("pinned_model_call_count")),
            }
            for key in ("elapsed_seconds", "cumulative_cost_cny"):
                value = _safe_non_negative(raw.get(key))
                if value is not None:
                    station[key] = round(value, 6 if key.endswith("cost_cny") else 3)
            text_metrics["stations"][step] = station
    for row in image_attempts:
        attempt: Dict[str, Any] = {
            "attempt": row.get("attempt"),
            "status": row.get("status"),
        }
        prompt_profile = row.get("prompt_profile")
        if prompt_profile in {"initial_complete_v1", "retry_simplified_v1"}:
            attempt["prompt_profile"] = prompt_profile
        for key in ("elapsed_seconds", "estimated_cost_cny"):
            value = _safe_non_negative(row.get(key))
            if value is not None:
                attempt[key] = round(value, 6 if key == "estimated_cost_cny" else 3)
        for key in ("width", "height", "file_size_bytes"):
            value = row.get(key)
            if type(value) is int and value >= 0:
                attempt[key] = value
        image_metrics["attempts"].append(attempt)
    for key in ("elapsed_seconds", "cost_cny", "budget_cny", "file_size_bytes", "duration_seconds"):
        if key == "cost_cny" and video_accounting["source_ledger_present"]:
            continue
        if key == "cost_cny" and video.get("cost_unreported") is True:
            video_metrics["cost_status"] = "unreported"
            video_metrics["cost_cny"] = None
            continue
        value = _safe_non_negative(video.get(key))
        if value is not None:
            video_metrics[key] = round(value, 6 if "cost" in key or "budget" in key else 3)
    ratio = validated_video_meta.get("ratio")
    resolution = validated_video_meta.get("resolution")
    if isinstance(ratio, str) and len(ratio) <= 12 and ratio.replace(":", "").isdigit() and ratio.count(":") == 1:
        video_metrics["ratio"] = ratio
    if isinstance(resolution, str) and len(resolution) <= 20 and all(ch.isdigit() or ch in "px" for ch in resolution.lower()):
        video_metrics["resolution"] = resolution

    real_image_artifacts = (
        len(successful_images) == _safe_count(images.get("character_count"))
        and bool(successful_images)
        and image_artifacts_current
        and isinstance(images.get("provider_fingerprint"), str)
        and len(images["provider_fingerprint"]) == 64
        and images["provider_fingerprint"] != _model_sha256("mock")
        and all(
            isinstance(row.get("generated_by"), str)
            and "mock" not in row["generated_by"].lower()
            and row.get("provider_fingerprint") == images.get("provider_fingerprint")
            and isinstance(row.get("artifact_record_sha256"), str)
            and len(row["artifact_record_sha256"]) == 64
            for row in successful_images
        )
    )
    pinned_models = text.get("model_fingerprints")
    pinned_providers = text.get("provider_fingerprints")
    exact_text_steps = isinstance(completed_steps, list) and tuple(completed_steps) == tuple(TEXT_STEP_TASKS)
    text_provider_evidence = (
        exact_text_steps
        and _text_artifacts_current(workspace, text)
        and isinstance(station_evidence, dict)
        and isinstance(pinned_models, dict)
        and isinstance(pinned_providers, dict)
        and all(
            isinstance(station_evidence.get(step), dict)
            and station_evidence[step].get("status") == "succeeded"
            and _safe_count(station_evidence[step].get("non_mock_call_count")) > 0
            and _safe_count(station_evidence[step].get("pinned_model_call_count")) > 0
            and isinstance(pinned_models.get(step), str)
            and len(pinned_models[step]) == 64
            and pinned_models[step] != _model_sha256("mock")
            and station_evidence[step].get("model_sha256") == pinned_models[step]
            and isinstance(pinned_providers.get(step), str)
            and len(pinned_providers[step]) == 64
            for step in TEXT_STEP_TASKS
        )
    )
    text_evidence = _evidence_level(text, real_provider_observed=text_provider_evidence)
    image_evidence = _evidence_level(images, real_provider_observed=real_image_artifacts)
    video_evidence = _evidence_level(
        video,
        real_provider_observed=(
            video_accounting["submission_consumed"] is True
            and video.get("attempt") == 1
            and video_request_count > 0
            and video_artifact_current
        ),
    )
    stages = {
        "text": {
            "status": text.get("status"), "evidence_level": text_evidence,
            "quality_assessment": "pending_operator_review" if text_evidence == "real_execution_recorded_unverified" else "not_real_sample",
            "metrics": text_metrics,
        },
        "images": {
            "status": images.get("status"), "evidence_level": image_evidence,
            "quality_assessment": "pending_operator_review" if image_evidence == "real_execution_recorded_unverified" else "not_real_sample",
            "metrics": image_metrics,
        },
        "video": {
            "status": video.get("status"), "evidence_level": video_evidence,
            "quality_assessment": "pending_operator_review" if video_evidence == "real_execution_recorded_unverified" else "not_real_sample",
            "metrics": video_metrics,
        },
    }
    real_execution_recorded = all(
        row["evidence_level"] == "real_execution_recorded_unverified" for row in stages.values()
    )
    return {
        "schema_version": CALIBRATION_REPORT_SCHEMA_VERSION,
        "workspace": workspace,
        "status": "real_execution_recorded_pending_operator_review" if real_execution_recorded else "real_sample_incomplete",
        "real_execution_recorded": real_execution_recorded,
        "real_sample_complete": False,
        "evidence_integrity": "local_records_unverified",
        "stages": stages,
    }


def public_status(workspace: str) -> Dict[str, Any]:
    """Return a deliberately narrow, credential/prompt-free Web projection."""
    state = load_state(workspace)
    if state is None:
        return {"workspace": workspace, "status": "not_started", "phases": list(PHASES)}
    calibration = calibration_report(workspace)
    def public_phase(row: Mapping[str, Any]) -> Dict[str, Any]:
        projected: Dict[str, Any] = {"status": row["status"]}
        if row.get("error_code") in {"image_attempt_limit_exhausted", "image_budget_exhausted"}:
            projected["error_code"] = row["error_code"]
        elif row.get("status") == "failed_after_submission":
            projected["error_code"] = "video_submission_failed"
        character_id = row.get("character_id")
        if isinstance(character_id, str) and len(character_id) == 4 and character_id.startswith("c") and character_id[1:].isdigit():
            projected["character_id"] = character_id
        for key in ("next_attempt", "character_count", "reference_count", "automatic_retries", "network_requests"):
            value = row.get(key)
            if type(value) is int and 0 <= value <= 1_000_000:
                projected[key] = value
        for key in ("actual_cost_cny", "remaining_budget_cny", "remaining_seconds"):
            value = _safe_non_negative(row.get(key))
            if value is not None:
                projected[key] = value
        return projected

    return {
        "workspace": workspace,
        "status": state.get("status"),
        "phases": {name: public_phase(row) for name, row in state["phases"].items()},
        "image_attempt_count": sum(len(rows) for rows in state.get("image_attempts", {}).values()),
        "image_estimated_spend_cny": state.get("image_estimated_spend_cny", 0.0),
        "calibration": {
            "status": calibration["status"],
            "real_execution_recorded": calibration["real_execution_recorded"],
            "real_sample_complete": calibration["real_sample_complete"],
            "evidence_levels": {
                name: row["evidence_level"] for name, row in calibration["stages"].items()
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", required=True)
    parser.add_argument("--real-text", action="store_true")
    parser.add_argument("--real-image", action="store_true")
    parser.add_argument("--real-video", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--confirm-real-text", action="store_true")
    parser.add_argument("--confirm-text-retry", action="store_true")
    parser.add_argument("--confirm-real-image", action="store_true")
    parser.add_argument("--confirm-image-retry", action="store_true")
    parser.add_argument("--confirm-upstream-status-and-billing-checked", action="store_true")
    parser.add_argument("--confirm-real-video", action="store_true")
    parser.add_argument("--confirm-asset-callback-reachable", action="store_true")
    # Deprecated compatibility alias: same-process is a stronger form of
    # reachability, but no longer the required topology with the shared store.
    parser.add_argument("--confirm-asset-callback-same-process", action="store_true")
    parser.add_argument("--text-budget-cny", type=float)
    parser.add_argument("--text-timeout-seconds", type=float)
    parser.add_argument("--image-budget-cny", type=float)
    parser.add_argument("--image-estimated-cost-cny", type=float)
    parser.add_argument("--image-timeout-seconds", type=float)
    parser.add_argument("--video-budget-cny", type=float)
    parser.add_argument("--video-timeout-seconds", type=float)
    args = parser.parse_args()
    flags = vars(args)
    workspace = flags.pop("book")
    real_text = flags.pop("real_text")
    real_image = flags.pop("real_image")
    real_video = flags.pop("real_video")
    report_only = flags.pop("report_only")
    if report_only:
        if real_text or real_image or real_video:
            print(json.dumps({"ok": False, "workspace": workspace, "error_code": "report_only_paid_mode_conflict"}, ensure_ascii=False))
            return 64
        try:
            report = calibration_report(workspace)
        except Exception as exc:
            print(json.dumps({"ok": False, "workspace": workspace, "error_code": type(exc).__name__}, ensure_ascii=False))
            return 1
        print(json.dumps({"ok": True, **report}, ensure_ascii=False))
        return 0
    if (
        real_text
        and flags.get("confirm_real_text") is True
        and not drama_smoke.real_text_tasks_ready()
    ):
        readiness_errors = drama_smoke.real_text_readiness_errors()
        print(json.dumps({
            "ok": False,
            "workspace": workspace,
            "error_code": drama_smoke.real_text_readiness_error_code(readiness_errors),
            "readiness_errors": list(readiness_errors),
        }, ensure_ascii=False))
        return 64
    try:
        state = run(workspace, real_text=real_text, real_image=real_image, real_video=real_video, options=flags)
    except Exception as exc:
        print(json.dumps({"ok": False, "workspace": workspace, "error_code": type(exc).__name__}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": state.get("status") == "succeeded", **state}, ensure_ascii=False))
    return 0 if state.get("status") == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
