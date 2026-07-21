"""Deterministic, bounded project archives for short-drama workspaces.

The archive is a migration snapshot, not a raw workspace backup.  Exporters
copy only explicitly classified creative/media files plus a redacted evidence
projection.  Import validates the complete ZIP before creating a new workspace
and never overwrites an existing target.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
import ctypes
import errno
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ai_draw_client import _validate_png
from . import (
    drama_compose_web,
    drama_compositor,
    drama_edit_export,
    drama_timeline,
    paths,
)
from .drama_asset_versions import (
    inspect_character_asset_catalog,
    inspect_prop_or_clue_asset_catalog,
    inspect_scene_asset_catalog,
)
from .drama_asset_web import build_asset_web_overview
from .drama_production_workbench import build_production_workbench
from .drama_render_store import inspect_render_plan
from .drama_shot_image_candidate_store import inspect_episode_shot_image_candidates
from .drama_shot_video_candidate_store import inspect_episode_shot_video_candidates
from .drama_schemas import (
    DramaComposeQaReport,
    DramaEpisode,
    DramaEpisodeMeta,
    TimelineManifest,
    episode_paths,
)
from .drama_season_export import (
    _build_zip,
    _read_workspace_file_safely,
    _write_bytes_atomic,
)
from .schemas import model_to_dict
from .utils import sha256_data
from .web import workspace_meta
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


ARCHIVE_GENERATOR_VERSION = "drama-project-archive-v1"
MAX_ARCHIVE_COMPRESSED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 1024
MAX_ARCHIVE_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_COMPRESSION_RATIO = 100
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_ZIP_DATETIME = (1980, 1, 1, 0, 0, 0)

ArchivePartition = Literal["creative", "assets", "media", "evidence"]


class DramaProjectArchiveError(ValueError):
    """Fail-closed archive boundary with a stable, non-sensitive code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ProjectArchiveMember(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    archive_path: str = Field(min_length=1, max_length=360)
    target_path: str = Field(min_length=1, max_length=300)
    partition: ArchivePartition
    size: int = Field(ge=1, le=MAX_ARCHIVE_MEMBER_BYTES)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    mime: Literal[
        "application/json",
        "video/mp4",
        "image/png",
        "image/jpeg",
        "image/webp",
        "audio/wav",
        "application/x-subrip",
        "text/x-ssa",
    ]
    schema_label: Literal[
        "portable_drama_episode_v1",
        "portable_drama_episode_meta_v1",
        "timeline_envelope_v1",
        "workbench_archive_summary_v1",
        "mp4_v1",
        "png_v1",
        "jpeg_v1",
        "webp_v1",
        "wav_v1",
        "srt_v1",
        "ass_v1",
        "edit_project_v1",
    ] = Field(alias="schema")

    @model_validator(mode="after")
    def _identity_is_canonical(self) -> "ProjectArchiveMember":
        partition, mime, schema = _classify_target(self.target_path)
        if (
            self.partition != partition
            or self.mime != mime
            or self.schema_label != schema
            or self.archive_path != _archive_path(partition, self.target_path)
        ):
            raise ValueError("archive member classification is invalid")
        _validate_zip_name(self.archive_path)
        return self


class ProjectArchiveEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    episode_no: int = Field(ge=1, le=100)
    source_episode_sha256: str = Field(pattern=_SHA256_PATTERN)
    episode_sha256: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)
    render_plan_fingerprint: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)
    selection_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    timeline_fingerprint: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)
    qa_fingerprint: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)
    output_sha256: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)


class ArchiveArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    target_path: str = Field(min_length=1, max_length=300)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=1, le=MAX_ARCHIVE_MEMBER_BYTES)


class PortableDramaCoreSetup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    protagonist: str = Field(default="", max_length=1200)
    antagonist: str = Field(default="", max_length=1200)
    emotional_hook: str = Field(default="", max_length=1200)


class PortableDramaConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scene_count: int = Field(default=0, ge=0, le=100)
    main_character_count: int = Field(default=0, ge=0, le=100)
    max_dialog_chars_per_line: int = Field(default=0, ge=0, le=1000)
    narrative_mode: str = Field(default="", max_length=120)


class PortableDramaShot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shot_no: int = Field(ge=1, le=100)
    shot_size: str = Field(default="", max_length=40)
    camera_move: str = Field(default="", max_length=80)
    duration_seconds: int = Field(ge=1, le=300)
    visual_content: str = Field(default="", max_length=1000)
    voiceover: str = Field(default="", max_length=500)
    dialogue: str = Field(default="", max_length=500)
    is_highlight: bool = False


class PortableDramaHook(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: str = Field(default="", max_length=80)
    content: str = Field(default="", max_length=1000)


class PortableDramaSelfCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    hook_match_track: Optional[bool] = None
    highlight_shot_no: Optional[int] = Field(default=None, ge=1, le=100)
    duration_within_tolerance: Optional[bool] = None


class PortableDramaEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    artifact_type: Literal["portable_drama_episode"] = "portable_drama_episode"
    episode_no: int = Field(ge=1, le=100)
    season_no: int = Field(ge=1)
    title: str = Field(default="", max_length=120)
    logline: str = Field(default="", max_length=500)
    track: str = Field(default="", max_length=20)
    target_duration_seconds: int = Field(ge=1, le=300)
    estimated_duration_seconds: int = Field(ge=0, le=600)
    core_setup: PortableDramaCoreSetup
    ai_friendly_constraints: PortableDramaConstraints
    narrative: str = Field(default="", max_length=5000)
    storyboard: List[PortableDramaShot] = Field(max_length=100)
    ending_hook: PortableDramaHook
    self_check: PortableDramaSelfCheck


class ArchiveSelectedAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["character", "art_direction", "scene", "prop", "clue"]
    asset_id: str = Field(pattern=r"^(?:c|s|p|l)[0-9]{3}$|^[a-z][a-z0-9_-]{0,63}$")
    scope: Optional[Literal["global", "series", "episode"]] = None
    episode_no: Optional[int] = Field(default=None, ge=1, le=100)
    selected_version_id: str = Field(pattern=r"^(?:av|ad|sv|pcv)_[0-9a-f]{24}$")
    selection_revision: int = Field(ge=0, le=2_147_483_647)
    selected_status: Literal["active", "disabled"]
    artifact: Optional[ArchiveArtifactReference] = None

    @model_validator(mode="after")
    def _asset_identity_matches_kind(self) -> "ArchiveSelectedAsset":
        expected = {
            "character": (r"^c[0-9]{3}$", "av_"),
            "art_direction": (r"^[a-z][a-z0-9_-]{0,63}$", "ad_"),
            "scene": (r"^s[0-9]{3}$", "sv_"),
            "prop": (r"^p[0-9]{3}$", "pcv_"),
            "clue": (r"^l[0-9]{3}$", "pcv_"),
        }[self.kind]
        if re.fullmatch(expected[0], self.asset_id) is None or not self.selected_version_id.startswith(expected[1]):
            raise ValueError("selected asset identity does not match its kind")
        if self.kind == "art_direction":
            if self.scope is None or (self.scope == "episode") != (self.episode_no is not None):
                raise ValueError("art direction scope identity is invalid")
        elif self.scope is not None or self.episode_no is not None:
            raise ValueError("non-art asset cannot carry scope identity")
        return self


class ArchiveImageBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["direct", "previous_tail"]
    candidate_id: str = Field(pattern=r"^sic_[0-9a-f]{24}$")
    candidate_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    source_shot_id: Optional[str] = Field(default=None, pattern=r"^shot_[0-9a-f]{24}$")
    source_tail_revision: Optional[int] = Field(default=None, ge=1, le=2_147_483_647)
    target_request_fingerprint: Optional[str] = Field(default=None, pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _binding_shape_matches_kind(self) -> "ArchiveImageBinding":
        extras = (
            self.source_shot_id,
            self.source_tail_revision,
            self.target_request_fingerprint,
        )
        if self.kind == "direct" and any(item is not None for item in extras):
            raise ValueError("direct image binding has previous-tail fields")
        if self.kind == "previous_tail" and any(item is None for item in extras):
            raise ValueError("previous-tail image binding is incomplete")
        return self


class ArchiveSelectedImageFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    binding: ArchiveImageBinding
    candidate_id: str = Field(pattern=r"^sic_[0-9a-f]{24}$")
    candidate_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    artifact: ArchiveArtifactReference

    @model_validator(mode="after")
    def _candidate_matches_binding(self) -> "ArchiveSelectedImageFrame":
        if (
            self.candidate_id != self.binding.candidate_id
            or self.candidate_fingerprint != self.binding.candidate_fingerprint
        ):
            raise ValueError("selected image does not match its binding")
        return self


class ArchiveImageSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    current_request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    selection_revision: int = Field(ge=0, le=2_147_483_647)
    tail_binding_revision: int = Field(ge=0, le=2_147_483_647)
    first: Optional[ArchiveSelectedImageFrame] = None
    tail: Optional[ArchiveSelectedImageFrame] = None


class ArchiveSelectedVideo(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    candidate_id: str = Field(pattern=r"^svc_[0-9a-f]{24}$")
    candidate_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    artifact: ArchiveArtifactReference


class ArchiveVideoSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    manifest_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    current_request_fingerprint: str = Field(pattern=_SHA256_PATTERN)
    selection_revision: int = Field(ge=0, le=2_147_483_647)
    selected: Optional[ArchiveSelectedVideo] = None


class ArchiveSelectedShot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shot_id: str = Field(pattern=r"^shot_[0-9a-f]{24}$")
    image: Optional[ArchiveImageSelection] = None
    video: Optional[ArchiveVideoSelection] = None


class ProjectArchiveManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    generator_version: Literal["drama-project-archive-v1"] = ARCHIVE_GENERATOR_VERSION
    project_id: str = Field(pattern=r"^dpa_[0-9a-f]{24}$")
    season_no: Literal[1] = 1
    episodes: List[ProjectArchiveEpisode] = Field(max_length=100)
    members: List[ProjectArchiveMember] = Field(min_length=1, max_length=MAX_ARCHIVE_MEMBERS)
    archive_fingerprint: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def _manifest_is_canonical(self) -> "ProjectArchiveManifest":
        episode_numbers = [item.episode_no for item in self.episodes]
        if episode_numbers != sorted(set(episode_numbers)):
            raise ValueError("archive episodes are not unique and sorted")
        archive_paths = [item.archive_path for item in self.members]
        target_paths = [item.target_path for item in self.members]
        if archive_paths != sorted(archive_paths):
            raise ValueError("archive members are not sorted")
        if len(archive_paths) != len(set(archive_paths)):
            raise ValueError("archive members are not unique")
        if len(target_paths) != len(set(target_paths)):
            raise ValueError("archive targets are not unique")
        if len({value.casefold() for value in archive_paths}) != len(archive_paths):
            raise ValueError("archive members collide case-insensitively")
        if len({value.casefold() for value in target_paths}) != len(target_paths):
            raise ValueError("archive targets collide case-insensitively")
        member_identity = [
            {"target_path": item.target_path, "size": item.size, "sha256": item.sha256}
            for item in self.members
        ]
        expected_project = f"dpa_{_fingerprint(member_identity)[:24]}"
        if self.project_id != expected_project:
            raise ValueError("archive project identity is invalid")
        payload = self.model_dump(
            exclude={"archive_fingerprint"},
            by_alias=True,
        )
        if self.archive_fingerprint != _fingerprint(payload):
            raise ValueError("archive fingerprint is invalid")
        return self


@dataclass(frozen=True)
class ProjectArchive:
    filename: str
    content_type: str
    path: Path
    body: bytes
    manifest: ProjectArchiveManifest


@dataclass(frozen=True)
class ProjectArchiveImport:
    workspace: str
    project_id: str
    archive_fingerprint: str
    member_count: int
    target: Path
    durability: Literal["confirmed", "commit_uncertain"]


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _validate_zip_name(value: str) -> None:
    pure = PurePosixPath(value)
    if (
        not value
        or pure.is_absolute()
        or ".." in pure.parts
        or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or str(pure) != value
        or any(part in {"", "."} for part in pure.parts)
    ):
        raise DramaProjectArchiveError("member_path_invalid")


def _classify_target(target: str) -> tuple[ArchivePartition, str, str]:
    if not isinstance(target, str):
        raise DramaProjectArchiveError("target_path_invalid")
    _validate_zip_name(target)
    patterns: list[tuple[str, ArchivePartition, str, str]] = [
        (r"outputs/episodes/episode_[0-9]{2,3}\.json", "creative", "application/json", "portable_drama_episode_v1"),
        (r"outputs/episodes/episode_[0-9]{2,3}\.meta\.json", "creative", "application/json", "portable_drama_episode_meta_v1"),
        (r"outputs/episodes/episode_[0-9]{2,3}\.shot_images/shot_[0-9a-f]{24}/sic_[0-9a-f]{24}\.png", "assets", "image/png", "png_v1"),
        (r"data/character_refs/.{1,215}\.png", "assets", "image/png", "png_v1"),
        (r"data/scene_refs/s[0-9]{3}/.{1,215}\.png", "assets", "image/png", "png_v1"),
        (r"data/prop_clue_refs/(?:p|l)[0-9]{3}/.{1,215}\.png", "assets", "image/png", "png_v1"),
        (r"outputs/drama/timeline/episode_[0-9]{3}\.timeline\.json", "media", "application/json", "timeline_envelope_v1"),
        (r"outputs/episodes/episode_[0-9]{2,3}\.shot_videos/shot_[0-9a-f]{24}/svc_[0-9a-f]{24}\.mp4", "media", "video/mp4", "mp4_v1"),
        (r"outputs/drama/audio/episode_[0-9]{3}/utt_[0-9a-f]{24}\.wav", "media", "audio/wav", "wav_v1"),
        (r"outputs/drama/optional_audio/[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.wav", "media", "audio/wav", "wav_v1"),
        (r"outputs/drama/compose/episode_[0-9]{3}/timeline_[0-9a-f]{24}\.mp4", "media", "video/mp4", "mp4_v1"),
        (r"outputs/drama/compose/episode_[0-9]{3}/timeline_[0-9a-f]{24}\.srt", "media", "application/x-subrip", "srt_v1"),
        (r"outputs/drama/edit/episode_[0-9]{3}/timeline_[0-9a-f]{24}\.ass", "media", "text/x-ssa", "ass_v1"),
        (r"outputs/drama/edit/episode_[0-9]{3}/timeline_[0-9a-f]{24}\.edit\.json", "media", "application/json", "edit_project_v1"),
        (r"data/drama_project_archive/evidence/episode_[0-9]{3}\.json", "evidence", "application/json", "workbench_archive_summary_v1"),
    ]
    for pattern, partition, mime, schema in patterns:
        if re.fullmatch(pattern, target):
            return partition, mime, schema
    raise DramaProjectArchiveError("target_path_not_allowed")


def _archive_path(partition: str, target: str) -> str:
    if partition == "evidence":
        return f"evidence/{PurePosixPath(target).name}"
    return f"{partition}/{target}"


def _read_target(root: Path, target: str, *, maximum: int = MAX_ARCHIVE_MEMBER_BYTES) -> bytes:
    try:
        return _read_workspace_file_safely(
            root,
            PurePosixPath(target),
            max_bytes=maximum,
        )
    except FileNotFoundError:
        raise
    except (OSError, ValueError) as exc:
        raise DramaProjectArchiveError("source_member_invalid") from exc


def _artifact_projection(artifact: Any) -> dict[str, Any]:
    return {
        "target_path": artifact.path,
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
    }


def _selected_asset_projection(
    workspace: str,
    episode_no: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    overview = build_asset_web_overview(workspace, season_no=1, episode_no=episode_no)
    artifact_by_selection: dict[tuple[str, str, str], Any] = {}
    character = inspect_character_asset_catalog(workspace, season_no=1).catalog
    if character is not None:
        for asset in character.assets:
            version = next(
                item for item in asset.versions
                if item.asset_version_id == asset.selected_version_id
            )
            if version.artifact is not None:
                artifact_by_selection[("character", asset.asset_id, asset.selected_version_id)] = version.artifact
    scene = inspect_scene_asset_catalog(workspace, season_no=1).catalog
    if scene is not None:
        for asset in scene.assets:
            version = next(
                item for item in asset.versions
                if item.scene_version_id == asset.selected_version_id
            )
            if version.artifact is not None:
                artifact_by_selection[("scene", asset.scene_id, asset.selected_version_id)] = version.artifact
    prop_clue = inspect_prop_or_clue_asset_catalog(workspace, season_no=1).catalog
    if prop_clue is not None:
        for asset in prop_clue.assets:
            version = next(
                item for item in asset.versions
                if item.asset_version_id == asset.selected_version_id
            )
            if version.artifact is not None:
                artifact_by_selection[(asset.kind, asset.asset_id, asset.selected_version_id)] = version.artifact

    rows: list[dict[str, Any]] = []
    targets: list[str] = []
    for section in overview.sections:
        for item in section.items:
            selected = next(
                version for version in item.versions
                if version.version_id == item.selected_version_id
            )
            artifact = artifact_by_selection.get(
                (item.kind, item.asset_id, item.selected_version_id)
            )
            artifact_projection = (
                _artifact_projection(artifact) if artifact is not None else None
            )
            if artifact is not None:
                targets.append(artifact.path)
            rows.append(
                {
                    "kind": item.kind,
                    "asset_id": item.asset_id,
                    "scope": item.scope,
                    "episode_no": item.episode_no,
                    "selected_version_id": item.selected_version_id,
                    "selection_revision": item.selection_revision,
                    "selected_status": selected.status,
                    "artifact": artifact_projection,
                }
            )
    rows.sort(
        key=lambda item: (
            item["kind"], item.get("scope") or "", item["asset_id"],
            item.get("episode_no") or 0,
        )
    )
    return rows, sorted(set(targets))


def _selected_shot_projection(
    workspace: str,
    episode_no: int,
    shot_ids: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    image = inspect_episode_shot_image_candidates(workspace, episode_no=episode_no)
    video = inspect_episode_shot_video_candidates(workspace, episode_no=episode_no)
    image_pools = {
        item.shot_id: item for item in (image.manifest.shots if image.manifest else [])
    }
    image_candidates_by_id = {
        candidate.candidate_id: candidate
        for item in (image.manifest.shots if image.manifest else [])
        for candidate in item.candidates
    }
    video_pools = {
        item.shot_id: item for item in (video.manifest.shots if video.manifest else [])
    }
    artifact_targets: list[str] = []
    rows: list[dict[str, Any]] = []

    def image_binding(binding: Any) -> Optional[dict[str, Any]]:
        if binding is None or getattr(binding, "kind", None) == "none":
            return None
        candidate = image_candidates_by_id.get(binding.candidate_id)
        if candidate is None:
            raise DramaProjectArchiveError("selected_image_candidate_missing")
        artifact_targets.append(candidate.artifact.path)
        return {
            "binding": model_to_dict(binding),
            "candidate_id": candidate.candidate_id,
            "candidate_fingerprint": candidate.candidate_fingerprint,
            "request_fingerprint": candidate.request_fingerprint,
            "artifact": _artifact_projection(candidate.artifact),
        }

    for shot_id in sorted(set(shot_ids) | set(image_pools) | set(video_pools)):
        image_pool = image_pools.get(shot_id)
        video_pool = video_pools.get(shot_id)
        image_row = None
        if image_pool is not None:
            image_row = {
                "manifest_fingerprint": image.manifest.manifest_fingerprint,
                "current_request_fingerprint": image_pool.current_request_fingerprint,
                "selection_revision": image_pool.selection_revision,
                "tail_binding_revision": image_pool.tail_binding_revision,
                "first": image_binding(image_pool.first_binding),
                "tail": image_binding(image_pool.tail_binding),
            }
        video_row = None
        if video_pool is not None:
            selected_candidate = None
            if video_pool.selected is not None:
                selected_candidate = next(
                    (
                        item for item in video_pool.candidates
                        if item.candidate_id == video_pool.selected.candidate_id
                        and item.candidate_fingerprint == video_pool.selected.candidate_fingerprint
                    ),
                    None,
                )
                if selected_candidate is None:
                    raise DramaProjectArchiveError("selected_video_candidate_missing")
                artifact_targets.append(selected_candidate.artifact.path)
            video_row = {
                "manifest_fingerprint": video.manifest.manifest_fingerprint,
                "current_request_fingerprint": video_pool.current_request_fingerprint,
                "selection_revision": video_pool.selection_revision,
                "selected": (
                    {
                        "candidate_id": selected_candidate.candidate_id,
                        "candidate_fingerprint": selected_candidate.candidate_fingerprint,
                        "request_fingerprint": selected_candidate.request_fingerprint,
                        "artifact": _artifact_projection(selected_candidate.artifact),
                    }
                    if selected_candidate is not None
                    else None
                ),
            }
        rows.append({"shot_id": shot_id, "image": image_row, "video": video_row})
    return rows, sorted(set(artifact_targets))


def _evidence_projection(
    workspace: str,
    episode_no: int,
) -> tuple[dict[str, Any], str, list[str]]:
    projection = build_production_workbench(workspace, episode_no=episode_no)
    selected_assets, asset_targets = _selected_asset_projection(workspace, episode_no)
    selected_shots, shot_targets = _selected_shot_projection(
        workspace, episode_no, [item.shot_id for item in projection.shots]
    )
    selection_fingerprint = _fingerprint(
        {"assets": selected_assets, "shots": selected_shots}
    )
    render_projection = model_to_dict(projection.render)
    inspected_render = inspect_render_plan(workspace, episode_no=episode_no)
    render_projection["source_episode_sha256"] = (
        inspected_render.plan.source_episode_sha256
        if inspected_render.plan is not None
        else None
    )
    evidence = {
        "schema_version": 1,
        "artifact_type": "drama_project_archive_evidence",
        "episode_no": episode_no,
        "state": projection.state,
        "source_projection_fingerprint": projection.source_projection_fingerprint,
        "selection_fingerprint": selection_fingerprint,
        "render": render_projection,
        "selected_assets": selected_assets,
        "selected_shots": selected_shots,
        "image_state": projection.image_state,
        "video_state": projection.video_state,
        "video_attempts": model_to_dict(projection.video_attempts),
        "tasks": {
            key: getattr(projection.tasks, key)
            for key in (
                "state",
                "ledger_revision",
                "ledger_fingerprint",
                "task_count",
                "omitted_count",
                "unknown_count",
                "failed_count",
            )
        },
        "timeline": {
            "state": projection.timeline.state,
            "timeline_fingerprint": projection.timeline.timeline_fingerprint,
            "duration_ms": projection.timeline.duration_ms,
            "shot_count": projection.timeline.shot_count,
            "subtitle_count": projection.timeline.subtitle_count,
            "qa": (
                model_to_dict(projection.timeline.qa)
                if projection.timeline.qa is not None
                else None
            ),
            "deliverables": [
                {"kind": item.kind, "filename": item.filename}
                for item in projection.timeline.deliverables
            ],
        },
    }
    return evidence, selection_fingerprint, sorted(set(asset_targets) | set(shot_targets))


def _add_payload(
    payloads: dict[str, bytes],
    records: list[ProjectArchiveMember],
    *,
    target: str,
    payload: bytes,
) -> None:
    if not payload:
        raise DramaProjectArchiveError("source_member_empty")
    if len(payload) > MAX_ARCHIVE_MEMBER_BYTES:
        raise DramaProjectArchiveError("source_member_too_large")
    partition, mime, schema = _classify_target(target)
    archive_path = _archive_path(partition, target)
    existing = next((item for item in records if item.target_path == target), None)
    if existing is not None:
        if (
            existing.archive_path == archive_path
            and existing.partition == partition
            and existing.mime == mime
            and existing.schema_label == schema
            and existing.size == len(payload)
            and existing.sha256 == hashlib.sha256(payload).hexdigest()
            and payloads.get(archive_path) == payload
        ):
            return
        raise DramaProjectArchiveError("source_member_duplicate")
    if archive_path in payloads:
        raise DramaProjectArchiveError("source_member_duplicate")
    _validate_payload(payload, mime=mime, schema=schema)
    payloads[archive_path] = payload
    records.append(
        ProjectArchiveMember(
            archive_path=archive_path,
            target_path=target,
            partition=partition,
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            mime=mime,
            schema_label=schema,
        )
    )


def _episode_number_from_target(target: str) -> Optional[int]:
    patterns = (
        r"^outputs/episodes/episode_([0-9]{2,3})(?:\.|$)",
        r"^outputs/drama/(?:timeline|audio|compose|edit)/episode_([0-9]{3})(?:/|\.)",
        r"^data/drama_project_archive/evidence/episode_([0-9]{3})\.json$",
    )
    for pattern in patterns:
        match = re.search(pattern, target)
        if match is not None:
            return int(match.group(1))
    return None


def _collect_imported_archive(
    root: Path,
) -> tuple[dict[str, bytes], list[ProjectArchiveMember], list[ProjectArchiveEpisode]] | None:
    receipt = "data/drama_project_archive/import_manifest.json"
    try:
        raw = _read_target(root, receipt, maximum=MAX_ARCHIVE_MANIFEST_BYTES)
    except FileNotFoundError:
        return None
    try:
        manifest = ProjectArchiveManifest(**_load_json_strict(raw))
    except (DramaProjectArchiveError, TypeError, ValueError) as exc:
        raise DramaProjectArchiveError("import_receipt_invalid") from exc
    payloads: dict[str, bytes] = {}
    records: list[ProjectArchiveMember] = []
    for record in manifest.members:
        payload = _read_target(root, record.target_path)
        if len(payload) != record.size or hashlib.sha256(payload).hexdigest() != record.sha256:
            raise DramaProjectArchiveError("imported_member_drift")
        payloads[record.archive_path] = payload
        records.append(record)
    return payloads, records, list(manifest.episodes)


def _portable_creative_projection(
    episode: DramaEpisode,
    meta: DramaEpisodeMeta,
) -> tuple[bytes, bytes, str, str]:
    source_sha = sha256_data(model_to_dict(episode))
    if not source_sha or meta.episode_sha256 != source_sha:
        raise DramaProjectArchiveError("creative_source_hash_mismatch")
    raw = model_to_dict(episode)
    core = raw.get("core_setup") if isinstance(raw.get("core_setup"), dict) else {}
    constraints = (
        raw.get("ai_friendly_constraints")
        if isinstance(raw.get("ai_friendly_constraints"), dict)
        else {}
    )
    hook = raw.get("ending_hook") if isinstance(raw.get("ending_hook"), dict) else {}
    check = raw.get("self_check") if isinstance(raw.get("self_check"), dict) else {}
    portable_shots: list[dict[str, Any]] = []
    for index, item in enumerate(raw.get("storyboard") or [], 1):
        if not isinstance(item, dict):
            raise DramaProjectArchiveError("creative_storyboard_invalid")
        portable_shots.append(
            {
                "shot_no": item.get("shot_no", index),
                "shot_size": str(item.get("shot_size") or ""),
                "camera_move": str(
                    item.get("camera_move") or item.get("camera_movement") or ""
                ),
                "duration_seconds": item.get("duration_seconds", 1),
                "visual_content": str(
                    item.get("visual_content") or item.get("visual") or ""
                ),
                "voiceover": str(
                    item.get("voiceover") or item.get("narration") or ""
                ),
                "dialogue": str(item.get("dialogue") or ""),
                "is_highlight": bool(item.get("is_highlight") is True),
            }
        )
    portable_episode = PortableDramaEpisode(
        episode_no=episode.episode_no,
        season_no=episode.season_no,
        title=episode.title,
        logline=episode.logline,
        track=episode.track,
        target_duration_seconds=episode.target_duration_seconds,
        estimated_duration_seconds=episode.estimated_duration_seconds,
        core_setup={
            "protagonist": str(core.get("protagonist") or ""),
            "antagonist": str(core.get("antagonist") or ""),
            "emotional_hook": str(core.get("emotional_hook") or ""),
        },
        ai_friendly_constraints={
            "scene_count": constraints.get("scene_count", 0),
            "main_character_count": constraints.get("main_character_count", 0),
            "max_dialog_chars_per_line": constraints.get(
                "max_dialog_chars_per_line", 0
            ),
            "narrative_mode": str(constraints.get("narrative_mode") or ""),
        },
        narrative=episode.narrative,
        storyboard=portable_shots,
        ending_hook={
            "type": str(hook.get("type") or ""),
            "content": str(hook.get("content") or ""),
        },
        self_check={
            "hook_match_track": (
                check.get("hook_match_track")
                if type(check.get("hook_match_track")) is bool
                else None
            ),
            "highlight_shot_no": check.get("highlight_shot_no"),
            "duration_within_tolerance": (
                check.get("duration_within_tolerance")
                if type(check.get("duration_within_tolerance")) is bool
                else None
            ),
        },
    )
    portable_sha = sha256_data(model_to_dict(portable_episode))
    portable_meta = meta.model_copy(
        update={"agent_reviews": [], "episode_sha256": portable_sha}
    )
    return (
        _json_bytes(model_to_dict(portable_episode)),
        _json_bytes(model_to_dict(portable_meta)),
        source_sha,
        portable_sha,
    )


def export_project_archive(workspace: str, *, season_no: int = 1) -> ProjectArchive:
    """Build one coherent project snapshot under the cooperative workspace lock."""

    try:
        with use_workspace(workspace), acquire_write_lock(
            source="drama-project-archive-export"
        ):
            return _export_project_archive_under_lock(workspace, season_no=season_no)
    except WorkspaceLocked as exc:
        raise DramaProjectArchiveError("workspace_busy") from exc


def _export_project_archive_under_lock(
    workspace: str,
    *,
    season_no: int = 1,
) -> ProjectArchive:
    """Build and persist one deterministic, sanitized project archive."""

    if not isinstance(season_no, int) or isinstance(season_no, bool) or season_no != 1:
        raise DramaProjectArchiveError("season_invalid")
    if workspace_meta.read(workspace).get("type") != "drama":
        raise DramaProjectArchiveError("workspace_not_drama")
    root = paths.workspace_root(workspace)
    if root.is_symlink() or not root.is_dir():
        raise DramaProjectArchiveError("workspace_invalid")

    imported = _collect_imported_archive(root)
    if imported is not None:
        payloads, records, episode_rows = imported
    else:
        payloads = {}
        records = []
        episode_rows: list[ProjectArchiveEpisode] = []
        for episode_no in range(1, 101):
            ep = episode_paths(workspace, episode_no=episode_no)
            try:
                episode_bytes = _read_target(
                    root,
                    str(ep.episode_path.relative_to(root).as_posix()),
                    maximum=2 * 1024 * 1024,
                )
            except FileNotFoundError:
                continue
            try:
                episode = DramaEpisode(**_load_json_strict(episode_bytes))
                meta_target = str(ep.meta_path.relative_to(root).as_posix())
                meta_bytes = _read_target(root, meta_target, maximum=2 * 1024 * 1024)
                meta = DramaEpisodeMeta(**_load_json_strict(meta_bytes))
            except (FileNotFoundError, TypeError, ValueError) as exc:
                raise DramaProjectArchiveError("creative_source_invalid") from exc
            if episode.episode_no != episode_no or meta.episode_no != episode_no:
                raise DramaProjectArchiveError("creative_identity_mismatch")
            episode_target = str(ep.episode_path.relative_to(root).as_posix())
            (
                portable_episode_bytes,
                portable_meta_bytes,
                source_episode_sha,
                portable_episode_sha,
            ) = (
                _portable_creative_projection(episode, meta)
            )
            _add_payload(
                payloads, records, target=episode_target, payload=portable_episode_bytes
            )
            _add_payload(
                payloads, records, target=meta_target, payload=portable_meta_bytes
            )

            render_fingerprint: Optional[str] = None
            inspection = inspect_render_plan(workspace, episode_no=episode_no)
            if inspection.plan is not None:
                render_fingerprint = inspection.plan.plan_fingerprint

            evidence, selection_fingerprint, selected_artifact_targets = (
                _evidence_projection(workspace, episode_no)
            )
            evidence_target = (
                "data/drama_project_archive/evidence/"
                f"episode_{episode_no:03d}.json"
            )
            for selected_target in selected_artifact_targets:
                _add_payload(
                    payloads,
                    records,
                    target=selected_target,
                    payload=_read_target(root, selected_target),
                )

            timeline: Optional[TimelineManifest] = None
            timeline_fingerprint: Optional[str] = None
            qa_fingerprint: Optional[str] = None
            output_sha256: Optional[str] = None
            try:
                timeline = drama_compose_web._current_timeline_under_lock(
                    workspace, root, episode_no
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                timeline = None
            if timeline is not None:
                timeline_target = drama_compose_web._timeline_path(episode_no)
                timeline_bytes = _read_target(
                    root, timeline_target, maximum=drama_compose_web.MAX_TIMELINE_STORE_BYTES
                )
                _add_payload(payloads, records, target=timeline_target, payload=timeline_bytes)
                timeline_fingerprint = timeline.timeline_fingerprint
                for clip in [
                    *timeline.video_clips,
                    *timeline.audio_clips,
                    *timeline.optional_audio_clips,
                ]:
                    source_target = clip.artifact_path
                    source_bytes = _read_target(root, source_target)
                    _add_payload(
                        payloads,
                        records,
                        target=source_target,
                        payload=source_bytes,
                    )
                overview = drama_compose_web.build_compose_web_overview_readonly(
                    workspace, episode_no=episode_no
                )
                if overview.get("state") == "complete":
                    plan = drama_compositor.build_compose_plan(timeline)
                    edit_paths = drama_edit_export._export_paths(timeline)
                    _qa_record, output_bytes, srt_bytes = (
                        drama_compositor._require_workspace_compose_result_under_lock(
                            root,
                            timeline,
                            maximum_output_bytes=drama_compose_web.MAX_WEB_COMPOSE_MP4_BYTES,
                        )
                    )
                    _edit_record, ass_bytes, edit_bytes = (
                        drama_edit_export._require_workspace_editable_sidecars_under_lock(
                            workspace, timeline
                        )
                    )
                    delivery_payloads = {
                        plan.output_path: output_bytes,
                        plan.srt_path: srt_bytes,
                        edit_paths[0]: ass_bytes,
                        edit_paths[1]: edit_bytes,
                    }
                    for target, delivered in delivery_payloads.items():
                        _add_payload(payloads, records, target=target, payload=delivered)
                    evidence["timeline"]["qa"] = model_to_dict(_qa_record)
                    qa_fingerprint = _qa_record.qa_fingerprint
                    output_sha256 = _qa_record.output_sha256

            _add_payload(
                payloads,
                records,
                target=evidence_target,
                payload=_json_bytes(evidence),
            )

            episode_rows.append(
                ProjectArchiveEpisode(
                    episode_no=episode_no,
                    source_episode_sha256=source_episode_sha,
                    episode_sha256=portable_episode_sha,
                    render_plan_fingerprint=render_fingerprint,
                    selection_fingerprint=selection_fingerprint,
                    timeline_fingerprint=timeline_fingerprint,
                    qa_fingerprint=qa_fingerprint,
                    output_sha256=output_sha256,
                )
            )

    if not records:
        raise DramaProjectArchiveError("archive_empty")
    records.sort(key=lambda item: item.archive_path)
    if len(records) > MAX_ARCHIVE_MEMBERS:
        raise DramaProjectArchiveError("member_count_exceeded")
    total = sum(item.size for item in records)
    if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        raise DramaProjectArchiveError("archive_uncompressed_too_large")
    episode_rows.sort(key=lambda item: item.episode_no)
    member_identity = [
        {"target_path": item.target_path, "size": item.size, "sha256": item.sha256}
        for item in records
    ]
    core = {
        "schema_version": 1,
        "generator_version": ARCHIVE_GENERATOR_VERSION,
        "project_id": f"dpa_{_fingerprint(member_identity)[:24]}",
        "season_no": 1,
        "episodes": [model_to_dict(item) for item in episode_rows],
        "members": [model_to_dict(item) for item in records],
    }
    manifest = ProjectArchiveManifest(
        **core,
        archive_fingerprint=_fingerprint(core),
    )
    members = dict(payloads)
    members["manifest.json"] = _json_bytes(model_to_dict(manifest))
    body = _build_archive_zip(members)
    if len(body) > MAX_ARCHIVE_COMPRESSED_BYTES:
        raise DramaProjectArchiveError("archive_compressed_too_large")
    # Exercise the same complete, semantic preflight used by import before a
    # generated archive becomes a durable workspace artifact.
    validated, _ = _preflight(body)
    if validated != manifest:
        raise DramaProjectArchiveError("archive_self_validation_failed")
    filename = f"project_archive_{manifest.project_id[4:]}.zip"
    target = root / "outputs" / "exports" / filename
    try:
        _write_bytes_atomic(target, body, workspace_root=root)
    except Exception as exc:
        raise DramaProjectArchiveError("archive_write_failed") from exc
    return ProjectArchive(
        filename=filename,
        content_type="application/zip",
        path=target,
        body=body,
        manifest=manifest,
    )


def _build_archive_zip(members: Mapping[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(
        stream,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=False,
    ) as archive:
        for name, payload in sorted(members.items()):
            _validate_zip_name(name)
            info = zipfile.ZipInfo(name, date_time=_ZIP_DATETIME)
            info.create_system = 3
            info.external_attr = (0o100644 & 0xFFFF) << 16
            compression = zipfile.ZIP_STORED if name.endswith((".mp4", ".png", ".wav")) else zipfile.ZIP_DEFLATED
            archive.writestr(
                info,
                payload,
                compress_type=compression,
                compresslevel=9 if compression == zipfile.ZIP_DEFLATED else None,
            )
    return stream.getvalue()


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DramaProjectArchiveError("json_duplicate_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise DramaProjectArchiveError("json_nonfinite")


def _load_json_strict(payload: bytes) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except DramaProjectArchiveError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise DramaProjectArchiveError("json_invalid") from exc


def _validate_payload(payload: bytes, *, mime: str, schema: str) -> None:
    if not payload:
        raise DramaProjectArchiveError("member_empty")
    if mime == "application/json":
        value = _load_json_strict(payload)
        if not isinstance(value, dict):
            raise DramaProjectArchiveError("json_shape_invalid")
        if schema == "portable_drama_episode_v1":
            PortableDramaEpisode(**value)
        elif schema == "portable_drama_episode_meta_v1":
            meta = DramaEpisodeMeta(**value)
            if meta.agent_reviews:
                raise DramaProjectArchiveError("creative_projection_private")
        elif schema == "timeline_envelope_v1":
            if set(value) != {
                "schema_version",
                "artifact_type",
                "timeline_fingerprint",
                "timeline",
            }:
                raise DramaProjectArchiveError("timeline_envelope_invalid")
            timeline = TimelineManifest(**value["timeline"])
            if value.get("timeline_fingerprint") != timeline.timeline_fingerprint:
                raise DramaProjectArchiveError("timeline_envelope_invalid")
        elif schema == "workbench_archive_summary_v1":
            if (
                value.get("schema_version") != 1
                or value.get("artifact_type") != "drama_project_archive_evidence"
                or not re.fullmatch(_SHA256_PATTERN, str(value.get("selection_fingerprint") or ""))
            ):
                raise DramaProjectArchiveError("evidence_invalid")
        elif schema == "edit_project_v1":
            if value.get("schema_version") != 1:
                raise DramaProjectArchiveError("edit_project_invalid")
    elif mime == "video/mp4":
        if len(payload) < 12 or payload[4:8] != b"ftyp":
            raise DramaProjectArchiveError("mp4_invalid")
    elif mime == "image/png":
        if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise DramaProjectArchiveError("png_invalid")
        try:
            _validate_png(payload)
        except ValueError as exc:
            raise DramaProjectArchiveError("png_invalid") from exc
        # Portable archives accept only the minimal pixel-bearing PNG grammar.
        # Even valid ancillary/private chunks can carry prompts or credentials,
        # so fail closed instead of trying to enumerate known metadata names.
        offset = 8
        while offset < len(payload):
            size = int.from_bytes(payload[offset : offset + 4], "big")
            kind = payload[offset + 4 : offset + 8]
            end = offset + 12 + size
            if kind not in {b"IHDR", b"PLTE", b"IDAT", b"IEND"}:
                raise DramaProjectArchiveError("png_private_metadata")
            offset = end
    elif mime == "image/jpeg":
        if len(payload) < 4 or not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
            raise DramaProjectArchiveError("jpeg_invalid")
    elif mime == "image/webp":
        if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
            raise DramaProjectArchiveError("webp_invalid")
    elif mime == "audio/wav":
        if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
            raise DramaProjectArchiveError("wav_invalid")
    else:
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DramaProjectArchiveError("text_member_invalid") from exc
        if "\x00" in text:
            raise DramaProjectArchiveError("text_member_invalid")


def _zip_member_is_regular(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return mode == 0 or stat.S_ISREG(mode)


def _require_projection_dict(value: Any, *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DramaProjectArchiveError(code)
    return value


def _require_exact_keys(value: Mapping[str, Any], keys: set[str], *, code: str) -> None:
    if set(value) != keys:
        raise DramaProjectArchiveError(code)


def _validate_archive_semantics(
    manifest: ProjectArchiveManifest,
    payloads: Mapping[str, bytes],
) -> None:
    """Cross-check the manifest, evidence, timelines, sources and delivery.

    ZIP metadata and per-member hashes alone cannot prove that the files form
    one coherent project.  This pass binds every episode summary to the
    content-addressed creative source, the redacted selection evidence, the
    current timeline sources, and (when present) the exact composed MP4.
    """

    records = {item.target_path: item for item in manifest.members}
    declared = {item.episode_no for item in manifest.episodes}
    if not declared:
        raise DramaProjectArchiveError("archive_episode_missing")
    for record in manifest.members:
        episode_no = _episode_number_from_target(record.target_path)
        if episode_no is not None and episode_no not in declared:
            raise DramaProjectArchiveError("member_episode_undeclared")

    referenced_media: set[str] = set()
    referenced_assets: set[str] = set()

    def validate_artifact_reference(
        value: ArchiveArtifactReference,
        *,
        expected_partition: ArchivePartition,
        expected_mime: str,
        expected_schema: str,
        expected_target: Optional[str] = None,
        expected_prefix: Optional[str] = None,
    ) -> str:
        target_path = value.target_path
        if target_path not in payloads:
            raise DramaProjectArchiveError("selection_artifact_missing")
        record = records.get(target_path)
        payload = payloads[target_path]
        if (
            record is None
            or record.partition != expected_partition
            or record.mime != expected_mime
            or record.schema_label != expected_schema
            or (expected_target is not None and target_path != expected_target)
            or (expected_prefix is not None and not target_path.startswith(expected_prefix))
            or value.size_bytes != len(payload)
            or value.sha256 != hashlib.sha256(payload).hexdigest()
        ):
            raise DramaProjectArchiveError("selection_artifact_mismatch")
        if record.partition == "assets":
            referenced_assets.add(target_path)
        else:
            referenced_media.add(target_path)
        return target_path

    for summary in manifest.episodes:
        episode_no = summary.episode_no
        episode_target = f"outputs/episodes/episode_{episode_no:02d}.json"
        meta_target = f"outputs/episodes/episode_{episode_no:02d}.meta.json"
        evidence_target = (
            "data/drama_project_archive/evidence/"
            f"episode_{episode_no:03d}.json"
        )
        required = (episode_target, meta_target, evidence_target)
        if any(target not in payloads for target in required):
            raise DramaProjectArchiveError("episode_member_missing")
        try:
            episode = PortableDramaEpisode(**_load_json_strict(payloads[episode_target]))
            meta = DramaEpisodeMeta(**_load_json_strict(payloads[meta_target]))
            evidence = _require_projection_dict(
                _load_json_strict(payloads[evidence_target]),
                code="evidence_invalid",
            )
        except DramaProjectArchiveError:
            raise
        except (TypeError, ValueError) as exc:
            raise DramaProjectArchiveError("episode_semantics_invalid") from exc
        if episode.episode_no != episode_no or meta.episode_no != episode_no:
            raise DramaProjectArchiveError("creative_identity_mismatch")
        episode_sha = sha256_data(model_to_dict(episode))
        if not episode_sha or meta.episode_sha256 != episode_sha:
            raise DramaProjectArchiveError("episode_hash_mismatch")
        if summary.episode_sha256 != episode_sha:
            raise DramaProjectArchiveError("episode_summary_mismatch")
        if evidence.get("episode_no") != episode_no:
            raise DramaProjectArchiveError("evidence_episode_mismatch")
        _require_exact_keys(
            evidence,
            {
                "schema_version", "artifact_type", "episode_no", "state",
                "source_projection_fingerprint", "selection_fingerprint",
                "render", "selected_assets", "selected_shots", "image_state",
                "video_state", "video_attempts", "tasks", "timeline",
            },
            code="evidence_shape_invalid",
        )
        selected_assets = evidence.get("selected_assets")
        selected_shots = evidence.get("selected_shots")
        if (
            not isinstance(selected_assets, list)
            or not isinstance(selected_shots, list)
            or len(selected_assets) > 256
            or len(selected_shots) > 100
        ):
            raise DramaProjectArchiveError("selection_evidence_invalid")
        try:
            typed_assets = [ArchiveSelectedAsset(**item) for item in selected_assets]
            typed_shots = [ArchiveSelectedShot(**item) for item in selected_shots]
        except (TypeError, ValueError) as exc:
            raise DramaProjectArchiveError("selection_evidence_invalid") from exc
        asset_keys = [
            (item.kind, item.scope or "", item.asset_id, item.episode_no or 0)
            for item in typed_assets
        ]
        shot_keys = [item.shot_id for item in typed_shots]
        if (
            asset_keys != sorted(asset_keys)
            or len(asset_keys) != len(set(asset_keys))
            or shot_keys != sorted(shot_keys)
            or len(shot_keys) != len(set(shot_keys))
        ):
            raise DramaProjectArchiveError("selection_evidence_noncanonical")
        for item, typed in zip(selected_assets, typed_assets):
            row = _require_projection_dict(item, code="selection_evidence_invalid")
            _require_exact_keys(
                row,
                {
                    "kind", "asset_id", "scope", "episode_no",
                    "selected_version_id", "selection_revision",
                    "selected_status", "artifact",
                },
                code="selection_evidence_invalid",
            )
            if typed.artifact is not None:
                if typed.kind == "art_direction":
                    raise DramaProjectArchiveError("selection_artifact_mismatch")
                prefix_root = {
                    "character": "data/character_refs",
                    "scene": "data/scene_refs",
                    "prop": "data/prop_clue_refs",
                    "clue": "data/prop_clue_refs",
                }[typed.kind]
                validate_artifact_reference(
                    typed.artifact,
                    expected_partition="assets",
                    expected_mime="image/png",
                    expected_schema="png_v1",
                    expected_prefix=f"{prefix_root}/{typed.asset_id}/",
                )
        for item, typed in zip(selected_shots, typed_shots):
            row = _require_projection_dict(item, code="selection_evidence_invalid")
            _require_exact_keys(
                row,
                {"shot_id", "image", "video"},
                code="selection_evidence_invalid",
            )
            image = row.get("image")
            if image is not None:
                image_row = _require_projection_dict(
                    image, code="selection_evidence_invalid"
                )
                _require_exact_keys(
                    image_row,
                    {
                        "manifest_fingerprint", "current_request_fingerprint",
                        "selection_revision", "tail_binding_revision", "first", "tail",
                    },
                    code="selection_evidence_invalid",
                )
                typed_image = typed.image
                if typed_image is None:
                    raise DramaProjectArchiveError("selection_evidence_invalid")
                for frame, typed_frame in (
                    (image_row.get("first"), typed_image.first),
                    (image_row.get("tail"), typed_image.tail),
                ):
                    if frame is None:
                        if typed_frame is not None:
                            raise DramaProjectArchiveError("selection_evidence_invalid")
                        continue
                    if typed_frame is None:
                        raise DramaProjectArchiveError("selection_evidence_invalid")
                    frame_row = _require_projection_dict(
                        frame, code="selection_evidence_invalid"
                    )
                    _require_exact_keys(
                        frame_row,
                        {
                            "binding", "candidate_id", "candidate_fingerprint",
                            "request_fingerprint", "artifact",
                        },
                        code="selection_evidence_invalid",
                    )
                    binding = _require_projection_dict(
                        frame_row["binding"], code="selection_evidence_invalid"
                    )
                    if (
                        binding.get("candidate_id") != frame_row.get("candidate_id")
                        or binding.get("candidate_fingerprint")
                        != frame_row.get("candidate_fingerprint")
                    ):
                        raise DramaProjectArchiveError("selection_binding_mismatch")
                    validate_artifact_reference(
                        typed_frame.artifact,
                        expected_partition="assets",
                        expected_mime="image/png",
                        expected_schema="png_v1",
                        expected_target=(
                            f"outputs/episodes/episode_{episode_no:02d}.shot_images/"
                            f"{typed_frame.binding.source_shot_id or typed.shot_id}/"
                            f"{typed_frame.candidate_id}.png"
                        ),
                    )
            video = row.get("video")
            if video is not None:
                video_row = _require_projection_dict(
                    video, code="selection_evidence_invalid"
                )
                _require_exact_keys(
                    video_row,
                    {
                        "manifest_fingerprint", "current_request_fingerprint",
                        "selection_revision", "selected",
                    },
                    code="selection_evidence_invalid",
                )
                selected = video_row.get("selected")
                if selected is not None:
                    if typed.video is None or typed.video.selected is None:
                        raise DramaProjectArchiveError("selection_evidence_invalid")
                    selected_row = _require_projection_dict(
                        selected, code="selection_evidence_invalid"
                    )
                    _require_exact_keys(
                        selected_row,
                        {
                            "candidate_id", "candidate_fingerprint",
                            "request_fingerprint", "artifact",
                        },
                        code="selection_evidence_invalid",
                    )
                    validate_artifact_reference(
                        typed.video.selected.artifact,
                        expected_partition="media",
                        expected_mime="video/mp4",
                        expected_schema="mp4_v1",
                        expected_target=(
                            f"outputs/episodes/episode_{episode_no:02d}.shot_videos/"
                            f"{typed.shot_id}/{typed.video.selected.candidate_id}.mp4"
                        ),
                    )
        selection_fingerprint = _fingerprint(
            {"assets": selected_assets, "shots": selected_shots}
        )
        if (
            evidence.get("selection_fingerprint") != selection_fingerprint
            or selection_fingerprint != summary.selection_fingerprint
        ):
            raise DramaProjectArchiveError("selection_fingerprint_mismatch")
        render = _require_projection_dict(
            evidence.get("render"), code="evidence_render_invalid"
        )
        _require_exact_keys(
            render,
            {
                "state", "reasons", "season_no", "creative_revision",
                "plan_fingerprint", "shot_count", "spoken_segment_count",
                "source_event_binding_state", "source_event_counts",
                "source_episode_sha256",
            },
            code="evidence_render_invalid",
        )
        video_attempts = _require_projection_dict(
            evidence.get("video_attempts"), code="evidence_attempts_invalid"
        )
        _require_exact_keys(
            video_attempts,
            {"state", "not_sent_count", "unknown_count", "submitted_count", "terminal_count"},
            code="evidence_attempts_invalid",
        )
        task_summary = _require_projection_dict(
            evidence.get("tasks"), code="evidence_tasks_invalid"
        )
        _require_exact_keys(
            task_summary,
            {
                "state", "ledger_revision", "ledger_fingerprint", "task_count",
                "omitted_count", "unknown_count", "failed_count",
            },
            code="evidence_tasks_invalid",
        )
        if render.get("plan_fingerprint") != summary.render_plan_fingerprint:
            raise DramaProjectArchiveError("render_fingerprint_mismatch")
        if (
            summary.render_plan_fingerprint is not None
            and render.get("source_episode_sha256") != summary.source_episode_sha256
        ) or (
            summary.render_plan_fingerprint is None
            and render.get("source_episode_sha256") is not None
        ):
            raise DramaProjectArchiveError("render_source_mismatch")
        timeline_evidence = _require_projection_dict(
            evidence.get("timeline"), code="evidence_timeline_invalid"
        )
        _require_exact_keys(
            timeline_evidence,
            {
                "state", "timeline_fingerprint", "duration_ms", "shot_count",
                "subtitle_count", "qa", "deliverables",
            },
            code="evidence_timeline_invalid",
        )
        if timeline_evidence.get("timeline_fingerprint") != summary.timeline_fingerprint:
            raise DramaProjectArchiveError("timeline_fingerprint_mismatch")

        timeline_target = (
            f"outputs/drama/timeline/episode_{episode_no:03d}.timeline.json"
        )
        if summary.timeline_fingerprint is None:
            if timeline_target in payloads:
                raise DramaProjectArchiveError("timeline_summary_mismatch")
            if summary.qa_fingerprint is not None or summary.output_sha256 is not None:
                raise DramaProjectArchiveError("delivery_summary_mismatch")
            if timeline_evidence.get("qa") is not None:
                raise DramaProjectArchiveError("delivery_evidence_mismatch")
            continue
        if timeline_target not in payloads:
            raise DramaProjectArchiveError("timeline_member_missing")
        referenced_media.add(timeline_target)
        envelope = _require_projection_dict(
            _load_json_strict(payloads[timeline_target]),
            code="timeline_envelope_invalid",
        )
        try:
            timeline = TimelineManifest(**envelope["timeline"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DramaProjectArchiveError("timeline_envelope_invalid") from exc
        if (
            timeline.episode_no != episode_no
            or timeline.timeline_fingerprint != summary.timeline_fingerprint
            or envelope.get("timeline_fingerprint") != summary.timeline_fingerprint
        ):
            raise DramaProjectArchiveError("timeline_identity_mismatch")
        for clip in [
            *timeline.video_clips,
            *timeline.audio_clips,
            *timeline.optional_audio_clips,
        ]:
            source = payloads.get(clip.artifact_path)
            if source is None:
                raise DramaProjectArchiveError("timeline_source_missing")
            if hashlib.sha256(source).hexdigest() != clip.artifact_sha256:
                raise DramaProjectArchiveError("timeline_source_hash_mismatch")
            referenced_media.add(clip.artifact_path)

        evidence_qa = timeline_evidence.get("qa")
        if evidence_qa is None:
            if summary.qa_fingerprint is not None or summary.output_sha256 is not None:
                raise DramaProjectArchiveError("delivery_summary_mismatch")
            continue
        qa = _require_projection_dict(evidence_qa, code="delivery_evidence_mismatch")
        try:
            qa_report = DramaComposeQaReport(**qa)
        except (TypeError, ValueError) as exc:
            raise DramaProjectArchiveError("delivery_evidence_mismatch") from exc
        if (
            qa_report.qa_fingerprint != summary.qa_fingerprint
            or qa_report.output_sha256 != summary.output_sha256
            or qa_report.timeline_fingerprint != timeline.timeline_fingerprint
            or qa_report.episode_no != episode_no
        ):
            raise DramaProjectArchiveError("delivery_fingerprint_mismatch")
        plan = drama_compositor.build_compose_plan(timeline)
        edit_paths = drama_edit_export._export_paths(timeline)
        delivery_targets = (plan.output_path, plan.srt_path, edit_paths[0], edit_paths[1])
        if any(target not in payloads for target in delivery_targets):
            raise DramaProjectArchiveError("delivery_member_missing")
        if hashlib.sha256(payloads[plan.output_path]).hexdigest() != summary.output_sha256:
            raise DramaProjectArchiveError("delivery_output_hash_mismatch")
        if (
            qa_report.output_size_bytes != len(payloads[plan.output_path])
            or qa_report.srt_sha256
            != hashlib.sha256(payloads[plan.srt_path]).hexdigest()
        ):
            raise DramaProjectArchiveError("delivery_qa_member_mismatch")
        if payloads[plan.srt_path] != drama_timeline.export_timeline_srt(timeline).content.encode("utf-8"):
            raise DramaProjectArchiveError("delivery_srt_mismatch")
        if payloads[edit_paths[0]] != drama_edit_export.export_timeline_ass(timeline).content.encode("utf-8"):
            raise DramaProjectArchiveError("delivery_ass_mismatch")
        expected_edit = drama_edit_export._project_bytes(
            drama_edit_export.build_editable_timeline_project(timeline)
        )
        if payloads[edit_paths[1]] != expected_edit:
            raise DramaProjectArchiveError("delivery_edit_mismatch")
        referenced_media.update(delivery_targets)

    actual_media = {
        record.target_path for record in manifest.members if record.partition == "media"
    }
    if actual_media != referenced_media:
        raise DramaProjectArchiveError("media_reference_set_mismatch")
    actual_assets = {
        record.target_path for record in manifest.members if record.partition == "assets"
    }
    if actual_assets != referenced_assets:
        raise DramaProjectArchiveError("asset_reference_set_mismatch")


def _preflight(body: bytes) -> tuple[ProjectArchiveManifest, dict[str, bytes]]:
    if not isinstance(body, bytes) or not body:
        raise DramaProjectArchiveError("archive_empty_input")
    if len(body) > MAX_ARCHIVE_COMPRESSED_BYTES:
        raise DramaProjectArchiveError("archive_compressed_too_large")
    try:
        archive = zipfile.ZipFile(io.BytesIO(body), "r")
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise DramaProjectArchiveError("archive_invalid") from exc
    with archive:
        infos = archive.infolist()
        if not 2 <= len(infos) <= MAX_ARCHIVE_MEMBERS + 1:
            raise DramaProjectArchiveError("member_count_invalid")
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or len({name.casefold() for name in names}) != len(names):
            raise DramaProjectArchiveError("member_duplicate")
        total = 0
        by_name: dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            _validate_zip_name(info.filename)
            if info.is_dir() or not _zip_member_is_regular(info) or info.flag_bits & 0x1:
                raise DramaProjectArchiveError("member_attributes_invalid")
            if info.file_size <= 0 or info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                raise DramaProjectArchiveError("member_size_invalid")
            total += info.file_size
            if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise DramaProjectArchiveError("archive_uncompressed_too_large")
            if info.compress_size == 0:
                if info.file_size:
                    raise DramaProjectArchiveError("compression_ratio_invalid")
            elif info.file_size > info.compress_size * MAX_ARCHIVE_COMPRESSION_RATIO:
                raise DramaProjectArchiveError("compression_ratio_invalid")
            by_name[info.filename] = info
        manifest_info = by_name.get("manifest.json")
        if manifest_info is None or manifest_info.file_size > MAX_ARCHIVE_MANIFEST_BYTES:
            raise DramaProjectArchiveError("manifest_missing_or_large")
        try:
            manifest_bytes = archive.read(manifest_info)
            manifest = ProjectArchiveManifest(**_load_json_strict(manifest_bytes))
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            if isinstance(exc, DramaProjectArchiveError):
                raise
            raise DramaProjectArchiveError("manifest_invalid") from exc
        expected_names = {"manifest.json", *(item.archive_path for item in manifest.members)}
        if set(names) != expected_names:
            raise DramaProjectArchiveError("manifest_member_set_mismatch")
        payloads: dict[str, bytes] = {}
        for record in manifest.members:
            info = by_name[record.archive_path]
            if info.file_size != record.size:
                raise DramaProjectArchiveError("member_size_mismatch")
            try:
                payload = archive.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise DramaProjectArchiveError("member_read_failed") from exc
            if len(payload) != record.size or hashlib.sha256(payload).hexdigest() != record.sha256:
                raise DramaProjectArchiveError("member_hash_mismatch")
            _validate_payload(payload, mime=record.mime, schema=record.schema_label)
            payloads[record.target_path] = payload
        _validate_archive_semantics(manifest, payloads)
        return manifest, payloads


def preflight_project_archive(body: bytes) -> ProjectArchiveManifest:
    """Validate the complete archive without writing any workspace state."""

    manifest, _payloads = _preflight(body)
    return manifest


def read_project_archive_file(path: Path) -> bytes:
    """Read a bounded regular ZIP without following any symlink component."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd: Optional[int] = None
    directory_fd: Optional[int] = None
    try:
        candidate = Path(path)
        parts = list(candidate.parts)
        if not parts or candidate.name in {"", ".", ".."}:
            raise DramaProjectArchiveError("archive_file_invalid")
        if candidate.is_absolute():
            directory_fd = os.open(
                candidate.anchor,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            )
            parts = parts[1:]
        else:
            directory_fd = os.open(
                ".",
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            )
        for component in parts[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        fd = os.open(parts[-1], flags, dir_fd=directory_fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= MAX_ARCHIVE_COMPRESSED_BYTES:
            raise DramaProjectArchiveError("archive_file_invalid")
        chunks: list[bytes] = []
        remaining = MAX_ARCHIVE_COMPRESSED_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        body = b"".join(chunks)
        if len(body) > MAX_ARCHIVE_COMPRESSED_BYTES:
            raise DramaProjectArchiveError("archive_compressed_too_large")
        return body
    except DramaProjectArchiveError:
        raise
    except OSError as exc:
        raise DramaProjectArchiveError("archive_file_invalid") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if directory_fd is not None:
            os.close(directory_fd)


def _write_owned_file(root: Path, relative: str, payload: bytes) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.resolve().is_relative_to(root.resolve()):
        raise DramaProjectArchiveError("import_target_invalid")
    with target.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_tree(root: Path) -> None:
    for directory, subdirs, _files in os.walk(root, topdown=False, followlinks=False):
        for subdir in subdirs:
            path = Path(directory) / subdir
            if path.is_symlink():
                raise DramaProjectArchiveError("import_staging_invalid")
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _rename_directory_noreplace(source: Path, target: Path) -> None:
    """Atomically install a directory while refusing an existing target."""

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    target_bytes = os.fsencode(target)
    result: Optional[int] = None
    if hasattr(libc, "renamex_np"):
        renamex_np = libc.renamex_np
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(source_bytes, target_bytes, 0x00000004)  # RENAME_EXCL
    elif hasattr(libc, "renameat2"):
        renameat2 = libc.renameat2
        renameat2.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            -100, source_bytes, -100, target_bytes, 0x00000001  # RENAME_NOREPLACE
        )
    else:
        raise DramaProjectArchiveError("atomic_noreplace_unavailable")
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in {errno.EEXIST, errno.ENOTEMPTY}:
        raise DramaProjectArchiveError("target_workspace_exists")
    raise OSError(error, os.strerror(error), str(target))


def import_project_archive(body: bytes, *, target_workspace: str) -> ProjectArchiveImport:
    """Preflight then atomically install into one new drama workspace."""

    target = paths.workspace_root(target_workspace)
    if target.parent != paths.WORKSPACE_DIR:
        raise DramaProjectArchiveError("target_workspace_invalid")
    manifest, payloads = _preflight(body)
    workspace_parent = paths.WORKSPACE_DIR
    if workspace_parent.is_symlink():
        raise DramaProjectArchiveError("workspace_parent_invalid")
    workspace_parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise DramaProjectArchiveError("target_workspace_exists")
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{target_workspace}.archive-import.",
            dir=workspace_parent,
        )
    )
    committed = False
    durability: Literal["confirmed", "commit_uncertain"] = "confirmed"
    try:
        for name in ("小说txt", "data", "outputs", "logs"):
            (staging / name).mkdir(mode=0o755)
        _write_owned_file(
            staging,
            "data/workspace.json",
            _json_bytes({"type": "drama", "created_at": None, "schema_version": 1}),
        )
        for record in manifest.members:
            _write_owned_file(staging, record.target_path, payloads[record.target_path])
        _write_owned_file(
            staging,
            "data/drama_project_archive/import_manifest.json",
            _json_bytes(model_to_dict(manifest)),
        )
        _fsync_tree(staging)
        if target.exists() or target.is_symlink():
            raise DramaProjectArchiveError("target_workspace_exists")
        _rename_directory_noreplace(staging, target)
        committed = True
        try:
            parent_fd = os.open(
                workspace_parent,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        except OSError:
            # rename is the commit point.  The complete target and receipt are
            # already visible; report durability uncertainty without lying to
            # the operator that import failed or inviting a duplicate retry.
            durability = "commit_uncertain"
    except DramaProjectArchiveError:
        raise
    except (OSError, ValueError) as exc:
        raise DramaProjectArchiveError("import_failed") from exc
    finally:
        if not committed and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return ProjectArchiveImport(
        workspace=target_workspace,
        project_id=manifest.project_id,
        archive_fingerprint=manifest.archive_fingerprint,
        member_count=len(manifest.members),
        target=target,
        durability=durability,
    )
