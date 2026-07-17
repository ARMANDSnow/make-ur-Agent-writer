"""iter125 F2 ASS and generic editable-project export."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from scripts.run_local_drama_compose import build_synthetic_timeline
from src import drama_audio, drama_edit_export, drama_timeline, paths
from src.drama_schemas import (
    AssArtifact,
    EditableTimelineMaterial,
    EditableTimelineProject,
    TimelineManifest,
    _canonical_sha256,
)
from src.schemas import model_to_dict
from src.workspace_lock import WorkspaceLocked


class DramaEditExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="drama_edit_export_")
        self.root = Path(self.temp.name)
        self.old_workspace_dir = paths.WORKSPACE_DIR
        paths.WORKSPACE_DIR = self.root.parent
        self.timeline = build_synthetic_timeline(self.root)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self.old_workspace_dir
        self.temp.cleanup()

    def _with_optional_audio(self, *, kind: str, ranges: list[tuple[int, int]]):
        raw = model_to_dict(self.timeline)
        wav = (self.root / self.timeline.audio_clips[0].artifact_path).read_bytes()
        duration = drama_audio.probe_mock_wav_fixture(wav)["duration_milliseconds"]
        optional = []
        for index, (start, end) in enumerate(ranges):
            relative = f"outputs/drama/optional_audio/{kind}_{index}.wav"
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(wav)
            payload = {
                "kind": kind,
                "artifact_path": relative,
                "artifact_sha256": hashlib.sha256(wav).hexdigest(),
                "artifact_size_bytes": len(wav),
                "artifact_duration_ms": duration,
                "sample_rate": 16000,
                "start_ms": start,
                "end_ms": end,
                "loop": end - start > duration,
            }
            fingerprint = _canonical_sha256(payload)
            optional.append(
                {
                    "clip_id": f"opt_{fingerprint[:24]}",
                    "clip_fingerprint": fingerprint,
                    **payload,
                }
            )
        optional.sort(
            key=lambda item: (item["start_ms"], item["end_ms"], item["clip_id"])
        )
        raw["optional_audio_clips"] = optional
        raw["warnings"] = (
            ["optional_bgm_missing"]
            if raw["bgm_policy"] == "optional" and kind != "bgm"
            else []
        )
        raw["timeline_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in raw.items()
                if key != "timeline_fingerprint"
            }
        )
        return TimelineManifest(**raw)

    def _dense_unrepresentable_timeline(self) -> TimelineManifest:
        raw = model_to_dict(self.timeline)
        self.assertEqual(len(raw["video_clips"]), 2)
        self.assertEqual(len(raw["audio_clips"]), 2)
        raw["total_duration_ms"] = 1000
        first_shot = raw["video_clips"][0]["shot_id"]
        for index, clip in enumerate(raw["video_clips"]):
            clip["start_ms"] = index * 500
            clip["end_ms"] = (index + 1) * 500
            clip["artifact_duration_ms"] = 500
        for index, clip in enumerate(raw["audio_clips"]):
            clip["shot_id"] = first_shot
            clip["start_ms"] = index
            clip["end_ms"] = index + 1
            clip["artifact_duration_ms"] = 1
        raw["silence_clips"] = [
            {"shot_id": first_shot, "start_ms": 2, "end_ms": 500},
            {
                "shot_id": raw["video_clips"][1]["shot_id"],
                "start_ms": 500,
                "end_ms": 1000,
            },
        ]
        for index, cue in enumerate(raw["subtitle_cues"]):
            cue["start_ms"] = index
            cue["end_ms"] = index + 1
            cue["cue_fingerprint"] = _canonical_sha256(
                {
                    key: value
                    for key, value in cue.items()
                    if key not in {"cue_id", "cue_fingerprint"}
                }
            )
            cue["cue_id"] = f"cue_{cue['cue_fingerprint'][:24]}"
        raw["timeline_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in raw.items()
                if key != "timeline_fingerprint"
            }
        )
        return TimelineManifest(**raw)

    def test_ass_and_edit_project_are_stable_and_share_one_timeline(self) -> None:
        first_ass = drama_edit_export.export_timeline_ass(self.timeline)
        second_ass = drama_edit_export.export_timeline_ass(self.timeline)
        first_project = drama_edit_export.build_editable_timeline_project(
            self.timeline
        )
        second_project = drama_edit_export.build_editable_timeline_project(
            self.timeline
        )
        self.assertEqual(first_ass, second_ass)
        self.assertEqual(first_project, second_project)
        self.assertEqual(
            first_ass.timeline_fingerprint,
            first_project.timeline_fingerprint,
        )
        self.assertEqual(
            [track.kind for track in first_project.tracks],
            ["video", "dialogue", "narration", "bgm", "sfx", "silence"],
        )
        self.assertEqual(
            [segment.timeline_start_ms for segment in first_project.tracks[0].segments],
            [clip.start_ms for clip in self.timeline.video_clips],
        )
        self.assertEqual(
            first_project.tracks[0].segments[-1].timeline_end_ms,
            self.timeline.total_duration_ms,
        )
        self.assertEqual(
            [row.cue_id for row in first_project.subtitles],
            [row.cue_id for row in self.timeline.subtitle_cues],
        )
        self.assertEqual(first_ass.cue_count, len(self.timeline.subtitle_cues))
        self.assertIn("PlayResX: 1080", first_ass.content)
        self.assertIn("PlayResY: 1920", first_ass.content)
        self.assertEqual(first_project.audio_sample_rate, 48000)
        self.assertEqual(first_project.audio_layout, "stereo")
        self.assertEqual(first_project.audio_codec_profile, "aac-128k-v1")
        for segment in (
            first_project.tracks[1].segments
            + first_project.tracks[2].segments
        ):
            expected = 10 if segment.timeline_end_ms - segment.timeline_start_ms >= 100 else 0
            self.assertEqual(segment.fade_in_ms, expected)
            self.assertEqual(segment.fade_out_ms, expected)
            self.assertEqual(segment.gain_permille, 1000)

    def test_ass_escapes_override_syntax_and_uses_centisecond_bounds(self) -> None:
        cue = self.timeline.subtitle_cues[0]
        revised = drama_timeline.revise_timeline_subtitles(
            self.timeline,
            {cue.cue_id: r"{\pos(1,1)}字幕,测试"},
        )
        ass = drama_edit_export.export_timeline_ass(revised)
        self.assertNotIn(r"{\pos(1,1)}", ass.content)
        self.assertIn(r"\{\\pos(1,1)\}字幕,测试", ass.content)
        dialogue = next(
            line for line in ass.content.splitlines() if line.startswith("Dialogue: ")
        )
        self.assertRegex(
            dialogue,
            r"^Dialogue: 0,\d+:\d{2}:\d{2}\.\d{2},"
            r"\d+:\d{2}:\d{2}\.\d{2},",
        )
        first = drama_edit_export._ass_centisecond_range(
            0, 1001, previous_end_centiseconds=0
        )
        second = drama_edit_export._ass_centisecond_range(
            1001, 2000, previous_end_centiseconds=first[1]
        )
        self.assertGreaterEqual(second[0], first[1])
        with self.assertRaisesRegex(
            drama_edit_export.DramaEditExportError,
            "ASS export was rejected",
        ):
            drama_edit_export.export_timeline_ass(
                self._dense_unrepresentable_timeline()
            )

    def test_subtitle_revision_changes_sidecars_not_media_materials(self) -> None:
        cue = self.timeline.subtitle_cues[0]
        revised = drama_timeline.revise_timeline_subtitles(
            self.timeline,
            {cue.cue_id: "人工校订字幕"},
        )
        before = drama_edit_export.build_editable_timeline_project(self.timeline)
        after = drama_edit_export.build_editable_timeline_project(revised)
        self.assertNotEqual(before.project_fingerprint, after.project_fingerprint)
        self.assertEqual(before.materials, after.materials)
        self.assertEqual(before.tracks, after.tracks)
        self.assertNotEqual(before.subtitles, after.subtitles)
        self.assertEqual(
            before.subtitles[0].utterance_id,
            after.subtitles[0].utterance_id,
        )
        self.assertEqual(
            before.subtitles[0].source_text_sha256,
            after.subtitles[0].source_text_sha256,
        )
        self.assertEqual(after.subtitles[0].revision, before.subtitles[0].revision + 1)
        self.assertNotEqual(
            drama_edit_export.export_timeline_ass(self.timeline).content_sha256,
            drama_edit_export.export_timeline_ass(revised).content_sha256,
        )

    def test_workspace_export_is_atomic_and_exactly_revalidated(self) -> None:
        result = drama_edit_export.export_workspace_editable_sidecars(
            self.root.name,
            self.timeline,
        )
        self.assertEqual(
            result,
            drama_edit_export.require_workspace_editable_sidecars(
                self.root.name,
                self.timeline,
            ),
        )
        ass_path = self.root / result.ass_path
        project_path = self.root / result.project_path
        completion_path = self.root / result.completion_path
        self.assertEqual(
            hashlib.sha256(ass_path.read_bytes()).hexdigest(),
            result.ass_sha256,
        )
        stored = EditableTimelineProject(
            **json.loads(project_path.read_text("utf-8"))
        )
        self.assertEqual(
            json.loads(completion_path.read_text("utf-8")),
            model_to_dict(result),
        )
        self.assertEqual(
            stored,
            drama_edit_export.build_editable_timeline_project(self.timeline),
        )

        ass_path.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(
            drama_edit_export.DramaEditExportError,
            "do not match",
        ):
            drama_edit_export.require_workspace_editable_sidecars(
                self.root.name,
                self.timeline,
            )

    def test_tampered_source_and_unsafe_output_targets_fail_closed(self) -> None:
        project = drama_edit_export.build_editable_timeline_project(self.timeline)
        source = self.root / project.materials[0].artifact_path
        source.write_bytes(b"tampered")
        with self.assertRaisesRegex(
            drama_edit_export.DramaEditExportError,
            "source artifact changed",
        ):
            drama_edit_export.export_workspace_editable_sidecars(
                self.root.name,
                self.timeline,
            )

        self.timeline = build_synthetic_timeline(self.root)
        ass_path, _, _ = drama_edit_export._export_paths(self.timeline)
        target = self.root / ass_path
        target.parent.mkdir(parents=True, exist_ok=True)
        outside = self.root.parent / f"{self.root.name}-outside.ass"
        outside.write_text("outside", encoding="utf-8")
        target.symlink_to(outside)
        try:
            with self.assertRaisesRegex(
                drama_edit_export.DramaEditExportError,
                "invalid|rejected",
            ):
                drama_edit_export.export_workspace_editable_sidecars(
                    self.root.name,
                    self.timeline,
                )
            self.assertEqual(outside.read_text("utf-8"), "outside")
        finally:
            try:
                target.unlink()
            except OSError:
                pass
            try:
                outside.unlink()
            except OSError:
                pass

    def test_schema_and_regeneration_reject_forged_or_unsafe_artifacts(self) -> None:
        ass = drama_edit_export.export_timeline_ass(self.timeline)
        forged_ass = model_to_dict(ass)
        forged_ass["content"] += "Dialogue: forged\n"
        with self.assertRaises(ValidationError):
            AssArtifact(**forged_ass)
        with self.assertRaises(drama_edit_export.DramaEditExportError):
            drama_edit_export.require_timeline_ass_artifact(
                self.timeline,
                {**model_to_dict(ass), "timeline_fingerprint": "0" * 64},
            )

        project = drama_edit_export.build_editable_timeline_project(self.timeline)
        forged_project = model_to_dict(project)
        forged_project["timeline_fingerprint"] = "0" * 64
        with self.assertRaises(drama_edit_export.DramaEditExportError):
            drama_edit_export.require_editable_timeline_project(
                self.timeline,
                forged_project,
            )

        material = model_to_dict(project.materials[0])
        material["artifact_path"] = "/tmp/escape.mp4"
        with self.assertRaises(ValidationError):
            EditableTimelineMaterial(**material)
        material["artifact_path"] = "../escape.mp4"
        with self.assertRaises(ValidationError):
            EditableTimelineMaterial(**material)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unsupported")
    def test_fifo_output_target_is_rejected_without_blocking(self) -> None:
        ass_path, _, _ = drama_edit_export._export_paths(self.timeline)
        target = self.root / ass_path
        target.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(target)
        with self.assertRaisesRegex(
            drama_edit_export.DramaEditExportError,
            "invalid|rejected",
        ):
            drama_edit_export.export_workspace_editable_sidecars(
                self.root.name,
                self.timeline,
            )

    def test_overlapping_sfx_are_preserved_on_the_explicit_mix_bus(self) -> None:
        timeline = self._with_optional_audio(
            kind="sfx",
            ranges=[(0, 700), (300, 900)],
        )
        project = drama_edit_export.build_editable_timeline_project(timeline)
        sfx = next(track for track in project.tracks if track.kind == "sfx")
        self.assertEqual(len(sfx.segments), 2)
        self.assertLess(
            sfx.segments[1].timeline_start_ms,
            sfx.segments[0].timeline_end_ms,
        )
        self.assertEqual([row.gain_permille for row in sfx.segments], [500, 500])

    def test_simultaneous_sfx_keep_timeline_clip_id_order(self) -> None:
        timeline = self._with_optional_audio(
            kind="sfx",
            ranges=[(0, 100)] * 6,
        )
        project = drama_edit_export.build_editable_timeline_project(timeline)
        sfx = next(track for track in project.tracks if track.kind == "sfx")
        self.assertEqual(
            [row.source_id for row in sfx.segments],
            [row.clip_id for row in timeline.optional_audio_clips],
        )

    def test_valid_reversed_silence_input_exports_in_canonical_order(self) -> None:
        raw = model_to_dict(self.timeline)
        raw["silence_clips"] = list(reversed(raw["silence_clips"]))
        raw["timeline_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in raw.items()
                if key != "timeline_fingerprint"
            }
        )
        timeline = TimelineManifest(**raw)
        project = drama_edit_export.build_editable_timeline_project(timeline)
        silence = next(track for track in project.tracks if track.kind == "silence")
        self.assertEqual(
            [row.timeline_start_ms for row in silence.segments],
            sorted(row.start_ms for row in timeline.silence_clips),
        )

    def test_source_swap_during_export_never_commits_completion(self) -> None:
        project = drama_edit_export.build_editable_timeline_project(self.timeline)
        source = self.root / project.materials[0].artifact_path
        original_write = drama_edit_export._atomic_write_at
        calls = 0

        def swapping_write(*args, **kwargs):
            nonlocal calls
            original_write(*args, **kwargs)
            calls += 1
            if calls == 1:
                replacement = source.with_suffix(".replacement")
                replacement.write_bytes(b"changed-after-validation")
                os.replace(replacement, source)

        with patch.object(
            drama_edit_export,
            "_atomic_write_at",
            side_effect=swapping_write,
        ):
            with self.assertRaisesRegex(
                drama_edit_export.DramaEditExportError,
                "changed",
            ):
                drama_edit_export.export_workspace_editable_sidecars(
                    self.root.name,
                    self.timeline,
                )
        _, _, completion_path = drama_edit_export._export_paths(self.timeline)
        self.assertFalse((self.root / completion_path).exists())

    def test_partial_pair_has_no_completion_marker(self) -> None:
        original_write = drama_edit_export._atomic_write_at
        calls = 0

        def failing_write(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise drama_edit_export.DramaEditExportError("simulated")
            return original_write(*args, **kwargs)

        with patch.object(
            drama_edit_export,
            "_atomic_write_at",
            side_effect=failing_write,
        ):
            with self.assertRaisesRegex(
                drama_edit_export.DramaEditExportError,
                "simulated",
            ):
                drama_edit_export.export_workspace_editable_sidecars(
                    self.root.name,
                    self.timeline,
                )
        _, _, completion_path = drama_edit_export._export_paths(self.timeline)
        self.assertFalse((self.root / completion_path).exists())
        with self.assertRaises(drama_edit_export.DramaEditExportError):
            drama_edit_export.require_workspace_editable_sidecars(
                self.root.name,
                self.timeline,
            )

    def test_failed_reexport_invalidates_existing_completion_marker(self) -> None:
        result = drama_edit_export.export_workspace_editable_sidecars(
            self.root.name,
            self.timeline,
        )
        self.assertTrue((self.root / result.completion_path).is_file())
        original_write = drama_edit_export._atomic_write_at
        calls = 0

        def failing_write(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise drama_edit_export.DramaEditExportError("simulated reexport")
            return original_write(*args, **kwargs)

        with patch.object(
            drama_edit_export,
            "_atomic_write_at",
            side_effect=failing_write,
        ):
            with self.assertRaisesRegex(
                drama_edit_export.DramaEditExportError,
                "simulated reexport",
            ):
                drama_edit_export.export_workspace_editable_sidecars(
                    self.root.name,
                    self.timeline,
                )
        self.assertFalse((self.root / result.completion_path).exists())

    def test_source_namespace_swap_after_open_is_rejected(self) -> None:
        project = drama_edit_export.build_editable_timeline_project(self.timeline)
        source = self.root / project.materials[0].artifact_path
        original_open = drama_edit_export._open_workspace_file
        swapped = False

        def swapping_open(root, relative_path):
            nonlocal swapped
            opened = original_open(root, relative_path)
            if not swapped and relative_path == project.materials[0].artifact_path:
                swapped = True
                replacement = source.with_suffix(".namespace-swap")
                replacement.write_bytes(b"namespace-swap")
                os.replace(replacement, source)
            return opened

        with patch.object(
            drama_edit_export,
            "_open_workspace_file",
            side_effect=swapping_open,
        ):
            with self.assertRaisesRegex(
                drama_edit_export.DramaEditExportError,
                "namespace changed",
            ):
                drama_edit_export.export_workspace_editable_sidecars(
                    self.root.name,
                    self.timeline,
                )

    def test_output_directory_namespace_swap_is_rejected(self) -> None:
        original_write = drama_edit_export._atomic_write_at
        ass_path, _, completion_path = drama_edit_export._export_paths(self.timeline)
        output_directory = self.root / Path(ass_path).parent
        moved_directory = output_directory.with_name(output_directory.name + ".moved")
        calls = 0

        def swapping_write(*args, **kwargs):
            nonlocal calls
            original_write(*args, **kwargs)
            calls += 1
            if calls == 1:
                output_directory.rename(moved_directory)
                output_directory.mkdir(mode=0o700)

        with patch.object(
            drama_edit_export,
            "_atomic_write_at",
            side_effect=swapping_write,
        ):
            with self.assertRaisesRegex(
                drama_edit_export.DramaEditExportError,
                "output directory changed",
            ):
                drama_edit_export.export_workspace_editable_sidecars(
                    self.root.name,
                    self.timeline,
                )
        self.assertFalse((self.root / completion_path).exists())
        self.assertFalse(
            (moved_directory / Path(completion_path).name).exists()
        )

    def test_workspace_lock_errors_are_bounded(self) -> None:
        secret = "/abs/private sk-secret https://provider.example/path?token=x"
        with patch.object(
            drama_edit_export,
            "acquire_write_lock",
            side_effect=WorkspaceLocked(secret),
        ):
            with self.assertRaisesRegex(
                drama_edit_export.DramaEditExportError,
                "^editable workspace is busy$",
            ) as captured:
                drama_edit_export.export_workspace_editable_sidecars(
                    self.root.name,
                    self.timeline,
                )
        self.assertNotIn("secret", str(captured.exception))
        self.assertNotIn("/abs", str(captured.exception))


if __name__ == "__main__":
    unittest.main()
