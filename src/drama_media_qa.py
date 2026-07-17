"""Bounded ffprobe parsing and post-compose F1 media QA."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import subprocess
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

from .drama_schemas import DramaComposePlan, DramaComposeQaReport, _canonical_sha256


class DramaMediaQaError(ValueError):
    pass


def _run_bounded_process(
    argv: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    stdout_limit: int,
    stderr_limit: int,
    checkpoint: Callable[[], None] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run without a shell and kill as soon as either captured stream exceeds cap."""

    if (
        not isinstance(argv, list)
        or not 1 <= len(argv) <= 1200
        or any(not isinstance(item, str) or not item for item in argv)
        or not 1 <= timeout_seconds <= 180
        or not 0 <= stdout_limit <= 1_000_000
        or not 0 <= stderr_limit <= 1_000_000
    ):
        raise DramaMediaQaError("bounded process request is invalid")
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if stdout_limit else subprocess.DEVNULL,
            stderr=subprocess.PIPE if stderr_limit else subprocess.DEVNULL,
        )
    except OSError:
        raise DramaMediaQaError("media process launch failed") from None
    selector = selectors.DefaultSelector()
    buffers: dict[str, bytearray] = {
        "stdout": bytearray(),
        "stderr": bytearray(),
    }
    limits = {"stdout": stdout_limit, "stderr": stderr_limit}
    for name in ("stdout", "stderr"):
        stream = getattr(process, name)
        if stream is not None:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
    deadline = time.monotonic() + timeout_seconds
    try:
        while selector.get_map():
            if checkpoint is not None:
                checkpoint()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DramaMediaQaError("media process timed out")
            events = selector.select(min(remaining, 0.25))
            if not events and process.poll() is not None:
                events = [
                    (key, selectors.EVENT_READ)
                    for key in list(selector.get_map().values())
                ]
            for key, _mask in events:
                try:
                    chunk = os.read(key.fileobj.fileno(), 8192)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                bucket = buffers[key.data]
                bucket.extend(chunk)
                if len(bucket) > limits[key.data]:
                    raise DramaMediaQaError("media process output exceeded its limit")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DramaMediaQaError("media process timed out")
        returncode = process.wait(timeout=remaining)
        return subprocess.CompletedProcess(
            argv, returncode, bytes(buffers["stdout"]), bytes(buffers["stderr"])
        )
    except (DramaMediaQaError, subprocess.SubprocessError) as exc:
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.SubprocessError:
            pass
        if isinstance(exc, DramaMediaQaError):
            raise
        raise DramaMediaQaError("media process failed") from None
    except BaseException:
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.SubprocessError:
            pass
        raise
    finally:
        selector.close()
        for name in ("stdout", "stderr"):
            stream = getattr(process, name)
            if stream is not None and not stream.closed:
                stream.close()


@dataclass(frozen=True)
class MediaProbe:
    format_names: tuple[str, ...]
    duration_ms: int
    video_duration_ms: int | None
    audio_duration_ms: int | None
    video_codec: str | None
    width: int | None
    height: int | None
    pixel_format: str | None
    fps: Fraction | None
    sample_aspect_ratio: str | None
    video_time_base: Fraction | None
    audio_codec: str | None
    audio_sample_rate: int | None
    audio_channels: int | None
    audio_layout: str | None
    audio_time_base: Fraction | None
    timeline_fingerprint: str | None


def _strict_positive_int(value: Any, label: str, *, maximum: int) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise DramaMediaQaError(f"media probe {label} is invalid")
    parsed = int(value)
    if not 0 < parsed <= maximum:
        raise DramaMediaQaError(f"media probe {label} is invalid")
    return parsed


def _duration_ms(value: Any) -> int:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise DramaMediaQaError("media probe duration is invalid") from None
    if not parsed.is_finite() or parsed <= 0 or parsed > Decimal(3600):
        raise DramaMediaQaError("media probe duration is invalid")
    return int((parsed * 1000).to_integral_value(rounding=ROUND_HALF_UP))


def _fraction(value: Any) -> Fraction:
    if not isinstance(value, str) or len(value) > 32 or "/" not in value:
        raise DramaMediaQaError("media probe frame rate is invalid")
    left, right = value.split("/", 1)
    numerator = _strict_positive_int(left, "frame rate", maximum=1_000_000)
    denominator = _strict_positive_int(right, "frame rate", maximum=1_000_000)
    return Fraction(numerator, denominator)


def probe_media(root: Path, relative_path: str, *, timeout_seconds: int = 20) -> MediaProbe:
    if (
        not isinstance(root, Path)
        or not root.is_absolute()
        or not isinstance(relative_path, str)
        or Path(relative_path).is_absolute()
        or relative_path.startswith("-")
        or ":" in relative_path
        or "\\" in relative_path
        or any(part in {"", ".", ".."} for part in relative_path.split("/"))
        or any(ord(char) < 32 for char in relative_path)
        or not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or not 1 <= timeout_seconds <= 60
    ):
        raise DramaMediaQaError("media probe request is invalid")
    argv = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=format_name,duration:format_tags=comment:"
        "stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate,"
        "sample_aspect_ratio,time_base,sample_rate,channels,channel_layout,duration",
        "-of", "json", relative_path,
    ]
    try:
        completed = _run_bounded_process(
            argv, cwd=root, timeout_seconds=timeout_seconds,
            stdout_limit=65_536, stderr_limit=16_384,
        )
    except DramaMediaQaError:
        raise DramaMediaQaError("ffprobe execution failed") from None
    if completed.returncode != 0:
        raise DramaMediaQaError("ffprobe rejected media")
    try:
        raw = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DramaMediaQaError("ffprobe returned invalid JSON") from None
    if (
        not isinstance(raw, dict)
        or set(raw).difference({"streams", "format", "programs", "stream_groups"})
        or raw.get("programs", []) != []
        or raw.get("stream_groups", []) != []
    ):
        raise DramaMediaQaError("ffprobe response shape is invalid")
    streams = raw.get("streams")
    media_format = raw.get("format")
    if (
        not isinstance(streams, list)
        or len(streams) > 8
        or not isinstance(media_format, dict)
    ):
        raise DramaMediaQaError("ffprobe response shape is invalid")
    video_rows = [
        row for row in streams
        if isinstance(row, dict) and row.get("codec_type") == "video"
    ]
    audio_rows = [
        row for row in streams
        if isinstance(row, dict) and row.get("codec_type") == "audio"
    ]
    if (
        any(
            not isinstance(row, dict) or row.get("codec_type") not in {"video", "audio"}
            for row in streams
        )
        or len(video_rows) > 1
        or len(audio_rows) > 1
    ):
        raise DramaMediaQaError("media must have at most one video and audio track")
    duration_value = media_format.get("duration")
    if duration_value in {None, "N/A"}:
        candidates = [
            _duration_ms(row.get("duration"))
            for row in [*video_rows, *audio_rows]
            if row.get("duration") not in {None, "N/A"}
        ]
        if not candidates:
            raise DramaMediaQaError("media duration is missing")
        parsed_duration_ms = max(candidates)
    else:
        parsed_duration_ms = _duration_ms(duration_value)
    video = video_rows[0] if video_rows else None
    audio = audio_rows[0] if audio_rows else None
    format_names = media_format.get("format_name")
    if not isinstance(format_names, str) or len(format_names) > 128:
        raise DramaMediaQaError("media format is invalid")
    tags = media_format.get("tags", {})
    if tags is None:
        tags = {}
    if not isinstance(tags, dict):
        raise DramaMediaQaError("media tags are invalid")
    comment = tags.get("comment")
    timeline_fingerprint = None
    if isinstance(comment, str) and comment.startswith("timeline_fingerprint="):
        candidate = comment.removeprefix("timeline_fingerprint=")
        if len(candidate) == 64 and all(char in "0123456789abcdef" for char in candidate):
            timeline_fingerprint = candidate
    return MediaProbe(
        format_names=tuple(part for part in format_names.split(",") if part),
        duration_ms=parsed_duration_ms,
        video_duration_ms=(
            _duration_ms(video.get("duration"))
            if video and video.get("duration") not in {None, "N/A"}
            else None
        ),
        audio_duration_ms=(
            _duration_ms(audio.get("duration"))
            if audio and audio.get("duration") not in {None, "N/A"}
            else None
        ),
        video_codec=video.get("codec_name") if video else None,
        width=(
            _strict_positive_int(str(video.get("width")), "width", maximum=8192)
            if video else None
        ),
        height=(
            _strict_positive_int(str(video.get("height")), "height", maximum=8192)
            if video else None
        ),
        pixel_format=video.get("pix_fmt") if video else None,
        fps=_fraction(video.get("r_frame_rate")) if video else None,
        sample_aspect_ratio=video.get("sample_aspect_ratio") if video else None,
        video_time_base=_fraction(video.get("time_base")) if video else None,
        audio_codec=audio.get("codec_name") if audio else None,
        audio_sample_rate=(
            _strict_positive_int(audio.get("sample_rate"), "sample rate", maximum=192000)
            if audio else None
        ),
        audio_channels=(
            _strict_positive_int(str(audio.get("channels")), "channels", maximum=16)
            if audio else None
        ),
        audio_layout=audio.get("channel_layout") if audio else None,
        audio_time_base=_fraction(audio.get("time_base")) if audio else None,
        timeline_fingerprint=timeline_fingerprint,
    )


def build_compose_qa_report(
    plan: DramaComposePlan,
    probe: MediaProbe,
    *,
    output_bytes: bytes,
    srt_bytes: bytes,
) -> DramaComposeQaReport:
    try:
        # A CFR encoder cannot end between frames.  ``-t`` therefore rounds a
        # non-frame-aligned TimelineManifest duration up to the next 25 fps
        # frame (for example 402 ms -> 440 ms).  Bind QA to that deterministic
        # frame-grid result instead of requiring the encoded video stream to
        # reproduce an impossible sub-frame duration.
        frame_denominator = 1000 * plan.fps_denominator
        expected_video_frames = (
            plan.total_duration_ms * plan.fps_numerator
            + frame_denominator
            - 1
        ) // frame_denominator
        expected_video_duration_ms = (
            expected_video_frames * frame_denominator
            + plan.fps_numerator // 2
        ) // plan.fps_numerator
        if (
            "mp4" not in probe.format_names
            or probe.video_codec != "h264"
            or probe.audio_codec != "aac"
            or probe.width != plan.width
            or probe.height != plan.height
            or probe.pixel_format != "yuv420p"
            or probe.fps != Fraction(plan.fps_numerator, plan.fps_denominator)
            or probe.sample_aspect_ratio != "1:1"
            or probe.video_time_base != Fraction(
                plan.video_time_base_numerator, plan.video_time_base_denominator
            )
            or probe.audio_sample_rate != plan.audio_sample_rate
            or probe.audio_channels != 2
            or probe.audio_layout != "stereo"
            or probe.audio_time_base != Fraction(1, plan.audio_sample_rate)
            or probe.timeline_fingerprint != plan.timeline_fingerprint
            or abs(probe.duration_ms - plan.total_duration_ms) > 160
            or probe.video_duration_ms is None
            or abs(probe.video_duration_ms - expected_video_duration_ms) > 1
        ):
            raise ValueError("post-compose probe did not match profile")
        payload = {
            "schema_version": 1,
            "generator_version": "drama-compose-qa-v1",
            "status": "passed",
            "acceptance_level": "local-e2e",
            "provider_validated": False,
            "profile": plan.profile,
            "plan_fingerprint": plan.plan_fingerprint,
            "timeline_fingerprint": plan.timeline_fingerprint,
            "episode_no": plan.episode_no,
            "output_path": plan.output_path,
            "output_sha256": hashlib.sha256(output_bytes).hexdigest(),
            "output_size_bytes": len(output_bytes),
            "srt_path": plan.srt_path,
            "srt_sha256": hashlib.sha256(srt_bytes).hexdigest(),
            "required_shot_ids": list(plan.required_shot_ids),
            "covered_shot_ids": list(plan.required_shot_ids),
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
            "width": probe.width,
            "height": probe.height,
            "fps_numerator": probe.fps.numerator,
            "fps_denominator": probe.fps.denominator,
            "sample_aspect_ratio": probe.sample_aspect_ratio,
            "video_time_base": (
                f"{probe.video_time_base.numerator}/{probe.video_time_base.denominator}"
            ),
            "pixel_format": probe.pixel_format,
            "audio_sample_rate": probe.audio_sample_rate,
            "audio_channels": probe.audio_channels,
            "audio_layout": probe.audio_layout,
            "audio_time_base": (
                f"{probe.audio_time_base.numerator}/{probe.audio_time_base.denominator}"
            ),
            "expected_duration_ms": plan.total_duration_ms,
            "duration_ms": probe.duration_ms,
            "metadata_timeline_fingerprint": probe.timeline_fingerprint,
        }
        payload["qa_fingerprint"] = _canonical_sha256(payload)
        return DramaComposeQaReport(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaQaError("post-compose QA failed") from None
