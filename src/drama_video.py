"""One-task, episode-1 short-drama video production pipeline.

The default path is deterministic and network-free.  Real mode is opt-in at
configuration *and* request level, performs no paid retries, and persists only
safe provider/task metadata after a verified atomic download.
"""

from __future__ import annotations

import json
import base64
import hashlib
import http.client
import math
import os
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional
from urllib.parse import quote, urlparse

from . import paths
from .ai_draw_client import MAX_RESPONSE_BYTES as MAX_IMAGE_BYTES
from .ai_draw_client import (
    _detect_image_type,
    _download_generated_image,
    _validate_public_endpoint,
    validate_api_base_url,
)
from .drama_schemas import CharacterSheet, DramaEpisode, DramaEpisodeMeta, DramaStoryboard, character_paths, episode_paths
from .drama_store import is_episode_stale
from .drama_video_client import DEFAULT_VIDEO_MODEL, DramaVideoClient, build_video_payload
from .paid_recovery_states import (
    VIDEO_INCOMPLETE_STATUSES,
    VIDEO_LEDGER_STATUSES,
    VIDEO_TASK_ID_STATUSES,
)
from .schemas import model_to_dict
from .secure_http import RequestNotSentError
from .utils import read_json_optional, sha256_data, write_json


VIDEO_DURATION_SECONDS = 5
VIDEO_RATIO = "9:16"
VIDEO_RESOLUTION = "720p"
MAX_VIDEO_BYTES = 100 * 1024 * 1024
POLL_INTERVAL_SECONDS = 2.0
MAX_REFERENCE_ASSETS = 8
_TERMINAL_SUCCESS = frozenset({"success", "succeeded", "completed", "done"})
_TERMINAL_FAILURE = frozenset({"failed", "failure", "error", "cancelled", "canceled"})
_RUNNING = frozenset({"pending", "queued", "queueing", "processing", "running", "generating", "in_progress"})
PUBLIC_ASSET_STORE_SCHEMA_VERSION = 1
PUBLIC_ASSET_STORE_DIRNAME = ".drama_public_assets"
_MOCK_MP4 = base64.b64decode(
    "AAAAHGZ0eXBtcDQyAAAAAWlzb21tcDQxbXA0MgAAAAFtZGF0AAAAAAAAAH8AAAA1BgUtR1ZK3FxMQz+U78URPNFDqAEAAAMAAQMAAAMAAQIAAeYACwAAAwAAAwAACVYMA5EIAIAAAAAyJbggH94I5Uz/gswem1JEAFF721iPegoZHua5g6fVtrKB82GsqGNvqOenAAA2gBXDPRgAAAKnbW9vdgAAAGxtdmhkAAAAAOZ5GRPmeRkUAAACWAAAACgAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAAAjN0cmFrAAAAXHRraGQAAAAB5nkZFOZ5GRQAAAABAAAAAAAAACgAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAABAAAAAQAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAAoAAAAAAABAAAAAAGrbWRpYQAAACBtZGhkAAAAAOZ5GRTmeRkUAAACWAAAAChVxAAAAAAAMWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABDb3JlIE1lZGlhIFZpZGVvAAAAAVJtaW5mAAAAFHZtaGQAAAABAAAAAAAAAAAAAAAkZGluZgAAABxkcmVmAAAAAAAAAAEAAAAMdXJsIAAAAAEAAAESc3RibAAAAKFzdHNkAAAAAAAAAAEAAACRYXZjMQAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAQABAASAAAAEgAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABj//wAAACdhdmNDAWQAC//hAAwnZAALrFZQw3gWYKUBAAQo7jyw/fj4AAAAAApmaWVsAQAAAAAKY2hybQAAAAAAGHN0dHMAAAAAAAAAAQAAAAEAAAAoAAAADXNkdHAAAAAAIAAAABxzdHNjAAAAAAAAAAEAAAABAAAAAQAAAAEAAAAUc3RzegAAAAAAAABvAAAAAQAAABRzdGNvAAAAAAAAAAEAAAAs"
)


class DramaVideoInputError(ValueError):
    """The current episode/material snapshot is unsafe or incomplete."""


class DramaVideoProviderError(RuntimeError):
    """A public-safe provider failure suitable for a job error code."""


class DramaVideoTimedOut(TimeoutError):
    """Polling crossed the finite user-authorized deadline."""


class DramaVideoSubmissionUnknown(RuntimeError):
    """A paid POST may have reached the provider but returned no task id."""


@dataclass(frozen=True)
class VideoPaths:
    video_path: Path
    meta_path: Path


@dataclass(frozen=True)
class VideoInputs:
    workspace: str
    episode: Dict[str, Any]
    meta: Dict[str, Any]
    storyboard: Dict[str, Any]
    characters: Dict[str, Any]
    references: tuple[tuple[str, str, Path], ...]
    fingerprint: str


@dataclass(frozen=True)
class VideoSpec:
    duration_seconds: float
    width: int
    height: int


def video_paths(workspace: str, *, episode_no: int = 1) -> VideoPaths:
    if episode_no != 1:
        raise DramaVideoInputError("video MVP supports episode 1 only")
    ep = episode_paths(workspace, episode_no=episode_no)
    return VideoPaths(
        video_path=ep.episodes_dir / "episode_01.video.mp4",
        meta_path=ep.episodes_dir / "episode_01.video.meta.json",
    )


def video_submission_path(workspace: str, *, episode_no: int = 1) -> Path:
    if episode_no != 1:
        raise DramaVideoInputError("video MVP supports episode 1 only")
    return paths.workspace_root(workspace) / "logs" / "drama_video_submission.json"


def read_video_submission(workspace: str, *, episode_no: int = 1) -> Dict[str, Any] | None:
    ledger_path = video_submission_path(workspace, episode_no=episode_no)
    try:
        ledger_path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError("video submission ledger is unreadable") from exc
    if ledger_path.is_symlink() or not ledger_path.is_file():
        raise ValueError("video submission ledger must be a regular file")
    try:
        raw = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("video submission ledger is unreadable") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or raw.get("episode_no") != 1:
        raise ValueError("video submission ledger is invalid")
    status = raw.get("status")
    if status not in VIDEO_LEDGER_STATUSES:
        raise ValueError("video submission ledger status is invalid")
    fingerprint = raw.get("input_fingerprint")
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(ch not in "0123456789abcdef" for ch in fingerprint)
    ):
        raise ValueError("video submission ledger fingerprint is invalid")
    if raw.get("submission_count") != 1:
        raise ValueError("video submission ledger count is invalid")
    provider_fingerprint = raw.get("provider_fingerprint")
    if (
        not isinstance(provider_fingerprint, str)
        or len(provider_fingerprint) != 64
        or any(ch not in "0123456789abcdef" for ch in provider_fingerprint)
    ):
        raise ValueError("video submission provider fingerprint is invalid")
    result_hosts_fingerprint = raw.get("result_hosts_fingerprint")
    if result_hosts_fingerprint is not None and (
        not isinstance(result_hosts_fingerprint, str)
        or len(result_hosts_fingerprint) != 64
        or any(ch not in "0123456789abcdef" for ch in result_hosts_fingerprint)
    ):
        raise ValueError("video submission result-host fingerprint is invalid")
    if status == "submitted" and result_hosts_fingerprint is None:
        raise ValueError("video submitted ledger requires result-host reconciliation")
    task_id = raw.get("task_id")
    if status in VIDEO_TASK_ID_STATUSES:
        _extract_resource_id({"id": task_id}, "task")
    elif task_id is not None:
        raise ValueError("video submitting ledger must not claim a task id")
    if "cost_cny" in raw:
        cost = raw.get("cost_cny")
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(float(cost)) or cost < 0:
            raise ValueError("video submission ledger cost is invalid")
    if "cost_unreported" in raw and type(raw.get("cost_unreported")) is not bool:
        raise ValueError("video submission ledger cost state is invalid")
    present_authorization = {
        key for key in (
            "authorized_budget_cny", "authorized_timeout_minutes",
            "estimated_cost_cny", "authorization_fingerprint",
        ) if key in raw
    }
    if present_authorization and len(present_authorization) != 4:
        raise ValueError("video submission authorization state is incomplete")
    if present_authorization:
        for key in ("authorized_budget_cny", "authorized_timeout_minutes", "estimated_cost_cny"):
            value = raw.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value <= 0:
                raise ValueError("video submission authorization value is invalid")
        expected = _video_authorization(
            float(raw["authorized_budget_cny"]),
            float(raw["authorized_timeout_minutes"]),
            float(raw["estimated_cost_cny"]),
        )["authorization_fingerprint"]
        if raw.get("authorization_fingerprint") != expected:
            raise ValueError("video submission authorization fingerprint is invalid")
    return raw


def _write_video_submission(workspace: str, payload: Mapping[str, Any]) -> None:
    write_json(video_submission_path(workspace), {"schema_version": 1, "episode_no": 1, **dict(payload)})


def real_video_enabled() -> bool:
    return os.getenv("SD_VIDEO_MODE", "mock").strip().lower() == "real"


def validate_real_video_gate(params: Mapping[str, Any]) -> tuple[float, float, float]:
    """Last-hop authorization; call before dotenv/client construction/network."""

    if params.get("confirm_real_video") is not True:
        raise PermissionError("real video requires confirm_real_video=true")
    budget = _finite_positive(params.get("budget_cny"), "budget_cny", maximum=1_000_000.0)
    timeout_minutes = _finite_positive(params.get("timeout_minutes"), "timeout_minutes", maximum=60.0)
    estimate = _finite_positive(os.getenv("SD_VIDEO_ESTIMATED_COST_CNY"), "SD_VIDEO_ESTIMATED_COST_CNY", maximum=1_000_000.0)
    if estimate > budget:
        raise PermissionError("video estimated cost exceeds the authorized budget")
    return budget, timeout_minutes, estimate


def _video_authorization(budget: float, timeout_minutes: float, estimate: float) -> Dict[str, Any]:
    payload = {
        "authorized_budget_cny": budget,
        "authorized_timeout_minutes": timeout_minutes,
        "estimated_cost_cny": estimate,
    }
    payload["authorization_fingerprint"] = sha256_data(payload)
    return payload


def load_video_inputs(workspace: str, *, episode_no: int = 1) -> VideoInputs:
    if episode_no != 1:
        raise DramaVideoInputError("video MVP supports episode 1 only")
    ep = episode_paths(workspace, episode_no=episode_no)
    episode_raw = read_json_optional(ep.episode_path, None)
    meta_raw = read_json_optional(ep.meta_path, None)
    storyboard_raw = read_json_optional(ep.storyboard_path, None)
    characters_raw = read_json_optional(character_paths(workspace).sheet_path, None)
    if not all(isinstance(item, dict) for item in (episode_raw, meta_raw, storyboard_raw, characters_raw)):
        raise DramaVideoInputError("fresh episode, storyboard, characters, and reference images are required")
    episode = model_to_dict(DramaEpisode(**episode_raw))
    meta = model_to_dict(DramaEpisodeMeta(**meta_raw))
    storyboard = model_to_dict(DramaStoryboard(**storyboard_raw))
    characters = model_to_dict(CharacterSheet(**characters_raw))
    if (
        episode["episode_no"] != 1
        or meta["episode_no"] != 1
        or storyboard["episode_no"] != 1
        or characters["season_no"] != 1
    ):
        raise DramaVideoInputError("video inputs must all belong to episode 1")
    if not meta.get("episode_sha256") or meta["episode_sha256"] != sha256_data(episode):
        raise DramaVideoInputError("assembled episode content does not match its fresh metadata")
    if not meta.get("input_fingerprint") or is_episode_stale(workspace, episode_no=1):
        raise DramaVideoInputError("episode is stale; review and assemble it again before video generation")
    references: List[tuple[str, str, Path]] = []
    episode_characters: List[Dict[str, Any]] = []
    root = paths.workspace_root(workspace).resolve()
    for character in characters.get("characters", []):
        if not isinstance(character, dict) or 1 not in (character.get("appearances") or [1]):
            continue
        stable_character = dict(character)
        stable_character["appearances"] = [1]
        stable_character.pop("agent_suggestions", None)
        stable_character.pop("manual_override", None)
        episode_characters.append(stable_character)
        refs = character.get("reference_images") or []
        if not isinstance(refs, list) or not refs:
            raise DramaVideoInputError("every episode-1 character must have a current reference image")
        ref = refs[0]
        if not isinstance(ref, dict):
            raise DramaVideoInputError("reference image schema is invalid")
        rel = str(ref.get("path") or "")
        relative = Path(rel)
        if relative.is_absolute() or ".." in relative.parts:
            raise DramaVideoInputError("reference image path is invalid")
        candidate = root / relative
        cursor = root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise DramaVideoInputError("reference image path must not use symbolic links")
        target = candidate.resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise DramaVideoInputError("reference image escapes the workspace") from exc
        try:
            size = target.stat().st_size
            data = target.read_bytes()
        except OSError as exc:
            raise DramaVideoInputError("reference image file is missing") from exc
        if size <= 0 or size > MAX_IMAGE_BYTES or len(data) != size:
            raise DramaVideoInputError("reference image size is invalid")
        _detect_image_type(data)
        cid = str(character.get("id") or "")
        references.append((cid, target.name, target))
        if len(references) >= MAX_REFERENCE_ASSETS:
            break
    if not references:
        raise DramaVideoInputError("at least one episode-1 reference image is required")
    # CharacterSheet is season-scoped and its top-level episode_no/source title
    # move forward as later episodes are produced.  Episode-1 video lineage must
    # depend only on the characters that actually appear in episode 1.
    character_projection = {
        "schema_version": characters.get("schema_version", 1),
        "season_no": characters.get("season_no", 1),
        "track": characters.get("track", ""),
        "characters": episode_characters,
    }
    fingerprint = sha256_data(
        {
            "episode": episode,
            "episode_meta_fingerprint": meta.get("input_fingerprint"),
            "storyboard": storyboard,
            "characters": character_projection,
            "reference_files": [
                {"character_id": cid, "filename": name, "sha256": _sha256_file(path)}
                for cid, name, path in references
            ],
        }
    )
    return VideoInputs(
        workspace, episode, meta, storyboard, character_projection,
        tuple(references), fingerprint,
    )


def run_video_job(
    workspace: str,
    params: Mapping[str, Any],
    progress_cb: Callable[[str, float], None],
    *,
    client: Optional[DramaVideoClient] = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    """Produce one video. Paid POSTs are never retried by this function."""

    inputs = load_video_inputs(workspace, episode_no=1)
    progress_cb("upload-assets", 0.12)
    submission = read_video_submission(workspace)
    if not real_video_enabled():
        if submission is not None:
            raise DramaVideoProviderError(
                "durable real video submission exists; restore the original real provider configuration"
            )
        return _run_mock_video(inputs, progress_cb)
    resuming_submitted = params.get("resume_submitted") is True
    if resuming_submitted:
        if submission is None or submission.get("status") != "submitted":
            raise DramaVideoProviderError("no submitted video task is available to resume")
        try:
            budget = float(submission["authorized_budget_cny"])
            timeout_minutes = float(submission["authorized_timeout_minutes"])
            estimate = float(submission["estimated_cost_cny"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DramaVideoProviderError(
                "submitted video task is missing its original authorization"
            ) from exc
    else:
        budget, timeout_minutes, estimate = validate_real_video_gate(params)
    deadline = monotonic() + timeout_minutes * 60.0
    authorization = _video_authorization(budget, timeout_minutes, estimate)
    model = os.getenv("SD_VIDEO_MODEL") or DEFAULT_VIDEO_MODEL
    result_hosts = _result_hosts(os.getenv("SD_VIDEO_RESULT_HOSTS") or "")
    if not result_hosts:
        raise ValueError("SD_VIDEO_RESULT_HOSTS must contain at least one exact hostname")
    result_hosts_fingerprint = sha256_data(sorted(result_hosts))
    api = client or DramaVideoClient(request_timeout_seconds=min(60.0, timeout_minutes * 60.0))
    provider_fingerprint = _video_provider_fingerprint(api, model)
    if submission is not None and submission.get("input_fingerprint") != inputs.fingerprint:
        raise DramaVideoInputError("video submission ledger belongs to different inputs")
    if (
        submission is not None
        and submission.get("status") != "succeeded"
        and submission.get("provider_fingerprint") != provider_fingerprint
    ):
        raise DramaVideoProviderError("video submission ledger belongs to different provider configuration")
    if submission is not None and any(
        submission.get(key) != value for key, value in authorization.items()
    ):
        raise DramaVideoProviderError("video submission ledger belongs to different authorization")
    if (
        submission is not None
        and submission.get("result_hosts_fingerprint") is not None
        and submission.get("result_hosts_fingerprint") != result_hosts_fingerprint
    ):
        raise DramaVideoProviderError("video submission result-host allowlist changed")
    if submission is not None and submission.get("status") == "submitted":
        # The process may have crashed after committing the verified MP4/meta
        # pair but before advancing the durable submission ledger.  Adopt that
        # exact local result before polling an expired provider task or URL.
        out = video_paths(workspace)
        local_meta = read_json_optional(out.meta_path, None)
        if (
            isinstance(local_meta, dict)
            and local_meta.get("task_id") == submission.get("task_id")
            and local_meta.get("input_fingerprint") == inputs.fingerprint
            and local_meta.get("provider_fingerprint") == submission.get("provider_fingerprint")
        ):
            try:
                _data, meta = read_video(workspace, episode_no=1)
                reported_cost, cost_unreported = _validated_video_cost_state(local_meta)
            except (FileNotFoundError, OSError, TypeError, ValueError):
                pass
            else:
                _write_video_submission(workspace, {
                    "status": "succeeded",
                    "input_fingerprint": inputs.fingerprint,
                    "provider_fingerprint": provider_fingerprint,
                    "result_hosts_fingerprint": result_hosts_fingerprint,
                    "submission_count": 1,
                    "task_id": submission["task_id"],
                    "cost_cny": reported_cost,
                    "cost_unreported": cost_unreported,
                    **authorization,
                    "updated_at": int(time.time()),
                })
                return {**meta, "committed": True, "resumed": True, "network_requests": 0}
    if submission is not None and submission.get("status") == "succeeded":
        raw_meta = read_json_optional(video_paths(workspace).meta_path, None)
        if not isinstance(raw_meta, dict):
            raise DramaVideoProviderError("video submission artifact metadata is missing")
        _data, meta = read_video(workspace, episode_no=1)
        reported_cost, cost_unreported = _validated_video_cost_state(raw_meta)
        ledger_cost = submission.get("cost_cny")
        if (
            raw_meta.get("task_id") != submission.get("task_id")
            or raw_meta.get("provider_fingerprint") != submission.get("provider_fingerprint")
            or submission.get("cost_unreported") is not cost_unreported
            or isinstance(ledger_cost, bool)
            or not isinstance(ledger_cost, (int, float))
            or not math.isclose(
                float(ledger_cost), 0.0 if cost_unreported else reported_cost,
                rel_tol=0.0, abs_tol=1e-9,
            )
        ):
            raise DramaVideoProviderError("video submission ledger and artifact lineage differ")
        return {**meta, "committed": True, "resumed": True, "network_requests": 0}
    if submission is not None and submission.get("status") == "submitting":
        raise DramaVideoSubmissionUnknown(
            "video submission outcome is unknown; reconcile provider task/billing before any retry"
        )
    if submission is not None and submission.get("status") == "failed":
        raise DramaVideoProviderError("the one authorized video submission already failed")

    final: Dict[str, Any] = {}
    task_id = str(submission.get("task_id") or "") if submission is not None else ""
    if submission is None:
        prompt = _video_prompt(inputs)
        # Callback topology and payload shape are prerequisites only for a new
        # upload/create attempt. A durable submitted task needs neither.
        build_video_payload(
            prompt=prompt,
            duration=VIDEO_DURATION_SECONDS,
            resolution=VIDEO_RESOLUTION,
            ratio=VIDEO_RATIO,
            generate_audio=False,
            watermark=False,
            model=model,
        )
        public_base = (os.getenv("SD_ASSET_PUBLIC_BASE_URL") or "").strip().rstrip("/")
        validate_api_base_url(public_base, label="SD_ASSET_PUBLIC_BASE_URL")
        asset_ids: List[str] = []
        public_tokens: List[str] = []
        try:
            for index, (cid, _filename, asset_path) in enumerate(inputs.references):
                _deadline_checkpoint(deadline, monotonic)
                token = register_public_asset(asset_path, expires_at=deadline)
                public_tokens.append(token)
                asset_url = public_base + "/media/drama-assets/" + quote(token, safe="")
                # Prove the exact public URL reaches the shared durable
                # capability store before the first provider upload. Injected
                # test clients exercise protocol logic without external
                # callback topology.
                if index == 0 and client is None:
                    _verify_public_asset_callback(asset_url, asset_path, deadline, monotonic)
                _set_api_timeout(api, deadline, monotonic)
                response = api.upload_asset(
                    url=asset_url,
                    name=f"episode-1-{cid}",
                    asset_type="Image",
                )
                asset_ids.append(_extract_resource_id(response, "asset"))
                progress_cb(
                    "upload-assets",
                    0.12 + 0.18 * len(asset_ids) / len(inputs.references),
                )
            for asset_id in asset_ids:
                while True:
                    _deadline_checkpoint(deadline, monotonic)
                    _set_api_timeout(api, deadline, monotonic)
                    asset = api.get_asset(asset_id)
                    asset_obj = (
                        asset.get("asset")
                        if isinstance(asset.get("asset"), dict)
                        else asset.get("data")
                    )
                    if (
                        not isinstance(asset_obj, dict)
                        or str(_first(asset_obj, "id", "asset_id", "AssetID", "ID") or "")
                        != asset_id
                    ):
                        raise DramaVideoProviderError(
                            "uploaded asset query did not match the requested asset"
                        )
                    asset_status = str(
                        _first(asset_obj, "status", "Status") or ""
                    ).strip().lower()
                    if asset_status in {
                        "ready", "available", "completed", "succeeded", "success"
                    }:
                        break
                    if not asset_status:
                        raise DramaVideoProviderError(
                            "uploaded asset response is missing status"
                        )
                    if asset_status in _TERMINAL_FAILURE:
                        raise DramaVideoProviderError("uploaded asset processing failed")
                    if asset_status not in _RUNNING:
                        raise DramaVideoProviderError(
                            "uploaded asset returned an unsupported status"
                        )
                    progress_cb("upload-assets", 0.31)
                    sleep(min(POLL_INTERVAL_SECONDS, max(0.0, deadline - monotonic())))
            progress_cb("queued", 0.34)
            _set_api_timeout(api, deadline, monotonic)
            # Persist the ambiguity boundary immediately before the one and only
            # possibly-billable POST.  Any exception before this point is safe
            # to retry; any exception after it requires reconciliation.
            _write_video_submission(workspace, {
                "status": "submitting",
                "input_fingerprint": inputs.fingerprint,
                "provider_fingerprint": provider_fingerprint,
                "result_hosts_fingerprint": result_hosts_fingerprint,
                "submission_count": 1,
                **authorization,
                "updated_at": int(time.time()),
            })
            try:
                created = api.create_video_task(
                    prompt=prompt,
                    reference_asset_ids=asset_ids,
                    duration=VIDEO_DURATION_SECONDS,
                    resolution=VIDEO_RESOLUTION,
                    ratio=VIDEO_RATIO,
                    generate_audio=False,
                    watermark=False,
                    model=model,
                    allow_real_video=True,
                )
            except RequestNotSentError:
                # The transport proves that no request headers/body crossed
                # the socket.  Remove only the marker created immediately
                # above so the single paid opportunity is not falsely spent.
                video_submission_path(workspace).unlink(missing_ok=True)
                raise
            task_id = _extract_resource_id(created, "task")
            _write_video_submission(workspace, {
                "status": "submitted",
                "input_fingerprint": inputs.fingerprint,
                "provider_fingerprint": provider_fingerprint,
                "result_hosts_fingerprint": result_hosts_fingerprint,
                "submission_count": 1,
                "task_id": task_id,
                **authorization,
                "updated_at": int(time.time()),
            })
            progress_cb("queued", 0.4)
            final = created
        finally:
            revoke_public_assets(public_tokens)

    while True:
        _deadline_checkpoint(deadline, monotonic)
        _set_api_timeout(api, deadline, monotonic)
        final = api.get_task(task_id)
        if _extract_resource_id(final, "task") != task_id:
            raise DramaVideoProviderError("video task query did not match the requested task")
        status = _task_status(final)
        if status in _TERMINAL_SUCCESS:
            break
        if status in _TERMINAL_FAILURE:
            terminal_cost = _task_cost_cny(final)
            _write_video_submission(workspace, {
                "status": "failed",
                "input_fingerprint": inputs.fingerprint,
                "provider_fingerprint": provider_fingerprint,
                "result_hosts_fingerprint": result_hosts_fingerprint,
                "submission_count": 1,
                "task_id": task_id,
                "cost_cny": terminal_cost if terminal_cost is not None else 0.0,
                "cost_unreported": terminal_cost is None,
                **authorization,
                "updated_at": int(time.time()),
            })
            raise DramaVideoProviderError(f"video task ended with status={status}")
        if status not in _RUNNING:
            raise DramaVideoProviderError("video task returned an unsupported status")
        progress_cb(
            "generating" if status not in {"pending", "queued", "queueing"} else "queued",
            0.45,
        )
        sleep(min(POLL_INTERVAL_SECONDS, max(0.0, deadline - monotonic())))
    progress_cb("download", 0.82)
    result_url = _task_result_url(final)
    video_bytes, content_type = download_video(
        result_url,
        allowed_hosts=result_hosts,
        timeout_seconds=_remaining_timeout(deadline, monotonic),
    )
    if content_type != "video/mp4":
        raise ValueError("real video result must be an MP4 for strict specification validation")
    spec = _probe_mp4(video_bytes)
    if (
        abs(spec.duration_seconds - VIDEO_DURATION_SECONDS) > 0.25
        or (spec.width, spec.height) != (720, 1280)
    ):
        raise ValueError("video result does not match the authorized duration, ratio, or resolution")
    _deadline_checkpoint(deadline, monotonic)
    if load_video_inputs(workspace, episode_no=1).fingerprint != inputs.fingerprint:
        raise DramaVideoInputError("video inputs changed while the provider task was running")
    cost_cny = _task_cost_cny(final)
    terminal_status = "budget_exceeded" if cost_cny is not None and cost_cny > budget else "succeeded"
    out = video_paths(workspace)
    safe_meta = {
        "schema_version": 1,
        "episode_no": 1,
        "status": terminal_status,
        "provider": urlparse(api.base_url).hostname or "",
        "provider_model": str(os.getenv("SD_VIDEO_MODEL") or DEFAULT_VIDEO_MODEL)[:120],
        "provider_fingerprint": provider_fingerprint,
        "task_id": task_id,
        "input_fingerprint": inputs.fingerprint,
        "duration_seconds": round(spec.duration_seconds, 3),
        "ratio": f"{spec.width // math.gcd(spec.width, spec.height)}:{spec.height // math.gcd(spec.width, spec.height)}",
        "resolution": f"{spec.width}x{spec.height}px",
        "content_type": content_type,
        "file_size_bytes": len(video_bytes),
        "video_sha256": hashlib.sha256(video_bytes).hexdigest(),
        "cost_cny": cost_cny,
        "cost_unreported": cost_cny is None,
        "budget_cny": budget,
        "estimated_cost_cny": estimate,
    }
    _commit_video_pair(out, video_bytes, safe_meta)
    _write_video_submission(workspace, {
        "status": "succeeded",
        "input_fingerprint": inputs.fingerprint,
        "provider_fingerprint": provider_fingerprint,
        "result_hosts_fingerprint": result_hosts_fingerprint,
        "submission_count": 1,
        "task_id": task_id,
        "cost_cny": cost_cny if cost_cny is not None else 0.0,
        "cost_unreported": cost_cny is None,
        **authorization,
        "updated_at": int(time.time()),
    })
    progress_cb(terminal_status, 1.0)
    return {**safe_meta, "committed": True, "resumed": resuming_submitted}


def video_status(workspace: str, *, episode_no: int = 1) -> Dict[str, Any]:
    out = video_paths(workspace, episode_no=episode_no)
    try:
        submission = read_video_submission(workspace, episode_no=episode_no)
    except ValueError:
        return {
            "state": "blocked",
            "error_code": "video_submission_ledger_invalid",
            "download_ready": False,
        }
    if submission is not None:
        ledger_status = submission.get("status")
        if ledger_status in VIDEO_INCOMPLETE_STATUSES:
            authorization_keys = {
                "authorized_budget_cny", "authorized_timeout_minutes",
                "estimated_cost_cny", "authorization_fingerprint",
            }
            if ledger_status == "submitted" and not authorization_keys.issubset(submission):
                return {
                    "state": "blocked",
                    "error_code": "video_submission_authorization_reconciliation_required",
                    "requires_reconciliation": True,
                    "download_ready": False,
                }
            if ledger_status == "submitting":
                return {
                    "state": "submission_unknown",
                    "requires_reconciliation": True,
                    "download_ready": False,
                }
            if ledger_status == "submitted":
                return {"state": "submitted", "resumable_poll": True, "download_ready": False}
            return {"state": "failed", "submission_consumed": True, "download_ready": False}
    meta = read_json_optional(out.meta_path, None)
    if isinstance(meta, dict) and out.video_path.is_file():
        try:
            _data, safe_meta = read_video(workspace, episode_no=episode_no)
        except (FileNotFoundError, OSError, DramaVideoInputError, ValueError):
            safe_meta = None
        if safe_meta is not None:
            return {"state": str(safe_meta.get("status") or "succeeded"), "video": safe_meta, "download_ready": True}
        return {"state": "not_ready", "stale_video": True, "download_ready": False}
    if submission is not None:
        return {
            "state": "blocked",
            "error_code": "video_submission_artifact_missing",
            "download_ready": False,
        }
    try:
        load_video_inputs(workspace, episode_no=episode_no)
    except (DramaVideoInputError, ValueError):
        return {"state": "not_ready", "download_ready": False}
    return {"state": "ready", "download_ready": False}


def read_video(workspace: str, *, episode_no: int = 1) -> tuple[bytes, Dict[str, Any]]:
    out = video_paths(workspace, episode_no=episode_no)
    meta = read_json_optional(out.meta_path, None)
    if not isinstance(meta, dict):
        raise FileNotFoundError("video metadata is missing")
    data = out.video_path.read_bytes()
    if len(data) <= 0 or len(data) > MAX_VIDEO_BYTES or _detect_video_container(data) != "mp4":
        raise ValueError("stored video failed container validation")
    if int(meta.get("file_size_bytes") or -1) != len(data):
        raise ValueError("stored video size does not match metadata")
    if meta.get("video_sha256") != hashlib.sha256(data).hexdigest():
        raise ValueError("stored video hash does not match metadata")
    _validated_video_cost_state(meta)
    if meta.get("provider") != "mock":
        probed = _probe_mp4(data)
        if (
            abs(probed.duration_seconds - VIDEO_DURATION_SECONDS) > 0.25
            or (probed.width, probed.height) != (720, 1280)
            or meta.get("duration_seconds") != round(probed.duration_seconds, 3)
            or meta.get("resolution") != f"{probed.width}x{probed.height}px"
            or meta.get("ratio") != VIDEO_RATIO
        ):
            raise ValueError("stored video measured specification is invalid")
    current = load_video_inputs(workspace, episode_no=episode_no)
    if meta.get("input_fingerprint") != current.fingerprint:
        raise ValueError("stored video is stale for the current episode inputs")
    return data, _safe_video_meta(meta)


def _validated_video_cost_state(meta: Mapping[str, Any]) -> tuple[float, bool]:
    unreported = meta.get("cost_unreported")
    cost = meta.get("cost_cny")
    if type(unreported) is not bool:
        raise ValueError("stored video cost reporting state is invalid")
    if unreported:
        if cost is not None:
            raise ValueError("stored video unreported cost must remain null")
        return 0.0, True
    if (
        isinstance(cost, bool)
        or not isinstance(cost, (int, float))
        or not math.isfinite(float(cost))
        or float(cost) < 0
    ):
        raise ValueError("stored video reported cost is invalid")
    return float(cost), False


def register_public_asset(path: Path, *, expires_at: float) -> str:
    """Freeze an exact image behind an unguessable, host-local short URL.

    The callback route may live in a different Web process from the CLI
    orchestrator, so the capability is persisted under the gitignored
    workspaces root instead of relying on process memory.
    """
    remaining = expires_at - time.monotonic()
    if not math.isfinite(expires_at) or not math.isfinite(remaining) or remaining <= 0:
        raise ValueError("public asset expiry must be in the future")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise DramaVideoInputError("public drama asset is unreadable") from exc
    if len(data) <= 0 or len(data) > MAX_IMAGE_BYTES:
        raise DramaVideoInputError("public drama asset size is invalid")
    try:
        content_type, _suffix = _detect_image_type(data)
    except ValueError as exc:
        raise DramaVideoInputError("public drama asset is invalid") from exc
    token = secrets.token_urlsafe(32)
    data_path, meta_path = _public_asset_paths(token, create_store=True)
    try:
        _atomic_write(data_path, data)
        write_json(meta_path, {
            "schema_version": PUBLIC_ASSET_STORE_SCHEMA_VERSION,
            "token": token,
            "content_type": content_type,
            "file_size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "expires_at_epoch": time.time() + remaining,
        })
    except BaseException:
        meta_path.unlink(missing_ok=True)
        data_path.unlink(missing_ok=True)
        raise
    return token


def revoke_public_assets(tokens: Iterable[str]) -> None:
    for token in tokens:
        if not _valid_public_asset_token(token):
            continue
        try:
            data_path, meta_path = _public_asset_paths(token)
        except (FileNotFoundError, OSError, ValueError):
            continue
        meta_path.unlink(missing_ok=True)
        data_path.unlink(missing_ok=True)


def read_public_asset(token: str) -> tuple[bytes, str]:
    if not _valid_public_asset_token(token):
        raise FileNotFoundError("public drama asset token not found")
    try:
        data_path, meta_path = _public_asset_paths(token)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise FileNotFoundError("public drama asset token not found") from exc
    try:
        if (
            data_path.is_symlink()
            or meta_path.is_symlink()
            or not data_path.is_file()
            or not meta_path.is_file()
        ):
            raise FileNotFoundError("public drama asset token not found")
        meta = json.loads(_read_public_asset_file(meta_path, 16_384).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FileNotFoundError("public drama asset token not found") from exc
    if (
        not isinstance(meta, dict)
        or meta.get("schema_version") != PUBLIC_ASSET_STORE_SCHEMA_VERSION
        or meta.get("token") != token
        or meta.get("content_type") != "image/png"
        or type(meta.get("file_size_bytes")) is not int
        or not 0 < meta["file_size_bytes"] <= MAX_IMAGE_BYTES
        or not isinstance(meta.get("sha256"), str)
        or len(meta["sha256"]) != 64
        or isinstance(meta.get("expires_at_epoch"), bool)
        or not isinstance(meta.get("expires_at_epoch"), (int, float))
        or not math.isfinite(float(meta["expires_at_epoch"]))
    ):
        raise FileNotFoundError("public drama asset token not found")
    if time.time() >= float(meta["expires_at_epoch"]):
        revoke_public_assets([token])
        raise FileNotFoundError("public drama asset token expired")
    try:
        data = _read_public_asset_file(data_path, MAX_IMAGE_BYTES)
    except OSError as exc:
        raise FileNotFoundError("public drama asset token not found") from exc
    try:
        content_type, _suffix = _detect_image_type(data)
    except ValueError as exc:
        raise FileNotFoundError("public drama asset token not found") from exc
    if (
        len(data) != meta["file_size_bytes"]
        or hashlib.sha256(data).hexdigest() != meta["sha256"]
    ):
        raise FileNotFoundError("public drama asset token not found")
    return data, content_type


def _valid_public_asset_token(token: Any) -> bool:
    return (
        isinstance(token, str)
        and 32 <= len(token) <= 64
        and all(
            ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            for ch in token
        )
    )


def _public_asset_store(*, create: bool = False) -> Path:
    root = paths.WORKSPACE_DIR
    store = root / PUBLIC_ASSET_STORE_DIRNAME
    if create:
        store.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        stat_result = store.lstat()
    except OSError:
        raise
    if store.is_symlink() or not store.is_dir() or stat_result.st_nlink < 1:
        raise ValueError("public drama asset store must be a regular directory")
    resolved = store.resolve(strict=True)
    try:
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ValueError("public drama asset store escapes the workspace root") from exc
    return resolved


def _public_asset_paths(token: str, *, create_store: bool = False) -> tuple[Path, Path]:
    store = _public_asset_store(create=create_store)
    return store / f"{token}.bin", store / f"{token}.json"


def _read_public_asset_file(path: Path, maximum: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(maximum + 1)
    finally:
        os.close(fd)
    if len(data) > maximum:
        raise ValueError("public drama asset store file exceeds its size limit")
    return data


def _verify_public_asset_callback(
    url: str,
    expected_path: Path,
    deadline: float,
    monotonic: Callable[[], float],
) -> None:
    """Prove the public callback serves this host's exact frozen capability.

    This zero-provider-cost GET is deliberately completed before any asset API
    request.  This also proves that a separate Web process shares the same
    bounded capability store before the provider sees any asset URL.
    """

    parsed = urlparse(url)
    data, _content_type, _suffix = _download_generated_image(
        url,
        api_hostname=parsed.hostname or "",
        timeout_seconds=_remaining_timeout(deadline, monotonic, maximum=15.0),
    )
    try:
        expected = expected_path.read_bytes()
    except OSError as exc:
        raise DramaVideoInputError("callback source asset disappeared") from exc
    if not secrets.compare_digest(hashlib.sha256(data).digest(), hashlib.sha256(expected).digest()):
        raise DramaVideoInputError("public asset callback did not return the registered image")


def download_video(url: str, *, allowed_hosts: Iterable[str], timeout_seconds: float) -> tuple[bytes, str]:
    parsed = urlparse(url)
    hosts = {str(item).strip().lower().rstrip(".") for item in allowed_hosts if str(item).strip()}
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("video result must be an https URL without credentials or fragment")
    if hostname not in hosts:
        raise ValueError("video result hostname is not allowlisted")
    _validate_public_endpoint(hostname)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("video download timeout must be finite and positive")
    connection = http.client.HTTPSConnection(hostname, port=parsed.port or 443, timeout=timeout_seconds)
    try:
        # Connect/TLS first, then validate the actual peer before sending the signed URL.
        connection.connect()
        peer_ip = connection.sock.getpeername()[0] if connection.sock is not None else ""
        _validate_public_endpoint(peer_ip)
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        connection.request("GET", target, headers={"User-Agent": "DragonRajaAIContinuer/1.0"})
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise ValueError("video download redirects are not allowed")
        if response.status != 200:
            raise ValueError("video download returned a non-success status")
        content_type = response.getheader("content-type", "").split(";", 1)[0].strip().lower()
        content_length = response.getheader("content-length")
        if content_length:
            try:
                declared_length = int(content_length)
                if declared_length < 0:
                    raise ValueError("video content-length is invalid")
                if declared_length > MAX_VIDEO_BYTES:
                    raise ValueError("video download exceeds size limit")
            except ValueError as exc:
                if "exceeds" in str(exc):
                    raise
                raise ValueError("video content-length is invalid") from exc
        data = response.read(MAX_VIDEO_BYTES + 1)
    finally:
        connection.close()
    if len(data) > MAX_VIDEO_BYTES:
        raise ValueError("video download exceeds size limit")
    container = _detect_video_container(data)
    if container != "mp4":
        raise ValueError("video MVP requires an MP4 container")
    if content_type != "video/mp4":
        raise ValueError("video content-type does not match container")
    return data, content_type


def _run_mock_video(inputs: VideoInputs, progress_cb: Callable[[str, float], None]) -> Dict[str, Any]:
    progress_cb("queued", 0.35)
    progress_cb("generating", 0.62)
    data = _MOCK_MP4
    out = video_paths(inputs.workspace)
    meta = {
        "schema_version": 1,
        "episode_no": 1,
        "status": "succeeded",
        "provider": "mock",
        "provider_model": "mock",
        "task_id": "mock-video-task-1",
        "input_fingerprint": inputs.fingerprint,
        "duration_seconds": VIDEO_DURATION_SECONDS,
        "ratio": VIDEO_RATIO,
        "resolution": VIDEO_RESOLUTION,
        "content_type": "video/mp4",
        "file_size_bytes": len(data),
        "video_sha256": hashlib.sha256(data).hexdigest(),
        "cost_cny": 0.0,
        "cost_unreported": False,
        "budget_cny": 0.0,
        "estimated_cost_cny": 0.0,
    }
    _commit_video_pair(out, data, meta)
    progress_cb("succeeded", 1.0)
    return {**meta, "committed": True, "network_requests": 0}


def _video_prompt(inputs: VideoInputs) -> str:
    highlight = next((row for row in inputs.episode.get("storyboard", []) if isinstance(row, dict) and row.get("is_highlight")), None)
    shot = highlight if isinstance(highlight, dict) else (inputs.episode.get("storyboard") or [{}])[0]
    visual = " ".join(str(shot.get("visual_content") or "原创短剧高光镜头").split())[:900]
    return f"竖屏短剧，第1集高光片段。{visual}。角色外观严格参考上传素材；镜头连贯，无文字水印。"


def _video_provider_fingerprint(api: Any, model: str) -> str:
    """Bind a resumable task id to the exact non-secret provider configuration."""

    base_url = str(getattr(api, "base_url", "") or "").strip().rstrip("/")
    if not base_url:
        raise ValueError("video provider base URL is required")
    return sha256_data({
        "base_url": base_url,
        "model": model,
        "api_key": str(getattr(api, "api_key", "") or ""),
    })


def _extract_resource_id(response: Mapping[str, Any], kind: str) -> str:
    nested = response.get(kind) if isinstance(response.get(kind), dict) else None
    data = response.get("data") if isinstance(response.get("data"), dict) else None
    candidates: List[Any] = []
    keys = ("id", "ID", f"{kind}_id", "AssetID", "TaskID")
    for container in (response, nested or {}, data or {}):
        candidates.extend(container[key] for key in keys if key in container)
    valid: List[str] = []
    for value in candidates:
        if value is None:
            continue
        if not (
            isinstance(value, str)
            and value.isascii()
            and value
            and len(value) <= 128
            and all(ch.isalnum() or ch in "_-" for ch in value)
        ):
            raise DramaVideoProviderError(f"video API response contains an invalid {kind} id")
        valid.append(value)
    if valid:
        if len(set(valid)) != 1:
            raise DramaVideoProviderError(f"video API response contains conflicting {kind} ids")
        return valid[0]
    raise DramaVideoProviderError(f"video API response is missing a valid {kind} id")


def _task_object(response: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("task", "data"):
        value = response.get(key)
        if isinstance(value, dict):
            return value
    return response


def _task_status(response: Mapping[str, Any]) -> str:
    value = _first(_task_object(response), "status", "Status")
    if not isinstance(value, str) or not value.strip():
        raise DramaVideoProviderError("video task response is missing status")
    return value.strip().lower()


def _task_result_url(response: Mapping[str, Any]) -> str:
    task = _task_object(response)
    output = task.get("output") if isinstance(task.get("output"), dict) else {}
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    for value in (
        _first(task, "video_url", "result_url", "videoUrl", "VideoURL"),
        _first(output, "video_url", "url", "videoUrl", "VideoURL", "URL"),
        _first(result, "video_url", "url", "videoUrl", "VideoURL", "URL"),
    ):
        if isinstance(value, str) and len(value) <= 4096:
            return value
    raise DramaVideoProviderError("completed video task is missing a result URL")


def _task_cost_cny(response: Mapping[str, Any]) -> Optional[float]:
    task = _task_object(response)
    for raw in (task.get("cost_cny"), (task.get("usage") or {}).get("cost_cny") if isinstance(task.get("usage"), dict) else None):
        if isinstance(raw, bool):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(value) and value >= 0:
            return value
    return None


def _first(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value:
            return value.get(key)
    return None


def _safe_video_meta(meta: Mapping[str, Any]) -> Dict[str, Any]:
    allowed = (
        "schema_version", "episode_no", "status", "provider", "provider_model", "task_id",
        "duration_seconds", "ratio", "resolution", "content_type", "file_size_bytes", "cost_cny",
        "budget_cny", "estimated_cost_cny", "cost_unreported",
    )
    return {key: meta.get(key) for key in allowed if key in meta}


def _detect_video_container(data: bytes) -> str:
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    raise ValueError("video bytes must be an MP4 or WebM container")


def _mp4_boxes(data: bytes, start: int, end: int) -> list[tuple[bytes, int, int]]:
    boxes: list[tuple[bytes, int, int]] = []
    cursor = start
    while cursor < end:
        if end - cursor < 8:
            raise ValueError("MP4 contains a truncated box header")
        size = int.from_bytes(data[cursor:cursor + 4], "big")
        box_type = data[cursor + 4:cursor + 8]
        header = 8
        if size == 1:
            if end - cursor < 16:
                raise ValueError("MP4 contains a truncated extended box header")
            size = int.from_bytes(data[cursor + 8:cursor + 16], "big")
            header = 16
        elif size == 0:
            size = end - cursor
        if size < header or cursor + size > end:
            raise ValueError("MP4 box size is invalid")
        boxes.append((box_type, cursor + header, cursor + size))
        cursor += size
    return boxes


def _first_mp4_box(data: bytes, start: int, end: int, wanted: bytes) -> tuple[int, int]:
    for box_type, payload_start, box_end in _mp4_boxes(data, start, end):
        if box_type == wanted:
            return payload_start, box_end
    raise ValueError(f"MP4 is missing required {wanted.decode('ascii', 'ignore')} box")


def _probe_mp4(data: bytes) -> VideoSpec:
    """Parse bounded ISO-BMFF metadata without trusting MIME or filename."""

    top = _mp4_boxes(data, 0, len(data))
    types = {box_type for box_type, _start, _end in top}
    if not {b"ftyp", b"moov", b"mdat"}.issubset(types):
        raise ValueError("MP4 must contain ftyp, moov, and mdat boxes")
    if not any(box_type == b"mdat" and box_end > payload_start for box_type, payload_start, box_end in top):
        raise ValueError("MP4 media data is empty")
    moov_start, moov_end = _first_mp4_box(data, 0, len(data), b"moov")
    mvhd_start, mvhd_end = _first_mp4_box(data, moov_start, moov_end, b"mvhd")
    mvhd = data[mvhd_start:mvhd_end]
    if len(mvhd) < 20:
        raise ValueError("MP4 mvhd box is truncated")
    version = mvhd[0]
    if version == 0:
        timescale = int.from_bytes(mvhd[12:16], "big")
        duration = int.from_bytes(mvhd[16:20], "big")
    elif version == 1 and len(mvhd) >= 32:
        timescale = int.from_bytes(mvhd[20:24], "big")
        duration = int.from_bytes(mvhd[24:32], "big")
    else:
        raise ValueError("MP4 mvhd version is unsupported or truncated")
    if timescale <= 0 or duration <= 0:
        raise ValueError("MP4 duration metadata is invalid")

    width = height = 0
    for box_type, trak_start, trak_end in _mp4_boxes(data, moov_start, moov_end):
        if box_type != b"trak":
            continue
        try:
            mdia_start, mdia_end = _first_mp4_box(data, trak_start, trak_end, b"mdia")
            hdlr_start, hdlr_end = _first_mp4_box(data, mdia_start, mdia_end, b"hdlr")
            hdlr = data[hdlr_start:hdlr_end]
            if len(hdlr) < 12 or hdlr[8:12] != b"vide":
                continue
            minf_start, minf_end = _first_mp4_box(data, mdia_start, mdia_end, b"minf")
            stbl_start, stbl_end = _first_mp4_box(data, minf_start, minf_end, b"stbl")
            stsd_start, stsd_end = _first_mp4_box(data, stbl_start, stbl_end, b"stsd")
            stsz_start, stsz_end = _first_mp4_box(data, stbl_start, stbl_end, b"stsz")
            stsd = data[stsd_start:stsd_end]
            stsz = data[stsz_start:stsz_end]
            if (
                len(stsd) < 8 or int.from_bytes(stsd[4:8], "big") <= 0
                or len(stsz) < 12 or int.from_bytes(stsz[8:12], "big") <= 0
            ):
                raise ValueError("MP4 video sample table is empty or truncated")
            tkhd_start, tkhd_end = _first_mp4_box(data, trak_start, trak_end, b"tkhd")
            tkhd = data[tkhd_start:tkhd_end]
            if not tkhd:
                continue
            offset = 76 if tkhd[0] == 0 else 88 if tkhd[0] == 1 else -1
            if offset < 0 or len(tkhd) < offset + 8:
                raise ValueError("MP4 tkhd box is truncated")
            width = int.from_bytes(tkhd[offset:offset + 4], "big") >> 16
            height = int.from_bytes(tkhd[offset + 4:offset + 8], "big") >> 16
            break
        except ValueError:
            continue
    if width <= 0 or height <= 0:
        raise ValueError("MP4 has no valid video track dimensions")
    return VideoSpec(duration / timescale, width, height)


def _result_hosts(raw: str) -> frozenset[str]:
    hosts = set()
    for item in raw.split(","):
        host = item.strip().lower().rstrip(".")
        if host and "/" not in host and ":" not in host and "@" not in host:
            hosts.add(host)
        elif host:
            raise ValueError("SD_VIDEO_RESULT_HOSTS must contain exact hostnames")
    return frozenset(hosts)


def _finite_positive(raw: Any, name: str, *, maximum: float) -> float:
    if isinstance(raw, bool):
        raise ValueError(f"{name} must be a finite positive number")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite positive number") from exc
    if not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def _deadline_checkpoint(deadline: float, monotonic: Callable[[], float]) -> None:
    if monotonic() >= deadline:
        raise DramaVideoTimedOut("video job timed out; no automatic retry was attempted")


def _remaining_timeout(
    deadline: float,
    monotonic: Callable[[], float],
    *,
    maximum: float = 60.0,
) -> float:
    remaining = deadline - monotonic()
    if not math.isfinite(remaining) or remaining <= 0:
        raise DramaVideoTimedOut("video job timed out; no automatic retry was attempted")
    return min(maximum, remaining)


def _set_api_timeout(api: DramaVideoClient, deadline: float, monotonic: Callable[[], float]) -> None:
    api.request_timeout_seconds = _remaining_timeout(deadline, monotonic)


def _commit_video_pair(out: VideoPaths, data: bytes, meta: Mapping[str, Any]) -> None:
    """Replace video+metadata as one recoverable pair."""

    old_video = out.video_path.read_bytes() if out.video_path.is_file() else None
    old_meta = out.meta_path.read_bytes() if out.meta_path.is_file() else None
    try:
        _atomic_write(out.video_path, data)
        write_json(out.meta_path, dict(meta))
    except BaseException:
        if old_video is None:
            out.video_path.unlink(missing_ok=True)
        else:
            _atomic_write(out.video_path, old_video)
        if old_meta is None:
            out.meta_path.unlink(missing_ok=True)
        else:
            _atomic_write(out.meta_path, old_meta)
        raise


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
