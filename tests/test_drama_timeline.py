"""iter122 single TimelineManifest, strict numeric bounds, and SRT."""

from __future__ import annotations

import hashlib

from pydantic import ValidationError

from src import (
    drama_audio,
    drama_shot_video_continuity,
    drama_timeline,
    drama_tts_attempts,
    paths,
)
from src.drama_schemas import TimelineManifest, _canonical_sha256
from src.drama_tts_attempt_store import (
    LocalFakeTtsAdapter,
    run_tts_attempt,
    tts_identity_from_authorization,
)
from src.schemas import model_to_dict
from tests.test_drama_shot_video_continuity import DramaShotVideoContinuityTests


class DramaTimelineTests(DramaShotVideoContinuityTests):
    def _timeline_sources(
        self,
        name: str = "timeline",
        *,
        wav_duration_ms: int = 20,
    ):
        sources = self._seed_video_candidate_sources(name)
        plan = sources["video_plan"]
        videos = sources["video_candidate_manifest"]
        for index, spec in enumerate(plan.shot_specs):
            videos, candidate = self._append_video_candidate(
                name, videos, spec.shot_id, marker=index
            )
            videos = self._select_video_candidate(name, videos, candidate)
        report = drama_shot_video_continuity.build_shot_video_continuity_report(
            plan, videos
        )
        render_plan = sources["render_plan"]
        character = drama_audio.build_voice_profile(
            scope="character", character_id=render_plan.frozen_character_ids[0],
            display_name="主角", language_tag="zh-CN", provider_id="fixture",
            model_id="mock/tts-v1", voice_name="lead",
        )
        narrator = drama_audio.build_voice_profile(
            scope="narrator", character_id=None, display_name="旁白",
            language_tag="zh-CN", provider_id="fixture",
            model_id="mock/tts-v1", voice_name="narrator",
        )
        assignments = []
        for segment in render_plan.spoken_segments:
            profile = narrator if segment.kind == "narration" else character
            assignments.append(drama_audio.build_voice_assignment(
                segment_id=segment.segment_id, profile=profile,
                speaker_character_id=(
                    None if segment.kind == "narration"
                    else render_plan.frozen_character_ids[0]
                ),
            ))
        audio_manifest = drama_audio.build_audio_manifest(
            render_plan, profiles=[character, narrator], assignments=assignments
        )
        capability = drama_tts_attempts.build_tts_provider_capability(
            backend_id="fake-tts", capability_version="v1",
            provider_id="fixture", model_id="mock/tts-v1", sample_rate=16000,
        )
        wav = drama_audio.build_mock_wav_fixture(
            duration_milliseconds=wav_duration_ms, sample_rate=16000
        )
        records = []
        for utterance in audio_manifest.utterances:
            authorization = drama_tts_attempts.build_tts_authorization(
                utterance, capability, provider_fingerprint="1" * 64,
                model_fingerprint="2" * 64, account_fingerprint="3" * 64,
                endpoint_fingerprint="4" * 64, auth_fingerprint="5" * 64,
            )
            records.append(run_tts_attempt(
                name, utterance, capability=capability,
                authorization=authorization,
                adapter=LocalFakeTtsAdapter(
                    identity=tts_identity_from_authorization(capability, authorization),
                    wav_bytes=wav,
                ),
            ))
        return plan, videos, report, audio_manifest, records

    def test_workspace_gate_builds_stable_complete_timeline_and_srt(self) -> None:
        plan, videos, report, audio_manifest, records = self._timeline_sources()
        first = drama_timeline.require_workspace_timeline_manifest(
            "timeline", audio_manifest, records
        )
        second = drama_timeline.require_workspace_timeline_manifest(
            "timeline", audio_manifest, records
        )
        self.assertEqual(first, second)
        self.assertEqual(
            [row.shot_id for row in first.video_clips],
            [row.shot_id for row in plan.shot_specs],
        )
        self.assertEqual(first.video_clips[0].start_ms, 0)
        self.assertEqual(first.video_clips[-1].end_ms, first.total_duration_ms)
        self.assertEqual(first.warnings, ["optional_bgm_missing"])
        srt = drama_timeline.export_timeline_srt(first)
        self.assertEqual(srt.timeline_fingerprint, first.timeline_fingerprint)
        self.assertEqual(srt.cue_count, len(first.audio_clips))
        self.assertIn(" --> ", srt.content)

    def test_missing_stale_audio_and_nonready_video_fail_closed(self) -> None:
        plan, videos, report, audio_manifest, records = self._timeline_sources("timeline-block")
        with self.assertRaises(drama_timeline.DramaTimelineError):
            drama_timeline._build_timeline_manifest_from_validated_sources(
                plan, videos, report, audio_manifest, records[:-1]
            )
        stale = model_to_dict(audio_manifest)
        stale["source_render_plan_fingerprint"] = "0" * 64
        stale["manifest_fingerprint"] = _canonical_sha256(
            {key: value for key, value in stale.items() if key != "manifest_fingerprint"}
        )
        with self.assertRaises(drama_timeline.DramaTimelineError):
            drama_timeline._build_timeline_manifest_from_validated_sources(
                plan, videos, report, stale, records
            )
        blocked = model_to_dict(report)
        blocked["status"] = "blocked"
        blocked["ready_for_compose"] = False
        blocked["blocked_shot_ids"] = [plan.shot_specs[0].shot_id]
        blocked["report_fingerprint"] = _canonical_sha256(
            {key: value for key, value in blocked.items() if key != "report_fingerprint"}
        )
        with self.assertRaises(drama_timeline.DramaTimelineError):
            drama_timeline._build_timeline_manifest_from_validated_sources(
                plan, videos, blocked, audio_manifest, records
            )

    def test_spoken_audio_over_shot_is_blocked_not_truncated(self) -> None:
        sources = self._timeline_sources("timeline-overrun", wav_duration_ms=1000)
        with self.assertRaisesRegex(drama_timeline.DramaTimelineError, "rejected"):
            drama_timeline._build_timeline_manifest_from_validated_sources(*sources)

    def test_schema_rejects_bool_negative_overlap_gap_cross_shot_and_forgery(self) -> None:
        sources = self._timeline_sources("timeline-forgery")
        timeline = drama_timeline._build_timeline_manifest_from_validated_sources(*sources)
        for value in (True, -1, 1.5, float("nan"), float("inf")):
            raw = model_to_dict(timeline)
            raw["video_clips"][0]["start_ms"] = value
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    TimelineManifest(**raw)

        raw = model_to_dict(timeline)
        raw["audio_clips"][0]["end_ms"] = raw["video_clips"][0]["end_ms"] + 1
        raw["subtitle_cues"][0]["end_ms"] = raw["audio_clips"][0]["end_ms"]
        for cue in raw["subtitle_cues"][:1]:
            cue["cue_fingerprint"] = _canonical_sha256(
                {key: value for key, value in cue.items() if key not in {"cue_id", "cue_fingerprint"}}
            )
            cue["cue_id"] = f"cue_{cue['cue_fingerprint'][:24]}"
        raw["timeline_fingerprint"] = _canonical_sha256(
            {key: value for key, value in raw.items() if key != "timeline_fingerprint"}
        )
        with self.assertRaisesRegex(ValidationError, "duration|crosses|partition"):
            TimelineManifest(**raw)

    def test_subtitle_revision_is_deterministic_and_does_not_change_audio(self) -> None:
        timeline = drama_timeline._build_timeline_manifest_from_validated_sources(
            *self._timeline_sources("timeline-revision"), bgm_policy="disabled"
        )
        cue = timeline.subtitle_cues[0]
        revised = drama_timeline.revise_timeline_subtitles(
            timeline, {cue.cue_id: "人工修订字幕"}
        )
        again = drama_timeline.revise_timeline_subtitles(
            timeline, {cue.cue_id: "人工修订字幕"}
        )
        self.assertEqual(revised, again)
        self.assertNotEqual(revised.timeline_fingerprint, timeline.timeline_fingerprint)
        self.assertEqual(revised.audio_clips, timeline.audio_clips)
        self.assertEqual(revised.subtitle_cues[0].source_text_sha256, cue.source_text_sha256)
        self.assertEqual(revised.warnings, [])
        self.assertEqual(
            drama_timeline.export_timeline_srt(revised).timeline_fingerprint,
            revised.timeline_fingerprint,
        )
        for bad in ("", " " * 2, "x" * 121, "bad\rtext", "bad\x00text"):
            with self.subTest(text=repr(bad)):
                with self.assertRaises(drama_timeline.DramaTimelineError):
                    drama_timeline.revise_timeline_subtitles(
                        timeline, {cue.cue_id: bad}
                    )

    def test_workspace_gate_rejects_tampered_wav(self) -> None:
        _, _, _, audio_manifest, records = self._timeline_sources("timeline-tamper")
        artifact = records[0].artifact
        (paths.workspace_root("timeline-tamper") / artifact.path).write_bytes(b"bad")
        with self.assertRaisesRegex(drama_timeline.DramaTimelineError, "invalid"):
            drama_timeline.require_workspace_timeline_manifest(
                "timeline-tamper", audio_manifest, records
            )

    def test_optional_bgm_is_hash_bound_and_clears_only_optional_warning(self) -> None:
        _, _, _, audio_manifest, records = self._timeline_sources("timeline-bgm")
        wav = drama_audio.build_mock_wav_fixture(
            duration_milliseconds=20, sample_rate=16000
        )
        relative = "outputs/drama/optional_audio/synthetic_bgm.wav"
        target = paths.workspace_root("timeline-bgm") / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(wav)
        payload = {
            "kind": "bgm",
            "artifact_path": relative,
            "artifact_sha256": drama_audio.probe_mock_wav_fixture(wav)["sha256"],
            "artifact_size_bytes": drama_audio.probe_mock_wav_fixture(wav)["size_bytes"],
            "artifact_duration_ms": 20,
            "sample_rate": 16000,
            "start_ms": 0,
            "end_ms": 20,
            "loop": False,
        }
        fingerprint = _canonical_sha256(payload)
        clip = {
            "clip_id": f"opt_{fingerprint[:24]}",
            "clip_fingerprint": fingerprint,
            **payload,
        }
        timeline = drama_timeline.require_workspace_timeline_manifest(
            "timeline-bgm", audio_manifest, records, optional_audio_clips=[clip]
        )
        self.assertEqual(timeline.warnings, [])
        self.assertEqual(timeline.optional_audio_clips[0].kind, "bgm")
        target.write_bytes(b"bad")
        with self.assertRaisesRegex(drama_timeline.DramaTimelineError, "invalid"):
            drama_timeline.require_workspace_timeline_manifest(
                "timeline-bgm", audio_manifest, records,
                optional_audio_clips=[clip],
            )

    def test_optional_audio_policy_order_overlap_and_duration_fail_closed(self) -> None:
        sources = self._timeline_sources("timeline-optional-policy")
        base = {
            "kind": "bgm",
            "artifact_path": "outputs/drama/optional_audio/bgm.wav",
            "artifact_sha256": "a" * 64,
            "artifact_size_bytes": 364,
            "artifact_duration_ms": 20,
            "sample_rate": 16000,
            "start_ms": 0,
            "end_ms": 21,
            "loop": False,
        }
        fingerprint = _canonical_sha256(base)
        too_short = {
            "clip_id": f"opt_{fingerprint[:24]}",
            "clip_fingerprint": fingerprint,
            **base,
        }
        with self.assertRaises(drama_timeline.DramaTimelineError):
            drama_timeline._build_timeline_manifest_from_validated_sources(
                *sources, optional_audio_clips=[too_short]
            )

        base["end_ms"] = 20
        fingerprint = _canonical_sha256(base)
        valid = {
            "clip_id": f"opt_{fingerprint[:24]}",
            "clip_fingerprint": fingerprint,
            **base,
        }
        with self.assertRaises(drama_timeline.DramaTimelineError):
            drama_timeline._build_timeline_manifest_from_validated_sources(
                *sources, bgm_policy="disabled", optional_audio_clips=[valid]
            )
        later_payload = {**base, "start_ms": 10, "end_ms": 20, "artifact_duration_ms": 10}
        later_fingerprint = _canonical_sha256(later_payload)
        later = {
            "clip_id": f"opt_{later_fingerprint[:24]}",
            "clip_fingerprint": later_fingerprint,
            **later_payload,
        }
        with self.assertRaises(drama_timeline.DramaTimelineError):
            drama_timeline._build_timeline_manifest_from_validated_sources(
                *sources, optional_audio_clips=[later, valid]
            )

    def test_artifact_identity_and_srt_structure_are_fail_closed(self) -> None:
        timeline = drama_timeline._build_timeline_manifest_from_validated_sources(
            *self._timeline_sources("timeline-identity")
        )
        raw = model_to_dict(timeline)
        raw["video_clips"][0]["artifact_path"] = raw["video_clips"][1]["artifact_path"]
        raw["timeline_fingerprint"] = _canonical_sha256(
            {key: value for key, value in raw.items() if key != "timeline_fingerprint"}
        )
        with self.assertRaisesRegex(ValidationError, "identity"):
            TimelineManifest(**raw)

        cue = timeline.subtitle_cues[0]
        for unsafe in ("bad --> cue", "bad\ncue", "bad\n\ncue"):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(drama_timeline.DramaTimelineError):
                    drama_timeline.revise_timeline_subtitles(
                        timeline, {cue.cue_id: unsafe}
                    )
        srt = drama_timeline.export_timeline_srt(timeline)
        self.assertEqual(
            drama_timeline.require_timeline_srt_artifact(timeline, srt), srt
        )
        forged = model_to_dict(srt)
        forged["content"] += "forged"
        forged["content_sha256"] = hashlib.sha256(
            forged["content"].encode("utf-8")
        ).hexdigest()
        with self.assertRaises(drama_timeline.DramaTimelineError):
            drama_timeline.require_timeline_srt_artifact(timeline, forged)
        mutated = timeline.model_copy(deep=True)
        mutated.subtitle_cues[0].text = "forged --> timing"
        with self.assertRaises(drama_timeline.DramaTimelineError):
            drama_timeline.export_timeline_srt(mutated)
        with self.assertRaises(drama_timeline.DramaTimelineError):
            drama_timeline.revise_timeline_subtitles(
                mutated, {mutated.subtitle_cues[0].cue_id: "revision"}
            )
