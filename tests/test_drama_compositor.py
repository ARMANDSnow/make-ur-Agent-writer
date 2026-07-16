"""iter123 F1 compose plan, runtime failure boundaries, and real local E2E."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from scripts.run_local_drama_compose import build_synthetic_timeline
from src import drama_compositor, paths
from src.drama_media_qa import (
    DramaMediaQaError,
    _run_bounded_process,
    probe_media,
)
from src.drama_schemas import (
    DramaComposePlan,
    DramaComposeQaReport,
    TimelineManifest,
    _canonical_sha256,
)
from src.schemas import model_to_dict


ROOT = Path(__file__).resolve().parents[1]


class DramaCompositorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="drama_compose_test_")
        self.root = Path(self.temp.name)
        self.old_workspace_dir = paths.WORKSPACE_DIR
        paths.WORKSPACE_DIR = self.root.parent
        self.timeline = build_synthetic_timeline(self.root)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self.old_workspace_dir
        self.temp.cleanup()

    def test_compose_plan_is_stable_explicit_argv_and_no_absolute_paths(self) -> None:
        first = drama_compositor.build_compose_plan(self.timeline)
        second = drama_compositor.build_compose_plan(self.timeline)
        self.assertEqual(first, second)
        self.assertEqual(first.width, 1080)
        self.assertEqual(first.height, 1920)
        self.assertEqual((first.fps_numerator, first.fps_denominator), (25, 1))
        self.assertEqual(first.ffmpeg_argv[0], "ffmpeg")
        self.assertEqual(first.ffmpeg_argv[-1], "{output_temp}")
        self.assertIn("concat=n=2:v=1:a=0", first.filter_graph)
        self.assertIn("amix=inputs=3", first.filter_graph)
        self.assertNotIn("shell=True", " ".join(first.ffmpeg_argv))
        self.assertFalse(any(Path(arg).is_absolute() for arg in first.ffmpeg_argv))

    def test_real_ffmpeg_outputs_vertical_mp4_audio_srt_and_bound_qa(self) -> None:
        plan, qa = drama_compositor.compose_workspace_timeline(
            self.root.name, self.timeline
        )
        output = self.root / plan.output_path
        srt = self.root / plan.srt_path
        qa_path = self.root / plan.qa_path
        self.assertTrue(output.is_file())
        self.assertTrue(srt.is_file())
        self.assertTrue(qa_path.is_file())
        probe = probe_media(self.root, plan.output_path)
        self.assertEqual((probe.width, probe.height), (1080, 1920))
        self.assertEqual(str(probe.fps), "25")
        self.assertEqual(probe.audio_codec, "aac")
        self.assertEqual(probe.timeline_fingerprint, self.timeline.timeline_fingerprint)
        self.assertEqual(qa.timeline_fingerprint, self.timeline.timeline_fingerprint)
        self.assertEqual(qa.required_shot_ids, qa.covered_shot_ids)
        stored = DramaComposeQaReport(**json.loads(qa_path.read_text("utf-8")))
        self.assertEqual(stored, qa)
        self.assertEqual(
            drama_compositor.require_workspace_compose_result(
                self.root.name, self.timeline
            ),
            qa,
        )
        self.assertIn("合成本地测试字幕 1", srt.read_text("utf-8"))
        srt.write_text("tampered", encoding="utf-8")
        forged_qa = json.loads(qa_path.read_text("utf-8"))
        forged_qa["srt_sha256"] = hashlib.sha256(b"tampered").hexdigest()
        forged_qa["qa_fingerprint"] = _canonical_sha256(
            {key: value for key, value in forged_qa.items() if key != "qa_fingerprint"}
        )
        qa_path.write_text(json.dumps(forged_qa), encoding="utf-8")
        with self.assertRaisesRegex(drama_compositor.DramaComposeError, "rejected"):
            drama_compositor.require_workspace_compose_result(
                self.root.name, self.timeline
            )

    def test_optional_bgm_is_mixed_from_the_same_timeline(self) -> None:
        wav = (self.root / self.timeline.audio_clips[0].artifact_path).read_bytes()
        relative = "outputs/drama/optional_audio/local_bgm.wav"
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(wav)
        optional_payload = {
            "kind": "bgm",
            "artifact_path": relative,
            "artifact_sha256": hashlib.sha256(wav).hexdigest(),
            "artifact_size_bytes": len(wav),
            "artifact_duration_ms": 400,
            "sample_rate": 16000,
            "start_ms": 0,
            "end_ms": 2000,
            "loop": True,
        }
        optional_fingerprint = _canonical_sha256(optional_payload)
        raw = model_to_dict(self.timeline)
        raw["bgm_policy"] = "optional"
        raw["warnings"] = []
        raw["optional_audio_clips"] = [{
            "clip_id": f"opt_{optional_fingerprint[:24]}",
            "clip_fingerprint": optional_fingerprint,
            **optional_payload,
        }]
        raw["timeline_fingerprint"] = _canonical_sha256(
            {key: value for key, value in raw.items() if key != "timeline_fingerprint"}
        )
        timeline = TimelineManifest(**raw)
        plan, qa = drama_compositor.compose_workspace_timeline(self.root.name, timeline)
        self.assertIn("volume=0.20", plan.filter_graph)
        self.assertEqual(
            drama_compositor.require_workspace_compose_result(self.root.name, timeline),
            qa,
        )

    def test_verified_bytes_are_staged_before_noncooperative_source_replacement(self) -> None:
        original_validate = drama_compositor._validate_sources

        def replace_after_validation(root, timeline):
            verified = original_validate(root, timeline)
            (root / timeline.video_clips[0].artifact_path).write_bytes(b"replaced")
            return verified

        with patch(
            "src.drama_compositor._validate_sources",
            side_effect=replace_after_validation,
        ):
            plan, qa = drama_compositor.compose_workspace_timeline(
                self.root.name, self.timeline
            )
        self.assertEqual(qa.required_shot_ids, qa.covered_shot_ids)
        self.assertTrue((self.root / plan.output_path).is_file())

    def test_one_frame_short_required_video_cannot_be_masked_by_audio_duration(self) -> None:
        relative = self.timeline.video_clips[0].artifact_path
        completed = _run_bounded_process(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=540x960:r=25:d=0.96",
                "-an", "-c:v", "libx264", "-threads", "1",
                "-pix_fmt", "yuv420p", relative,
            ],
            cwd=self.root,
            timeout_seconds=60,
            stdout_limit=0,
            stderr_limit=16_384,
        )
        self.assertEqual(completed.returncode, 0)
        raw = model_to_dict(self.timeline)
        raw["video_clips"][0]["artifact_sha256"] = hashlib.sha256(
            (self.root / relative).read_bytes()
        ).hexdigest()
        raw["timeline_fingerprint"] = _canonical_sha256(
            {key: value for key, value in raw.items() if key != "timeline_fingerprint"}
        )
        short_timeline = TimelineManifest(**raw)
        with self.assertRaisesRegex(drama_compositor.DramaComposeError, "duration"):
            drama_compositor.compose_workspace_timeline(
                self.root.name, short_timeline
            )

    def test_missing_tampered_symlink_and_ffmpeg_failure_never_complete(self) -> None:
        audio = self.root / self.timeline.audio_clips[0].artifact_path
        audio.write_bytes(b"tampered")
        with self.assertRaisesRegex(drama_compositor.DramaComposeError, "audio"):
            drama_compositor.compose_workspace_timeline(self.root.name, self.timeline)
        plan = drama_compositor.build_compose_plan(self.timeline)
        self.assertFalse((self.root / plan.output_path).exists())
        self.assertFalse((self.root / plan.qa_path).exists())

        self.temp.cleanup()
        self.temp = tempfile.TemporaryDirectory(prefix="drama_compose_test_")
        self.root = Path(self.temp.name)
        paths.WORKSPACE_DIR = self.root.parent
        self.timeline = build_synthetic_timeline(self.root)
        source = self.root / self.timeline.video_clips[0].artifact_path
        replacement = source.with_suffix(".owned")
        source.rename(replacement)
        source.symlink_to(replacement.name)
        with self.assertRaisesRegex(drama_compositor.DramaComposeError, "video"):
            drama_compositor.compose_workspace_timeline(self.root.name, self.timeline)

    def test_missing_binary_and_nonzero_ffmpeg_are_fail_closed(self) -> None:
        plan = drama_compositor.build_compose_plan(self.timeline)
        with patch("src.drama_compositor.shutil.which", return_value=None):
            with self.assertRaisesRegex(drama_compositor.DramaComposeError, "required"):
                drama_compositor.compose_workspace_timeline(self.root.name, self.timeline)
        self.assertFalse((self.root / plan.output_path).exists())
        with patch(
            "src.drama_compositor._run_bounded_process",
            return_value=subprocess.CompletedProcess(["ffmpeg"], 9, b"", b"failed"),
        ):
            with self.assertRaisesRegex(drama_compositor.DramaComposeError, "failed"):
                drama_compositor._run_ffmpeg(
                    self.root,
                    self.timeline,
                    plan,
                    drama_compositor._validate_sources(self.root, self.timeline),
                )
        self.assertFalse((self.root / plan.output_path).exists())
        self.assertFalse((self.root / plan.qa_path).exists())

    def test_plan_schema_rejects_bool_absolute_path_and_action_injection(self) -> None:
        plan = drama_compositor.build_compose_plan(self.timeline)
        for mutate in ("bool", "absolute", "action"):
            raw = model_to_dict(plan)
            if mutate == "bool":
                raw["total_duration_ms"] = True
            elif mutate == "absolute":
                raw["input_paths"][0] = "/tmp/escape.mp4"
            else:
                raw["ffmpeg_argv"].insert(-1, "-filter_complex_script")
            raw["plan_fingerprint"] = _canonical_sha256(
                {key: value for key, value in raw.items() if key != "plan_fingerprint"}
            )
            with self.subTest(mutate=mutate):
                with self.assertRaises(ValidationError):
                    DramaComposePlan(**raw)
        raw = model_to_dict(plan)
        raw["ffmpeg_argv"].insert(-1, "extra-output.mp4")
        raw["plan_fingerprint"] = _canonical_sha256(
            {key: value for key, value in raw.items() if key != "plan_fingerprint"}
        )
        forged = DramaComposePlan(**raw)
        verified = drama_compositor._validate_sources(self.root, self.timeline)
        with self.assertRaisesRegex(drama_compositor.DramaComposeError, "authorized"):
            drama_compositor._run_ffmpeg(
                self.root, self.timeline, forged, verified
            )

    def test_ffprobe_parser_rejects_nan_bool_zero_denominator_and_extra_tracks(self) -> None:
        base = {
            "programs": [],
            "stream_groups": [],
            "streams": [{
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "pix_fmt": "yuv420p",
                "r_frame_rate": "25/1",
                "sample_aspect_ratio": "1:1",
                "time_base": "1/25000",
                "duration": "2.0",
            }],
            "format": {"format_name": "mov,mp4", "duration": "2.0", "tags": {}},
        }
        cases = []
        nan = json.loads(json.dumps(base))
        nan["format"]["duration"] = "NaN"
        cases.append(nan)
        boolean = json.loads(json.dumps(base))
        boolean["streams"][0]["width"] = True
        cases.append(boolean)
        zero = json.loads(json.dumps(base))
        zero["streams"][0]["r_frame_rate"] = "25/0"
        cases.append(zero)
        extra = json.loads(json.dumps(base))
        extra["streams"].append({"codec_type": "subtitle", "codec_name": "mov_text"})
        cases.append(extra)
        for raw in cases:
            completed = subprocess.CompletedProcess(
                ["ffprobe"], 0, json.dumps(raw).encode("utf-8"), b""
            )
            with self.subTest(raw=raw):
                with patch(
                    "src.drama_media_qa._run_bounded_process",
                    return_value=completed,
                ):
                    with self.assertRaises(DramaMediaQaError):
                        probe_media(self.root, "outputs/synthetic.mp4")
        with self.assertRaises(DramaMediaQaError):
            probe_media(self.root, "/tmp/escape.mp4")
        for stream in ("stdout", "stderr"):
            code = f"import sys; sys.{stream}.write('x' * 10000)"
            with self.subTest(stream=stream):
                with self.assertRaisesRegex(DramaMediaQaError, "exceeded"):
                    _run_bounded_process(
                        [sys.executable, "-c", code],
                        cwd=self.root,
                        timeout_seconds=10,
                        stdout_limit=100 if stream == "stdout" else 0,
                        stderr_limit=100 if stream == "stderr" else 0,
                    )

    def test_cli_runner_emits_relative_local_e2e_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="drama_compose_cli_") as directory:
            completed = subprocess.run(
                [
                    str(ROOT / ".venv/bin/python3"),
                    str(ROOT / "scripts/run_local_drama_compose.py"),
                    "--workspace-root", directory,
                ],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
                check=False,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            evidence = json.loads(completed.stdout)
            self.assertEqual(evidence["acceptance_level"], "local-e2e")
            self.assertFalse(evidence["provider_validated"])
            for key in ("timeline_path", "mp4_path", "srt_path", "qa_path"):
                self.assertFalse(Path(evidence[key]).is_absolute())
                self.assertTrue((Path(directory) / evidence[key]).is_file())
        with tempfile.TemporaryDirectory(prefix="drama_compose_target_") as target:
            link = Path(target).parent / f"{Path(target).name}_link"
            link.symlink_to(target, target_is_directory=True)
            try:
                rejected = subprocess.run(
                    [
                        str(ROOT / ".venv/bin/python3"),
                        str(ROOT / "scripts/run_local_drama_compose.py"),
                        "--workspace-root", str(link),
                    ],
                    cwd=ROOT,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                    check=False,
                    text=True,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(list(Path(target).iterdir()), [])
            finally:
                link.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix="drama_compose_broken_") as parent:
            missing = Path(parent) / "missing-target"
            broken = Path(parent) / "broken-link"
            broken.symlink_to(missing, target_is_directory=True)
            rejected = subprocess.run(
                [
                    str(ROOT / ".venv/bin/python3"),
                    str(ROOT / "scripts/run_local_drama_compose.py"),
                    "--workspace-root", str(broken),
                ],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
                text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
