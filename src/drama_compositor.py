"""F1 argv-only FFmpeg compositor driven by one TimelineManifest."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import stat
from pathlib import Path
from typing import Any, Callable, Mapping

from . import paths
from .drama_media_qa import (
    DramaMediaQaError,
    _run_bounded_process,
    build_compose_qa_report,
    probe_media,
)
from .drama_schemas import (
    DramaComposePlan,
    DramaComposeQaReport,
    TimelineManifest,
    _canonical_sha256,
)
from .drama_store import _read_strict_workspace_bytes
from .drama_timeline import export_timeline_srt
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


class DramaComposeError(ValueError):
    pass


_OUTPUT_TOKEN = "{output_temp}"
MAX_COMPOSE_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_COMPOSE_SOURCE_SET_BYTES = 128 * 1024 * 1024


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.3f}"


def _safe_timeline(value: TimelineManifest | Mapping[str, Any]) -> TimelineManifest:
    return TimelineManifest(**(
        model_to_dict(value) if isinstance(value, TimelineManifest) else value
    ))


def _audio_filter(
    *, input_index: int, output_label: str, start_ms: int, duration_ms: int,
    volume: str = "1.0",
) -> str:
    filters = [
        f"[{input_index}:a:0]aresample=48000",
        "aformat=sample_fmts=fltp:channel_layouts=stereo",
        f"atrim=duration={_seconds(duration_ms)}",
        "asetpts=PTS-STARTPTS",
        f"volume={volume}",
    ]
    if duration_ms >= 100:
        filters.extend([
            "afade=t=in:st=0:d=0.010",
            f"afade=t=out:st={_seconds(duration_ms - 10)}:d=0.010",
        ])
    filters.extend([f"adelay={start_ms}:all=1", f"apad[{output_label}]"])
    return ",".join(filters)


def build_compose_plan(
    manifest: TimelineManifest | Mapping[str, Any],
) -> DramaComposePlan:
    """Pure deterministic projection; it never reads media or launches a process."""

    try:
        timeline = _safe_timeline(manifest)
        base = f"outputs/drama/compose/episode_{timeline.episode_no:03d}"
        stem = f"timeline_{timeline.timeline_fingerprint[:24]}"
        video_paths = [clip.artifact_path for clip in timeline.video_clips]
        audio_paths = [clip.artifact_path for clip in timeline.audio_clips]
        optional_paths = [clip.artifact_path for clip in timeline.optional_audio_clips]
        input_paths = [*video_paths, *audio_paths, *optional_paths]
        argv = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n"]
        for path in video_paths:
            argv.extend(["-i", path])
        for path in audio_paths:
            argv.extend(["-i", path])
        for clip in timeline.optional_audio_clips:
            if clip.loop:
                argv.extend(["-stream_loop", "-1"])
            argv.extend(["-i", clip.artifact_path])
        total_seconds = _seconds(timeline.total_duration_ms)
        argv.extend([
            "-f", "lavfi", "-t", total_seconds,
            "-i", "anullsrc=r=48000:cl=stereo",
        ])

        graph: list[str] = []
        video_labels: list[str] = []
        for index, clip in enumerate(timeline.video_clips):
            label = f"v{index}"
            video_labels.append(f"[{label}]")
            graph.append(
                f"[{index}:v:0]scale=1080:1920:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25,settb=1/25,"
                f"format=yuv420p,trim=duration={_seconds(clip.artifact_duration_ms)},"
                f"setpts=PTS-STARTPTS[{label}]"
            )
        graph.append(
            "".join(video_labels)
            + f"concat=n={len(video_labels)}:v=1:a=0[vout]"
        )

        audio_labels = ["[asil]"]
        lavfi_index = len(input_paths)
        graph.append(
            f"[{lavfi_index}:a:0]atrim=duration={total_seconds},"
            "asetpts=PTS-STARTPTS[asil]"
        )
        next_index = len(video_paths)
        for position, clip in enumerate(timeline.audio_clips):
            label = f"a{position}"
            graph.append(_audio_filter(
                input_index=next_index + position,
                output_label=label,
                start_ms=clip.start_ms,
                duration_ms=clip.artifact_duration_ms,
            ))
            audio_labels.append(f"[{label}]")
        next_index += len(timeline.audio_clips)
        for position, clip in enumerate(timeline.optional_audio_clips):
            label = f"o{position}"
            graph.append(_audio_filter(
                input_index=next_index + position,
                output_label=label,
                start_ms=clip.start_ms,
                duration_ms=clip.end_ms - clip.start_ms,
                volume="0.20" if clip.kind == "bgm" else "0.50",
            ))
            audio_labels.append(f"[{label}]")
        graph.append(
            "".join(audio_labels)
            + f"amix=inputs={len(audio_labels)}:duration=longest:"
            f"dropout_transition=0,atrim=duration={total_seconds}[aout]"
        )
        filter_graph = ";".join(graph)
        argv.extend([
            "-filter_complex", filter_graph,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-threads", "1", "-filter_threads", "1",
            "-filter_complex_threads", "1",
            "-pix_fmt", "yuv420p", "-r", "25", "-g", "50",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-t", total_seconds,
            "-fs", str(MAX_COMPOSE_OUTPUT_BYTES),
            "-metadata", f"comment=timeline_fingerprint={timeline.timeline_fingerprint}",
            "-video_track_timescale", "25000",
            "-movflags", "+faststart", "-f", "mp4", _OUTPUT_TOKEN,
        ])
        payload = {
            "schema_version": 1,
            "generator_version": "drama-compose-plan-v1",
            "profile": "vertical-1080x1920-25-v1",
            "timeline_fingerprint": timeline.timeline_fingerprint,
            "episode_no": timeline.episode_no,
            "width": 1080,
            "height": 1920,
            "fps_numerator": 25,
            "fps_denominator": 1,
            "video_time_base_numerator": 1,
            "video_time_base_denominator": 25000,
            "audio_sample_rate": 48000,
            "audio_layout": "stereo",
            "total_duration_ms": timeline.total_duration_ms,
            "required_shot_ids": [clip.shot_id for clip in timeline.video_clips],
            "input_paths": input_paths,
            "srt_path": f"{base}/{stem}.srt",
            "output_path": f"{base}/{stem}.mp4",
            "qa_path": f"{base}/{stem}.qa.json",
            "filter_graph": filter_graph,
            "ffmpeg_argv": argv,
        }
        payload["plan_fingerprint"] = _canonical_sha256(payload)
        return DramaComposePlan(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaComposeError("compose plan input was rejected") from None


def _ensure_safe_parent(root: Path, relative_path: str) -> Path:
    try:
        root_info = root.lstat()
    except OSError:
        raise DramaComposeError("compose workspace root is invalid") from None
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise DramaComposeError("compose workspace root is invalid")
    target = root / relative_path
    current = root
    for part in Path(relative_path).parts[:-1]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            current.mkdir(mode=0o700)
            info = current.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise DramaComposeError("compose output parent is invalid")
    try:
        info = target.lstat()
    except FileNotFoundError:
        return target
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise DramaComposeError("compose output target is invalid")
    return target


def _atomic_write(root: Path, relative_path: str, data: bytes, *, maximum: int) -> None:
    if not 0 <= len(data) <= maximum:
        raise DramaComposeError("compose output exceeds its limit")
    target = _ensure_safe_parent(root, relative_path)
    temporary = target.parent / f".{target.name}.tmp.{secrets.token_hex(16)}"
    fd: int | None = None
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = None
        _ensure_safe_parent(root, relative_path)
        os.replace(temporary, target)
        parent_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except DramaComposeError:
        raise
    except OSError:
        raise DramaComposeError("compose durable write failed") from None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            temporary.unlink()
        except OSError:
            pass


def _validate_sources(root: Path, timeline: TimelineManifest) -> dict[str, bytes]:
    verified: dict[str, bytes] = {}
    total_bytes = 0

    def remember(relative_path: str, data: bytes) -> None:
        nonlocal total_bytes
        previous = verified.get(relative_path)
        if previous is not None:
            if previous != data:
                raise DramaComposeError("compose source identity is ambiguous")
            return
        total_bytes += len(data)
        if total_bytes > MAX_COMPOSE_SOURCE_SET_BYTES:
            raise DramaComposeError("compose source set exceeds its limit")
        verified[relative_path] = data

    for clip in timeline.video_clips:
        try:
            data = _read_strict_workspace_bytes(
                root, root / clip.artifact_path, maximum=100 * 1024 * 1024
            )
        except (OSError, TypeError, ValueError):
            raise DramaComposeError("required video artifact is invalid") from None
        if hashlib.sha256(data).hexdigest() != clip.artifact_sha256:
            raise DramaComposeError("required video artifact is stale")
        remember(clip.artifact_path, data)
    for clip in timeline.audio_clips:
        try:
            data = _read_strict_workspace_bytes(
                root, root / clip.artifact_path, maximum=3_000_000
            )
        except (OSError, TypeError, ValueError):
            raise DramaComposeError("required audio artifact is invalid") from None
        if hashlib.sha256(data).hexdigest() != clip.artifact_sha256:
            raise DramaComposeError("required audio artifact is stale")
        remember(clip.artifact_path, data)
    for clip in timeline.optional_audio_clips:
        try:
            data = _read_strict_workspace_bytes(
                root, root / clip.artifact_path, maximum=10_000_000
            )
        except (OSError, TypeError, ValueError):
            raise DramaComposeError("optional audio artifact is invalid") from None
        if (
            len(data) != clip.artifact_size_bytes
            or hashlib.sha256(data).hexdigest() != clip.artifact_sha256
        ):
            raise DramaComposeError("optional audio artifact is stale")
        remember(clip.artifact_path, data)
    return verified


def _probe_staged_sources(
    root: Path,
    timeline: TimelineManifest,
    staging_paths: Mapping[str, str],
) -> None:
    for clip in timeline.video_clips:
        probe = probe_media(root, staging_paths[clip.artifact_path])
        if (
            probe.video_codec is None
            or probe.video_duration_ms is None
            or abs(probe.video_duration_ms - clip.artifact_duration_ms) > 20
        ):
            raise DramaComposeError("required video artifact duration is invalid")
    for clip in timeline.audio_clips:
        probe = probe_media(root, staging_paths[clip.artifact_path])
        if (
            probe.audio_codec is None
            or probe.audio_duration_ms is None
            or abs(probe.audio_duration_ms - clip.artifact_duration_ms) > 20
        ):
            raise DramaComposeError("required audio artifact duration is invalid")
    for clip in timeline.optional_audio_clips:
        probe = probe_media(root, staging_paths[clip.artifact_path])
        if (
            probe.audio_sample_rate != clip.sample_rate
            or probe.audio_duration_ms is None
            or abs(probe.audio_duration_ms - clip.artifact_duration_ms) > 20
        ):
            raise DramaComposeError("optional audio artifact duration is invalid")


def _cleanup_staging(root: Path, staging_paths: Mapping[str, str]) -> None:
    directories: set[Path] = set()
    for relative in set(staging_paths.values()):
        target = root / relative
        directories.add(target.parent)
        try:
            target.unlink()
        except OSError:
            pass
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass


def _run_ffmpeg(
    root: Path,
    timeline: TimelineManifest,
    plan: DramaComposePlan,
    verified_sources: Mapping[str, bytes],
    *,
    checkpoint: Callable[[], None] | None = None,
) -> tuple[str, bytes]:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise DramaComposeError("ffmpeg and ffprobe are required")
    expected_plan = build_compose_plan(_safe_timeline(timeline))
    supplied_plan = DramaComposePlan(**model_to_dict(plan))
    source_snapshot = dict(verified_sources)
    if (
        supplied_plan != expected_plan
        or set(source_snapshot) != set(expected_plan.input_paths)
        or any(type(value) is not bytes for value in source_snapshot.values())
    ):
        raise DramaComposeError("compose plan or source set is not authorized")
    plan = expected_plan
    verified_sources = source_snapshot
    final_target = _ensure_safe_parent(root, plan.output_path)
    temp_name = f".{final_target.stem}.tmp.{secrets.token_hex(16)}.mp4"
    temp_target = final_target.parent / temp_name
    temp_relative = temp_target.relative_to(root).as_posix()
    stage_token = secrets.token_hex(16)
    stage_base = (
        f"outputs/drama/compose/episode_{plan.episode_no:03d}/.stage_{stage_token}"
    )
    staging_paths: dict[str, str] = {}
    try:
        for index, original in enumerate(dict.fromkeys(plan.input_paths)):
            suffix = Path(original).suffix
            staged = f"{stage_base}/input_{index:03d}{suffix}"
            staging_paths[original] = staged
            _atomic_write(
                root, staged, verified_sources[original], maximum=100 * 1024 * 1024
            )
        argv = [
            temp_relative if item == _OUTPUT_TOKEN else staging_paths.get(item, item)
            for item in plan.ffmpeg_argv
        ]
        _probe_staged_sources(root, timeline, staging_paths)
        completed = _run_bounded_process(
            argv, cwd=root, timeout_seconds=180,
            stdout_limit=0, stderr_limit=65_536,
            checkpoint=checkpoint,
        )
        if completed.returncode != 0:
            raise DramaComposeError("ffmpeg composition failed")
        output_bytes = _read_strict_workspace_bytes(
            root, temp_target, maximum=MAX_COMPOSE_OUTPUT_BYTES
        )
        return temp_relative, output_bytes
    except DramaComposeError:
        try:
            temp_target.unlink()
        except OSError:
            pass
        raise
    except (DramaMediaQaError, OSError, TypeError, ValueError):
        try:
            temp_target.unlink()
        except OSError:
            pass
        raise DramaComposeError("ffmpeg composition failed") from None
    finally:
        _cleanup_staging(root, staging_paths)


def compose_workspace_timeline(
    workspace: str,
    manifest: TimelineManifest | Mapping[str, Any],
    *,
    precompose_check: Callable[[], None] | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> tuple[DramaComposePlan, DramaComposeQaReport]:
    """Production F1 entry. A result is returned only after MP4/SRT/QA pass."""

    try:
        timeline = _safe_timeline(manifest)
        plan = build_compose_plan(timeline)
        with use_workspace(workspace), acquire_write_lock(source="drama-compositor"):
            root = paths.workspace_root(workspace)
            if precompose_check is not None:
                precompose_check()
            verified_sources = _validate_sources(root, timeline)
            srt = export_timeline_srt(timeline)
            srt_bytes = srt.content.encode("utf-8")
            _atomic_write(root, plan.srt_path, srt_bytes, maximum=100_000)
            temp_relative, output_bytes = _run_ffmpeg(
                root,
                timeline,
                plan,
                verified_sources,
                checkpoint=checkpoint,
            )
            try:
                output_probe = probe_media(root, temp_relative)
                qa = build_compose_qa_report(
                    plan, output_probe,
                    output_bytes=output_bytes, srt_bytes=srt_bytes,
                )
                final_target = _ensure_safe_parent(root, plan.output_path)
                temp_target = root / temp_relative
                _ensure_safe_parent(root, temp_relative)
                os.replace(temp_target, final_target)
                parent_fd = os.open(
                    final_target.parent,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                )
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
                qa_bytes = (
                    json.dumps(model_to_dict(qa), ensure_ascii=False, indent=2, allow_nan=False)
                    + "\n"
                ).encode("utf-8")
                _atomic_write(root, plan.qa_path, qa_bytes, maximum=200_000)
                return plan, qa
            except (OSError, TypeError, ValueError, DramaMediaQaError):
                try:
                    (root / temp_relative).unlink()
                except OSError:
                    pass
                raise DramaComposeError("post-compose validation failed") from None
    except WorkspaceLocked:
        raise DramaComposeError("compose workspace is busy") from None
    except DramaComposeError:
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaComposeError("compose input was rejected") from None


def _require_workspace_compose_result_under_lock(
    root: Path,
    timeline: TimelineManifest,
    *,
    maximum_output_bytes: int = MAX_COMPOSE_OUTPUT_BYTES,
) -> tuple[DramaComposeQaReport, bytes, bytes]:
    """Verify F1 while the caller owns the workspace lock."""

    if (
        not isinstance(maximum_output_bytes, int)
        or isinstance(maximum_output_bytes, bool)
        or not 1 <= maximum_output_bytes <= MAX_COMPOSE_OUTPUT_BYTES
    ):
        raise DramaComposeError("compose verification limit is invalid")
    plan = build_compose_plan(timeline)
    qa_bytes = _read_strict_workspace_bytes(
        root, root / plan.qa_path, maximum=200_000
    )
    raw = json.loads(qa_bytes.decode("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("QA envelope must be an object")
    stored = DramaComposeQaReport(**raw)
    if stored.output_size_bytes > maximum_output_bytes:
        raise ValueError("compose output exceeds verifier limit")
    output_bytes = _read_strict_workspace_bytes(
        root, root / plan.output_path, maximum=maximum_output_bytes
    )
    srt_bytes = _read_strict_workspace_bytes(
        root, root / plan.srt_path, maximum=100_000
    )
    expected_srt_bytes = export_timeline_srt(timeline).content.encode("utf-8")
    if srt_bytes != expected_srt_bytes:
        raise ValueError("SRT is not the deterministic timeline export")
    if (
        stored.plan_fingerprint != plan.plan_fingerprint
        or stored.timeline_fingerprint != plan.timeline_fingerprint
        or stored.output_sha256 != hashlib.sha256(output_bytes).hexdigest()
        or stored.output_size_bytes != len(output_bytes)
        or stored.srt_sha256 != hashlib.sha256(srt_bytes).hexdigest()
    ):
        raise ValueError("compose artifacts do not match QA")
    probe = probe_media(root, plan.output_path)
    rebuilt = build_compose_qa_report(
        plan, probe, output_bytes=output_bytes, srt_bytes=srt_bytes
    )
    if rebuilt != stored:
        raise ValueError("compose QA is stale")
    return stored, output_bytes, srt_bytes


def require_workspace_compose_result(
    workspace: str,
    manifest: TimelineManifest | Mapping[str, Any],
    *,
    maximum_output_bytes: int = MAX_COMPOSE_OUTPUT_BYTES,
) -> DramaComposeQaReport:
    """Re-read MP4/SRT/QA and authorize only the exact timeline-derived result."""

    try:
        timeline = _safe_timeline(manifest)
        with use_workspace(workspace), acquire_write_lock(source="drama-compose-verify"):
            stored, _output_bytes, _srt_bytes = (
                _require_workspace_compose_result_under_lock(
                    paths.workspace_root(workspace),
                    timeline,
                    maximum_output_bytes=maximum_output_bytes,
                )
            )
            return stored
    except WorkspaceLocked:
        raise DramaComposeError("compose workspace is busy") from None
    except DramaComposeError:
        raise
    except (DramaMediaQaError, OSError, RecursionError, TypeError, ValueError):
        raise DramaComposeError("compose result was rejected") from None
