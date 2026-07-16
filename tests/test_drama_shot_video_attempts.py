"""iter117: provider-neutral D3 capability and attempt state transitions."""

from __future__ import annotations

import copy

from src import drama_shot_video_attempts, drama_shot_video_candidates
from src.drama_schemas import (
    EpisodeShotVideoAttemptLedger,
    ShotVideoAttemptArtifactReceipt,
    ShotVideoAttemptRecord,
    ShotVideoAttemptSpec,
    ShotVideoProviderCapability,
    ShotVideoSubmissionGate,
    ShotVideoSubmissionReceipt,
    ShotVideoTerminalReceipt,
)
from src.schemas import model_to_dict
from tests._drama_shot_video_attempt_base import DramaShotVideoAttemptFixture


class DramaShotVideoAttemptPureTests(DramaShotVideoAttemptFixture):
    def _spec(self, sources, **overrides):
        values = {
            "mode": "reference_to_video",
            "output_width": 16,
            "output_height": 16,
        }
        values.update(overrides)
        return drama_shot_video_attempts.build_shot_video_attempt_spec(
            sources["video_plan"],
            sources["video_candidate_manifest"],
            shot_id=sources["shot_id"],
            capability=sources["capability"],
            submission_gate=sources["gate"],
            **values,
        )

    def test_capability_gate_and_spec_are_strict_byte_stable(self) -> None:
        sources = self._seed_video_attempt_sources("video-attempt-pure-contract")
        capability = sources["capability"]
        gate = sources["gate"]
        spec = self._spec(sources)
        self.assertEqual(ShotVideoProviderCapability(**model_to_dict(capability)), capability)
        self.assertEqual(ShotVideoSubmissionGate(**model_to_dict(gate)), gate)
        self.assertEqual(ShotVideoAttemptSpec(**model_to_dict(spec)), spec)
        request = sources["video_plan"].shot_specs[0]
        self.assertEqual(spec.first_frame, request.first_frame)
        self.assertEqual(spec.tail_frame, request.tail_frame)
        self.assertEqual(spec.ordered_references, request.ordered_references)
        self.assertNotIn("visual_action", model_to_dict(spec))
        for model, payload, field in (
            (ShotVideoProviderCapability, model_to_dict(capability), "max_reference_images"),
            (ShotVideoSubmissionGate, model_to_dict(gate), "max_submit_calls"),
            (ShotVideoAttemptSpec, model_to_dict(spec), "episode_no"),
        ):
            tampered = copy.deepcopy(payload)
            tampered[field] = True
            with self.assertRaises(ValueError):
                model(**tampered)

    def test_capability_and_budget_block_before_attempt_build(self) -> None:
        sources = self._seed_video_attempt_sources("video-attempt-pure-block")
        sources["capability"] = self._capability(
            [item.target_duration_seconds for item in sources["video_plan"].shot_specs],
            max_references=0,
        )
        with self.assertRaisesRegex(ValueError, "rejected"):
            self._spec(sources)
        with self.assertRaisesRegex(ValueError, "authorization"):
            self._gate(budget=0, estimate=1)

    def test_started_submitted_terminal_artifact_and_completion_are_guarded(self) -> None:
        sources = self._seed_video_attempt_sources("video-attempt-pure-transitions")
        spec = self._spec(sources)
        ledger = drama_shot_video_attempts.build_empty_shot_video_attempt_ledger(
            sources["video_plan"]
        )
        ledger, started = drama_shot_video_attempts.start_shot_video_attempt(
            ledger,
            spec,
            expected_ledger_fingerprint=ledger.ledger_fingerprint,
        )
        self.assertEqual(started.status, "started")
        self.assertEqual(ShotVideoAttemptRecord(**model_to_dict(started)), started)
        submission = drama_shot_video_attempts.build_shot_video_submission_receipt(
            started, "task-1"
        )
        self.assertEqual(ShotVideoSubmissionReceipt(**model_to_dict(submission)), submission)
        ledger, submitted = drama_shot_video_attempts.record_shot_video_submitted(
            ledger,
            started,
            submission,
            expected_ledger_fingerprint=ledger.ledger_fingerprint,
        )
        terminal = drama_shot_video_attempts.build_shot_video_terminal_receipt(
            submitted,
            terminal_status="succeeded",
            result_token="result-1",
            cost_reported=True,
            actual_cost_microunits=10,
        )
        self.assertEqual(ShotVideoTerminalReceipt(**model_to_dict(terminal)), terminal)
        ledger, provider_done = drama_shot_video_attempts.record_shot_video_terminal(
            ledger,
            submitted,
            terminal,
            expected_ledger_fingerprint=ledger.ledger_fingerprint,
        )
        data = self._mp4_for_duration(spec.target_duration_seconds)
        from src.drama_shot_video_candidate_store import _candidate_payload_identity

        identity = _candidate_payload_identity(data)
        receipt = drama_shot_video_attempts.build_shot_video_artifact_receipt(
            provider_done,
            artifact_sha256=identity[0],
            artifact_size_bytes=identity[1],
            duration_milliseconds=identity[2],
            width=identity[3],
            height=identity[4],
            has_audio_track=identity[5],
        )
        self.assertEqual(ShotVideoAttemptArtifactReceipt(**model_to_dict(receipt)), receipt)
        ledger, received = drama_shot_video_attempts.record_shot_video_artifact_received(
            ledger,
            provider_done,
            receipt,
            expected_ledger_fingerprint=ledger.ledger_fingerprint,
        )
        self.assertEqual(received.status, "artifact_received")
        self.assertEqual(EpisodeShotVideoAttemptLedger(**model_to_dict(ledger)), ledger)

    def test_four_outcome_classes_are_exhaustive(self) -> None:
        sources = self._seed_video_attempt_sources("video-attempt-pure-outcomes")
        spec = self._spec(sources)
        empty = drama_shot_video_attempts.build_empty_shot_video_attempt_ledger(
            sources["video_plan"]
        )
        ledger, started = drama_shot_video_attempts.start_shot_video_attempt(
            empty, spec, expected_ledger_fingerprint=empty.ledger_fingerprint
        )
        self.assertEqual(drama_shot_video_attempts.classify_shot_video_attempt(started), "unknown")
        not_sent_ledger, not_sent = drama_shot_video_attempts.record_shot_video_not_sent(
            ledger, started, expected_ledger_fingerprint=ledger.ledger_fingerprint
        )
        self.assertEqual(drama_shot_video_attempts.classify_shot_video_attempt(not_sent), "not_sent")
        next_ledger, next_started = drama_shot_video_attempts.start_shot_video_attempt(
            not_sent_ledger,
            spec,
            expected_ledger_fingerprint=not_sent_ledger.ledger_fingerprint,
        )
        submission = drama_shot_video_attempts.build_shot_video_submission_receipt(
            next_started, "task-2"
        )
        next_ledger, submitted = drama_shot_video_attempts.record_shot_video_submitted(
            next_ledger,
            next_started,
            submission,
            expected_ledger_fingerprint=next_ledger.ledger_fingerprint,
        )
        self.assertEqual(drama_shot_video_attempts.classify_shot_video_attempt(submitted), "submitted")
        terminal = drama_shot_video_attempts.build_shot_video_terminal_receipt(
            submitted,
            terminal_status="failed",
            result_token=None,
            cost_reported=False,
            actual_cost_microunits=None,
        )
        _ledger, failed = drama_shot_video_attempts.record_shot_video_terminal(
            next_ledger,
            submitted,
            terminal,
            expected_ledger_fingerprint=next_ledger.ledger_fingerprint,
        )
        self.assertEqual(drama_shot_video_attempts.classify_shot_video_attempt(failed), "terminal")

    def test_episode_two_attempt_identity_and_staging_path_are_scoped(self) -> None:
        sources = self._seed_video_attempt_sources("video-attempt-pure-episode-two")
        plan = self._episode_plan_variant(sources["video_plan"], 2)
        manifest = drama_shot_video_candidates.build_episode_shot_video_candidate_manifest(plan)
        capability = self._capability(
            [item.target_duration_seconds for item in plan.shot_specs]
        )
        gate = self._gate(
            episode_no=2,
            shot_id=plan.shot_specs[0].shot_id,
            request_fingerprint=plan.shot_specs[0].spec_fingerprint,
        )
        spec = drama_shot_video_attempts.build_shot_video_attempt_spec(
            plan,
            manifest,
            shot_id=plan.shot_specs[0].shot_id,
            capability=capability,
            submission_gate=gate,
            mode="reference_to_video",
            output_width=16,
            output_height=16,
        )
        ledger = drama_shot_video_attempts.build_empty_shot_video_attempt_ledger(plan)
        ledger, record = drama_shot_video_attempts.start_shot_video_attempt(
            ledger,
            spec,
            expected_ledger_fingerprint=ledger.ledger_fingerprint,
        )
        self.assertEqual((spec.episode_no, ledger.episode_no), (2, 2))
        self.assertTrue(record.staging_path.startswith("logs/drama_shot_videos/episode_02/"))
