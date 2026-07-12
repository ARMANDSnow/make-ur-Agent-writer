"""Recoverable, consent-scoped short-drama multimodal smoke orchestration."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Mapping

from . import drama_smoke, drama_store, drama_video, paths
from .ai_draw_client import (
    AIDrawNetworkError,
    AIDrawProviderError,
    AIDrawTimeout,
    DEFAULT_IMAGE_MODEL,
    _atomic_write_bytes,
    redraw_character_reference,
    validate_api_base_url,
)
from .drama_schemas import CharacterSheet, character_paths
from .drama_video_smoke import run_smoke as run_video_smoke
from .config import get_model_config
from .schemas import model_to_dict
from .utils import read_json, read_json_optional, write_json
from .web.drama_insights import collect_drama_insights
from .web.workspace_ctx import use_workspace
from .workspace_lock import acquire_write_lock


PHASES = ("real_text", "all_character_images", "reassemble", "video_readiness", "real_video")
PHASE_STATUSES = {
    "pending", "running", "succeeded", "failed", "blocked",
    "awaiting_retry_authorization", "awaiting_real_video_authorization",
    "submission_consumed", "failed_after_submission",
}
RUN_STATUSES = {
    "pending", "running", "succeeded", "failed", "blocked",
    "awaiting_retry_authorization", "awaiting_text_authorization",
    "awaiting_image_authorization", "awaiting_video_authorization",
    "failed_after_video_submission", "video_submission_already_consumed",
}
RETRY_TIMEOUT_SECONDS = 180.0
MAX_IMAGE_ATTEMPTS_PER_CHARACTER = 3
STATE_SCHEMA_VERSION = 1
CALIBRATION_REPORT_SCHEMA_VERSION = 1
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


def load_state(workspace: str) -> Dict[str, Any] | None:
    path = state_path(workspace)
    if not path.exists():
        return None
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
    allowed_status = {"started", "succeeded", "timeout", "network_error", "provider_error", "local_error"}
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
                or row.get("status") not in allowed_status
            ):
                raise ValueError("multimodal smoke image attempt billing state is invalid")
            if row.get("status") == "succeeded":
                artifact_path = row.get("artifact_path")
                artifact_sha256 = row.get("artifact_sha256")
                if (
                    not isinstance(artifact_path, str)
                    or not artifact_path
                    or Path(artifact_path).is_absolute()
                    or not isinstance(artifact_sha256, str)
                    or len(artifact_sha256) != 64
                    or any(ch not in "0123456789abcdef" for ch in artifact_sha256)
                ):
                    raise ValueError("multimodal smoke image artifact state is invalid")
            estimated_sum += float(estimate)
    if not math.isclose(estimated_sum, float(spend), rel_tol=0.0, abs_tol=1e-6):
        raise ValueError("multimodal smoke image spend does not match attempt ledger")
    video = phases["real_video"]
    if "submission_consumed" in video and type(video["submission_consumed"]) is not bool:
        raise ValueError("multimodal smoke video consumed state is invalid")
    if video.get("submission_consumed") is True and video.get("attempt") != 1:
        raise ValueError("multimodal smoke video attempt ledger is invalid")
    if "paid_submission_count" in video:
        paid = video["paid_submission_count"]
        if type(paid) is not int or paid not in {0, 1} or paid != int(video.get("submission_consumed") is True):
            raise ValueError("multimodal smoke video paid submission ledger is invalid")
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


@contextmanager
def _orchestrator_lock(workspace: str):
    """Cross-process claim spanning state read/claim and all paid attempts."""
    root = paths.workspace_root(workspace)
    lock = root.parent / f".{root.name}.drama_multimodal_smoke.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o644)
    try:
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
    write_json(state_path(str(state["workspace"])), state)


def _profile_prompt(character: Mapping[str, Any], *, simplified: bool) -> tuple[str, str, str]:
    name = str(character.get("name") or "原创角色")[:80]
    signature = str(character.get("visual_signature") or character.get("prompt_template_sd") or name)
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
    write_json(cp.sheet_path, payload)


def _completed_image_is_current(workspace: str, character: Mapping[str, Any], records: list[Dict[str, Any]]) -> bool:
    succeeded = next((row for row in reversed(records) if row.get("status") == "succeeded"), None)
    if succeeded is None:
        return False
    refs = character.get("reference_images")
    if not isinstance(refs, list) or len(refs) != 1 or not isinstance(refs[0], dict):
        return False
    rel = str(succeeded.get("artifact_path") or "")
    if refs[0].get("path") != rel or not rel:
        return False
    root = paths.workspace_root(workspace).resolve()
    try:
        target = (root / rel).resolve()
        target.relative_to(root)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return False
    return digest == succeeded.get("artifact_sha256")


def _all_completed_images_are_current(workspace: str, state: Mapping[str, Any]) -> bool:
    raw = read_json_optional(character_paths(workspace).sheet_path, None)
    sheet = CharacterSheet(**raw)
    attempts = state.get("image_attempts") or {}
    for character in _appearing_characters(sheet):
        records = attempts.get(str(character["id"]))
        if not isinstance(records, list) or not _completed_image_is_current(workspace, character, records):
            return False
        succeeded = next(row for row in reversed(records) if row.get("status") == "succeeded")
        _prompt, _profile, current_hash = _profile_prompt(character, simplified=int(succeeded["attempt"]) > 1)
        if succeeded.get("prompt_sha256") != current_hash:
            return False
    return True


def _insight_cost(workspace: str) -> float:
    value = collect_drama_insights(workspace).get("llm_cost", {}).get("cost_cny", 0.0)
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("drama text cost ledger is invalid") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError("drama text cost ledger is invalid")
    return number


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
    if real_image:
        if options.get("confirm_real_image") is not True:
            raise MultimodalAuthorizationError("confirm_real_image=true is required for this invocation")
        image_budget = _positive(options.get("image_budget_cny"), "image_budget_cny")
        estimate = _positive(options.get("image_estimated_cost_cny"), "image_estimated_cost_cny")
        initial_timeout = _positive(options.get("image_timeout_seconds"), "image_timeout_seconds", maximum=3600)
        if str(os.getenv("AI_DRAW_ENDPOINT") or "").strip():
            raise ValueError("multimodal image smoke requires the bounded OpenAI-compatible image API")
        if "total_budget_cny" not in phase:
            phase["total_budget_cny"] = image_budget
            phase["estimated_cost_per_attempt_cny"] = estimate
        elif image_budget != float(phase["total_budget_cny"]) or estimate != float(phase["estimated_cost_per_attempt_cny"]):
            raise ValueError("image resume budget and estimate must match the original image-stage authorization")
        os.environ["AI_DRAW_MODEL"] = os.getenv("AI_DRAW_MODEL") or DEFAULT_IMAGE_MODEL
    else:
        image_budget, estimate, initial_timeout = 0.0, 0.0, 30.0

    attempts = state.setdefault("image_attempts", {})
    for character in characters:
        cid = str(character["id"])
        records = attempts.setdefault(cid, [])
        current = next((item for item in _appearing_characters(CharacterSheet(**read_json_optional(character_paths(workspace).sheet_path, None))) if item["id"] == cid), character)
        if _completed_image_is_current(workspace, current, records):
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
            "status": "started",
        }
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
            generated["prompt"] = f"<{profile}:{prompt_hash[:16]}>"
            _replace_character_reference(workspace, cid, generated)
            audit["status"] = "succeeded"
            audit["artifact_path"] = generated["path"]
            audit["artifact_sha256"] = hashlib.sha256(
                (paths.workspace_root(workspace) / generated["path"]).read_bytes()
            ).hexdigest()
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
                audit["file_size_bytes"] = (paths.workspace_root(workspace) / generated["path"]).stat().st_size
            except OSError:
                pass
        except AIDrawTimeout:
            audit["status"] = "timeout"
        except AIDrawNetworkError:
            audit["status"] = "network_error"
        except AIDrawProviderError:
            audit["status"] = "provider_error"
        except Exception:
            audit["status"] = "local_error"
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
    phase.update({"status": "succeeded", "real": real_image, "character_count": len(characters)})
    state["status"] = "running"
    _save(state)
    return True


def _video_readiness(workspace: str, options: Mapping[str, Any], *, real_video: bool) -> Dict[str, Any]:
    inputs = drama_video.load_video_inputs(workspace, episode_no=1)
    result: Dict[str, Any] = {"input_fingerprint": inputs.fingerprint, "reference_count": len(inputs.references)}
    if real_video:
        if options.get("confirm_real_video") is not True:
            raise MultimodalAuthorizationError("confirm_real_video=true is required for this invocation")
        if options.get("confirm_asset_callback_same_process") is not True:
            raise MultimodalAuthorizationError("operator must confirm provider callback reaches this same service process")
        budget = _positive(options.get("video_budget_cny"), "video_budget_cny")
        timeout = _positive(options.get("video_timeout_seconds"), "video_timeout_seconds", maximum=3600)
        os.environ["SD_VIDEO_MODE"] = "real"
        _, _, estimate = drama_video.validate_real_video_gate({
            "confirm_real_video": True,
            "budget_cny": budget,
            "timeout_minutes": timeout / 60.0,
        })
        public_base = str(os.getenv("SD_ASSET_PUBLIC_BASE_URL") or "").strip()
        validate_api_base_url(public_base, label="SD_ASSET_PUBLIC_BASE_URL")
        hosts = [item.strip() for item in str(os.getenv("SD_VIDEO_RESULT_HOSTS") or "").split(",") if item.strip()]
        if not hosts:
            raise ValueError("SD_VIDEO_RESULT_HOSTS must contain an exact provider result host")
        result.update({"estimated_cost_cny": estimate, "budget_cny": budget, "callback_same_process_confirmed": True})
    return result


def _validate_invocation(real_text: bool, real_image: bool, real_video: bool, opts: Mapping[str, Any]) -> None:
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
        _positive(opts.get("video_budget_cny"), "video_budget_cny")
        _positive(opts.get("video_timeout_seconds"), "video_timeout_seconds", maximum=3600)
        if opts.get("confirm_asset_callback_same_process") is not True:
            raise MultimodalAuthorizationError("operator must confirm provider callback reaches this same service process")


def run(
    workspace: str,
    *,
    real_text: bool = False,
    real_image: bool = False,
    real_video: bool = False,
    options: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    opts = dict(options or {})
    _validate_invocation(real_text, real_image, real_video, opts)
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
        # A multimodal run owns a fresh smoke workspace. Never reinterpret an
        # existing user workspace as disposable smoke state.
        if paths.workspace_root(workspace).exists():
            raise ValueError("fresh multimodal smoke requires a new workspace name")
        drama_smoke._create_workspace(workspace, "推理")
    state = existing or _new_state(workspace)
    for requested, phase_name in (
        (real_text, "real_text"), (real_image, "all_character_images"), (real_video, "real_video")
    ):
        phase_row = state["phases"][phase_name]
        if requested and phase_row.get("status") == "succeeded" and phase_row.get("real") is False:
            raise ValueError(f"cannot upgrade completed mock phase {phase_name} to a real paid phase")
    state["status"] = "running"
    _save(state)

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
        if real_text:
            current_fingerprints = _text_model_fingerprints()
            if "model_fingerprints" not in phase:
                phase["model_fingerprints"] = current_fingerprints
            elif phase["model_fingerprints"] != current_fingerprints:
                raise ValueError("text resume model identity differs from the original authorization")
        if "cost_baseline_cny" not in phase:
            phase["cost_baseline_cny"] = _insight_cost(workspace)
        # Crash recovery reconciliation must happen before calculating a
        # remaining budget or starting the next station. LLM logs are durable
        # even if the previous process died before its exception handler.
        current_cost = _insight_cost(workspace)
        cost_baseline = float(phase["cost_baseline_cny"])
        if current_cost < cost_baseline:
            raise ValueError("drama text cost ledger regressed below the run baseline")
        phase["spent_cost_cny"] = round(
            max(float(phase["spent_cost_cny"]), current_cost - cost_baseline), 6
        )
        # A previous process may have died after persisting active_step and
        # making a provider call. Reconcile that durable ledger before a
        # budget/deadline gate can stop this resume without another request.
        _reconcile_failed_text_station(workspace, phase, real_text=real_text)
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
            current = _insight_cost(workspace)
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
            )
        except Exception:
            settle_text_spend()
            settle_text_runtime()
            _reconcile_failed_text_station(workspace, phase, real_text=real_text)
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
            "budget_semantics": "single_station_may_overshoot_before_settlement",
        }
        if real_text:
            state["phases"]["real_text"].update({
                "total_budget_cny": phase["total_budget_cny"],
                "deadline_epoch": phase["deadline_epoch"],
                "cost_baseline_cny": phase["cost_baseline_cny"],
                "model_fingerprints": phase["model_fingerprints"],
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
        if real_video and video_phase.get("submission_consumed") is True:
            state["status"] = "video_submission_already_consumed"
            _save(state)
            return state
        if real_video:
            # Persist the one-shot token before any upload/submission. A crash,
            # timeout or ambiguous provider response can never authorize a new POST.
            video_phase.update({
                "status": "submission_consumed", "submission_consumed": True,
                "attempt": 1, "automatic_retries": 0, "paid_submission_count": 1,
            })
            _save(state)
        video_started = time.monotonic()
        try:
            result = run_video_smoke(
                workspace,
                real_video=real_video,
                confirm_real_video=opts.get("confirm_real_video") is True,
                budget_cny=_positive(opts.get("video_budget_cny"), "video_budget_cny") if real_video else 0.0,
                timeout_seconds=_positive(opts.get("video_timeout_seconds"), "video_timeout_seconds", maximum=3600) if real_video else 30.0,
                prepare_inputs=False,
                reset_jobs=False,
            )
        except Exception as exc:
            video_phase.update({
                "status": "failed_after_submission",
                "error_code": type(exc).__name__,
                "elapsed_seconds": round(max(0.0, time.monotonic() - video_started), 3),
            })
            state["status"] = "failed_after_video_submission"
            _save(state)
            raise
        state["phases"]["real_video"] = {
            "status": "succeeded", "real": real_video,
            "submission_consumed": bool(real_video), "attempt": 1 if real_video else 0,
            "automatic_retries": 0, "network_requests": result.get("network_requests", 0),
            "paid_submission_count": 1 if real_video else 0,
            "elapsed_seconds": result.get("elapsed_seconds"),
            "cost_cny": result.get("cost_cny"),
            "budget_cny": result.get("budget_cny"),
            "file_size_bytes": result.get("file_size_bytes"),
            "duration_seconds": result.get("duration_seconds"),
            "ratio": result.get("ratio"),
            "resolution": result.get("resolution"),
        }
        state["status"] = "succeeded"
        _save(state)
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
    successful_images = [row for row in image_attempts if row.get("status") == "succeeded"]
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
    video_request_count = _safe_count(video.get("paid_submission_count"))
    completed_steps = text.get("completed_steps")
    text_metrics: Dict[str, Any] = {
        "request_count": text_request_count,
        "completed_station_count": len(completed_steps) if isinstance(completed_steps, list) else 0,
        "stations": {},
    }
    image_metrics: Dict[str, Any] = {
        "request_count": len(image_attempts) if images.get("real") is True else 0,
        "successful_character_count": len(successful_images),
        "character_count": _safe_count(images.get("character_count")),
        "estimated_cost_cny": round(float(state.get("image_estimated_spend_cny") or 0.0), 6),
        "cost_semantics": "pre_request_estimate_not_provider_settlement",
        "attempts": [],
    }
    video_metrics: Dict[str, Any] = {
        "request_count": video_request_count,
        "request_semantics": "paid_submission_count",
        "automatic_retries": _safe_count(video.get("automatic_retries")),
    }
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
        and all(
        isinstance(row.get("generated_by"), str)
        and "mock" not in row["generated_by"].lower()
        for row in successful_images
        )
    )
    pinned_models = text.get("model_fingerprints")
    exact_text_steps = isinstance(completed_steps, list) and tuple(completed_steps) == tuple(TEXT_STEP_TASKS)
    text_provider_evidence = (
        exact_text_steps
        and isinstance(station_evidence, dict)
        and isinstance(pinned_models, dict)
        and all(
            isinstance(station_evidence.get(step), dict)
            and station_evidence[step].get("status") == "succeeded"
            and _safe_count(station_evidence[step].get("non_mock_call_count")) > 0
            and _safe_count(station_evidence[step].get("pinned_model_call_count")) > 0
            and isinstance(pinned_models.get(step), str)
            and len(pinned_models[step]) == 64
            and pinned_models[step] != _model_sha256("mock")
            and station_evidence[step].get("model_sha256") == pinned_models[step]
            for step in TEXT_STEP_TASKS
        )
    )
    text_evidence = _evidence_level(text, real_provider_observed=text_provider_evidence)
    image_evidence = _evidence_level(images, real_provider_observed=real_image_artifacts)
    video_evidence = _evidence_level(
        video,
        real_provider_observed=(
            video.get("submission_consumed") is True
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
    parser.add_argument("--confirm-real-image", action="store_true")
    parser.add_argument("--confirm-image-retry", action="store_true")
    parser.add_argument("--confirm-upstream-status-and-billing-checked", action="store_true")
    parser.add_argument("--confirm-real-video", action="store_true")
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
    try:
        state = run(workspace, real_text=real_text, real_image=real_image, real_video=real_video, options=flags)
    except Exception as exc:
        print(json.dumps({"ok": False, "workspace": workspace, "error_code": type(exc).__name__}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": state.get("status") == "succeeded", **state}, ensure_ascii=False))
    return 0 if state.get("status") == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
