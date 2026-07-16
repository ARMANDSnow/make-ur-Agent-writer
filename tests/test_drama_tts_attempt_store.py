"""iter121 durable TTS store, download recovery, and process crash tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from src import drama_audio, drama_tts_attempts, paths
from src.drama_tts_attempt_store import (
    DramaTtsAttemptStoreError,
    LocalFakeTtsAdapter,
    TtsAdapterIdentity,
    TtsAttemptReconciliationRequired,
    TtsSubmissionUnknownError,
    TtsProviderTerminalError,
    run_tts_attempt,
    tts_identity_from_authorization,
)
from src.secure_http import RequestNotSentError
from src.schemas import model_to_dict
from tests.test_drama_audio import DramaAudioManifestTests


class DramaTtsAttemptStoreTests(DramaAudioManifestTests):
    def _store_inputs(self, name: str):
        plan, profiles, assignments = self._inputs(name)
        manifest = drama_audio.build_audio_manifest(
            plan, profiles=profiles, assignments=assignments
        )
        utterance = manifest.utterances[0]
        capability = drama_tts_attempts.build_tts_provider_capability(
            backend_id="fake-tts", capability_version="v1", model_id="mock/tts-v1"
            , provider_id="fixture"
        )
        authorization = drama_tts_attempts.build_tts_authorization(
            utterance, capability,
            provider_fingerprint="1" * 64, model_fingerprint="2" * 64,
            account_fingerprint="3" * 64, endpoint_fingerprint="4" * 64,
            auth_fingerprint="5" * 64,
        )
        wav = drama_audio.build_mock_wav_fixture(duration_milliseconds=100)
        identity = tts_identity_from_authorization(capability, authorization)
        return utterance, capability, authorization, wav, identity

    def test_success_replay_and_verified_artifact_are_zero_call(self) -> None:
        utterance, capability, authorization, wav, identity = self._store_inputs("tts-ok")
        first_adapter = LocalFakeTtsAdapter(identity=identity, wav_bytes=wav)
        record = run_tts_attempt(
            "tts-ok", utterance, capability=capability,
            authorization=authorization, adapter=first_adapter,
        )
        self.assertEqual(record.status, "succeeded")
        self.assertEqual((first_adapter.synthesis_calls, first_adapter.download_calls), (1, 1))
        replay = LocalFakeTtsAdapter(identity=identity, wav_bytes=wav)
        self.assertEqual(
            run_tts_attempt(
                "tts-ok", utterance, capability=capability,
                authorization=authorization, adapter=replay,
            ).status,
            "succeeded",
        )
        self.assertEqual((replay.synthesis_calls, replay.download_calls), (0, 0))

    def test_download_failure_only_retries_get(self) -> None:
        utterance, capability, authorization, wav, identity = self._store_inputs("tts-get")

        class Flaky(LocalFakeTtsAdapter):
            def download(self, *args, **kwargs):
                self.download_calls += 1
                if self.download_calls == 1:
                    raise ConnectionError("hidden upstream detail")
                return self._wav_bytes

        adapter = Flaky(identity=identity, wav_bytes=wav)
        with self.assertRaisesRegex(DramaTtsAttemptStoreError, "download failed"):
            run_tts_attempt(
                "tts-get", utterance, capability=capability,
                authorization=authorization, adapter=adapter,
            )
        self.assertEqual(adapter.synthesis_calls, 1)
        record = run_tts_attempt(
            "tts-get", utterance, capability=capability,
            authorization=authorization, adapter=adapter,
        )
        self.assertEqual(record.status, "succeeded")
        self.assertEqual((adapter.synthesis_calls, adapter.download_calls), (1, 2))

    def test_sample_rate_mismatch_and_missing_succeeded_artifact_fail_closed(self) -> None:
        utterance, capability, authorization, _, identity = self._store_inputs("tts-rate")
        wrong_wav = drama_audio.build_mock_wav_fixture(
            duration_milliseconds=100, sample_rate=48000
        )
        adapter = LocalFakeTtsAdapter(identity=identity, wav_bytes=wrong_wav)
        with self.assertRaisesRegex(DramaTtsAttemptStoreError, "rejected"):
            run_tts_attempt(
                "tts-rate", utterance, capability=capability,
                authorization=authorization, adapter=adapter,
            )
        self.assertEqual((adapter.synthesis_calls, adapter.download_calls), (1, 1))

        utterance, capability, authorization, wav, identity = self._store_inputs("tts-missing")
        adapter = LocalFakeTtsAdapter(identity=identity, wav_bytes=wav)
        record = run_tts_attempt(
            "tts-missing", utterance, capability=capability,
            authorization=authorization, adapter=adapter,
        )
        (paths.workspace_root("tts-missing") / record.artifact.path).unlink()
        replay = LocalFakeTtsAdapter(identity=identity, wav_bytes=wav)
        with self.assertRaisesRegex(DramaTtsAttemptStoreError, "missing"):
            run_tts_attempt(
                "tts-missing", utterance, capability=capability,
                authorization=authorization, adapter=replay,
            )
        self.assertEqual((replay.synthesis_calls, replay.download_calls), (0, 0))

    def test_response_loss_blocks_every_future_synthesis(self) -> None:
        utterance, capability, authorization, wav, identity = self._store_inputs("tts-unknown")

        class Unknown(LocalFakeTtsAdapter):
            def synthesize(self, spec, *, text: str):
                self.synthesis_calls += 1
                raise TtsSubmissionUnknownError("raw response lost")

        unknown = Unknown(identity=identity, wav_bytes=wav)
        with self.assertRaises(TtsAttemptReconciliationRequired):
            run_tts_attempt(
                "tts-unknown", utterance, capability=capability,
                authorization=authorization, adapter=unknown,
            )
        replay = LocalFakeTtsAdapter(identity=identity, wav_bytes=wav)
        with self.assertRaises(TtsAttemptReconciliationRequired):
            run_tts_attempt(
                "tts-unknown", utterance, capability=capability,
                authorization=authorization, adapter=replay,
            )
        self.assertEqual((unknown.synthesis_calls, replay.synthesis_calls), (1, 0))

    def test_proven_not_sent_is_the_only_safe_synthesis_retry(self) -> None:
        utterance, capability, authorization, wav, identity = self._store_inputs("tts-not-sent")

        class NotSent(LocalFakeTtsAdapter):
            def synthesize(self, spec, *, text: str):
                self.synthesis_calls += 1
                raise RequestNotSentError("bounded")

        blocked = NotSent(identity=identity, wav_bytes=wav)
        record = run_tts_attempt(
            "tts-not-sent", utterance, capability=capability,
            authorization=authorization, adapter=blocked,
        )
        self.assertEqual(record.status, "not_sent")
        retry = LocalFakeTtsAdapter(identity=identity, wav_bytes=wav)
        self.assertEqual(
            run_tts_attempt(
                "tts-not-sent", utterance, capability=capability,
                authorization=authorization, adapter=retry,
            ).status,
            "succeeded",
        )
        self.assertEqual((blocked.synthesis_calls, retry.synthesis_calls), (1, 1))

    def test_orphan_audio_and_symlink_attempt_target_block_before_adapter(self) -> None:
        utterance, capability, authorization, wav, identity = self._store_inputs("tts-orphan")
        spec = drama_tts_attempts.build_tts_attempt_spec(
            utterance, capability, authorization
        )
        orphan = paths.workspace_root("tts-orphan") / spec.output_path
        orphan.parent.mkdir(parents=True)
        orphan.write_bytes(wav)
        adapter = LocalFakeTtsAdapter(identity=identity, wav_bytes=wav)
        with self.assertRaisesRegex(DramaTtsAttemptStoreError, "without a submitted"):
            run_tts_attempt(
                "tts-orphan", utterance, capability=capability,
                authorization=authorization, adapter=adapter,
            )
        self.assertEqual(adapter.synthesis_calls, 0)

        utterance, capability, authorization, wav, identity = self._store_inputs("tts-link")
        spec = drama_tts_attempts.build_tts_attempt_spec(
            utterance, capability, authorization
        )
        record_path = (
            paths.workspace_root("tts-link") / "logs" / "drama_tts"
            / f"episode_{spec.episode_no:03d}" / f"{spec.utterance_id}.attempt.json"
        )
        record_path.parent.mkdir(parents=True)
        external = Path(self._tmp.name) / "external.json"
        external.write_text("unchanged")
        record_path.symlink_to(external)
        adapter = LocalFakeTtsAdapter(identity=identity, wav_bytes=wav)
        with self.assertRaises(DramaTtsAttemptStoreError):
            run_tts_attempt(
                "tts-link", utterance, capability=capability,
                authorization=authorization, adapter=adapter,
            )
        self.assertEqual(external.read_text(), "unchanged")
        self.assertEqual(adapter.synthesis_calls, 0)

    def test_provider_identity_and_single_utterance_reconfigure_are_isolated(self) -> None:
        utterance, capability, authorization, wav, identity = self._store_inputs("tts-isolate")
        wrong = LocalFakeTtsAdapter(
            identity=TtsAdapterIdentity(**{**identity.__dict__, "model_fingerprint": "f" * 64}),
            wav_bytes=wav,
        )
        with self.assertRaises(TtsAttemptReconciliationRequired):
            run_tts_attempt(
                "tts-isolate", utterance, capability=capability,
                authorization=authorization, adapter=wrong,
            )
        self.assertEqual(wrong.synthesis_calls, 0)

        class Terminal(LocalFakeTtsAdapter):
            def synthesize(self, spec, *, text: str):
                self.synthesis_calls += 1
                raise TtsProviderTerminalError("terminal-request-1")

        terminal = Terminal(identity=identity, wav_bytes=wav)
        failed = run_tts_attempt(
            "tts-isolate", utterance, capability=capability,
            authorization=authorization, adapter=terminal,
        )
        self.assertEqual(failed.status, "provider_failed")
        replay = LocalFakeTtsAdapter(identity=identity, wav_bytes=wav)
        self.assertEqual(
            run_tts_attempt(
                "tts-isolate", utterance, capability=capability,
                authorization=authorization, adapter=replay,
            ).status,
            "provider_failed",
        )
        self.assertEqual(replay.synthesis_calls, 0)

    def test_adapter_identity_flip_after_post_never_repeats_synthesis(self) -> None:
        utterance, capability, authorization, wav, identity = self._store_inputs("tts-flip")

        class Flip:
            def __init__(self):
                self.reads = 0
                self.synthesis_calls = 0
                self.download_calls = 0

            @property
            def identity(self):
                self.reads += 1
                if self.reads >= 3:
                    return TtsAdapterIdentity(
                        **{**identity.__dict__, "account_fingerprint": "f" * 64}
                    )
                return identity

            def synthesize(self, spec, *, text: str):
                self.synthesis_calls += 1
                return "flip-request"

            def download(self, spec, *, provider_request_id: str):
                self.download_calls += 1
                return wav

        flipped = Flip()
        with self.assertRaises(TtsAttemptReconciliationRequired):
            run_tts_attempt(
                "tts-flip", utterance, capability=capability,
                authorization=authorization, adapter=flipped,
            )
        replay = LocalFakeTtsAdapter(identity=identity, wav_bytes=wav)
        with self.assertRaises(TtsAttemptReconciliationRequired):
            run_tts_attempt(
                "tts-flip", utterance, capability=capability,
                authorization=authorization, adapter=replay,
            )
        self.assertEqual((flipped.synthesis_calls, flipped.download_calls), (1, 0))
        self.assertEqual(replay.synthesis_calls, 0)

        utterance, capability, authorization, wav, identity = self._store_inputs(
            "tts-flip-not-sent"
        )

        class FlipNotSent:
            def __init__(self):
                self.flipped = False
                self.synthesis_calls = 0

            @property
            def identity(self):
                if self.flipped:
                    return TtsAdapterIdentity(
                        **{**identity.__dict__, "endpoint_fingerprint": "e" * 64}
                    )
                return identity

            def synthesize(self, spec, *, text: str):
                self.synthesis_calls += 1
                self.flipped = True
                raise RequestNotSentError("claimed not sent")

            def download(self, spec, *, provider_request_id: str):
                raise AssertionError("download must not run")

        flip_not_sent = FlipNotSent()
        with self.assertRaises(TtsAttemptReconciliationRequired):
            run_tts_attempt(
                "tts-flip-not-sent", utterance, capability=capability,
                authorization=authorization, adapter=flip_not_sent,
            )
        replay = LocalFakeTtsAdapter(identity=identity, wav_bytes=wav)
        with self.assertRaises(TtsAttemptReconciliationRequired):
            run_tts_attempt(
                "tts-flip-not-sent", utterance, capability=capability,
                authorization=authorization, adapter=replay,
            )
        self.assertEqual((flip_not_sent.synthesis_calls, replay.synthesis_calls), (1, 0))

    def test_one_voice_reconfigure_does_not_rerun_other_utterance(self) -> None:
        plan, profiles, assignments = self._inputs("tts-reconfigure")
        before = drama_audio.build_audio_manifest(
            plan, profiles=profiles, assignments=assignments
        )
        dialogue = next(row for row in before.utterances if row.kind == "dialogue")
        narration = next(row for row in before.utterances if row.kind == "narration")
        capability = drama_tts_attempts.build_tts_provider_capability(
            backend_id="fake-tts", capability_version="v1", provider_id="fixture",
            model_id="mock/tts-v1",
        )

        def auth(row):
            return drama_tts_attempts.build_tts_authorization(
                row, capability, provider_fingerprint="1" * 64,
                model_fingerprint="2" * 64, account_fingerprint="3" * 64,
                endpoint_fingerprint="4" * 64, auth_fingerprint="5" * 64,
            )

        wav = drama_audio.build_mock_wav_fixture(duration_milliseconds=100)
        for row in (dialogue, narration):
            current_auth = auth(row)
            current_identity = tts_identity_from_authorization(capability, current_auth)
            run_tts_attempt(
                "tts-reconfigure", row, capability=capability,
                authorization=current_auth,
                adapter=LocalFakeTtsAdapter(identity=current_identity, wav_bytes=wav),
            )
        changed_profile = drama_audio.build_voice_profile(
            scope="character", character_id=plan.frozen_character_ids[0],
            display_name="主角", language_tag="zh-CN", provider_id="fixture",
            model_id="mock/tts-v1", voice_name="lead-v2",
        )
        changed_assignments = [
            drama_audio.build_voice_assignment(
                segment_id=row.segment_id, profile=changed_profile,
                speaker_character_id=row.speaker_character_id,
            ) if row.speaker_character_id is not None else row
            for row in assignments
        ]
        after = drama_audio.build_audio_manifest(
            plan, profiles=[changed_profile, profiles[1]], assignments=changed_assignments
        )
        changed_dialogue = next(row for row in after.utterances if row.segment_id == dialogue.segment_id)
        self.assertNotEqual(changed_dialogue.utterance_id, dialogue.utterance_id)
        changed_auth = auth(changed_dialogue)
        changed_adapter = LocalFakeTtsAdapter(
            identity=tts_identity_from_authorization(capability, changed_auth), wav_bytes=wav
        )
        run_tts_attempt(
            "tts-reconfigure", changed_dialogue, capability=capability,
            authorization=changed_auth, adapter=changed_adapter,
        )
        narration_auth = auth(narration)
        narration_replay = LocalFakeTtsAdapter(
            identity=tts_identity_from_authorization(capability, narration_auth), wav_bytes=wav
        )
        run_tts_attempt(
            "tts-reconfigure", narration, capability=capability,
            authorization=narration_auth, adapter=narration_replay,
        )
        self.assertEqual(changed_adapter.synthesis_calls, 1)
        self.assertEqual((narration_replay.synthesis_calls, narration_replay.download_calls), (0, 0))

    def test_five_real_process_crash_windows_never_repeat_synthesis(self) -> None:
        expectations = {
            "after_started_before_submit": (0, 0, 4),
            "after_submit_before_receipt": (1, 0, 4),
            "after_submission_receipt": (1, 1, 0),
            "during_download_after_bytes": (1, 2, 0),
            "after_artifact_write": (1, 1, 0),
        }
        for index, (phase, expected) in enumerate(expectations.items(), start=1):
            name = f"tts-crash-{index}"
            utterance, capability, authorization, wav, identity = self._store_inputs(name)
            counter = Path(self._tmp.name) / f"counter-{index}.json"
            bundle_path = Path(self._tmp.name) / f"bundle-{index}.json"
            bundle_path.write_text(json.dumps({
                "workspace_root": str(paths.WORKSPACE_DIR), "workspace": name,
                "utterance": model_to_dict(utterance),
                "capability": model_to_dict(capability),
                "authorization": model_to_dict(authorization),
                "identity": identity.__dict__, "counter": str(counter),
                "wav_hex": wav.hex(),
            }))
            crashed = subprocess.run(
                [sys.executable, "-m", "tests._tts_crash_worker", str(bundle_path), phase],
                cwd=Path(__file__).parents[1], check=False,
            )
            self.assertEqual(crashed.returncode, 73, phase)
            resumed = subprocess.run(
                [sys.executable, "-m", "tests._tts_crash_worker", str(bundle_path), "none"],
                cwd=Path(__file__).parents[1], check=False,
            )
            counts = json.loads(counter.read_text()) if counter.exists() else {"synthesis": 0, "download": 0}
            self.assertEqual(
                (counts["synthesis"], counts["download"], resumed.returncode),
                expected,
                phase,
            )
