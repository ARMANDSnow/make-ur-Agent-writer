"""iter121 pure provider-neutral TTS attempt contracts."""

from __future__ import annotations

from pydantic import ValidationError

from src import drama_audio, drama_tts_attempts
from src.schemas import model_to_dict
from tests.test_drama_audio import DramaAudioManifestTests


class DramaTtsAttemptPureTests(DramaAudioManifestTests):
    def _tts_inputs(self, name: str = "tts-pure"):
        plan, profiles, assignments = self._inputs(name)
        manifest = drama_audio.build_audio_manifest(
            plan, profiles=profiles, assignments=assignments
        )
        utterance = manifest.utterances[0]
        capability = drama_tts_attempts.build_tts_provider_capability(
            backend_id="fake-tts", capability_version="v1",
            provider_id="fixture", model_id="mock/tts-v1", sample_rate=16000,
        )
        authorization = drama_tts_attempts.build_tts_authorization(
            utterance, capability,
            provider_fingerprint="1" * 64, model_fingerprint="2" * 64,
            account_fingerprint="3" * 64, endpoint_fingerprint="4" * 64,
            auth_fingerprint="5" * 64,
        )
        spec = drama_tts_attempts.build_tts_attempt_spec(
            utterance, capability, authorization
        )
        return utterance, capability, authorization, spec

    def test_capability_authorization_and_spec_are_stable_and_exact(self) -> None:
        utterance, capability, authorization, spec = self._tts_inputs()
        again = drama_tts_attempts.build_tts_attempt_spec(
            utterance, capability, authorization
        )
        self.assertEqual(spec, again)
        self.assertEqual(authorization.utterance_id, utterance.utterance_id)
        self.assertEqual(authorization.max_synthesis_posts, 1)
        self.assertTrue(spec.output_path.endswith(f"/{utterance.utterance_id}.wav"))

    def test_non_audio_models_bool_and_tamper_fail_closed(self) -> None:
        for model_id in (
            "gpt-5.5-medium",
            "openai/gpt-5.5-medium",
            "gpt-image-2",
            "openai/gpt-image-2",
        ):
            with self.subTest(model_id=model_id):
                with self.assertRaises(drama_tts_attempts.DramaTtsAttemptError):
                    drama_tts_attempts.build_tts_provider_capability(
                        backend_id="bad", capability_version="v1", model_id=model_id
                        , provider_id="fixture"
                    )
        with self.assertRaises(drama_tts_attempts.DramaTtsAttemptError):
            drama_tts_attempts.build_tts_provider_capability(
                backend_id="bad", capability_version="v1", model_id="mock/tts",
                provider_id="fixture", sample_rate=True,
            )
        _, _, _, spec = self._tts_inputs("tts-tamper")
        raw = model_to_dict(spec)
        raw["output_path"] = raw["output_path"].replace("episode_001", "episode_002")
        with self.assertRaises(ValidationError):
            type(spec)(**raw)

        utterance, _, _, _ = self._tts_inputs("tts-provider-mismatch")
        mismatch = drama_tts_attempts.build_tts_provider_capability(
            backend_id="other", capability_version="v1", provider_id="other",
            model_id="other/tts-v1",
        )
        mismatch_auth = drama_tts_attempts.build_tts_authorization(
            utterance, mismatch, provider_fingerprint="1" * 64,
            model_fingerprint="2" * 64, account_fingerprint="3" * 64,
            endpoint_fingerprint="4" * 64, auth_fingerprint="5" * 64,
        )
        with self.assertRaises(drama_tts_attempts.DramaTtsAttemptError):
            drama_tts_attempts.build_tts_attempt_spec(
                utterance, mismatch, mismatch_auth
            )

    def test_attempt_transitions_are_exhaustive_and_guarded(self) -> None:
        _, _, _, spec = self._tts_inputs("tts-transitions")
        started = drama_tts_attempts.start_tts_attempt(spec)
        self.assertEqual(drama_tts_attempts.mark_tts_not_sent(started).status, "not_sent")
        self.assertEqual(
            drama_tts_attempts.mark_tts_submission_unknown(started).status,
            "submission_unknown",
        )
        submitted = drama_tts_attempts.record_tts_submission(started, "provider-1")
        self.assertEqual(submitted.status, "submitted")
        with self.assertRaises(drama_tts_attempts.DramaTtsAttemptError):
            drama_tts_attempts.record_tts_submission(submitted, "provider-2")
