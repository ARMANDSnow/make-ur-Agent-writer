"""F2 deterministic ASS and generic editable-project export."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any, Mapping

from . import paths
from .drama_schemas import (
    AssArtifact,
    DramaEditExportResult,
    EditableTimelineMaterial,
    EditableTimelineProject,
    EditableTimelineSegment,
    EditableTimelineSubtitle,
    EditableTimelineTrack,
    TimelineManifest,
    _canonical_sha256,
)
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_VIDEO_SOURCE_BYTES = 100 * 1024 * 1024
MAX_SPOKEN_SOURCE_BYTES = 3 * 1024 * 1024
MAX_OPTIONAL_SOURCE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 1024 * 1024 * 1024
MAX_ASS_BYTES = 100_000
MAX_EDIT_PROJECT_BYTES = 2_000_000
MAX_COMPLETION_BYTES = 20_000


class DramaEditExportError(ValueError):
    pass


def _safe_timeline(value: TimelineManifest | Mapping[str, Any]) -> TimelineManifest:
    return TimelineManifest(
        **(model_to_dict(value) if isinstance(value, TimelineManifest) else value)
    )


def _ass_time(centiseconds: int) -> str:
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centis:02d}"


def _ass_text(value: str) -> str:
    return (
        value.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )


def _ass_centisecond_range(
    start_ms: int,
    end_ms: int,
    *,
    previous_end_centiseconds: int,
) -> tuple[int, int]:
    start = max(start_ms // 10, previous_end_centiseconds)
    end = max(start + 1, (end_ms + 9) // 10)
    return start, end


def export_timeline_ass(
    manifest: TimelineManifest | Mapping[str, Any],
) -> AssArtifact:
    """Build a byte-stable ASS v4+ sidecar from canonical subtitle cues."""

    try:
        timeline = _safe_timeline(manifest)
        lines = [
            "[Script Info]",
            "; Script generated from Dragon Raja AI Continuer TimelineManifest",
            f"; TimelineFingerprint: {timeline.timeline_fingerprint}",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            (
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
                "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                "Alignment, MarginL, MarginR, MarginV, Encoding"
            ),
            (
                "Style: zh-primary-v1,Noto Sans CJK SC,64,&H00FFFFFF,&H000000FF,"
                "&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,80,80,160,1"
            ),
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
        previous_end_centiseconds = 0
        timeline_end_centiseconds = (timeline.total_duration_ms + 9) // 10
        for cue in timeline.subtitle_cues:
            start_centiseconds, end_centiseconds = _ass_centisecond_range(
                cue.start_ms,
                cue.end_ms,
                previous_end_centiseconds=previous_end_centiseconds,
            )
            cue_end_centiseconds = (cue.end_ms + 9) // 10
            if (
                end_centiseconds > cue_end_centiseconds
                or end_centiseconds > timeline_end_centiseconds
            ):
                raise ValueError("subtitle density exceeds ASS time resolution")
            previous_end_centiseconds = end_centiseconds
            lines.append(
                "Dialogue: "
                f"0,{_ass_time(start_centiseconds)},{_ass_time(end_centiseconds)},"
                f"zh-primary-v1,,0,0,0,,{_ass_text(cue.text)}"
            )
        content = "\n".join(lines) + "\n"
        return AssArtifact(
            timeline_fingerprint=timeline.timeline_fingerprint,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            cue_count=len(timeline.subtitle_cues),
            content=content,
        )
    except (RecursionError, TypeError, ValueError):
        raise DramaEditExportError("ASS export was rejected") from None


def require_timeline_ass_artifact(
    manifest: TimelineManifest | Mapping[str, Any],
    artifact: AssArtifact | Mapping[str, Any],
) -> AssArtifact:
    try:
        expected = export_timeline_ass(manifest)
        supplied = AssArtifact(
            **(model_to_dict(artifact) if isinstance(artifact, AssArtifact) else artifact)
        )
        if supplied != expected:
            raise ValueError("ASS artifact does not match timeline")
        return expected
    except (DramaEditExportError, RecursionError, TypeError, ValueError):
        raise DramaEditExportError("ASS artifact was rejected") from None


def _material(
    *,
    kind: str,
    source_id: str,
    artifact_path: str,
    artifact_sha256: str,
    source_duration_ms: int,
) -> EditableTimelineMaterial:
    payload = {
        "kind": kind,
        "source_id": source_id,
        "artifact_path": artifact_path,
        "artifact_sha256": artifact_sha256,
        "source_duration_ms": source_duration_ms,
    }
    fingerprint = _canonical_sha256(payload)
    return EditableTimelineMaterial(
        material_id=f"mat_{fingerprint[:24]}",
        material_fingerprint=fingerprint,
        **payload,
    )


def _segment(
    *,
    kind: str,
    source_id: str,
    material_id: str | None,
    timeline_start_ms: int,
    timeline_end_ms: int,
    source_in_ms: int,
    source_out_ms: int,
    loop: bool,
    gain_permille: int,
    fade_in_ms: int,
    fade_out_ms: int,
) -> EditableTimelineSegment:
    payload = {
        "kind": kind,
        "source_id": source_id,
        "material_id": material_id,
        "timeline_start_ms": timeline_start_ms,
        "timeline_end_ms": timeline_end_ms,
        "source_in_ms": source_in_ms,
        "source_out_ms": source_out_ms,
        "loop": loop,
        "gain_permille": gain_permille,
        "fade_in_ms": fade_in_ms,
        "fade_out_ms": fade_out_ms,
    }
    fingerprint = _canonical_sha256(payload)
    return EditableTimelineSegment(
        segment_id=f"editseg_{fingerprint[:24]}",
        segment_fingerprint=fingerprint,
        **payload,
    )


def _track(kind: str, segments: list[EditableTimelineSegment]) -> EditableTimelineTrack:
    ordered = sorted(
        segments,
        key=lambda item: (
            item.timeline_start_ms,
            item.timeline_end_ms,
            item.source_id,
            item.segment_id,
        ),
    )
    payload = {
        "track_id": f"{kind}-v1",
        "kind": kind,
        "segments": [model_to_dict(item) for item in ordered],
    }
    return EditableTimelineTrack(
        track_fingerprint=_canonical_sha256(payload),
        **payload,
    )


def build_editable_timeline_project(
    manifest: TimelineManifest | Mapping[str, Any],
) -> EditableTimelineProject:
    """Project one canonical timeline into a vendor-neutral editable schema."""

    try:
        timeline = _safe_timeline(manifest)
        materials: list[EditableTimelineMaterial] = []
        tracks: dict[str, list[EditableTimelineSegment]] = {
            "video": [],
            "dialogue": [],
            "narration": [],
            "bgm": [],
            "sfx": [],
            "silence": [],
        }

        for clip in timeline.video_clips:
            material = _material(
                kind="video",
                source_id=clip.candidate_id,
                artifact_path=clip.artifact_path,
                artifact_sha256=clip.artifact_sha256,
                source_duration_ms=clip.artifact_duration_ms,
            )
            materials.append(material)
            tracks["video"].append(
                _segment(
                    kind="video",
                    source_id=clip.shot_id,
                    material_id=material.material_id,
                    timeline_start_ms=clip.start_ms,
                    timeline_end_ms=clip.end_ms,
                    source_in_ms=0,
                    source_out_ms=clip.artifact_duration_ms,
                    loop=False,
                    gain_permille=1000,
                    fade_in_ms=0,
                    fade_out_ms=0,
                )
            )

        for clip in timeline.audio_clips:
            material = _material(
                kind=clip.kind,
                source_id=clip.utterance_id,
                artifact_path=clip.artifact_path,
                artifact_sha256=clip.artifact_sha256,
                source_duration_ms=clip.artifact_duration_ms,
            )
            materials.append(material)
            tracks[clip.kind].append(
                _segment(
                    kind=clip.kind,
                    source_id=clip.utterance_id,
                    material_id=material.material_id,
                    timeline_start_ms=clip.start_ms,
                    timeline_end_ms=clip.end_ms,
                    source_in_ms=0,
                    source_out_ms=clip.artifact_duration_ms,
                    loop=False,
                    gain_permille=1000,
                    fade_in_ms=10 if clip.artifact_duration_ms >= 100 else 0,
                    fade_out_ms=10 if clip.artifact_duration_ms >= 100 else 0,
                )
            )

        for clip in timeline.optional_audio_clips:
            material = _material(
                kind=clip.kind,
                source_id=clip.clip_id,
                artifact_path=clip.artifact_path,
                artifact_sha256=clip.artifact_sha256,
                source_duration_ms=clip.artifact_duration_ms,
            )
            materials.append(material)
            tracks[clip.kind].append(
                _segment(
                    kind=clip.kind,
                    source_id=clip.clip_id,
                    material_id=material.material_id,
                    timeline_start_ms=clip.start_ms,
                    timeline_end_ms=clip.end_ms,
                    source_in_ms=0,
                    source_out_ms=(
                        clip.artifact_duration_ms
                        if clip.loop
                        else clip.end_ms - clip.start_ms
                    ),
                    loop=clip.loop,
                    gain_permille=200 if clip.kind == "bgm" else 500,
                    fade_in_ms=10 if clip.end_ms - clip.start_ms >= 100 else 0,
                    fade_out_ms=10 if clip.end_ms - clip.start_ms >= 100 else 0,
                )
            )

        for clip in timeline.silence_clips:
            tracks["silence"].append(
                _segment(
                    kind="silence",
                    source_id=clip.shot_id,
                    material_id=None,
                    timeline_start_ms=clip.start_ms,
                    timeline_end_ms=clip.end_ms,
                    source_in_ms=0,
                    source_out_ms=0,
                    loop=False,
                    gain_permille=0,
                    fade_in_ms=0,
                    fade_out_ms=0,
                )
            )

        ordered_kinds = ["video", "dialogue", "narration", "bgm", "sfx", "silence"]
        subtitles = [
            EditableTimelineSubtitle(
                cue_id=cue.cue_id,
                utterance_id=cue.utterance_id,
                source_text_sha256=cue.source_text_sha256,
                cue_fingerprint=cue.cue_fingerprint,
                text=cue.text,
                revision=cue.revision,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
            )
            for cue in timeline.subtitle_cues
        ]
        payload = {
            "schema_version": 1,
            "exporter_version": "drama-edit-export-v1",
            "profile": "vertical-1080x1920-25-v1",
            "timeline_fingerprint": timeline.timeline_fingerprint,
            "season_no": timeline.season_no,
            "episode_no": timeline.episode_no,
            "width": 1080,
            "height": 1920,
            "fps_numerator": 25,
            "fps_denominator": 1,
            "audio_sample_rate": 48000,
            "audio_layout": "stereo",
            "audio_codec_profile": "aac-128k-v1",
            "total_duration_ms": timeline.total_duration_ms,
            "materials": [model_to_dict(item) for item in materials],
            "tracks": [
                model_to_dict(_track(kind, tracks[kind])) for kind in ordered_kinds
            ],
            "subtitles": [model_to_dict(item) for item in subtitles],
        }
        payload["project_fingerprint"] = _canonical_sha256(payload)
        return EditableTimelineProject(**payload)
    except (KeyError, RecursionError, TypeError, ValueError):
        raise DramaEditExportError("editable project export was rejected") from None


def require_editable_timeline_project(
    manifest: TimelineManifest | Mapping[str, Any],
    project: EditableTimelineProject | Mapping[str, Any],
) -> EditableTimelineProject:
    try:
        expected = build_editable_timeline_project(manifest)
        supplied = EditableTimelineProject(
            **(
                model_to_dict(project)
                if isinstance(project, EditableTimelineProject)
                else project
            )
        )
        if supplied != expected:
            raise ValueError("editable project does not match timeline")
        return expected
    except (DramaEditExportError, RecursionError, TypeError, ValueError):
        raise DramaEditExportError("editable project was rejected") from None


def _project_bytes(project: EditableTimelineProject) -> bytes:
    return (
        json.dumps(
            model_to_dict(project),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _export_paths(timeline: TimelineManifest) -> tuple[str, str, str]:
    base = f"outputs/drama/edit/episode_{timeline.episode_no:03d}"
    stem = f"timeline_{timeline.timeline_fingerprint[:24]}"
    return (
        f"{base}/{stem}.ass",
        f"{base}/{stem}.edit.json",
        f"{base}/{stem}.complete.json",
    )


def _source_limit(kind: str) -> int:
    if kind == "video":
        return MAX_VIDEO_SOURCE_BYTES
    if kind in {"dialogue", "narration"}:
        return MAX_SPOKEN_SOURCE_BYTES
    return MAX_OPTIONAL_SOURCE_BYTES


def _open_workspace_file(
    root: Path,
    relative_path: str,
) -> tuple[int, int, str]:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    if nofollow is None or directory is None or nonblock is None:
        raise DramaEditExportError("strict no-follow file access is unavailable")
    parts = tuple(Path(relative_path).parts)
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise DramaEditExportError("editable source path is invalid")
    directory_fd: int | None = None
    try:
        directory_fd = os.open(str(root), os.O_RDONLY | directory | nofollow)
        for part in parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY | directory | nofollow,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            parts[-1],
            os.O_RDONLY | nofollow | nonblock,
            dir_fd=directory_fd,
        )
        parent_fd = directory_fd
        directory_fd = None
        return file_fd, parent_fd, parts[-1]
    except DramaEditExportError:
        raise
    except OSError:
        raise DramaEditExportError("editable source artifact is unavailable") from None
    finally:
        if directory_fd is not None:
            try:
                os.close(directory_fd)
            except OSError:
                pass


def _stream_source_identity(
    root: Path,
    *,
    relative_path: str,
    maximum: int,
) -> tuple[int, int, int, int, str]:
    file_fd: int | None = None
    parent_fd: int | None = None
    try:
        file_fd, parent_fd, leaf_name = _open_workspace_file(root, relative_path)
        before = os.fstat(file_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size <= 0
            or before.st_size > maximum
        ):
            raise DramaEditExportError("editable source artifact is invalid")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(file_fd, 65_536)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise DramaEditExportError("editable source artifact exceeds its limit")
            digest.update(chunk)
        after = os.fstat(file_fd)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if total != before.st_size or identity_before != identity_after:
            raise DramaEditExportError("editable source artifact changed during hashing")
        current = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(current.st_mode)
            or (
                current.st_dev,
                current.st_ino,
                current.st_size,
                current.st_mtime_ns,
            )
            != identity_after
        ):
            raise DramaEditExportError(
                "editable source namespace changed during hashing"
            )
        return (*identity_after, digest.hexdigest())
    except DramaEditExportError:
        raise
    except OSError:
        raise DramaEditExportError("editable source artifact could not be hashed") from None
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except OSError:
                pass


def _validate_source_materials(
    workspace: str,
    project: EditableTimelineProject,
    *,
    expected: dict[str, tuple[int, int, int, int, str]] | None = None,
) -> dict[str, tuple[int, int, int, int, str]]:
    root = paths.workspace_root(workspace)
    identities: dict[str, tuple[int, int, int, int, str]] = {}
    total_bytes = 0
    for material in project.materials:
        previous = identities.get(material.artifact_path)
        if previous is not None:
            if previous[-1] != material.artifact_sha256:
                raise DramaEditExportError(
                    "editable source path has conflicting identities"
                )
            continue
        remaining = MAX_TOTAL_SOURCE_BYTES - total_bytes
        if remaining <= 0:
            raise DramaEditExportError("editable source set exceeds its total limit")
        identity = _stream_source_identity(
            root,
            relative_path=material.artifact_path,
            maximum=min(_source_limit(material.kind), remaining),
        )
        if identity[-1] != material.artifact_sha256:
            raise DramaEditExportError("editable source artifact changed")
        identities[material.artifact_path] = identity
        total_bytes += identity[2]
    if expected is not None and identities != expected:
        raise DramaEditExportError("editable source artifact changed during export")
    return identities


def _open_output_directory(
    root: Path,
    relative_directory: str,
    *,
    create: bool,
) -> int:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise DramaEditExportError("strict no-follow output access is unavailable")
    parts = tuple(Path(relative_directory).parts)
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise DramaEditExportError("editable output directory is invalid")
    directory_fd: int | None = None
    try:
        directory_fd = os.open(str(root), os.O_RDONLY | directory | nofollow)
        for part in parts:
            try:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=directory_fd,
                )
            except FileNotFoundError:
                if not create:
                    raise DramaEditExportError(
                        "editable output directory is unavailable"
                    )
                os.mkdir(part, 0o700, dir_fd=directory_fd)
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=directory_fd,
                )
            os.close(directory_fd)
            directory_fd = next_fd
        result = directory_fd
        directory_fd = None
        return result
    except DramaEditExportError:
        raise
    except OSError:
        raise DramaEditExportError("editable output directory is unavailable") from None
    finally:
        if directory_fd is not None:
            try:
                os.close(directory_fd)
            except OSError:
                pass


def _directory_identity(directory_fd: int) -> tuple[int, int]:
    info = os.fstat(directory_fd)
    if not stat.S_ISDIR(info.st_mode):
        raise DramaEditExportError("editable output directory is invalid")
    return info.st_dev, info.st_ino


def _require_current_output_directory(
    root: Path,
    relative_directory: str,
    *,
    expected: tuple[int, int],
) -> None:
    current_fd: int | None = None
    try:
        current_fd = _open_output_directory(
            root,
            relative_directory,
            create=False,
        )
        if _directory_identity(current_fd) != expected:
            raise DramaEditExportError(
                "editable output directory changed during export"
            )
    finally:
        if current_fd is not None:
            try:
                os.close(current_fd)
            except OSError:
                pass


def _target_token_at(directory_fd: int, name: str, *, maximum: int) -> tuple[Any, ...]:
    file_fd: int | None = None
    try:
        file_fd = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
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
            or info.st_size > maximum
        ):
            return ("invalid",)
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(file_fd, 65_536)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                return ("invalid",)
            digest.update(chunk)
        after = os.fstat(file_fd)
        if (
            total != info.st_size
            or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            return ("invalid",)
        return ("file", total, digest.hexdigest())
    except OSError:
        return ("invalid",)
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass


def _atomic_write_at(
    directory_fd: int,
    name: str,
    data: bytes,
    *,
    maximum: int,
) -> None:
    if (
        not name
        or "/" in name
        or "\\" in name
        or name in {".", ".."}
        or not 0 < len(data) <= maximum
    ):
        raise DramaEditExportError("editable output payload is invalid")
    expected = _target_token_at(directory_fd, name, maximum=maximum)
    if expected == ("invalid",):
        raise DramaEditExportError("editable output target is invalid")
    temp_name = f".{name}.tmp.{secrets.token_hex(16)}"
    temp_fd: int | None = None
    try:
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        view = memoryview(data)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError("short editable output write")
            view = view[written:]
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = None
        if _target_token_at(directory_fd, name, maximum=maximum) != expected:
            raise DramaEditExportError("editable output changed concurrently")
        os.replace(
            temp_name,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    except DramaEditExportError:
        raise
    except OSError:
        raise DramaEditExportError("editable output could not be committed") from None
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        try:
            os.unlink(temp_name, dir_fd=directory_fd)
        except OSError:
            pass


def _invalidate_completion_at(
    directory_fd: int,
    name: str,
) -> None:
    token = _target_token_at(
        directory_fd,
        name,
        maximum=MAX_COMPLETION_BYTES,
    )
    if token == ("missing",):
        return
    if token == ("invalid",):
        raise DramaEditExportError("editable completion target is invalid")
    try:
        os.unlink(name, dir_fd=directory_fd)
        os.fsync(directory_fd)
    except OSError:
        raise DramaEditExportError("editable completion could not be invalidated") from None


def _read_output_at(
    directory_fd: int,
    name: str,
    *,
    maximum: int,
) -> bytes:
    file_fd: int | None = None
    try:
        file_fd = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory_fd,
        )
        info = os.fstat(file_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size <= 0
            or info.st_size > maximum
        ):
            raise DramaEditExportError("editable output artifact is invalid")
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(file_fd, min(65_536, remaining))
            if not chunk:
                raise DramaEditExportError("editable output artifact is truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(file_fd)
        if (
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise DramaEditExportError("editable output artifact changed during read")
        return b"".join(chunks)
    except DramaEditExportError:
        raise
    except OSError:
        raise DramaEditExportError("editable output artifact is unavailable") from None
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass


def _result(
    timeline: TimelineManifest,
    *,
    ass_path: str,
    ass_sha256: str,
    project_path: str,
    project_sha256: str,
    completion_path: str,
) -> DramaEditExportResult:
    payload = {
        "schema_version": 1,
        "timeline_fingerprint": timeline.timeline_fingerprint,
        "episode_no": timeline.episode_no,
        "ass_path": ass_path,
        "ass_sha256": ass_sha256,
        "project_path": project_path,
        "project_sha256": project_sha256,
        "completion_path": completion_path,
    }
    payload["export_fingerprint"] = _canonical_sha256(payload)
    return DramaEditExportResult(**payload)


def export_workspace_editable_sidecars(
    workspace: str,
    manifest: TimelineManifest | Mapping[str, Any],
) -> DramaEditExportResult:
    """Validate exact sources and commit the pair with a durable completion marker."""

    try:
        timeline = _safe_timeline(manifest)
        ass = export_timeline_ass(timeline)
        project = build_editable_timeline_project(timeline)
        ass_bytes = ass.content.encode("utf-8")
        project_bytes = _project_bytes(project)
        ass_path, project_path, completion_path = _export_paths(timeline)
        result = _result(
            timeline,
            ass_path=ass_path,
            ass_sha256=hashlib.sha256(ass_bytes).hexdigest(),
            project_path=project_path,
            project_sha256=hashlib.sha256(project_bytes).hexdigest(),
            completion_path=completion_path,
        )
        completion_bytes = (
            json.dumps(
                model_to_dict(result),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        with use_workspace(workspace), acquire_write_lock(source="drama-edit-export"):
            identities = _validate_source_materials(workspace, project)
            output_fd = _open_output_directory(
                paths.workspace_root(workspace),
                str(Path(ass_path).parent),
                create=True,
            )
            output_identity = _directory_identity(output_fd)
            try:
                _invalidate_completion_at(
                    output_fd,
                    Path(completion_path).name,
                )
                _atomic_write_at(
                    output_fd,
                    Path(ass_path).name,
                    ass_bytes,
                    maximum=MAX_ASS_BYTES,
                )
                _atomic_write_at(
                    output_fd,
                    Path(project_path).name,
                    project_bytes,
                    maximum=MAX_EDIT_PROJECT_BYTES,
                )
                _validate_source_materials(
                    workspace,
                    project,
                    expected=identities,
                )
                _atomic_write_at(
                    output_fd,
                    Path(completion_path).name,
                    completion_bytes,
                    maximum=MAX_COMPLETION_BYTES,
                )
                try:
                    _validate_source_materials(
                        workspace,
                        project,
                        expected=identities,
                    )
                    _require_current_output_directory(
                        paths.workspace_root(workspace),
                        str(Path(ass_path).parent),
                        expected=output_identity,
                    )
                except DramaEditExportError:
                    try:
                        os.unlink(Path(completion_path).name, dir_fd=output_fd)
                        os.fsync(output_fd)
                    except OSError:
                        pass
                    raise
            finally:
                os.close(output_fd)
        return result
    except WorkspaceLocked:
        raise DramaEditExportError("editable workspace is busy") from None
    except DramaEditExportError:
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaEditExportError("editable sidecar export was rejected") from None


def require_workspace_editable_sidecars(
    workspace: str,
    manifest: TimelineManifest | Mapping[str, Any],
) -> DramaEditExportResult:
    """Authorize persisted sidecars only by exact regeneration from the timeline."""

    try:
        timeline = _safe_timeline(manifest)
        ass = export_timeline_ass(timeline)
        project = build_editable_timeline_project(timeline)
        expected_ass = ass.content.encode("utf-8")
        expected_project = _project_bytes(project)
        ass_path, project_path, completion_path = _export_paths(timeline)
        expected_result = _result(
            timeline,
            ass_path=ass_path,
            ass_sha256=hashlib.sha256(expected_ass).hexdigest(),
            project_path=project_path,
            project_sha256=hashlib.sha256(expected_project).hexdigest(),
            completion_path=completion_path,
        )
        expected_completion = (
            json.dumps(
                model_to_dict(expected_result),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        with use_workspace(workspace), acquire_write_lock(source="drama-edit-verify"):
            identities = _validate_source_materials(workspace, project)
            output_fd = _open_output_directory(
                paths.workspace_root(workspace),
                str(Path(ass_path).parent),
                create=False,
            )
            output_identity = _directory_identity(output_fd)
            try:
                stored_ass = _read_output_at(
                    output_fd,
                    Path(ass_path).name,
                    maximum=MAX_ASS_BYTES,
                )
                stored_project = _read_output_at(
                    output_fd,
                    Path(project_path).name,
                    maximum=MAX_EDIT_PROJECT_BYTES,
                )
                stored_completion = _read_output_at(
                    output_fd,
                    Path(completion_path).name,
                    maximum=MAX_COMPLETION_BYTES,
                )
                _validate_source_materials(
                    workspace,
                    project,
                    expected=identities,
                )
                _require_current_output_directory(
                    paths.workspace_root(workspace),
                    str(Path(ass_path).parent),
                    expected=output_identity,
                )
            finally:
                os.close(output_fd)
        if (
            stored_ass != expected_ass
            or stored_project != expected_project
            or stored_completion != expected_completion
        ):
            raise DramaEditExportError("editable sidecar bytes do not match timeline")
        return expected_result
    except WorkspaceLocked:
        raise DramaEditExportError("editable workspace is busy") from None
    except DramaEditExportError:
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaEditExportError("editable sidecar verification was rejected") from None
