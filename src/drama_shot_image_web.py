"""Strict Web projection and guarded mutation for C2 shot-image candidates."""

from __future__ import annotations

import hashlib
import re
import zlib
from typing import Any, Dict, List, Literal, Mapping, Optional
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import paths
from .drama_schemas import (
    DirectShotImageBinding,
    NoTailShotImageBinding,
    PreviousTailShotImageBinding,
    normalize_episode_no,
)
from .drama_shot_image_candidate_store import (
    MAX_SHOT_IMAGE_CANDIDATE_BYTES,
    _candidate_payload_identity,
    inspect_episode_shot_image_candidates,
    select_episode_shot_image_frame,
)
from .drama_store import _read_strict_workspace_bytes
from .schemas import model_to_dict


_SHOT_ID_PATTERN = r"^shot_[0-9a-f]{24}$"
_CANDIDATE_ID_PATTERN = r"^sic_[0-9a-f]{24}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_PUBLIC_REASONS = {
    "missing",
    "schema_invalid",
    "schema_unsupported",
    "manifest_hash_mismatch",
    "request_invalid",
    "source_not_fresh",
    "artifact_or_manifest_invalid",
    "source_plan_mismatch",
    "shot_source_blocked",
    "selection_or_lineage_stale",
}


class DramaShotImageWebConflict(RuntimeError):
    """A current-state mismatch that requires the browser to reload."""


class ShotImageWebCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    candidate_id: str = Field(pattern=_CANDIDATE_ID_PATTERN)
    candidate_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    size_bytes: int = Field(ge=1, le=MAX_SHOT_IMAGE_CANDIDATE_BYTES)
    selected_first: bool
    selected_tail: bool
    current: bool
    preview_url: str = Field(min_length=1, max_length=500)


class ShotImageWebShot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    source_status: Literal["assembled", "blocked"]
    current_request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    selection_revision: int = Field(ge=0, le=2_147_483_647)
    tail_binding_revision: int = Field(ge=0, le=2_147_483_647)
    first_binding: Optional[Dict[str, Any]] = None
    tail_binding: Dict[str, Any]
    affected: bool
    coverage_state: Literal["covered", "missing", "blocked", "stale", "broken"]
    candidates: List[ShotImageWebCandidate] = Field(max_length=32)


class ShotImageWebCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["ready", "incomplete", "stale", "blocked_source"]
    required_shot_ids: List[str] = Field(max_length=100)
    covered_shot_ids: List[str] = Field(max_length=100)
    missing_first_shot_ids: List[str] = Field(max_length=100)
    blocked_source_shot_ids: List[str] = Field(max_length=100)
    stale_candidate_shot_ids: List[str] = Field(max_length=100)
    broken_lineage_shot_ids: List[str] = Field(max_length=100)
    coverage_fingerprint: str = Field(pattern=_SHA256_PATTERN)


class ShotImageWebOverview(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    season_no: Optional[int] = Field(default=None, ge=1)
    episode_no: int = Field(ge=1, le=100)
    state: Literal[
        "needs_shot_image_assets",
        "fresh",
        "stale",
        "invalid",
        "blocked_source",
    ]
    reasons: List[str] = Field(max_length=8)
    manifest_fingerprint: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)
    mutation_allowed: bool
    affected_shot_ids: List[str] = Field(max_length=100)
    coverage: Optional[ShotImageWebCoverage] = None
    shots: List[ShotImageWebShot] = Field(max_length=100)


class ShotImageSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    episode_no: int = Field(ge=1, le=100)
    shot_id: str = Field(pattern=_SHOT_ID_PATTERN)
    frame: Literal["first", "tail"]
    candidate_id: Optional[str] = Field(default=None, pattern=_CANDIDATE_ID_PATTERN)
    expected_selection_revision: int = Field(ge=0, le=2_147_483_647)
    expected_current_binding: Optional[Dict[str, Any]] = None
    expected_manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("episode_no", "expected_selection_revision", mode="before")
    @classmethod
    def _integers_are_strict(cls, value: Any, info: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("expected_current_binding", mode="before")
    @classmethod
    def _binding_is_exact(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError("expected_current_binding must be an object or null")
        raw = dict(value)
        kind = raw.get("kind")
        if kind == "direct":
            return model_to_dict(DirectShotImageBinding(**raw))
        if kind == "previous_tail":
            return model_to_dict(PreviousTailShotImageBinding(**raw))
        if kind == "none":
            return model_to_dict(NoTailShotImageBinding(**raw))
        raise ValueError("expected_current_binding is invalid")

    @model_validator(mode="after")
    def _selection_target_is_valid(self) -> "ShotImageSelectionRequest":
        if self.frame == "first" and self.candidate_id is None:
            raise ValueError("first frame requires an exact candidate")
        return self


class ShotImageSelectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    changed: bool
    overview: ShotImageWebOverview


def _coverage_state(coverage: Any, shot_id: str) -> str:
    if coverage is None:
        return "missing"
    if shot_id in coverage.broken_lineage_shot_ids:
        return "broken"
    if shot_id in coverage.stale_candidate_shot_ids:
        return "stale"
    if shot_id in coverage.blocked_source_shot_ids:
        return "blocked"
    if shot_id in coverage.covered_shot_ids:
        return "covered"
    return "missing"


def build_shot_image_web_overview(
    workspace: str,
    *,
    episode_no: int = 1,
) -> ShotImageWebOverview:
    number = normalize_episode_no(episode_no)
    inspection = inspect_episode_shot_image_candidates(workspace, episode_no=number)
    manifest = inspection.manifest
    coverage = inspection.coverage
    expose_candidates = inspection.state in {"fresh", "stale"} and manifest is not None
    shots: list[ShotImageWebShot] = []
    if expose_candidates and manifest is not None:
        affected = set(inspection.affected_shot_ids)
        encoded_workspace = quote(workspace, safe="")
        for pool in manifest.shots:
            first = model_to_dict(pool.first_binding) if pool.first_binding is not None else None
            tail = model_to_dict(pool.tail_binding)
            candidates: list[ShotImageWebCandidate] = []
            for candidate in sorted(pool.candidates, key=lambda item: item.candidate_id):
                direct_first = (
                    isinstance(pool.first_binding, DirectShotImageBinding)
                    and pool.first_binding.candidate_id == candidate.candidate_id
                )
                direct_tail = (
                    isinstance(pool.tail_binding, DirectShotImageBinding)
                    and pool.tail_binding.candidate_id == candidate.candidate_id
                )
                candidates.append(
                    ShotImageWebCandidate(
                        candidate_id=candidate.candidate_id,
                        candidate_fingerprint=candidate.candidate_fingerprint,
                        request_fingerprint=candidate.request_fingerprint,
                        width=candidate.artifact.width,
                        height=candidate.artifact.height,
                        size_bytes=candidate.artifact.size_bytes,
                        selected_first=direct_first,
                        selected_tail=direct_tail,
                        current=(
                            candidate.request_fingerprint
                            == pool.current_request_fingerprint
                        ),
                        preview_url=(
                            f"/api/workspace/{encoded_workspace}/drama/shot-images/"
                            f"{number}/{pool.shot_id}/{candidate.candidate_id}.png"
                        ),
                    )
                )
            shots.append(
                ShotImageWebShot(
                    shot_id=pool.shot_id,
                    source_status=pool.source_status,
                    current_request_fingerprint=pool.current_request_fingerprint,
                    selection_revision=pool.selection_revision,
                    tail_binding_revision=pool.tail_binding_revision,
                    first_binding=first,
                    tail_binding=tail,
                    affected=pool.shot_id in affected,
                    coverage_state=_coverage_state(coverage, pool.shot_id),
                    candidates=candidates,
                )
            )
    public_coverage = None
    if coverage is not None:
        public_coverage = ShotImageWebCoverage(
            status=coverage.status,
            required_shot_ids=list(coverage.required_shot_ids),
            covered_shot_ids=list(coverage.covered_shot_ids),
            missing_first_shot_ids=list(coverage.missing_first_shot_ids),
            blocked_source_shot_ids=list(coverage.blocked_source_shot_ids),
            stale_candidate_shot_ids=list(coverage.stale_candidate_shot_ids),
            broken_lineage_shot_ids=list(coverage.broken_lineage_shot_ids),
            coverage_fingerprint=coverage.coverage_fingerprint,
        )
    return ShotImageWebOverview(
        season_no=manifest.season_no if manifest is not None else None,
        episode_no=number,
        state=inspection.state,
        reasons=[reason for reason in inspection.reasons if reason in _PUBLIC_REASONS],
        manifest_fingerprint=(
            manifest.manifest_fingerprint if expose_candidates and manifest is not None else None
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
        shots=shots,
    )


def load_exact_shot_image_candidate_png(
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
        raise ValueError("invalid shot image candidate identity")
    inspection = inspect_episode_shot_image_candidates(workspace, episode_no=number)
    if inspection.state not in {"fresh", "stale"} or inspection.manifest is None:
        raise ValueError("shot image candidate is unavailable")
    pool = next((item for item in inspection.manifest.shots if item.shot_id == shot_id), None)
    candidate = (
        next((item for item in pool.candidates if item.candidate_id == candidate_id), None)
        if pool is not None
        else None
    )
    if candidate is None:
        raise FileNotFoundError("shot image candidate not found")
    root = paths.workspace_root(workspace)
    payload = _read_strict_workspace_bytes(
        root,
        root / candidate.artifact.path,
        maximum=MAX_SHOT_IMAGE_CANDIDATE_BYTES,
    )
    identity = _candidate_payload_identity(payload)
    expected = (
        candidate.artifact.sha256,
        candidate.artifact.size_bytes,
        candidate.artifact.width,
        candidate.artifact.height,
    )
    if identity != expected or hashlib.sha256(payload).hexdigest() != candidate.artifact.sha256:
        raise ValueError("shot image candidate bytes changed")
    return _sanitize_png_for_web(payload)


def _sanitize_png_for_web(payload: bytes) -> bytes:
    """Remove ancillary metadata while preserving image-bearing chunks.

    C2 authenticates the stored artifact, but PNG text/EXIF chunks may contain
    provider prompts, paths, or signed URLs.  The browser receives a derived
    preview containing only the structural/image chunks required to render.
    """

    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("shot image candidate is not PNG")
    safe_chunks = {b"IHDR", b"PLTE", b"IDAT", b"IEND"}
    output = bytearray(payload[:8])
    offset = 8
    color_type: int | None = None
    palette_entries = 0
    saw_idat = False
    saw_trns = False
    while offset + 12 <= len(payload):
        length = int.from_bytes(payload[offset : offset + 4], "big")
        kind = payload[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(payload):
            raise ValueError("shot image candidate PNG is truncated")
        chunk_payload = payload[offset + 8 : offset + 8 + length]
        if kind == b"IHDR" and len(chunk_payload) == 13:
            color_type = chunk_payload[9]
        elif kind == b"PLTE":
            palette_entries = len(chunk_payload) // 3
        elif kind == b"IDAT":
            saw_idat = True
        valid_trns = False
        if kind == b"tRNS" and not saw_trns and not saw_idat:
            if color_type == 0:
                valid_trns = length == 2
            elif color_type == 2:
                valid_trns = length == 6
            elif color_type == 3:
                valid_trns = 1 <= length <= palette_entries
            saw_trns = True
        if kind in safe_chunks or valid_trns:
            output.extend(length.to_bytes(4, "big"))
            output.extend(kind)
            output.extend(chunk_payload)
            output.extend(
                (zlib.crc32(kind + chunk_payload) & 0xFFFFFFFF).to_bytes(4, "big")
            )
        offset = end
        if kind == b"IEND":
            break
    sanitized = bytes(output)
    original_identity = _candidate_payload_identity(payload)
    sanitized_identity = _candidate_payload_identity(sanitized)
    if original_identity[2:] != sanitized_identity[2:]:
        raise ValueError("shot image candidate preview dimensions changed")
    return sanitized


def select_shot_image_candidate(
    workspace: str,
    request: ShotImageSelectionRequest,
) -> ShotImageSelectionResult:
    before = build_shot_image_web_overview(workspace, episode_no=request.episode_no)
    if (
        before.manifest_fingerprint is None
        or not before.mutation_allowed
    ):
        raise DramaShotImageWebConflict("shot image candidates changed; refresh")
    shot = next((item for item in before.shots if item.shot_id == request.shot_id), None)
    if shot is None or shot.source_status != "assembled":
        raise ValueError("shot image selection target is unavailable")
    if request.candidate_id is None:
        desired: Dict[str, Any] = {"kind": "none"}
    else:
        candidate = next(
            (item for item in shot.candidates if item.candidate_id == request.candidate_id),
            None,
        )
        if candidate is None or candidate.request_fingerprint != shot.current_request_fingerprint:
            raise ValueError("shot image candidate is not current")
        desired = {
            "kind": "direct",
            "candidate_id": candidate.candidate_id,
            "candidate_fingerprint": candidate.candidate_fingerprint,
        }
    try:
        selected = select_episode_shot_image_frame(
            workspace,
            episode_no=request.episode_no,
            shot_id=request.shot_id,
            frame=request.frame,
            binding=desired,
            expected_selection_revision=request.expected_selection_revision,
            expected_current_binding=request.expected_current_binding,
            expected_manifest_fingerprint=request.expected_manifest_fingerprint,
        )
    except ValueError as exc:
        raise DramaShotImageWebConflict("shot image selection changed; refresh") from exc
    overview = build_shot_image_web_overview(workspace, episode_no=request.episode_no)
    return ShotImageSelectionResult(
        changed=selected.manifest_fingerprint != before.manifest_fingerprint,
        overview=overview,
    )
