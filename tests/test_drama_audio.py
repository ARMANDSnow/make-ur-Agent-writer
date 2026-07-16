"""iter120: explicit voice profiles, utterance projection, and offline WAVs."""

from __future__ import annotations

import hashlib
import json

from pydantic import ValidationError

from src import drama_audio
from src.drama_schemas import AudioManifest
from src.schemas import model_to_dict
from tests._drama_shot_image_base import DramaShotImageFixture


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class DramaAudioManifestTests(DramaShotImageFixture):
    def _inputs(self, name: str = "audio"):
        plan = self._seed_shot_image_sources(name)["render_plan"]
        character = drama_audio.build_voice_profile(
            scope="character",
            character_id=plan.frozen_character_ids[0],
            display_name="主角",
            language_tag="zh-CN",
            provider_id="fixture",
            model_id="mock/tts-v1",
            voice_name="lead",
            instructions="克制、清晰",
        )
        narrator = drama_audio.build_voice_profile(
            scope="narrator",
            character_id=None,
            display_name="旁白",
            language_tag="zh-CN",
            provider_id="fixture",
            model_id="mock/tts-v1",
            voice_name="narrator",
        )
        assignments = []
        for segment in plan.spoken_segments:
            profile = narrator if segment.kind == "narration" else character
            assignments.append(
                drama_audio.build_voice_assignment(
                    segment_id=segment.segment_id,
                    profile=profile,
                    speaker_character_id=(
                        None
                        if segment.kind == "narration"
                        else plan.frozen_character_ids[0]
                    ),
                )
            )
        return plan, [character, narrator], assignments

    def test_projection_is_stable_ordered_and_supports_legacy_unresolved_dialogue(self) -> None:
        plan, profiles, assignments = self._inputs()
        self.assertTrue(
            any(
                segment.kind == "dialogue"
                and segment.speaker_character_id is None
                for segment in plan.spoken_segments
            )
        )
        first = drama_audio.build_audio_manifest(
            plan, profiles=profiles, assignments=assignments
        )
        second = drama_audio.build_audio_manifest(
            plan, profiles=profiles, assignments=assignments
        )
        self.assertEqual(first, second)
        self.assertEqual(first.status, "ready")
        self.assertEqual(
            [row.segment_id for row in first.utterances], first.source_segment_ids
        )
        self.assertEqual(
            [row.sequence for row in first.utterances],
            [row.sequence for row in plan.spoken_segments],
        )

    def test_missing_assignment_and_missing_profile_are_explicitly_blocked(self) -> None:
        plan, profiles, assignments = self._inputs("blocked")
        missing_assignment = drama_audio.build_audio_manifest(
            plan, profiles=profiles, assignments=assignments[1:]
        )
        self.assertEqual(missing_assignment.status, "blocked")
        self.assertEqual(
            missing_assignment.blocked_segments[0].reason, "assignment_missing"
        )
        missing_profile = drama_audio.build_audio_manifest(
            plan, profiles=profiles[1:], assignments=assignments
        )
        self.assertIn(
            "profile_missing", [row.reason for row in missing_profile.blocked_segments]
        )

    def test_scope_illegal_speaker_and_unknown_segment_fail_closed(self) -> None:
        plan, profiles, assignments = self._inputs("scope")
        dialogue = next(row for row in plan.spoken_segments if row.kind == "dialogue")
        narrator = profiles[1]
        wrong_scope = drama_audio.build_voice_assignment(
            segment_id=dialogue.segment_id,
            profile=narrator,
            speaker_character_id=plan.frozen_character_ids[0],
        )
        rows = [wrong_scope if row.segment_id == dialogue.segment_id else row for row in assignments]
        manifest = drama_audio.build_audio_manifest(
            plan, profiles=profiles, assignments=rows
        )
        blocked = {row.segment_id: row.reason for row in manifest.blocked_segments}
        self.assertEqual(blocked[dialogue.segment_id], "scope_mismatch")

        illegal_speaker = drama_audio.build_voice_assignment(
            segment_id=dialogue.segment_id,
            profile=profiles[0],
            speaker_character_id="c999",
        )
        rows = [illegal_speaker if row.segment_id == dialogue.segment_id else row for row in assignments]
        manifest = drama_audio.build_audio_manifest(
            plan, profiles=profiles, assignments=rows
        )
        self.assertIn("speaker_not_frozen", [row.reason for row in manifest.blocked_segments])
        unknown = model_to_dict(assignments[0])
        unknown["segment_id"] = "seg_ffffffffffffffffffffffff"
        unknown["assignment_fingerprint"] = _sha(
            {key: value for key, value in unknown.items() if key != "assignment_fingerprint"}
        )
        with self.assertRaisesRegex(drama_audio.DramaAudioError, "rejected"):
            drama_audio.build_audio_manifest(
                plan, profiles=profiles, assignments=[unknown, *assignments]
            )

    def test_one_profile_change_only_changes_its_utterances(self) -> None:
        plan, profiles, assignments = self._inputs("local-stale")
        before = drama_audio.build_audio_manifest(
            plan, profiles=profiles, assignments=assignments
        )
        changed = drama_audio.build_voice_profile(
            scope="character",
            character_id=plan.frozen_character_ids[0],
            display_name="主角",
            language_tag="zh-CN",
            provider_id="fixture",
            model_id="mock/tts-v1",
            voice_name="lead",
            instructions="更克制",
        )
        changed_assignments = [
            drama_audio.build_voice_assignment(
                segment_id=row.segment_id,
                profile=changed,
                speaker_character_id=row.speaker_character_id,
            )
            if row.speaker_character_id is not None
            else row
            for row in assignments
        ]
        after = drama_audio.build_audio_manifest(
            plan,
            profiles=[changed, profiles[1]],
            assignments=changed_assignments,
        )
        before_by_id = {row.segment_id: row for row in before.utterances}
        for row in after.utterances:
            if row.kind == "dialogue":
                self.assertNotEqual(row.spec_fingerprint, before_by_id[row.segment_id].spec_fingerprint)
            else:
                self.assertEqual(row.spec_fingerprint, before_by_id[row.segment_id].spec_fingerprint)

    def test_schema_rejects_manifest_coverage_and_cross_binding_forgery(self) -> None:
        plan, profiles, assignments = self._inputs("forgery")
        manifest = drama_audio.build_audio_manifest(
            plan, profiles=profiles, assignments=assignments
        )
        forged = model_to_dict(manifest)
        forged["source_segment_ids"] = forged["source_segment_ids"][:-1]
        forged["manifest_fingerprint"] = _sha(
            {key: value for key, value in forged.items() if key != "manifest_fingerprint"}
        )
        with self.assertRaisesRegex(ValidationError, "cover every"):
            AudioManifest(**forged)

        forged = model_to_dict(manifest)
        forged["assignments"][0]["voice_profile_id"] = forged["profiles"][-1]["profile_id"]
        forged["assignments"][0]["voice_profile_fingerprint"] = forged["profiles"][-1]["profile_fingerprint"]
        forged["assignments"][0]["assignment_fingerprint"] = _sha(
            {
                key: value
                for key, value in forged["assignments"][0].items()
                if key != "assignment_fingerprint"
            }
        )
        forged["manifest_fingerprint"] = _sha(
            {key: value for key, value in forged.items() if key != "manifest_fingerprint"}
        )
        with self.assertRaisesRegex(ValidationError, "does not match"):
            AudioManifest(**forged)

        forged = model_to_dict(manifest)
        forged["utterances"][0]["sequence"] = 100
        forged["utterances"][0]["spec_fingerprint"] = _sha(
            {
                key: value
                for key, value in forged["utterances"][0].items()
                if key not in {"utterance_id", "spec_fingerprint"}
            }
        )
        forged["utterances"][0]["utterance_id"] = (
            f"utt_{forged['utterances'][0]['spec_fingerprint'][:24]}"
        )
        forged["manifest_fingerprint"] = _sha(
            {key: value for key, value in forged.items() if key != "manifest_fingerprint"}
        )
        with self.assertRaisesRegex(ValidationError, "source position"):
            AudioManifest(**forged)

        forged = model_to_dict(manifest)
        forged["frozen_character_ids"] = []
        forged["manifest_fingerprint"] = _sha(
            {key: value for key, value in forged.items() if key != "manifest_fingerprint"}
        )
        with self.assertRaisesRegex(ValidationError, "at least 1"):
            AudioManifest(**forged)

        for row_name in ("assignments", "utterances"):
            wrong_version = model_to_dict(manifest)
            wrong_version[row_name][0]["schema_version"] = 2
            with self.subTest(row=row_name):
                with self.assertRaises(ValidationError):
                    AudioManifest(**wrong_version)

    def test_mock_wav_is_bounded_hash_bound_and_path_safe(self) -> None:
        plan, profiles, assignments = self._inputs("wav")
        manifest = drama_audio.build_audio_manifest(
            plan, profiles=profiles, assignments=assignments
        )
        data = drama_audio.build_mock_wav_fixture(
            duration_milliseconds=125, sample_rate=16000
        )
        descriptor = drama_audio.describe_mock_wav_fixture(manifest.utterances[0], data)
        self.assertEqual(descriptor.sha256, hashlib.sha256(data).hexdigest())
        self.assertTrue(descriptor.path.endswith(f"/{descriptor.utterance_id}.wav"))
        for value in (True, 0, 30_001, 1.0, float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(drama_audio.DramaAudioError):
                    drama_audio.build_mock_wav_fixture(duration_milliseconds=value)
        for invalid in (
            b"",
            b"not-wave",
            data[:-1],
            data + b"SECRET_TRAILER",
            b"0" * 3_000_001,
        ):
            with self.subTest(size=len(invalid)):
                with self.assertRaises(drama_audio.DramaAudioError):
                    drama_audio.probe_mock_wav_fixture(invalid)
        for offset, packed in (
            (28, (1).to_bytes(4, "little")),
            (32, (1).to_bytes(2, "little")),
        ):
            mutated = bytearray(data)
            mutated[offset : offset + len(packed)] = packed
            with self.subTest(header_offset=offset):
                with self.assertRaises(drama_audio.DramaAudioError):
                    drama_audio.probe_mock_wav_fixture(bytes(mutated))

    def test_profile_rejects_provider_path_tricks_and_boolean_numbers(self) -> None:
        for model_id in ("../tts", "/tts", "mock//tts", "tts\\bad"):
            with self.subTest(model_id=model_id):
                with self.assertRaises(drama_audio.DramaAudioError):
                    drama_audio.build_voice_profile(
                        scope="narrator",
                        character_id=None,
                        display_name="旁白",
                        language_tag="zh-CN",
                        provider_id="fixture",
                        model_id=model_id,
                        voice_name="narrator",
                    )
        with self.assertRaises(drama_audio.DramaAudioError):
            drama_audio.build_voice_profile(
                scope="narrator",
                character_id=None,
                display_name="旁白",
                language_tag="zh-CN",
                provider_id="fixture",
                model_id="mock/tts-v1",
                voice_name="narrator",
                instructions=float("nan"),
            )
