#!/usr/bin/env python3
"""Create synthetic D4/E2 fixtures and a real local F1 MP4/SRT/QA set."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import drama_audio, drama_compositor, paths  # noqa: E402
from src.drama_media_qa import _run_bounded_process  # noqa: E402
from src.drama_schemas import TimelineManifest, _canonical_sha256  # noqa: E402
from src.schemas import model_to_dict  # noqa: E402


def _identity(prefix: str, label: str) -> str:
    return f"{prefix}_{hashlib.sha256(label.encode('utf-8')).hexdigest()[:24]}"


def _run_fixture_ffmpeg(root: Path, relative: str, color: str) -> None:
    target = root / relative
    drama_compositor._ensure_safe_parent(root, relative)
    completed = _run_bounded_process(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s=540x960:r=25:d=1",
            "-an", "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", relative,
        ],
        cwd=root, timeout_seconds=60, stdout_limit=0, stderr_limit=16_384,
    )
    if completed.returncode != 0:
        raise RuntimeError("synthetic video fixture generation failed")


def build_synthetic_timeline(root: Path) -> TimelineManifest:
    shot_ids = [_identity("shot", "compose-red"), _identity("shot", "compose-blue")]
    candidate_ids = [_identity("svc", "compose-red"), _identity("svc", "compose-blue")]
    video_paths = [
        f"outputs/episodes/episode_01.shot_videos/{shot_ids[index]}/{candidate_ids[index]}.mp4"
        for index in range(2)
    ]
    for relative, color in zip(video_paths, ("#a32222", "#2255a3")):
        _run_fixture_ffmpeg(root, relative, color)

    utterance_ids = [_identity("utt", "compose-line-1"), _identity("utt", "compose-line-2")]
    segment_ids = [
        _identity("segment", "compose-line-1"),
        _identity("segment", "compose-line-2"),
    ]
    audio_paths = [
        f"outputs/drama/audio/episode_001/{utterance_id}.wav"
        for utterance_id in utterance_ids
    ]
    wav = drama_audio.build_mock_wav_fixture(
        duration_milliseconds=400, sample_rate=16000
    )
    for relative in audio_paths:
        drama_compositor._atomic_write(root, relative, wav, maximum=3_000_000)

    video_clips = []
    for index, relative in enumerate(video_paths):
        data = (root / relative).read_bytes()
        video_clips.append({
            "shot_id": shot_ids[index],
            "candidate_id": candidate_ids[index],
            "artifact_path": relative,
            "artifact_sha256": hashlib.sha256(data).hexdigest(),
            "artifact_duration_ms": 1000,
            "start_ms": index * 1000,
            "end_ms": (index + 1) * 1000,
        })
    audio_clips = []
    cues = []
    for index, relative in enumerate(audio_paths):
        start = index * 1000
        end = start + 400
        audio_clips.append({
            "utterance_id": utterance_ids[index],
            "segment_id": segment_ids[index],
            "shot_id": shot_ids[index],
            "kind": "dialogue" if index == 0 else "narration",
            "artifact_path": relative,
            "artifact_sha256": hashlib.sha256(wav).hexdigest(),
            "artifact_duration_ms": 400,
            "start_ms": start,
            "end_ms": end,
        })
        cue_payload = {
            "utterance_id": utterance_ids[index],
            "source_text_sha256": hashlib.sha256(
                f"synthetic line {index + 1}".encode("utf-8")
            ).hexdigest(),
            "text": f"合成本地测试字幕 {index + 1}",
            "revision": 0,
            "start_ms": start,
            "end_ms": end,
        }
        fingerprint = _canonical_sha256(cue_payload)
        cues.append({
            "cue_id": f"cue_{fingerprint[:24]}",
            "cue_fingerprint": fingerprint,
            **cue_payload,
        })
    payload = {
        "schema_version": 1,
        "generator_version": "timeline-manifest-v1",
        "season_no": 1,
        "episode_no": 1,
        "d4_report_fingerprint": hashlib.sha256(b"synthetic-d4").hexdigest(),
        "selected_bindings_fingerprint": hashlib.sha256(
            b"synthetic-selected-bindings"
        ).hexdigest(),
        "audio_manifest_fingerprint": hashlib.sha256(
            b"synthetic-audio-manifest"
        ).hexdigest(),
        "total_duration_ms": 2000,
        "video_clips": video_clips,
        "audio_clips": audio_clips,
        "silence_clips": [
            {"shot_id": shot_ids[0], "start_ms": 400, "end_ms": 1000},
            {"shot_id": shot_ids[1], "start_ms": 1400, "end_ms": 2000},
        ],
        "optional_audio_clips": [],
        "subtitle_cues": cues,
        "bgm_policy": "disabled",
        "warnings": [],
    }
    payload["timeline_fingerprint"] = _canonical_sha256(payload)
    return TimelineManifest(**payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True)
    args = parser.parse_args(argv)
    requested_root = Path(args.workspace_root)
    if (
        not requested_root.is_absolute()
        or requested_root.name.startswith(".")
        or ".." in requested_root.name
    ):
        parser.error("workspace root must be an absolute named directory")
    try:
        requested_info = requested_root.lstat()
    except FileNotFoundError:
        requested_info = None
    if requested_info is not None:
        if stat.S_ISLNK(requested_info.st_mode) or not stat.S_ISDIR(requested_info.st_mode):
            parser.error("workspace root must not be a symlink or special file")
    root = requested_root.resolve(strict=False)
    marker = root / ".dragon-raja-local-compose"
    marker_owned = False
    try:
        marker_info = marker.lstat()
        marker_owned = stat.S_ISREG(marker_info.st_mode) and not stat.S_ISLNK(
            marker_info.st_mode
        )
    except FileNotFoundError:
        pass
    if root.exists() and not marker_owned and any(root.iterdir()):
        parser.error("existing non-empty workspace root is not owned by this runner")
    root.mkdir(parents=True, exist_ok=True)
    drama_compositor._atomic_write(
        root, marker.name, b"dragon-raja-local-compose\n", maximum=128
    )
    paths.WORKSPACE_DIR = root.parent
    timeline = build_synthetic_timeline(root)
    plan, qa = drama_compositor.compose_workspace_timeline(root.name, timeline)
    timeline_path = (
        f"outputs/drama/compose/episode_001/"
        f"timeline_{timeline.timeline_fingerprint[:24]}.timeline.json"
    )
    drama_compositor._atomic_write(
        root,
        timeline_path,
        (json.dumps(model_to_dict(timeline), ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        maximum=500_000,
    )
    print(json.dumps({
        "status": "passed",
        "acceptance_level": "local-e2e",
        "provider_validated": False,
        "timeline_fingerprint": timeline.timeline_fingerprint,
        "plan_fingerprint": plan.plan_fingerprint,
        "timeline_path": timeline_path,
        "mp4_path": plan.output_path,
        "srt_path": plan.srt_path,
        "qa_path": plan.qa_path,
        "output_sha256": qa.output_sha256,
        "profile": plan.profile,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
