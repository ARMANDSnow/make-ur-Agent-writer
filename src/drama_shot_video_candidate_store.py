"""Strict local persistence for D2 shot-video candidates and selections."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Mapping

from . import paths
from .drama_schemas import (
    EpisodeShotVideoCandidateManifest,
    EpisodeShotVideoPlan,
    ShotVideoCandidate,
    ShotVideoCoverageReport,
    ShotVideoSelection,
    episode_paths,
    normalize_episode_no,
)
from .drama_shot_video_candidates import (
    DramaShotVideoCandidateError,
    append_shot_video_candidate,
    blocked_shot_video_coverage,
    build_episode_shot_video_candidate_manifest,
    build_shot_video_candidate,
    reconcile_shot_video_candidate_manifest,
    select_shot_video_candidate,
    shot_video_candidate_affected_ids,
    shot_video_coverage,
)
from .drama_shot_video_store import load_fresh_episode_shot_video_plan
from .drama_store import (
    _read_strict_workspace_bytes,
    _read_strict_workspace_json,
    _validate_render_workspace_root,
)
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_SHOT_VIDEO_CANDIDATE_MANIFEST_BYTES = 6_000_000
MAX_SHOT_VIDEO_CANDIDATE_BYTES = 100 * 1024 * 1024
MAX_MP4_BOXES_PER_LEVEL = 4096
MAX_MP4_TOTAL_BOXES = 16_384
MAX_MP4_VIDEO_SAMPLES = 1_000_000
MAX_RECOVERY_DIRECTORY_ENTRIES = 2048
_SUPPORTED_FTYP_BRANDS = frozenset(
    {b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"hvc1", b"hevc"}
)
_SUPPORTED_VIDEO_SAMPLE_ENTRIES = frozenset(
    {b"avc1", b"avc3", b"hvc1", b"hev1", b"vp09", b"av01", b"mp4v"}
)

ShotVideoCandidateState = Literal[
    "needs_shot_video_assets",
    "fresh",
    "stale",
    "invalid",
    "blocked_source",
]


class DramaShotVideoCandidateStoreError(ValueError):
    pass


class _ManifestReadError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ShotVideoCandidateInspection:
    state: ShotVideoCandidateState
    reasons: tuple[str, ...]
    manifest: EpisodeShotVideoCandidateManifest | None = None
    affected_shot_ids: tuple[str, ...] = ()
    coverage: ShotVideoCoverageReport | None = None


def shot_video_candidate_manifest_path(
    workspace: str,
    *,
    episode_no: int = 1,
) -> Path:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    ep = episode_paths(workspace, episode_no=number)
    if ep.root != root:
        raise ValueError("shot video candidate path does not match the workspace")
    return ep.episodes_dir / f"episode_{number:02d}.shot_video_assets.json"


def _read_manifest(
    workspace: str,
    *,
    episode_no: int,
) -> EpisodeShotVideoCandidateManifest:
    root = paths.workspace_root(workspace)
    path = shot_video_candidate_manifest_path(workspace, episode_no=episode_no)
    try:
        raw = _read_strict_workspace_json(
            root,
            path,
            maximum=MAX_SHOT_VIDEO_CANDIDATE_MANIFEST_BYTES,
        )
    except FileNotFoundError:
        raise
    except (OSError, RecursionError, TypeError, ValueError) as exc:
        raise _ManifestReadError("schema_invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "artifact_type",
        "manifest_fingerprint",
        "manifest",
    }:
        raise _ManifestReadError("schema_invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise _ManifestReadError("schema_unsupported")
    if raw["artifact_type"] != "drama_episode_shot_video_assets":
        raise _ManifestReadError("schema_invalid")
    if not isinstance(raw["manifest"], dict):
        raise _ManifestReadError("schema_invalid")
    try:
        manifest = EpisodeShotVideoCandidateManifest(**raw["manifest"])
    except (TypeError, ValueError) as exc:
        raise _ManifestReadError("schema_invalid") from exc
    if raw["manifest_fingerprint"] != manifest.manifest_fingerprint:
        raise _ManifestReadError("manifest_hash_mismatch")
    if manifest.episode_no != episode_no:
        raise _ManifestReadError("schema_invalid")
    return manifest


def _mp4_boxes(
    data: bytes,
    start: int,
    end: int,
    *,
    cache: dict[tuple[int, int], list[tuple[bytes, int, int]]] | None = None,
    budget: list[int] | None = None,
) -> list[tuple[bytes, int, int]]:
    key = (start, end)
    if cache is not None and key in cache:
        return cache[key]
    boxes: list[tuple[bytes, int, int]] = []
    cursor = start
    while cursor < end:
        if end - cursor < 8:
            raise ValueError("MP4 contains a truncated box header")
        size = int.from_bytes(data[cursor : cursor + 4], "big")
        box_type = data[cursor + 4 : cursor + 8]
        header = 8
        if size == 1:
            if end - cursor < 16:
                raise ValueError("MP4 contains a truncated extended box header")
            size = int.from_bytes(data[cursor + 8 : cursor + 16], "big")
            header = 16
        elif size == 0:
            size = end - cursor
        if size < header or cursor + size > end:
            raise ValueError("MP4 box size is invalid")
        boxes.append((box_type, cursor + header, cursor + size))
        if len(boxes) > MAX_MP4_BOXES_PER_LEVEL:
            raise ValueError("MP4 contains too many boxes")
        cursor += size
    if budget is not None:
        budget[0] += len(boxes)
        if budget[0] > MAX_MP4_TOTAL_BOXES:
            raise ValueError("MP4 contains too many boxes in total")
    if cache is not None:
        cache[key] = boxes
    return boxes


def _first_mp4_box(
    data: bytes,
    start: int,
    end: int,
    wanted: bytes,
    *,
    cache: dict[tuple[int, int], list[tuple[bytes, int, int]]] | None = None,
    budget: list[int] | None = None,
) -> tuple[int, int]:
    for box_type, payload_start, box_end in _mp4_boxes(
        data,
        start,
        end,
        cache=cache,
        budget=budget,
    ):
        if box_type == wanted:
            return payload_start, box_end
    raise ValueError("MP4 is missing a required box")


def _validate_ftyp(data: bytes, top: list[tuple[bytes, int, int]]) -> None:
    matches = [item for item in top if item[0] == b"ftyp"]
    if len(matches) != 1:
        raise ValueError("MP4 must contain one ftyp box")
    _kind, start, end = matches[0]
    payload = data[start:end]
    if len(payload) < 8 or (len(payload) - 8) % 4 != 0:
        raise ValueError("MP4 ftyp payload is invalid")
    brands = {payload[:4]}
    brands.update(payload[index : index + 4] for index in range(8, len(payload), 4))
    if not brands & _SUPPORTED_FTYP_BRANDS:
        raise ValueError("MP4 ftyp has no supported brand")


def _parse_stsd(
    data: bytes,
    start: int,
    end: int,
    *,
    cache: dict[tuple[int, int], list[tuple[bytes, int, int]]] | None = None,
    budget: list[int] | None = None,
) -> tuple[int, dict[int, tuple[int, int]]]:
    payload = data[start:end]
    if len(payload) < 8:
        raise ValueError("MP4 stsd is truncated")
    entry_count = int.from_bytes(payload[4:8], "big")
    entries = _mp4_boxes(
        data,
        start + 8,
        end,
        cache=cache,
        budget=budget,
    )
    if entry_count <= 0 or entry_count != len(entries):
        raise ValueError("MP4 stsd entry count is invalid")
    dimensions: dict[int, tuple[int, int]] = {}
    for entry_index, (kind, entry_start, entry_end) in enumerate(entries, start=1):
        if kind not in _SUPPORTED_VIDEO_SAMPLE_ENTRIES:
            continue
        entry = data[entry_start:entry_end]
        if len(entry) < 28:
            raise ValueError("MP4 video sample entry is truncated")
        width = int.from_bytes(entry[24:26], "big")
        height = int.from_bytes(entry[26:28], "big")
        if width <= 0 or height <= 0:
            raise ValueError("MP4 video sample entry dimensions are invalid")
        dimensions[entry_index] = (width, height)
    if not dimensions:
        raise ValueError("MP4 has no supported video sample entry")
    return entry_count, dimensions


def _parse_stsz(
    data: bytes,
    start: int,
    end: int,
) -> tuple[int, int, list[int] | None]:
    payload = data[start:end]
    if len(payload) < 12:
        raise ValueError("MP4 stsz is truncated")
    sample_size = int.from_bytes(payload[4:8], "big")
    sample_count = int.from_bytes(payload[8:12], "big")
    if not 1 <= sample_count <= MAX_MP4_VIDEO_SAMPLES:
        raise ValueError("MP4 video sample count is invalid")
    if sample_size > 0:
        if len(payload) != 12:
            raise ValueError("MP4 fixed stsz has trailing data")
        return sample_count, sample_size, None
    expected = 12 + sample_count * 4
    if len(payload) != expected:
        raise ValueError("MP4 variable stsz table is truncated")
    sizes = [
        int.from_bytes(payload[index : index + 4], "big")
        for index in range(12, expected, 4)
    ]
    if any(size <= 0 for size in sizes):
        raise ValueError("MP4 video sample size is invalid")
    return sample_count, 0, sizes


def _parse_mdhd_timescale(data: bytes, start: int, end: int) -> int:
    payload = data[start:end]
    if not payload:
        raise ValueError("MP4 mdhd is truncated")
    if payload[0] == 0 and len(payload) >= 20:
        timescale = int.from_bytes(payload[12:16], "big")
    elif payload[0] == 1 and len(payload) >= 32:
        timescale = int.from_bytes(payload[20:24], "big")
    else:
        raise ValueError("MP4 mdhd version is unsupported")
    if timescale <= 0:
        raise ValueError("MP4 track timescale is invalid")
    return timescale


def _parse_stts_duration(
    data: bytes,
    start: int,
    end: int,
    *,
    sample_count: int,
) -> int:
    payload = data[start:end]
    if len(payload) < 8:
        raise ValueError("MP4 stts is truncated")
    count = int.from_bytes(payload[4:8], "big")
    if not 1 <= count <= MAX_MP4_BOXES_PER_LEVEL or len(payload) != 8 + count * 8:
        raise ValueError("MP4 stts entry count is invalid")
    accounted = 0
    duration = 0
    for index in range(count):
        offset = 8 + index * 8
        entry_samples = int.from_bytes(payload[offset : offset + 4], "big")
        sample_delta = int.from_bytes(payload[offset + 4 : offset + 8], "big")
        if entry_samples <= 0 or sample_delta <= 0:
            raise ValueError("MP4 stts entry is invalid")
        accounted += entry_samples
        duration += entry_samples * sample_delta
    if accounted != sample_count or duration <= 0:
        raise ValueError("MP4 stts does not account for every video sample")
    return duration


def _parse_chunk_offsets(
    data: bytes,
    start: int,
    end: int,
    *,
    width: int,
) -> list[int]:
    payload = data[start:end]
    if len(payload) < 8:
        raise ValueError("MP4 chunk offset table is truncated")
    count = int.from_bytes(payload[4:8], "big")
    if not 1 <= count <= MAX_MP4_VIDEO_SAMPLES:
        raise ValueError("MP4 chunk offset count is invalid")
    expected = 8 + count * width
    if len(payload) != expected:
        raise ValueError("MP4 chunk offset table is truncated")
    offsets = [
        int.from_bytes(payload[index : index + width], "big")
        for index in range(8, expected, width)
    ]
    if any(offset <= 0 for offset in offsets):
        raise ValueError("MP4 chunk offset is invalid")
    return offsets


def _parse_stsc(
    data: bytes,
    start: int,
    end: int,
    *,
    supported_descriptions: set[int],
) -> list[tuple[int, int, int]]:
    payload = data[start:end]
    if len(payload) < 8:
        raise ValueError("MP4 stsc is truncated")
    count = int.from_bytes(payload[4:8], "big")
    if not 1 <= count <= MAX_MP4_BOXES_PER_LEVEL or len(payload) != 8 + count * 12:
        raise ValueError("MP4 stsc entry count is invalid")
    entries: list[tuple[int, int, int]] = []
    previous_first = 0
    for index in range(count):
        offset = 8 + index * 12
        first_chunk = int.from_bytes(payload[offset : offset + 4], "big")
        samples_per_chunk = int.from_bytes(payload[offset + 4 : offset + 8], "big")
        description_index = int.from_bytes(payload[offset + 8 : offset + 12], "big")
        if (
            first_chunk <= previous_first
            or (index == 0 and first_chunk != 1)
            or samples_per_chunk <= 0
            or description_index not in supported_descriptions
        ):
            raise ValueError("MP4 stsc entry is invalid")
        entries.append((first_chunk, samples_per_chunk, description_index))
        previous_first = first_chunk
    return entries


def _validate_video_sample_ranges(
    *,
    chunk_offsets: list[int],
    stsc_entries: list[tuple[int, int, int]],
    sample_count: int,
    fixed_sample_size: int,
    variable_sample_sizes: list[int] | None,
    mdat_ranges: list[tuple[int, int]],
) -> None:
    sample_index = 0
    if variable_sample_sizes is not None and len(variable_sample_sizes) != sample_count:
        raise ValueError("MP4 sample size count is invalid")
    for chunk_number, chunk_offset in enumerate(chunk_offsets, start=1):
        entry_index = max(
            index
            for index, (first_chunk, _samples, _description) in enumerate(stsc_entries)
            if first_chunk <= chunk_number
        )
        samples_in_chunk = stsc_entries[entry_index][1]
        if variable_sample_sizes is None:
            if sample_index + samples_in_chunk > sample_count:
                raise ValueError("MP4 stsc assigns too many samples")
            chunk_size = samples_in_chunk * fixed_sample_size
        else:
            chunk_sizes = variable_sample_sizes[
                sample_index : sample_index + samples_in_chunk
            ]
            if len(chunk_sizes) != samples_in_chunk:
                raise ValueError("MP4 stsc assigns too many samples")
            chunk_size = sum(chunk_sizes)
        sample_index += samples_in_chunk
        if not any(
            start <= chunk_offset and chunk_offset + chunk_size <= end
            for start, end in mdat_ranges
        ):
            raise ValueError("MP4 video samples do not resolve inside mdat")
    if sample_index != sample_count:
        raise ValueError("MP4 stsc does not account for every video sample")


def _probe_mp4(data: bytes) -> tuple[int, int, int, bool]:
    cache: dict[tuple[int, int], list[tuple[bytes, int, int]]] = {}
    budget = [0]
    top = _mp4_boxes(data, 0, len(data), cache=cache, budget=budget)
    types = {box_type for box_type, _start, _end in top}
    if not {b"ftyp", b"moov", b"mdat"}.issubset(types):
        raise ValueError("MP4 is structurally incomplete")
    if sum(box_type == b"moov" for box_type, _start, _end in top) != 1:
        raise ValueError("MP4 must contain one moov box")
    if not any(
        box_type == b"mdat" and box_end > payload_start
        for box_type, payload_start, box_end in top
    ):
        raise ValueError("MP4 media data is empty")
    _validate_ftyp(data, top)
    mdat_ranges = [
        (payload_start, box_end)
        for box_type, payload_start, box_end in top
        if box_type == b"mdat" and box_end > payload_start
    ]
    moov_start, moov_end = _first_mp4_box(
        data, 0, len(data), b"moov", cache=cache, budget=budget
    )
    mvhd_start, mvhd_end = _first_mp4_box(
        data, moov_start, moov_end, b"mvhd", cache=cache, budget=budget
    )
    mvhd = data[mvhd_start:mvhd_end]
    if len(mvhd) < 20:
        raise ValueError("MP4 mvhd is truncated")
    version = mvhd[0]
    if version == 0:
        timescale = int.from_bytes(mvhd[12:16], "big")
        duration = int.from_bytes(mvhd[16:20], "big")
    elif version == 1 and len(mvhd) >= 32:
        timescale = int.from_bytes(mvhd[20:24], "big")
        duration = int.from_bytes(mvhd[24:32], "big")
    else:
        raise ValueError("MP4 mvhd version is unsupported")
    if timescale <= 0 or duration <= 0:
        raise ValueError("MP4 duration metadata is invalid")
    movie_duration_milliseconds = (duration * 1000 + timescale // 2) // timescale
    width = height = 0
    video_duration_milliseconds = 0
    has_audio_track = False
    for box_type, trak_start, trak_end in _mp4_boxes(
        data, moov_start, moov_end, cache=cache, budget=budget
    ):
        if box_type != b"trak":
            continue
        try:
            mdia_start, mdia_end = _first_mp4_box(
                data, trak_start, trak_end, b"mdia", cache=cache, budget=budget
            )
            hdlr_start, hdlr_end = _first_mp4_box(
                data, mdia_start, mdia_end, b"hdlr", cache=cache, budget=budget
            )
        except ValueError:
            continue
        hdlr = data[hdlr_start:hdlr_end]
        if len(hdlr) >= 12 and hdlr[8:12] == b"soun":
            has_audio_track = True
            continue
        if len(hdlr) < 12 or hdlr[8:12] != b"vide":
            continue
        try:
            mdhd_start, mdhd_end = _first_mp4_box(
                data, mdia_start, mdia_end, b"mdhd", cache=cache, budget=budget
            )
            track_timescale = _parse_mdhd_timescale(data, mdhd_start, mdhd_end)
            minf_start, minf_end = _first_mp4_box(
                data, mdia_start, mdia_end, b"minf", cache=cache, budget=budget
            )
            stbl_start, stbl_end = _first_mp4_box(
                data, minf_start, minf_end, b"stbl", cache=cache, budget=budget
            )
            stbl_boxes = _mp4_boxes(
                data,
                stbl_start,
                stbl_end,
                cache=cache,
                budget=budget,
            )
            stbl_types = [item[0] for item in stbl_boxes]
            if any(stbl_types.count(kind) != 1 for kind in (b"stsd", b"stsz", b"stsc", b"stts")):
                raise ValueError("MP4 video sample table has duplicate required boxes")
            if stbl_types.count(b"stco") + stbl_types.count(b"co64") != 1:
                raise ValueError("MP4 video sample table needs one chunk offset box")
            stsd_start, stsd_end = _first_mp4_box(
                data, stbl_start, stbl_end, b"stsd", cache=cache, budget=budget
            )
            stsz_start, stsz_end = _first_mp4_box(
                data, stbl_start, stbl_end, b"stsz", cache=cache, budget=budget
            )
            stsc_start, stsc_end = _first_mp4_box(
                data, stbl_start, stbl_end, b"stsc", cache=cache, budget=budget
            )
            stts_start, stts_end = _first_mp4_box(
                data, stbl_start, stbl_end, b"stts", cache=cache, budget=budget
            )
            try:
                stco_start, stco_end = _first_mp4_box(
                    data,
                    stbl_start,
                    stbl_end,
                    b"stco",
                    cache=cache,
                    budget=budget,
                )
                chunk_offsets = _parse_chunk_offsets(
                    data,
                    stco_start,
                    stco_end,
                    width=4,
                )
            except ValueError:
                co64_start, co64_end = _first_mp4_box(
                    data,
                    stbl_start,
                    stbl_end,
                    b"co64",
                    cache=cache,
                    budget=budget,
                )
                chunk_offsets = _parse_chunk_offsets(
                    data,
                    co64_start,
                    co64_end,
                    width=8,
                )
            description_count, sample_dimensions = _parse_stsd(
                data,
                stsd_start,
                stsd_end,
                cache=cache,
                budget=budget,
            )
            sample_count, fixed_sample_size, variable_sizes = _parse_stsz(
                data,
                stsz_start,
                stsz_end,
            )
            track_duration = _parse_stts_duration(
                data,
                stts_start,
                stts_end,
                sample_count=sample_count,
            )
            stsc_entries = _parse_stsc(
                data,
                stsc_start,
                stsc_end,
                supported_descriptions=set(sample_dimensions),
            )
            _validate_video_sample_ranges(
                chunk_offsets=chunk_offsets,
                stsc_entries=stsc_entries,
                sample_count=sample_count,
                fixed_sample_size=fixed_sample_size,
                variable_sample_sizes=variable_sizes,
                mdat_ranges=mdat_ranges,
            )
            tkhd_start, tkhd_end = _first_mp4_box(
                data, trak_start, trak_end, b"tkhd", cache=cache, budget=budget
            )
            tkhd = data[tkhd_start:tkhd_end]
            offset = 76 if tkhd and tkhd[0] == 0 else 88 if tkhd and tkhd[0] == 1 else -1
            if offset < 0 or len(tkhd) < offset + 8:
                continue
            candidate_width = int.from_bytes(tkhd[offset : offset + 4], "big") >> 16
            candidate_height = int.from_bytes(
                tkhd[offset + 4 : offset + 8],
                "big",
            ) >> 16
            if candidate_width > 0 and candidate_height > 0:
                used_descriptions = {item[2] for item in stsc_entries}
                used_dimensions = {
                    sample_dimensions[index] for index in used_descriptions
                }
                if used_dimensions != {(candidate_width, candidate_height)}:
                    raise ValueError("MP4 video dimensions disagree across tables")
                width, height = candidate_width, candidate_height
                current_duration = (
                    track_duration * 1000 + track_timescale // 2
                ) // track_timescale
                video_duration_milliseconds = max(
                    video_duration_milliseconds,
                    current_duration,
                )
        except ValueError:
            continue
    if width <= 0 or height <= 0 or video_duration_milliseconds <= 0:
        raise ValueError("MP4 has no valid video track")
    if movie_duration_milliseconds <= 0:
        raise ValueError("MP4 movie duration is invalid")
    return video_duration_milliseconds, width, height, has_audio_track


def _candidate_payload_identity(data: bytes) -> tuple[str, int, int, int, int, bool]:
    if type(data) is not bytes or not data or len(data) > MAX_SHOT_VIDEO_CANDIDATE_BYTES:
        raise DramaShotVideoCandidateStoreError("candidate artifact is not a bounded MP4")
    try:
        duration_milliseconds, width, height, has_audio_track = _probe_mp4(data)
    except (OverflowError, TypeError, ValueError) as exc:
        raise DramaShotVideoCandidateStoreError(
            "candidate artifact is not a valid MP4 video"
        ) from exc
    if (
        not 1 <= duration_milliseconds <= 300_000
        or width <= 0
        or height <= 0
        or width * height > 40_000_000
    ):
        raise DramaShotVideoCandidateStoreError("candidate MP4 metadata is invalid")
    return (
        hashlib.sha256(data).hexdigest(),
        len(data),
        duration_milliseconds,
        width,
        height,
        has_audio_track,
    )


def _validate_manifest_artifacts(
    workspace: str,
    manifest: EpisodeShotVideoCandidateManifest,
    *,
    skip_artifact_path: str | None = None,
) -> tuple[str, ...]:
    root = paths.workspace_root(workspace)
    invalid_shot_ids: list[str] = []
    checked_paths: set[str] = set()
    for pool in manifest.shots:
        if pool.selected is None:
            continue
        candidate = next(
            item
            for item in pool.candidates
            if item.candidate_id == pool.selected.candidate_id
        )
        artifact = candidate.artifact
        if artifact.path == skip_artifact_path or artifact.path in checked_paths:
            continue
        try:
            payload = _read_strict_workspace_bytes(
                root,
                root / artifact.path,
                maximum=artifact.size_bytes,
            )
            identity = (
                artifact.sha256,
                artifact.size_bytes,
                artifact.duration_milliseconds,
                artifact.width,
                artifact.height,
                artifact.has_audio_track,
            )
            if _candidate_payload_identity(payload) != identity:
                raise ValueError("candidate artifact bytes changed")
        except (OSError, RecursionError, TypeError, ValueError):
            invalid_shot_ids.append(pool.shot_id)
        checked_paths.add(artifact.path)
    return tuple(invalid_shot_ids)


def _validate_exact_candidate_artifact(
    workspace: str,
    candidate: ShotVideoCandidate,
) -> None:
    root = paths.workspace_root(workspace)
    artifact = candidate.artifact
    payload = _read_strict_workspace_bytes(
        root,
        root / artifact.path,
        maximum=artifact.size_bytes,
    )
    identity = (
        artifact.sha256,
        artifact.size_bytes,
        artifact.duration_milliseconds,
        artifact.width,
        artifact.height,
        artifact.has_audio_track,
    )
    if _candidate_payload_identity(payload) != identity:
        raise DramaShotVideoCandidateStoreError("candidate artifact bytes changed")


def _require_valid_selected_artifacts(
    workspace: str,
    manifest: EpisodeShotVideoCandidateManifest,
    *,
    skip_artifact_path: str | None = None,
) -> None:
    if _validate_manifest_artifacts(
        workspace,
        manifest,
        skip_artifact_path=skip_artifact_path,
    ):
        raise DramaShotVideoCandidateStoreError(
            "selected candidate artifact is invalid"
        )


def inspect_episode_shot_video_candidates(
    workspace: str,
    *,
    episode_no: int = 1,
) -> ShotVideoCandidateInspection:
    try:
        number = normalize_episode_no(episode_no)
        stored = _read_manifest(workspace, episode_no=number)
    except FileNotFoundError:
        stored = None
    except _ManifestReadError as exc:
        return ShotVideoCandidateInspection("invalid", (exc.reason,))
    except (OSError, RecursionError, TypeError, ValueError):
        return ShotVideoCandidateInspection("invalid", ("request_invalid",))
    try:
        plan = load_fresh_episode_shot_video_plan(workspace, episode_no=number)
    except (OSError, RecursionError, TypeError, ValueError):
        coverage = blocked_shot_video_coverage(stored) if stored is not None else None
        return ShotVideoCandidateInspection(
            "blocked_source",
            ("source_not_fresh",),
            stored,
            tuple(coverage.blocked_source_shot_ids) if coverage is not None else (),
            coverage,
        )
    if stored is None:
        return ShotVideoCandidateInspection("needs_shot_video_assets", ("missing",))
    try:
        invalid_artifacts = _validate_manifest_artifacts(workspace, stored)
        affected = shot_video_candidate_affected_ids(stored, plan)
        coverage = shot_video_coverage(
            stored,
            plan,
            invalid_artifact_shot_ids=invalid_artifacts,
        )
    except (OSError, RecursionError, TypeError, ValueError):
        return ShotVideoCandidateInspection(
            "invalid",
            ("artifact_or_manifest_invalid",),
            stored,
        )
    if coverage.invalid_artifact_shot_ids:
        return ShotVideoCandidateInspection(
            "invalid",
            ("artifact_invalid",),
            stored,
            tuple(coverage.invalid_artifact_shot_ids),
            coverage,
        )
    if stored.source_plan_fingerprint != plan.plan_fingerprint or affected:
        return ShotVideoCandidateInspection(
            "stale",
            ("source_plan_mismatch",),
            stored,
            tuple(affected),
            coverage,
        )
    if coverage.status == "stale":
        return ShotVideoCandidateInspection(
            "stale",
            ("selection_stale",),
            stored,
            tuple(coverage.stale_candidate_shot_ids),
            coverage,
        )
    return ShotVideoCandidateInspection("fresh", (), stored, (), coverage)


def load_fresh_episode_shot_video_candidates(
    workspace: str,
    *,
    episode_no: int = 1,
) -> EpisodeShotVideoCandidateManifest:
    inspection = inspect_episode_shot_video_candidates(
        workspace,
        episode_no=episode_no,
    )
    if inspection.state != "fresh" or inspection.manifest is None:
        raise DramaShotVideoCandidateStoreError(
            f"shot video candidates are not fresh: {inspection.state}"
        )
    return inspection.manifest


def _target_token(root: Path, path: Path) -> tuple[Any, ...]:
    try:
        payload = _read_strict_workspace_bytes(
            root,
            path,
            maximum=MAX_SHOT_VIDEO_CANDIDATE_MANIFEST_BYTES,
        )
    except FileNotFoundError:
        return ("missing",)
    except ValueError:
        return ("invalid",)
    return ("file", len(payload), hashlib.sha256(payload).hexdigest())


def _target_token_at(directory_fd: int, name: str) -> tuple[Any, ...]:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    file_fd: int | None = None
    try:
        file_fd = os.open(
            name,
            os.O_RDONLY | nofollow | nonblock,
            dir_fd=directory_fd,
        )
    except FileNotFoundError:
        return ("missing",)
    except OSError:
        return ("invalid",)
    try:
        info = os.fstat(file_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size <= 0
            or info.st_size > MAX_SHOT_VIDEO_CANDIDATE_MANIFEST_BYTES
        ):
            return ("invalid",)
        chunks: list[bytes] = []
        remaining = MAX_SHOT_VIDEO_CANDIDATE_MANIFEST_BYTES + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != info.st_size or len(payload) > MAX_SHOT_VIDEO_CANDIDATE_MANIFEST_BYTES:
            return ("invalid",)
        return ("file", len(payload), hashlib.sha256(payload).hexdigest())
    except OSError:
        return ("invalid",)
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass


def _open_parent_dir(root: Path, relative: Path, *, create: bool) -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise DramaShotVideoCandidateStoreError("strict no-follow writes are unavailable")
    directory_fd = os.open(str(root), os.O_RDONLY | directory | nofollow)
    try:
        for part in relative.parts[:-1]:
            try:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=directory_fd,
                )
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=directory_fd)
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=directory_fd,
                )
            os.close(directory_fd)
            directory_fd = next_fd
        return directory_fd
    except BaseException:
        try:
            os.close(directory_fd)
        except OSError:
            pass
        raise


def _recover_owned_crash_residue(
    workspace: str,
    *,
    episode_no: int,
    manifest: EpisodeShotVideoCandidateManifest | None,
) -> None:
    """Bounded cleanup for this store's canonical temp and orphan names."""

    root = paths.workspace_root(workspace)
    referenced = {
        candidate.artifact.path
        for pool in (
            [*manifest.shots, *manifest.retired_shots]
            if manifest is not None
            else []
        )
        for candidate in pool.candidates
    }
    manifest_path = shot_video_candidate_manifest_path(
        workspace,
        episode_no=episode_no,
    )
    manifest_parent_fd: int | None = None
    try:
        relative = manifest_path.relative_to(root)
        manifest_parent_fd = _open_parent_dir(root, relative, create=True)
        temp_pattern = re.compile(
            rf"^\.{re.escape(relative.name)}\.tmp\.[0-9a-f]{{32}}$"
        )
        names = os.listdir(manifest_parent_fd)
        if len(names) > MAX_RECOVERY_DIRECTORY_ENTRIES:
            raise DramaShotVideoCandidateStoreError(
                "candidate recovery directory exceeds its entry budget"
            )
        for name in names:
            if temp_pattern.fullmatch(name) is None:
                continue
            info = os.stat(name, dir_fd=manifest_parent_fd, follow_symlinks=False)
            if stat.S_ISREG(info.st_mode):
                os.unlink(name, dir_fd=manifest_parent_fd)
        os.fsync(manifest_parent_fd)
    except FileNotFoundError:
        pass
    except DramaShotVideoCandidateStoreError:
        raise
    except OSError as exc:
        raise DramaShotVideoCandidateStoreError(
            "candidate crash recovery was rejected"
        ) from exc
    finally:
        if manifest_parent_fd is not None:
            os.close(manifest_parent_fd)

    video_root = root / f"outputs/episodes/episode_{episode_no:02d}.shot_videos"
    try:
        relative_root = video_root.relative_to(root)
        root_fd = _open_parent_dir(
            root,
            relative_root / "sentinel",
            create=False,
        )
    except FileNotFoundError:
        return
    total = 0
    try:
        shot_names = os.listdir(root_fd)
        total += len(shot_names)
        for shot_name in shot_names:
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", shot_name) is None:
                continue
            try:
                shot_fd = os.open(
                    shot_name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=root_fd,
                )
            except OSError:
                continue
            try:
                artifact_names = os.listdir(shot_fd)
                total += len(artifact_names)
                if total > MAX_RECOVERY_DIRECTORY_ENTRIES:
                    raise DramaShotVideoCandidateStoreError(
                        "candidate recovery exceeds its entry budget"
                    )
                for name in artifact_names:
                    is_temp = re.fullmatch(
                        r"\.svc_[0-9a-f]{24}\.mp4\.tmp\.[0-9a-f]{32}",
                        name,
                    ) is not None
                    is_final = re.fullmatch(
                        r"svc_[0-9a-f]{24}\.mp4",
                        name,
                    ) is not None
                    relative_artifact = (
                        relative_root / shot_name / name
                    ).as_posix()
                    if not is_temp and not (
                        is_final and relative_artifact not in referenced
                    ):
                        continue
                    info = os.stat(name, dir_fd=shot_fd, follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode):
                        os.unlink(name, dir_fd=shot_fd)
                os.fsync(shot_fd)
            finally:
                os.close(shot_fd)
        os.fsync(root_fd)
    finally:
        os.close(root_fd)


def _write_manifest(
    workspace: str,
    manifest: EpisodeShotVideoCandidateManifest,
    *,
    expected_target_token: tuple[Any, ...],
    precommit_check: Callable[[], None] | None = None,
) -> None:
    envelope: Dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": "drama_episode_shot_video_assets",
        "manifest_fingerprint": manifest.manifest_fingerprint,
        "manifest": model_to_dict(manifest),
    }
    payload = (
        json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    if not payload or len(payload) > MAX_SHOT_VIDEO_CANDIDATE_MANIFEST_BYTES:
        raise DramaShotVideoCandidateStoreError("candidate manifest exceeds its size limit")
    root = paths.workspace_root(workspace)
    path = shot_video_candidate_manifest_path(
        workspace,
        episode_no=manifest.episode_no,
    )
    _validate_render_workspace_root(root)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DramaShotVideoCandidateStoreError(
            "candidate manifest path escapes the workspace"
        ) from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise DramaShotVideoCandidateStoreError("candidate manifest path is invalid")
    directory_fd: int | None = None
    temp_fd: int | None = None
    temp_identity: tuple[int, int] | None = None
    temp_name = f".{relative.name}.tmp.{secrets.token_hex(16)}"
    try:
        directory_fd = _open_parent_dir(root, relative, create=True)
        if _target_token_at(directory_fd, relative.name) != expected_target_token:
            raise DramaShotVideoCandidateStoreError(
                "candidate manifest changed concurrently; retry from inspection"
            )
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=directory_fd,
        )
        opened = os.fstat(temp_fd)
        temp_identity = (opened.st_dev, opened.st_ino)
        view = memoryview(payload)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError("short candidate manifest write")
            view = view[written:]
        os.fsync(temp_fd)
        if precommit_check is not None:
            precommit_check()
        if _target_token_at(directory_fd, relative.name) != expected_target_token:
            raise DramaShotVideoCandidateStoreError(
                "candidate manifest changed concurrently; retry from inspection"
            )
        opened = os.fstat(temp_fd)
        named = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise DramaShotVideoCandidateStoreError(
                "candidate manifest temporary file changed concurrently"
            )
        os.replace(
            temp_name,
            relative.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    except DramaShotVideoCandidateStoreError:
        raise
    except OSError as exc:
        raise DramaShotVideoCandidateStoreError(
            "candidate manifest could not be written safely"
        ) from exc
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if directory_fd is not None and temp_identity is not None:
            try:
                cleanup = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError:
                pass
            else:
                if (
                    stat.S_ISREG(cleanup.st_mode)
                    and (cleanup.st_dev, cleanup.st_ino) == temp_identity
                ):
                    try:
                        os.unlink(temp_name, dir_fd=directory_fd)
                    except OSError:
                        pass
        if directory_fd is not None:
            try:
                os.close(directory_fd)
            except OSError:
                pass


def _write_artifact_create_only(
    workspace: str,
    candidate: ShotVideoCandidate,
    data: bytes,
) -> tuple[int, int] | None:
    root = paths.workspace_root(workspace)
    path = root / candidate.artifact.path
    _validate_render_workspace_root(root)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DramaShotVideoCandidateStoreError(
            "candidate artifact path escapes the workspace"
        ) from exc
    try:
        existing = _read_strict_workspace_bytes(
            root,
            path,
            maximum=candidate.artifact.size_bytes,
        )
    except FileNotFoundError:
        existing = None
    except (OSError, ValueError) as exc:
        raise DramaShotVideoCandidateStoreError(
            "candidate artifact target is invalid"
        ) from exc
    expected = (
        candidate.artifact.sha256,
        candidate.artifact.size_bytes,
        candidate.artifact.duration_milliseconds,
        candidate.artifact.width,
        candidate.artifact.height,
        candidate.artifact.has_audio_track,
    )
    if existing is not None:
        if _candidate_payload_identity(existing) != expected or existing != data:
            raise DramaShotVideoCandidateStoreError(
                "candidate artifact path is occupied by different bytes"
            )
        return None
    directory_fd: int | None = None
    temp_fd: int | None = None
    temp_identity: tuple[int, int] | None = None
    linked = False
    completed = False
    temp_name = f".{relative.name}.tmp.{secrets.token_hex(16)}"
    try:
        directory_fd = _open_parent_dir(root, relative, create=True)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if _target_token_at(directory_fd, relative.name) != ("missing",):
            raise DramaShotVideoCandidateStoreError(
                "candidate artifact path changed concurrently"
            )
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=directory_fd,
        )
        opened = os.fstat(temp_fd)
        temp_identity = (opened.st_dev, opened.st_ino)
        view = memoryview(data)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError("short candidate artifact write")
            view = view[written:]
        os.fsync(temp_fd)
        named = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(named.st_mode) or (named.st_dev, named.st_ino) != temp_identity:
            raise DramaShotVideoCandidateStoreError(
                "candidate artifact temporary file changed"
            )
        os.link(
            temp_name,
            relative.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
        linked = True
        final = os.stat(relative.name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(final.st_mode) or (final.st_dev, final.st_ino) != temp_identity:
            raise DramaShotVideoCandidateStoreError(
                "candidate artifact link changed concurrently"
            )
        os.unlink(temp_name, dir_fd=directory_fd)
        os.fsync(directory_fd)
        completed = True
    except FileExistsError as exc:
        raise DramaShotVideoCandidateStoreError(
            "candidate artifact path changed concurrently"
        ) from exc
    except DramaShotVideoCandidateStoreError:
        raise
    except OSError as exc:
        raise DramaShotVideoCandidateStoreError(
            "candidate artifact could not be written safely"
        ) from exc
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if directory_fd is not None and temp_identity is not None:
            for name, remove in (
                (temp_name, True),
                (relative.name, linked and not completed),
            ):
                if not remove:
                    continue
                try:
                    cleanup = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                except OSError:
                    continue
                if (
                    stat.S_ISREG(cleanup.st_mode)
                    and (cleanup.st_dev, cleanup.st_ino) == temp_identity
                ):
                    try:
                        os.unlink(name, dir_fd=directory_fd)
                    except OSError:
                        pass
        if directory_fd is not None:
            try:
                os.close(directory_fd)
            except OSError:
                pass
    persisted = _read_strict_workspace_bytes(
        root,
        path,
        maximum=candidate.artifact.size_bytes,
    )
    if persisted != data or _candidate_payload_identity(persisted) != expected:
        raise DramaShotVideoCandidateStoreError(
            "candidate artifact persistence check failed"
        )
    return temp_identity


def _cleanup_unreferenced_artifact(
    workspace: str,
    candidate: ShotVideoCandidate,
    expected_identity: tuple[int, int],
) -> None:
    try:
        current = _read_manifest(workspace, episode_no=candidate.episode_no)
        if any(
            item.artifact.path == candidate.artifact.path
            for pool in [*current.shots, *current.retired_shots]
            for item in pool.candidates
        ):
            return
        root = paths.workspace_root(workspace)
        relative = (root / candidate.artifact.path).relative_to(root)
        directory_fd = _open_parent_dir(root, relative, create=False)
    except (OSError, RecursionError, TypeError, ValueError):
        return
    try:
        info = os.stat(relative.name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == expected_identity:
            os.unlink(relative.name, dir_fd=directory_fd)
    except OSError:
        pass
    finally:
        try:
            os.close(directory_fd)
        except OSError:
            pass


def _precommit_check(
    workspace: str,
    *,
    episode_no: int,
    source_plan_fingerprint: str,
    manifest: EpisodeShotVideoCandidateManifest,
) -> None:
    latest = load_fresh_episode_shot_video_plan(workspace, episode_no=episode_no)
    if latest.plan_fingerprint != source_plan_fingerprint:
        raise DramaShotVideoCandidateStoreError(
            "shot video plan changed during candidate operation"
        )
    _require_valid_selected_artifacts(workspace, manifest)


def _persist_manifest(
    workspace: str,
    manifest: EpisodeShotVideoCandidateManifest,
    *,
    target_token: tuple[Any, ...],
    source_plan_fingerprint: str,
) -> EpisodeShotVideoCandidateManifest:
    _write_manifest(
        workspace,
        manifest,
        expected_target_token=target_token,
        precommit_check=lambda: _precommit_check(
            workspace,
            episode_no=manifest.episode_no,
            source_plan_fingerprint=source_plan_fingerprint,
            manifest=manifest,
        ),
    )
    persisted = _read_manifest(workspace, episode_no=manifest.episode_no)
    if persisted.manifest_fingerprint != manifest.manifest_fingerprint:
        raise DramaShotVideoCandidateStoreError(
            "candidate manifest persistence check failed"
        )
    return persisted


def _create_manifest_impl(
    workspace: str,
    *,
    episode_no: int,
    replace_stale: bool,
    expected_manifest_fingerprint: str | None,
) -> EpisodeShotVideoCandidateManifest:
    if type(replace_stale) is not bool:
        raise ValueError("replace_stale must be bool")
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-shot-video-assets"):
        path = shot_video_candidate_manifest_path(workspace, episode_no=number)
        token = _target_token(root, path)
        try:
            current = _read_manifest(workspace, episode_no=number)
        except FileNotFoundError:
            current = None
        except _ManifestReadError as exc:
            raise DramaShotVideoCandidateStoreError(
                "invalid candidate manifest must be repaired explicitly"
            ) from exc
        _recover_owned_crash_residue(
            workspace,
            episode_no=number,
            manifest=current,
        )
        plan = load_fresh_episode_shot_video_plan(workspace, episode_no=number)
        if current is None:
            desired = build_episode_shot_video_candidate_manifest(plan)
        else:
            _require_valid_selected_artifacts(workspace, current)
            affected = shot_video_candidate_affected_ids(current, plan)
            source_matches = current.source_plan_fingerprint == plan.plan_fingerprint
            if source_matches and not affected:
                if _target_token(root, path) != token:
                    raise DramaShotVideoCandidateStoreError(
                        "candidate manifest changed concurrently; retry from inspection"
                    )
                persisted = _read_manifest(workspace, episode_no=number)
                if (
                    persisted.manifest_fingerprint != current.manifest_fingerprint
                    or _target_token(root, path) != token
                ):
                    raise DramaShotVideoCandidateStoreError(
                        "candidate manifest changed concurrently; retry from inspection"
                    )
                return persisted
            if not replace_stale:
                raise DramaShotVideoCandidateStoreError(
                    "stale candidate manifest requires explicit confirmation"
                )
            if expected_manifest_fingerprint != current.manifest_fingerprint:
                raise DramaShotVideoCandidateStoreError(
                    "candidate manifest changed; refresh before replacement"
                )
            desired = reconcile_shot_video_candidate_manifest(
                current,
                plan,
                expected_manifest_fingerprint=current.manifest_fingerprint,
            )
        return _persist_manifest(
            workspace,
            desired,
            target_token=token,
            source_plan_fingerprint=plan.plan_fingerprint,
        )


def create_episode_shot_video_candidate_manifest(
    workspace: str,
    *,
    episode_no: int = 1,
    replace_stale: bool = False,
    expected_manifest_fingerprint: str | None = None,
) -> EpisodeShotVideoCandidateManifest:
    try:
        return _create_manifest_impl(
            workspace,
            episode_no=episode_no,
            replace_stale=replace_stale,
            expected_manifest_fingerprint=expected_manifest_fingerprint,
        )
    except DramaShotVideoCandidateStoreError:
        raise
    except (OSError, RecursionError, TypeError, ValueError, WorkspaceLocked):
        raise DramaShotVideoCandidateStoreError(
            "candidate manifest operation was rejected"
        ) from None


def _append_candidate_impl(
    workspace: str,
    *,
    shot_id: str,
    mp4_bytes: bytes,
    is_placeholder: bool,
    episode_no: int,
    expected_manifest_fingerprint: str,
) -> tuple[EpisodeShotVideoCandidateManifest, ShotVideoCandidate]:
    identity = _candidate_payload_identity(mp4_bytes)
    if type(is_placeholder) is not bool:
        raise ValueError("is_placeholder must be bool")
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-shot-video-assets"):
        path = shot_video_candidate_manifest_path(workspace, episode_no=number)
        token = _target_token(root, path)
        try:
            current = _read_manifest(workspace, episode_no=number)
        except FileNotFoundError as exc:
            raise DramaShotVideoCandidateStoreError(
                "candidate manifest must be created first"
            ) from exc
        except _ManifestReadError as exc:
            raise DramaShotVideoCandidateStoreError("candidate manifest is invalid") from exc
        _recover_owned_crash_residue(
            workspace,
            episode_no=number,
            manifest=current,
        )
        plan = load_fresh_episode_shot_video_plan(workspace, episode_no=number)
        if (
            current.source_plan_fingerprint != plan.plan_fingerprint
            or shot_video_candidate_affected_ids(current, plan)
        ):
            raise DramaShotVideoCandidateStoreError(
                "candidate manifest must be reconciled first"
            )
        candidate = build_shot_video_candidate(
            plan,
            shot_id=shot_id,
            artifact_sha256=identity[0],
            artifact_size_bytes=identity[1],
            duration_milliseconds=identity[2],
            width=identity[3],
            height=identity[4],
            has_audio_track=identity[5],
            is_placeholder=is_placeholder,
        )
        existing = next(
            (
                item
                for pool in current.shots
                for item in pool.candidates
                if item.candidate_id == candidate.candidate_id
            ),
            None,
        )
        _require_valid_selected_artifacts(
            workspace,
            current,
            skip_artifact_path=(candidate.artifact.path if existing == candidate else None),
        )
        desired = append_shot_video_candidate(
            current,
            plan,
            candidate,
            expected_manifest_fingerprint=expected_manifest_fingerprint,
        )
        created_identity = _write_artifact_create_only(workspace, candidate, mp4_bytes)
        if desired.manifest_fingerprint == current.manifest_fingerprint:
            _validate_exact_candidate_artifact(workspace, candidate)
            if _target_token(root, path) != token:
                raise DramaShotVideoCandidateStoreError(
                    "candidate manifest changed concurrently; retry from inspection"
                )
            persisted = _read_manifest(workspace, episode_no=number)
            if persisted.manifest_fingerprint != current.manifest_fingerprint:
                raise DramaShotVideoCandidateStoreError(
                    "candidate manifest changed concurrently; retry from inspection"
                )
            return persisted, candidate
        try:
            persisted = _persist_manifest(
                workspace,
                desired,
                target_token=token,
                source_plan_fingerprint=plan.plan_fingerprint,
            )
        except BaseException:
            if created_identity is not None:
                _cleanup_unreferenced_artifact(workspace, candidate, created_identity)
            raise
        return persisted, candidate


def append_local_shot_video_candidate(
    workspace: str,
    *,
    shot_id: str,
    mp4_bytes: bytes,
    is_placeholder: bool = False,
    episode_no: int = 1,
    expected_manifest_fingerprint: str,
) -> tuple[EpisodeShotVideoCandidateManifest, ShotVideoCandidate]:
    try:
        if type(mp4_bytes) is not bytes:
            raise ValueError("mp4_bytes must be bytes")
        return _append_candidate_impl(
            workspace,
            shot_id=shot_id,
            mp4_bytes=mp4_bytes,
            is_placeholder=is_placeholder,
            episode_no=episode_no,
            expected_manifest_fingerprint=expected_manifest_fingerprint,
        )
    except DramaShotVideoCandidateStoreError:
        raise
    except (OSError, RecursionError, TypeError, ValueError, WorkspaceLocked):
        raise DramaShotVideoCandidateStoreError("candidate append was rejected") from None


def _repair_candidate_artifact_impl(
    workspace: str,
    *,
    candidate_id: str,
    mp4_bytes: bytes,
    episode_no: int,
    expected_manifest_fingerprint: str,
) -> ShotVideoCandidate:
    identity = _candidate_payload_identity(mp4_bytes)
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-shot-video-assets"):
        path = shot_video_candidate_manifest_path(workspace, episode_no=number)
        token = _target_token(root, path)
        try:
            current = _read_manifest(workspace, episode_no=number)
        except (FileNotFoundError, _ManifestReadError) as exc:
            raise DramaShotVideoCandidateStoreError("candidate manifest is unavailable") from exc
        _recover_owned_crash_residue(
            workspace,
            episode_no=number,
            manifest=current,
        )
        if expected_manifest_fingerprint != current.manifest_fingerprint:
            raise DramaShotVideoCandidateStoreError(
                "candidate manifest changed; refresh before artifact repair"
            )
        matches = [
            item
            for pool in [*current.shots, *current.retired_shots]
            for item in pool.candidates
            if item.candidate_id == candidate_id
        ]
        if len(matches) != 1:
            raise DramaShotVideoCandidateStoreError(
                "candidate artifact repair target is unknown"
            )
        candidate = matches[0]
        expected = (
            candidate.artifact.sha256,
            candidate.artifact.size_bytes,
            candidate.artifact.duration_milliseconds,
            candidate.artifact.width,
            candidate.artifact.height,
            candidate.artifact.has_audio_track,
        )
        if identity != expected:
            raise DramaShotVideoCandidateStoreError(
                "candidate artifact repair bytes do not match the manifest"
            )
        created_identity = _write_artifact_create_only(workspace, candidate, mp4_bytes)
        try:
            if _target_token(root, path) != token:
                raise DramaShotVideoCandidateStoreError(
                    "candidate manifest changed during artifact repair"
                )
            persisted = _read_manifest(workspace, episode_no=number)
            if persisted.manifest_fingerprint != expected_manifest_fingerprint:
                raise DramaShotVideoCandidateStoreError(
                    "candidate artifact repair target changed"
                )
            return candidate
        except BaseException:
            if created_identity is not None:
                _cleanup_unreferenced_artifact(workspace, candidate, created_identity)
            raise


def repair_referenced_shot_video_candidate_artifact(
    workspace: str,
    *,
    candidate_id: str,
    mp4_bytes: bytes,
    episode_no: int = 1,
    expected_manifest_fingerprint: str,
) -> ShotVideoCandidate:
    try:
        if type(candidate_id) is not str or not candidate_id:
            raise ValueError("candidate_id must be a non-empty string")
        if type(mp4_bytes) is not bytes:
            raise ValueError("mp4_bytes must be bytes")
        return _repair_candidate_artifact_impl(
            workspace,
            candidate_id=candidate_id,
            mp4_bytes=mp4_bytes,
            episode_no=episode_no,
            expected_manifest_fingerprint=expected_manifest_fingerprint,
        )
    except DramaShotVideoCandidateStoreError:
        raise
    except (OSError, RecursionError, TypeError, ValueError, WorkspaceLocked):
        raise DramaShotVideoCandidateStoreError(
            "candidate artifact repair was rejected"
        ) from None


def _select_candidate_impl(
    workspace: str,
    *,
    shot_id: str,
    selection: ShotVideoSelection | Mapping[str, Any] | None,
    expected_selection_revision: int,
    expected_current_selection: ShotVideoSelection | Mapping[str, Any] | None,
    episode_no: int,
    expected_manifest_fingerprint: str,
) -> EpisodeShotVideoCandidateManifest:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace), acquire_write_lock(source="drama-shot-video-assets"):
        path = shot_video_candidate_manifest_path(workspace, episode_no=number)
        token = _target_token(root, path)
        try:
            current = _read_manifest(workspace, episode_no=number)
        except (FileNotFoundError, _ManifestReadError) as exc:
            raise DramaShotVideoCandidateStoreError("candidate manifest is unavailable") from exc
        _recover_owned_crash_residue(
            workspace,
            episode_no=number,
            manifest=current,
        )
        _require_valid_selected_artifacts(workspace, current)
        plan = load_fresh_episode_shot_video_plan(workspace, episode_no=number)
        desired = select_shot_video_candidate(
            current,
            plan,
            shot_id=shot_id,
            selection=selection,
            expected_selection_revision=expected_selection_revision,
            expected_current_selection=expected_current_selection,
            expected_manifest_fingerprint=expected_manifest_fingerprint,
        )
        if desired.manifest_fingerprint == current.manifest_fingerprint:
            if _target_token(root, path) != token:
                raise DramaShotVideoCandidateStoreError(
                    "candidate manifest changed concurrently; retry from inspection"
                )
            persisted = _read_manifest(workspace, episode_no=number)
            if persisted.manifest_fingerprint != current.manifest_fingerprint:
                raise DramaShotVideoCandidateStoreError(
                    "candidate manifest changed concurrently; retry from inspection"
                )
            return persisted
        return _persist_manifest(
            workspace,
            desired,
            target_token=token,
            source_plan_fingerprint=plan.plan_fingerprint,
        )


def select_episode_shot_video_candidate(
    workspace: str,
    *,
    shot_id: str,
    selection: ShotVideoSelection | Mapping[str, Any] | None,
    expected_selection_revision: int,
    expected_current_selection: ShotVideoSelection | Mapping[str, Any] | None,
    episode_no: int = 1,
    expected_manifest_fingerprint: str,
) -> EpisodeShotVideoCandidateManifest:
    try:
        return _select_candidate_impl(
            workspace,
            shot_id=shot_id,
            selection=selection,
            expected_selection_revision=expected_selection_revision,
            expected_current_selection=expected_current_selection,
            episode_no=episode_no,
            expected_manifest_fingerprint=expected_manifest_fingerprint,
        )
    except DramaShotVideoCandidateStoreError:
        raise
    except (
        DramaShotVideoCandidateError,
        OSError,
        RecursionError,
        TypeError,
        ValueError,
        WorkspaceLocked,
    ):
        raise DramaShotVideoCandidateStoreError(
            "candidate selection was rejected"
        ) from None
