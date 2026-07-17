"""Strict Web projection and guarded mutation for D2-D4 shot-video facts."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Literal, Mapping, Optional
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import paths
from .drama_schemas import ShotVideoSelection, normalize_episode_no
from .drama_shot_video_attempt_store import (
    inspect_episode_shot_video_attempts,
    load_episode_shot_video_attempts,
)
from .drama_shot_video_candidate_store import (
    MAX_SHOT_VIDEO_CANDIDATE_BYTES,
    _read_manifest,
    _candidate_payload_identity,
    _mp4_boxes,
    inspect_episode_shot_video_candidates,
    select_episode_shot_video_candidate,
)
from .drama_shot_video_continuity import build_shot_video_continuity_report
from .drama_shot_video_store import load_fresh_episode_shot_video_plan
from .drama_store import _read_strict_workspace_bytes
from .schemas import model_to_dict


_SHOT_ID_PATTERN = r"^shot_[0-9a-f]{24}$"
_CANDIDATE_ID_PATTERN = r"^svc_[0-9a-f]{24}$"
_ATTEMPT_ID_PATTERN = r"^sva_[0-9a-f]{24}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
MAX_WEB_VIDEO_CANDIDATES_PER_SHOT = 8
MAX_WEB_VIDEO_PREVIEW_CANDIDATES = 64
MAX_WEB_VIDEO_PREVIEW_SOURCE_BYTES = 32 * 1024 * 1024
MAX_WEB_VIDEO_PREVIEW_BYTES = 4 * 1024 * 1024
MAX_WEB_VIDEO_PREVIEW_PIXELS = 2_073_600
MAX_WEB_VIDEO_PREVIEW_LONG_EDGE = 1920
MAX_WEB_VIDEO_PREVIEW_SHORT_EDGE = 1080
MAX_WEB_VIDEO_PREVIEW_SAMPLES = 36_000
MAX_WEB_VIDEO_PREVIEW_CACHE_ENTRIES = 4
_PUBLIC_CANDIDATE_REASONS = {
    "missing",
    "schema_invalid",
    "schema_unsupported",
    "manifest_hash_mismatch",
    "request_invalid",
    "source_not_fresh",
    "artifact_or_manifest_invalid",
    "artifact_invalid",
    "source_plan_mismatch",
    "selection_stale",
}
_PUBLIC_ATTEMPT_REASONS = {
    "missing",
    "incomplete",
    "unfinished_attempts",
    "source_changed",
    "schema_invalid",
    "inspection_failed",
}
_MP4_WEB_BOX_ALLOWLIST = {
    (): {
        b"ftyp",
        b"free",
        b"moov",
        b"mdat",
        b"moof",
        b"mfra",
        b"sidx",
        b"styp",
    },
    (b"moov",): {b"mvhd", b"trak", b"mvex"},
    (b"moov", b"trak"): {b"tkhd", b"edts", b"mdia"},
    (b"moov", b"trak", b"edts"): {b"elst"},
    (b"moov", b"trak", b"mdia"): {b"mdhd", b"hdlr", b"minf"},
    (b"moov", b"trak", b"mdia", b"minf"): {
        b"vmhd",
        b"smhd",
        b"hmhd",
        b"dinf",
        b"stbl",
    },
    (b"moov", b"trak", b"mdia", b"minf", b"dinf"): {b"dref"},
    (b"moov", b"trak", b"mdia", b"minf", b"stbl"): {
        b"stsd",
        b"stts",
        b"ctts",
        b"stsc",
        b"stsz",
        b"stco",
        b"co64",
        b"stss",
        b"sdtp",
        b"sgpd",
        b"sbgp",
        b"padb",
        b"subs",
    },
    (b"moov", b"mvex"): {b"trex", b"mehd"},
    (b"moof",): {b"mfhd", b"traf"},
    (b"moof", b"traf"): {
        b"tfhd",
        b"tfdt",
        b"trun",
        b"sdtp",
        b"saiz",
        b"saio",
        b"senc",
        b"sbgp",
        b"sgpd",
    },
    (b"mfra",): {b"tfra", b"mfro"},
}
_MP4_WEB_CONTAINER_PATHS = frozenset(_MP4_WEB_BOX_ALLOWLIST)
_PREVIEW_SEMAPHORE = threading.BoundedSemaphore(2)
_OVERVIEW_SEMAPHORE = threading.BoundedSemaphore(2)
_MUTATION_SEMAPHORE = threading.BoundedSemaphore(2)
_PREVIEW_CACHE_LOCK = threading.Lock()
_PREVIEW_CACHE: "OrderedDict[str, bytes]" = OrderedDict()
_PREVIEW_INFLIGHT: dict[str, threading.Event] = {}


class DramaShotVideoWebConflict(RuntimeError):
    """A current-state mismatch that requires the browser to reload."""


class DramaShotVideoWebBusy(RuntimeError):
    """A bounded local media operation is at capacity."""


class ShotVideoWebAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    attempt_id: str = Field(pattern=_ATTEMPT_ID_PATTERN)
    status: Literal[
        "started",
        "not_sent",
        "submission_unknown",
        "submitted",
        "provider_succeeded",
        "provider_failed",
        "artifact_received",
        "succeeded",
        "closed_unknown",
    ]
    outcome: Literal["not_sent", "unknown", "submitted", "terminal"]


class ShotVideoWebCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    candidate_id: str = Field(pattern=_CANDIDATE_ID_PATTERN)
    candidate_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    duration_milliseconds: int = Field(ge=1, le=300_000)
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    size_bytes: int = Field(ge=1, le=MAX_SHOT_VIDEO_CANDIDATE_BYTES)
    has_audio_track: bool
    is_placeholder: bool
    selected: bool
    current: bool
    preview_available: bool
    preview_url: Optional[str] = Field(default=None, min_length=1, max_length=500)


class ShotVideoWebShot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    current_request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    selection_revision: int = Field(ge=0, le=2_147_483_647)
    selected: Optional[Dict[str, str]] = None
    affected: bool
    coverage_state: Literal[
        "ready",
        "missing",
        "stale",
        "invalid",
        "web_unverified",
        "placeholder",
        "blocked",
    ]
    attempt: Optional[ShotVideoWebAttempt] = None
    candidate_count: int = Field(ge=0, le=32)
    omitted_candidate_count: int = Field(ge=0, le=32)
    candidates: List[ShotVideoWebCandidate] = Field(
        max_length=MAX_WEB_VIDEO_CANDIDATES_PER_SHOT
    )


class ShotVideoWebCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal[
        "ready",
        "incomplete",
        "stale",
        "invalid",
        "web_unverified",
        "blocked_source",
    ]
    required_shot_ids: List[str] = Field(max_length=100)
    selected_fresh_shot_ids: List[str] = Field(max_length=100)
    missing_selection_shot_ids: List[str] = Field(max_length=100)
    stale_candidate_shot_ids: List[str] = Field(max_length=100)
    invalid_artifact_shot_ids: List[str] = Field(max_length=100)
    web_unverified_shot_ids: List[str] = Field(max_length=100)
    non_production_shot_ids: List[str] = Field(max_length=100)
    blocked_source_shot_ids: List[str] = Field(max_length=100)
    coverage_fingerprint: str = Field(pattern=_SHA256_PATTERN)


class ShotVideoWebContinuity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["ready", "degraded_preview", "blocked"]
    ready_for_compose: bool
    blocked_shot_ids: List[str] = Field(max_length=100)
    degraded_preview_shot_ids: List[str] = Field(max_length=100)
    broken_lineage_shot_ids: List[str] = Field(max_length=100)
    character_version_change_shot_ids: List[str] = Field(max_length=100)
    scene_version_change_shot_ids: List[str] = Field(max_length=100)
    camera_reversal_shot_ids: List[str] = Field(max_length=100)
    report_fingerprint: str = Field(pattern=_SHA256_PATTERN)


class ShotVideoWebAttemptSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    state: Literal[
        "needs_attempts",
        "fresh",
        "reconciliation_required",
        "stale",
        "invalid",
    ]
    reasons: List[str] = Field(max_length=16)
    ledger_fingerprint: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)
    not_sent_count: int = Field(ge=0, le=100)
    unknown_count: int = Field(ge=0, le=100)
    submitted_count: int = Field(ge=0, le=100)
    terminal_count: int = Field(ge=0, le=100)


class ShotVideoWebOverview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: Optional[int] = Field(default=None, ge=1)
    episode_no: int = Field(ge=1, le=100)
    state: Literal[
        "needs_shot_video_assets",
        "fresh",
        "stale",
        "invalid",
        "blocked_source",
    ]
    reasons: List[str] = Field(max_length=8)
    manifest_fingerprint: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)
    mutation_allowed: bool
    affected_shot_ids: List[str] = Field(max_length=100)
    coverage: Optional[ShotVideoWebCoverage] = None
    continuity: Optional[ShotVideoWebContinuity] = None
    attempts: ShotVideoWebAttemptSummary
    shots: List[ShotVideoWebShot] = Field(max_length=100)


class ShotVideoSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    episode_no: int = Field(ge=1, le=100)
    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    candidate_id: Optional[str] = Field(default=None, pattern=_CANDIDATE_ID_PATTERN)
    expected_selection_revision: int = Field(ge=0, le=2_147_483_647)
    expected_current_selection: Optional[Dict[str, str]] = None
    expected_manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("episode_no", "expected_selection_revision", mode="before")
    @classmethod
    def _integers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("expected_current_selection", mode="before")
    @classmethod
    def _selection_is_exact(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError("expected_current_selection must be an object or null")
        return model_to_dict(ShotVideoSelection(**dict(value)))


class ShotVideoSelectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    changed: bool
    overview: ShotVideoWebOverview


def _attempt_outcome(status: str) -> str:
    if status == "not_sent":
        return "not_sent"
    if status in {"started", "submission_unknown"}:
        return "unknown"
    if status in {"submitted", "provider_succeeded", "artifact_received"}:
        return "submitted"
    return "terminal"


def _invalid_attempt_summary() -> ShotVideoWebAttemptSummary:
    return ShotVideoWebAttemptSummary(
        state="invalid",
        reasons=["inspection_failed"],
        ledger_fingerprint=None,
        not_sent_count=0,
        unknown_count=0,
        submitted_count=0,
        terminal_count=0,
    )


def _attempt_projection(
    workspace: str,
    episode_no: int,
) -> tuple[ShotVideoWebAttemptSummary, dict[str, Any]]:
    inspection = inspect_episode_shot_video_attempts(
        workspace,
        episode_no=episode_no,
    )
    latest: dict[str, Any] = {}
    if inspection.ledger_fingerprint is not None:
        try:
            ledger = load_episode_shot_video_attempts(
                workspace,
                episode_no=episode_no,
            )
            if ledger.ledger_fingerprint != inspection.ledger_fingerprint:
                return _invalid_attempt_summary(), {}
            for record in ledger.attempts:
                latest[record.spec.shot_id] = record
        except (OSError, RecursionError, TypeError, ValueError):
            return _invalid_attempt_summary(), {}
    return (
        ShotVideoWebAttemptSummary(
            state=inspection.state,
            reasons=[
                reason
                for reason in inspection.reasons
                if reason in _PUBLIC_ATTEMPT_REASONS
            ],
            ledger_fingerprint=inspection.ledger_fingerprint,
            not_sent_count=len(inspection.not_sent_attempt_ids),
            unknown_count=len(inspection.unknown_attempt_ids),
            submitted_count=len(inspection.submitted_attempt_ids),
            terminal_count=len(inspection.terminal_attempt_ids),
        ),
        latest,
    )


def _coverage_state(
    coverage: Any,
    shot_id: str,
    *,
    web_unverified_shot_ids: set[str],
) -> str:
    if coverage is None:
        return "missing"
    if shot_id in web_unverified_shot_ids:
        return "web_unverified"
    if shot_id in coverage.blocked_source_shot_ids:
        return "blocked"
    if shot_id in coverage.invalid_artifact_shot_ids:
        return "invalid"
    if shot_id in coverage.stale_candidate_shot_ids:
        return "stale"
    if shot_id in coverage.non_production_shot_ids:
        return "placeholder"
    if shot_id in coverage.selected_fresh_shot_ids:
        return "ready"
    return "missing"


def build_shot_video_web_overview(
    workspace: str,
    *,
    episode_no: int = 1,
) -> ShotVideoWebOverview:
    if not _OVERVIEW_SEMAPHORE.acquire(timeout=0.25):
        raise RuntimeError("shot video overview is busy")
    try:
        return _build_shot_video_web_overview(workspace, episode_no=episode_no)
    finally:
        _OVERVIEW_SEMAPHORE.release()


def _build_shot_video_web_overview(
    workspace: str,
    *,
    episode_no: int = 1,
) -> ShotVideoWebOverview:
    number = normalize_episode_no(episode_no)
    inspection = inspect_episode_shot_video_candidates(
        workspace,
        episode_no=number,
        maximum_artifact_bytes=MAX_WEB_VIDEO_PREVIEW_SOURCE_BYTES,
        defer_oversize_artifacts=True,
    )
    attempt_summary, latest_attempts = _attempt_projection(workspace, number)
    manifest = inspection.manifest
    coverage = inspection.coverage
    expose_candidates = inspection.state in {"fresh", "stale"} and manifest is not None
    continuity = None
    current_specs: dict[str, str] = {}
    web_unverified_shot_ids: set[str] = set()
    if manifest is not None:
        for pool in manifest.shots:
            if pool.selected is None:
                continue
            selected_candidate = next(
                (
                    item
                    for item in pool.candidates
                    if item.candidate_id == pool.selected.candidate_id
                    and item.candidate_fingerprint
                    == pool.selected.candidate_fingerprint
                ),
                None,
            )
            if (
                selected_candidate is not None
                and selected_candidate.artifact.size_bytes
                > MAX_WEB_VIDEO_PREVIEW_SOURCE_BYTES
            ):
                web_unverified_shot_ids.add(pool.shot_id)
    if manifest is not None and coverage is not None:
        try:
            plan = load_fresh_episode_shot_video_plan(workspace, episode_no=number)
            current_specs = {
                item.shot_id: item.spec_fingerprint for item in plan.shot_specs
            }
            report = build_shot_video_continuity_report(
                plan,
                manifest,
                invalid_artifact_shot_ids=(
                    *coverage.invalid_artifact_shot_ids,
                    *sorted(web_unverified_shot_ids),
                ),
                blocked_source_shot_ids=coverage.blocked_source_shot_ids,
            )
            continuity = ShotVideoWebContinuity(
                status=report.status,
                ready_for_compose=report.ready_for_compose,
                blocked_shot_ids=list(report.blocked_shot_ids),
                degraded_preview_shot_ids=list(report.degraded_preview_shot_ids),
                broken_lineage_shot_ids=list(report.broken_lineage_shot_ids),
                character_version_change_shot_ids=list(
                    report.character_version_change_shot_ids
                ),
                scene_version_change_shot_ids=list(
                    report.scene_version_change_shot_ids
                ),
                camera_reversal_shot_ids=list(report.camera_reversal_shot_ids),
                report_fingerprint=report.report_fingerprint,
            )
        except (OSError, RecursionError, TypeError, ValueError):
            continuity = None
    shots: list[ShotVideoWebShot] = []
    if expose_candidates and manifest is not None:
        affected = set(inspection.affected_shot_ids)
        encoded_workspace = quote(workspace, safe="")
        preview_slots = MAX_WEB_VIDEO_PREVIEW_CANDIDATES
        for pool in manifest.shots:
            selected = model_to_dict(pool.selected) if pool.selected is not None else None
            candidates: list[ShotVideoWebCandidate] = []
            ordered = sorted(pool.candidates, key=lambda item: item.candidate_id)
            selected_candidate = next(
                (
                    item
                    for item in ordered
                    if pool.selected is not None
                    and item.candidate_id == pool.selected.candidate_id
                    and item.candidate_fingerprint
                    == pool.selected.candidate_fingerprint
                ),
                None,
            )
            visible = list(ordered[-MAX_WEB_VIDEO_CANDIDATES_PER_SHOT:])
            if (
                selected_candidate is not None
                and selected_candidate not in visible
                and visible
            ):
                visible[0] = selected_candidate
                visible.sort(key=lambda item: item.candidate_id)
            for candidate in visible:
                is_selected = bool(
                    pool.selected is not None
                    and pool.selected.candidate_id == candidate.candidate_id
                    and pool.selected.candidate_fingerprint
                    == candidate.candidate_fingerprint
                )
                current = bool(
                    current_specs.get(pool.shot_id)
                    and candidate.request_fingerprint
                    == current_specs.get(pool.shot_id)
                )
                preview_available = (
                    preview_slots > 0
                    and max(
                        candidate.artifact.width,
                        candidate.artifact.height,
                    )
                    <= MAX_WEB_VIDEO_PREVIEW_LONG_EDGE
                    and min(
                        candidate.artifact.width,
                        candidate.artifact.height,
                    )
                    <= MAX_WEB_VIDEO_PREVIEW_SHORT_EDGE
                    and candidate.artifact.width
                    * candidate.artifact.height
                    <= MAX_WEB_VIDEO_PREVIEW_PIXELS
                    and candidate.artifact.size_bytes
                    <= MAX_WEB_VIDEO_PREVIEW_SOURCE_BYTES
                )
                if preview_available:
                    preview_slots -= 1
                candidates.append(
                    ShotVideoWebCandidate(
                        candidate_id=candidate.candidate_id,
                        candidate_fingerprint=candidate.candidate_fingerprint,
                        request_fingerprint=candidate.request_fingerprint,
                        duration_milliseconds=candidate.artifact.duration_milliseconds,
                        width=candidate.artifact.width,
                        height=candidate.artifact.height,
                        size_bytes=candidate.artifact.size_bytes,
                        has_audio_track=candidate.artifact.has_audio_track,
                        is_placeholder=candidate.is_placeholder,
                        selected=is_selected,
                        current=current,
                        preview_available=preview_available,
                        preview_url=(
                            (
                                f"/api/workspace/{encoded_workspace}/drama/shot-videos/"
                                f"{number}/{pool.shot_id}/{candidate.candidate_id}.mp4"
                            )
                            if preview_available
                            else None
                        ),
                    )
                )
            record = latest_attempts.get(pool.shot_id)
            attempt = (
                ShotVideoWebAttempt(
                    attempt_id=record.attempt_id,
                    status=record.status,
                    outcome=_attempt_outcome(record.status),
                )
                if record is not None
                else None
            )
            shots.append(
                ShotVideoWebShot(
                    shot_id=pool.shot_id,
                    current_request_fingerprint=pool.current_request_fingerprint,
                    selection_revision=pool.selection_revision,
                    selected=selected,
                    affected=pool.shot_id in affected,
                    coverage_state=_coverage_state(
                        coverage,
                        pool.shot_id,
                        web_unverified_shot_ids=web_unverified_shot_ids,
                    ),
                    attempt=attempt,
                    candidate_count=len(pool.candidates),
                    omitted_candidate_count=len(pool.candidates) - len(visible),
                    candidates=candidates,
                )
            )
    public_coverage = None
    if coverage is not None:
        public_coverage = ShotVideoWebCoverage(
            status=(
                "web_unverified"
                if web_unverified_shot_ids
                else coverage.status
            ),
            required_shot_ids=list(coverage.required_shot_ids),
            selected_fresh_shot_ids=list(coverage.selected_fresh_shot_ids),
            missing_selection_shot_ids=list(coverage.missing_selection_shot_ids),
            stale_candidate_shot_ids=list(coverage.stale_candidate_shot_ids),
            invalid_artifact_shot_ids=list(coverage.invalid_artifact_shot_ids),
            web_unverified_shot_ids=sorted(web_unverified_shot_ids),
            non_production_shot_ids=list(coverage.non_production_shot_ids),
            blocked_source_shot_ids=list(coverage.blocked_source_shot_ids),
            coverage_fingerprint=coverage.coverage_fingerprint,
        )
    return ShotVideoWebOverview(
        season_no=manifest.season_no if manifest is not None else None,
        episode_no=number,
        state=inspection.state,
        reasons=[
            reason
            for reason in inspection.reasons
            if reason in _PUBLIC_CANDIDATE_REASONS
        ],
        manifest_fingerprint=(
            manifest.manifest_fingerprint
            if expose_candidates and manifest is not None
            else None
        ),
        mutation_allowed=(
            inspection.state == "fresh"
            or (
                inspection.state == "stale"
                and "source_plan_mismatch" not in inspection.reasons
            )
        ),
        affected_shot_ids=list(inspection.affected_shot_ids),
        coverage=public_coverage,
        continuity=continuity,
        attempts=attempt_summary,
        shots=shots,
    )


def _assert_mp4_web_safe(payload: bytes) -> None:
    """Validate the *derived* preview against a structural allowlist."""

    if not payload or len(payload) > MAX_WEB_VIDEO_PREVIEW_BYTES:
        raise ValueError("shot video preview is not safely bounded")
    box_count = 0

    def walk(start: int, end: int, path: tuple[bytes, ...] = ()) -> None:
        nonlocal box_count
        allowed = _MP4_WEB_BOX_ALLOWLIST.get(path)
        if allowed is None:
            raise ValueError("shot video preview container is not allowlisted")
        for kind, payload_start, box_end in _mp4_boxes(payload, start, end):
            box_count += 1
            if box_count > 16_384 or kind not in allowed:
                raise ValueError("shot video preview box is not allowlisted")
            child_path = (*path, kind)
            if child_path in _MP4_WEB_CONTAINER_PATHS:
                walk(payload_start, box_end, child_path)

    walk(0, len(payload))
    _candidate_payload_identity(payload)


def _strip_derived_mp4_metadata(payload: bytes) -> bytes:
    """Remove ffmpeg's trailing ``moov/udta`` without moving media bytes."""

    top = _mp4_boxes(payload, 0, len(payload))
    mdat_ends = [box_end for kind, _start, box_end in top if kind == b"mdat"]
    if not mdat_ends:
        raise ValueError("shot video preview has no media payload")
    cursor = 0
    moov_box: tuple[int, int, int] | None = None
    for kind, payload_start, box_end in top:
        box_start = cursor
        cursor = box_end
        if kind == b"moov":
            moov_box = (box_start, payload_start, box_end)
    if moov_box is None or moov_box[0] < max(mdat_ends):
        raise ValueError("shot video preview metadata is not safely removable")
    box_start, payload_start, box_end = moov_box
    children = _mp4_boxes(payload, payload_start, box_end)
    child_cursor = payload_start
    kept: list[bytes] = []
    for kind, _child_payload_start, child_end in children:
        if kind != b"udta":
            kept.append(payload[child_cursor:child_end])
        child_cursor = child_end
    moov_payload = b"".join(kept)
    moov = (len(moov_payload) + 8).to_bytes(4, "big") + b"moov" + moov_payload
    return payload[:box_start] + moov + payload[box_end:]


def _derive_safe_mp4_preview(payload: bytes) -> bytes:
    """Decode/re-encode a bounded, silent Web preview without source metadata."""

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-fflags",
        "+bitexact",
        "-max_alloc",
        "67108864",
        "-probesize",
        "2097152",
        "-analyzeduration",
        "5000000",
        "-threads",
        "1",
        "-i",
        "pipe:0",
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-t",
        "30",
        "-vf",
        "scale=w='min(360,iw)':h=-2,fps=12",
        "-filter_threads",
        "1",
        "-filter_complex_threads",
        "1",
        "-c:v",
        "libx264",
        "-threads",
        "1",
        "-preset",
        "ultrafast",
        "-crf",
        "32",
        "-maxrate",
        "512k",
        "-bufsize",
        "1M",
        "-pix_fmt",
        "yuv420p",
        "-flags:v",
        "+bitexact",
        "-metadata",
        "encoder=",
        "-metadata:s:v:0",
        "handler_name=",
        "-metadata:s:v:0",
        "vendor_id=",
    ]
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C",
        "LC_ALL": "C",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="drama-shot-video-preview-") as tmp:
            output_path = os.path.join(tmp, "preview.mp4")
            result = subprocess.run(
                [*command, "-f", "mp4", output_path],
                input=payload,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=45,
                check=False,
                env=environment,
            )
            if result.returncode != 0:
                raise ValueError("shot video preview derivation failed")
            size = os.path.getsize(output_path)
            if not 1 <= size <= MAX_WEB_VIDEO_PREVIEW_BYTES:
                raise ValueError("shot video preview size is invalid")
            with open(output_path, "rb") as handle:
                preview = handle.read(MAX_WEB_VIDEO_PREVIEW_BYTES + 1)
    except ValueError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("shot video preview derivation failed") from exc
    preview = _strip_derived_mp4_metadata(preview)
    _assert_mp4_web_safe(preview)
    return preview


def _safe_preview_for_candidate(artifact_sha256: str, payload: bytes) -> bytes:
    with _PREVIEW_CACHE_LOCK:
        cached = _PREVIEW_CACHE.get(artifact_sha256)
        if cached is not None:
            _PREVIEW_CACHE.move_to_end(artifact_sha256)
            return cached
        inflight = _PREVIEW_INFLIGHT.get(artifact_sha256)
        if inflight is None:
            inflight = threading.Event()
            _PREVIEW_INFLIGHT[artifact_sha256] = inflight
            leader = True
        else:
            leader = False
    if not leader:
        if not inflight.wait(timeout=46):
            raise RuntimeError("shot video preview is busy")
        with _PREVIEW_CACHE_LOCK:
            cached = _PREVIEW_CACHE.get(artifact_sha256)
            if cached is None:
                raise ValueError("shot video preview derivation failed")
            _PREVIEW_CACHE.move_to_end(artifact_sha256)
            return cached
    try:
        preview = _derive_safe_mp4_preview(payload)
        with _PREVIEW_CACHE_LOCK:
            _PREVIEW_CACHE[artifact_sha256] = preview
            while len(_PREVIEW_CACHE) > MAX_WEB_VIDEO_PREVIEW_CACHE_ENTRIES:
                _PREVIEW_CACHE.popitem(last=False)
        return preview
    finally:
        with _PREVIEW_CACHE_LOCK:
            event = _PREVIEW_INFLIGHT.pop(artifact_sha256, None)
            if event is not None:
                event.set()


def load_exact_shot_video_candidate_mp4(
    workspace: str,
    *,
    episode_no: int,
    shot_id: str,
    candidate_id: str,
) -> bytes:
    number = normalize_episode_no(episode_no)
    if (
        not isinstance(shot_id, str)
        or not isinstance(candidate_id, str)
        or re.fullmatch(_SHOT_ID_PATTERN, shot_id) is None
        or re.fullmatch(_CANDIDATE_ID_PATTERN, candidate_id) is None
    ):
        raise ValueError("invalid shot video candidate identity")
    if not _PREVIEW_SEMAPHORE.acquire(timeout=1.0):
        raise RuntimeError("shot video preview is busy")
    try:
        manifest = _read_manifest(workspace, episode_no=number)
        load_fresh_episode_shot_video_plan(workspace, episode_no=number)
        pool = next(
            (item for item in manifest.shots if item.shot_id == shot_id),
            None,
        )
        candidate = (
            next(
                (
                    item
                    for item in pool.candidates
                    if item.candidate_id == candidate_id
                ),
                None,
            )
            if pool is not None
            else None
        )
        if candidate is None:
            raise FileNotFoundError("shot video candidate not found")
        if (
            candidate.artifact.size_bytes > MAX_WEB_VIDEO_PREVIEW_SOURCE_BYTES
            or max(candidate.artifact.width, candidate.artifact.height)
            > MAX_WEB_VIDEO_PREVIEW_LONG_EDGE
            or min(candidate.artifact.width, candidate.artifact.height)
            > MAX_WEB_VIDEO_PREVIEW_SHORT_EDGE
            or candidate.artifact.width * candidate.artifact.height
            > MAX_WEB_VIDEO_PREVIEW_PIXELS
        ):
            raise ValueError("shot video candidate exceeds the Web preview limit")
        root = paths.workspace_root(workspace)
        payload = _read_strict_workspace_bytes(
            root,
            root / candidate.artifact.path,
            maximum=MAX_WEB_VIDEO_PREVIEW_SOURCE_BYTES,
        )
        expected = (
            candidate.artifact.sha256,
            candidate.artifact.size_bytes,
            candidate.artifact.duration_milliseconds,
            candidate.artifact.width,
            candidate.artifact.height,
            candidate.artifact.has_audio_track,
        )
        if (
            _candidate_payload_identity(
                payload,
                maximum_video_samples=MAX_WEB_VIDEO_PREVIEW_SAMPLES,
                require_single_video_track=True,
            )
            != expected
            or hashlib.sha256(payload).hexdigest() != candidate.artifact.sha256
        ):
            raise ValueError("shot video candidate bytes changed")
        return _safe_preview_for_candidate(candidate.artifact.sha256, payload)
    except FileNotFoundError:
        raise
    except (OSError, RecursionError, TypeError, ValueError) as exc:
        raise ValueError("shot video candidate is unavailable") from exc
    finally:
        _PREVIEW_SEMAPHORE.release()


def select_shot_video_candidate(
    workspace: str,
    request: ShotVideoSelectionRequest,
) -> ShotVideoSelectionResult:
    if not _MUTATION_SEMAPHORE.acquire(timeout=0.25):
        raise DramaShotVideoWebBusy("shot video mutation is busy; retry shortly")
    try:
        return _select_shot_video_candidate(workspace, request)
    finally:
        _MUTATION_SEMAPHORE.release()


def _select_shot_video_candidate(
    workspace: str,
    request: ShotVideoSelectionRequest,
) -> ShotVideoSelectionResult:
    before = build_shot_video_web_overview(
        workspace,
        episode_no=request.episode_no,
    )
    if before.manifest_fingerprint is None or not before.mutation_allowed:
        raise DramaShotVideoWebConflict("shot video candidates changed; refresh")
    shot = next(
        (item for item in before.shots if item.shot_id == request.shot_id),
        None,
    )
    if shot is None:
        raise ValueError("shot video selection target is unavailable")
    desired = None
    if request.candidate_id is not None:
        candidate = next(
            (
                item
                for item in shot.candidates
                if item.candidate_id == request.candidate_id
            ),
            None,
        )
        if candidate is None or not candidate.current:
            raise ValueError("shot video candidate is not current")
        if candidate.size_bytes > MAX_WEB_VIDEO_PREVIEW_SOURCE_BYTES:
            raise ValueError("shot video candidate exceeds the Web validation limit")
        desired = {
            "candidate_id": candidate.candidate_id,
            "candidate_fingerprint": candidate.candidate_fingerprint,
        }
    try:
        selected = select_episode_shot_video_candidate(
            workspace,
            episode_no=request.episode_no,
            shot_id=request.shot_id,
            selection=desired,
            expected_selection_revision=request.expected_selection_revision,
            expected_current_selection=request.expected_current_selection,
            expected_manifest_fingerprint=request.expected_manifest_fingerprint,
            maximum_selected_artifact_bytes=MAX_WEB_VIDEO_PREVIEW_SOURCE_BYTES,
            defer_oversize_selected_artifacts=True,
        )
    except ValueError as exc:
        raise DramaShotVideoWebConflict(
            "shot video selection changed; refresh"
        ) from exc
    overview = build_shot_video_web_overview(
        workspace,
        episode_no=request.episode_no,
    )
    return ShotVideoSelectionResult(
        changed=selected.manifest_fingerprint != before.manifest_fingerprint,
        overview=overview,
    )
