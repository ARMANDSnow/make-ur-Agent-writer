"""iter114: pure provider capability and shot-image attempt transitions."""

from __future__ import annotations

import copy

from src import drama_shot_image_attempts
from src.drama_schemas import (
    EpisodeShotImageAttemptLedger,
    ShotImageAttemptArtifactReceipt,
    ShotImageAttemptRecord,
    ShotImageAttemptSpec,
    ShotImageProviderCapability,
)
from src.schemas import model_to_dict
from tests._drama_shot_image_attempt_base import DramaShotImageAttemptFixture


class DramaShotImageAttemptPureTests(DramaShotImageAttemptFixture):
    def _spec(self, sources):
        return drama_shot_image_attempts.build_shot_image_attempt_spec(
            sources["shot_image_plan"],
            sources["candidate_manifest"],
            shot_id=sources["shot_id"],
            capability=sources["capability"],
            provider_fingerprint=sources["provider_fingerprint"],
        )

    def test_capability_and_spec_are_strict_byte_stable_contracts(self) -> None:
        sources = self._seed_attempt_sources("attempt-pure-contract")
        capability = sources["capability"]
        spec = self._spec(sources)
        self.assertEqual(ShotImageProviderCapability(**model_to_dict(capability)), capability)
        self.assertEqual(ShotImageAttemptSpec(**model_to_dict(spec)), spec)
        self.assertEqual(spec.references, sources["shot_image_plan"].shot_specs[0].image_references)
        self.assertNotIn("image_prompt", model_to_dict(spec))

        for payload, field in (
            (model_to_dict(capability), "max_reference_images"),
            (model_to_dict(spec), "episode_no"),
        ):
            tampered = copy.deepcopy(payload)
            tampered[field] = True
            model = ShotImageProviderCapability if field == "max_reference_images" else ShotImageAttemptSpec
            with self.assertRaises(ValueError):
                model(**tampered)

    def test_capability_mismatch_blocks_before_attempt_build(self) -> None:
        sources = self._seed_attempt_sources("attempt-capability-block")
        unsupported = self._capability(0)
        with self.assertRaisesRegex(ValueError, "rejected"):
            drama_shot_image_attempts.build_shot_image_attempt_spec(
                sources["shot_image_plan"],
                sources["candidate_manifest"],
                shot_id=sources["shot_id"],
                capability=unsupported,
                provider_fingerprint=sources["provider_fingerprint"],
            )

    def test_started_receipt_and_completion_transitions_are_guarded(self) -> None:
        sources = self._seed_attempt_sources("attempt-transitions")
        spec = self._spec(sources)
        ledger = drama_shot_image_attempts.build_empty_shot_image_attempt_ledger(
            sources["shot_image_plan"]
        )
        ledger, started = drama_shot_image_attempts.start_shot_image_attempt(
            ledger,
            spec,
            expected_ledger_fingerprint=ledger.ledger_fingerprint,
        )
        self.assertEqual(started.status, "started")
        self.assertEqual(ShotImageAttemptRecord(**model_to_dict(started)), started)
        with self.assertRaisesRegex(ValueError, "rejected"):
            drama_shot_image_attempts.start_shot_image_attempt(
                ledger,
                spec,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
            )

        payload = self._png()
        from src.drama_shot_image_candidate_store import _candidate_payload_identity

        identity = _candidate_payload_identity(payload)
        receipt = drama_shot_image_attempts.build_shot_image_attempt_receipt(
            started,
            artifact_sha256=identity[0],
            artifact_size_bytes=identity[1],
            width=identity[2],
            height=identity[3],
        )
        self.assertEqual(ShotImageAttemptArtifactReceipt(**model_to_dict(receipt)), receipt)
        ledger, received = drama_shot_image_attempts.record_shot_image_artifact_received(
            ledger,
            started,
            receipt,
            expected_ledger_fingerprint=ledger.ledger_fingerprint,
        )
        self.assertEqual(received.status, "artifact_received")
        self.assertEqual(EpisodeShotImageAttemptLedger(**model_to_dict(ledger)), ledger)

    def test_not_sent_release_only_removes_latest_exact_started_marker(self) -> None:
        sources = self._seed_attempt_sources("attempt-not-sent")
        spec = self._spec(sources)
        empty = drama_shot_image_attempts.build_empty_shot_image_attempt_ledger(
            sources["shot_image_plan"]
        )
        ledger, started = drama_shot_image_attempts.start_shot_image_attempt(
            empty,
            spec,
            expected_ledger_fingerprint=empty.ledger_fingerprint,
        )
        released = drama_shot_image_attempts.discard_not_sent_shot_image_attempt(
            ledger,
            started,
            expected_ledger_fingerprint=ledger.ledger_fingerprint,
        )
        self.assertEqual(released.attempts, [])
        self.assertGreater(released.revision, ledger.revision)
