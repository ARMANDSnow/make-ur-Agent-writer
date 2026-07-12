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
from .schemas import model_to_dict
from .utils import read_json, read_json_optional, write_json
from .web.drama_insights import collect_drama_insights
from .web.workspace_ctx import use_workspace
from .workspace_lock import acquire_write_lock


PHASES = ("real_text", "all_character_images", "reassemble", "video_readiness", "real_video")
RETRY_TIMEOUT_SECONDS = 180.0
MAX_IMAGE_ATTEMPTS_PER_CHARACTER = 3
STATE_SCHEMA_VERSION = 1
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
    text = phases["real_text"]
    for key in ("spent_cost_cny", "total_budget_cny", "deadline_epoch", "cost_baseline_cny"):
        if key in text:
            value = text[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
                raise ValueError("multimodal smoke text billing state is invalid")
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
            _save(state)
        except AIDrawTimeout:
            audit["status"] = "timeout"
        except AIDrawNetworkError:
            audit["status"] = "network_error"
        except AIDrawProviderError:
            audit["status"] = "provider_error"
        except Exception:
            audit["status"] = "local_error"
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

        def text_step_done(step: str, _result: Dict[str, Any]) -> None:
            if step not in phase["completed_steps"]:
                phase["completed_steps"].append(step)
            settle_text_spend()
            _save(state)

        try:
            result = drama_smoke.run_smoke(
                workspace, real_text=real_text, real_image=False,
                budget_cny=text_budget, timeout_seconds=text_timeout, reset_jobs=False,
                completed_steps=phase["completed_steps"], on_step_complete=text_step_done,
                create_workspace=False,
            )
        except Exception:
            settle_text_spend()
            _save(state)
            raise
        total_spent = settle_text_spend()
        state["phases"]["real_text"] = {
            "status": "succeeded", "real": real_text,
            "completed_steps": list(phase["completed_steps"]),
            "spent_cost_cny": round(total_spent, 6),
            "actual_cost_cny": round(total_spent, 6),
            "remaining_budget_cny": round(max(0.0, requested_budget - total_spent), 6),
            "remaining_seconds": round(max(0.0, (float(phase.get("deadline_epoch") or time.time()) - time.time()) if real_text else float(result.get("remaining_seconds") or 0.0)), 3),
            "budget_semantics": "single_station_may_overshoot_before_settlement",
        }
        if real_text:
            state["phases"]["real_text"].update({
                "total_budget_cny": phase["total_budget_cny"],
                "deadline_epoch": phase["deadline_epoch"],
                "cost_baseline_cny": phase["cost_baseline_cny"],
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
                "attempt": 1, "automatic_retries": 0,
            })
            _save(state)
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
            video_phase.update({"status": "failed_after_submission", "error_code": type(exc).__name__})
            state["status"] = "failed_after_video_submission"
            _save(state)
            raise
        state["phases"]["real_video"] = {
            "status": "succeeded", "real": real_video,
            "submission_consumed": bool(real_video), "attempt": 1 if real_video else 0,
            "automatic_retries": 0, "network_requests": result.get("network_requests", 0),
        }
        state["status"] = "succeeded"
        _save(state)
    if all(state["phases"][phase].get("status") == "succeeded" for phase in PHASES):
        state["status"] = "succeeded"
        _save(state)
    return state


def public_status(workspace: str) -> Dict[str, Any]:
    """Return a deliberately narrow, credential/prompt-free Web projection."""
    state = load_state(workspace)
    if state is None:
        return {"workspace": workspace, "status": "not_started", "phases": list(PHASES)}
    return {
        "workspace": workspace,
        "status": state.get("status"),
        "phases": {name: {key: value for key, value in row.items() if key in {
            "status", "error_code", "character_id", "next_attempt", "character_count",
            "reference_count", "actual_cost_cny", "remaining_budget_cny", "remaining_seconds",
            "automatic_retries", "network_requests",
        }} for name, row in state["phases"].items()},
        "image_attempt_count": sum(len(rows) for rows in state.get("image_attempts", {}).values()),
        "image_estimated_spend_cny": state.get("image_estimated_spend_cny", 0.0),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", required=True)
    parser.add_argument("--real-text", action="store_true")
    parser.add_argument("--real-image", action="store_true")
    parser.add_argument("--real-video", action="store_true")
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
    try:
        state = run(workspace, real_text=real_text, real_image=real_image, real_video=real_video, options=flags)
    except Exception as exc:
        print(json.dumps({"ok": False, "workspace": workspace, "error_code": type(exc).__name__}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": state.get("status") == "succeeded", **state}, ensure_ascii=False))
    return 0 if state.get("status") == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
