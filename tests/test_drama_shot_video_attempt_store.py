"""iter117: strict D3 submit-once, poll/download, and D2 bridge behavior."""

from __future__ import annotations

import os
import json
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from src import (
    drama_shot_video_attempts,
    drama_shot_video_attempt_store as store,
    drama_shot_video_candidate_store,
    drama_shot_video_candidates,
    drama_shot_video_store,
    paths,
)
from src.secure_http import RequestNotSentError
from tests._drama_shot_video_attempt_base import DramaShotVideoAttemptFixture


class _FakeAdapter:
    def __init__(
        self,
        *,
        polls: list[store.ShotVideoPollResult] | None = None,
        submit_error: BaseException | None = None,
        poll_error: BaseException | None = None,
        download_error: BaseException | None = None,
        marker: int = 0,
        identity: store.ShotVideoAdapterIdentity | None = None,
        fixed_task_id: str | None = None,
        fixed_result_token: str | None = None,
    ) -> None:
        self.poll_results = list(
            polls
            or [
                store.ShotVideoPollResult(
                    "succeeded",
                    result_token="result-1",
                    cost_reported=True,
                    actual_cost_microunits=10,
                )
            ]
        )
        self.submit_error = submit_error
        self.poll_error = poll_error
        self.download_error = download_error
        self.marker = marker
        self.identity = identity
        self.identity_explicit = identity is not None
        self.fixed_task_id = fixed_task_id
        self.fixed_result_token = fixed_result_token
        self.submits = 0
        self.polls = 0
        self.downloads = 0

    def submit(self, spec, *, prompt, frame_bytes, reference_bytes):
        self.submits += 1
        if self.submit_error is not None:
            raise self.submit_error
        if not prompt or not frame_bytes or len(reference_bytes) != len(spec.ordered_references):
            raise AssertionError("adapter did not receive exact D1 inputs")
        return self.fixed_task_id or f"task-{spec.input_fingerprint[:24]}-{self.submits}"

    def poll(self, spec, submission):
        self.polls += 1
        if self.poll_error is not None:
            raise self.poll_error
        if self.poll_results:
            result = self.poll_results.pop(0)
            if result.state == "succeeded" and self.fixed_result_token is not None:
                return store.ShotVideoPollResult(
                    "succeeded",
                    result_token=self.fixed_result_token,
                    cost_reported=result.cost_reported,
                    actual_cost_microunits=result.actual_cost_microunits,
                )
            if result.state == "succeeded" and result.result_token == "result-1":
                return store.ShotVideoPollResult(
                    "succeeded",
                    result_token=f"result-{spec.input_fingerprint[:24]}",
                    cost_reported=result.cost_reported,
                    actual_cost_microunits=result.actual_cost_microunits,
                )
            return result
        return store.ShotVideoPollResult("pending")

    def download(self, spec, submission, terminal):
        self.downloads += 1
        if self.download_error is not None:
            raise self.download_error
        return DramaShotVideoAttemptFixture._mp4_for_duration(
            spec.target_duration_seconds,
            self.marker,
        )


class DramaShotVideoAttemptStoreTests(DramaShotVideoAttemptFixture):
    def _run(
        self,
        name: str,
        sources,
        adapter,
        *,
        shot_id: str | None = None,
        gate=None,
        start_new_attempt: bool = False,
    ):
        target_shot_id = shot_id or sources["shot_id"]
        current_gate = gate or sources["gate"]
        if gate is None and current_gate.authorized_shot_id != target_shot_id:
            request = next(
                item
                for item in sources["video_plan"].shot_specs
                if item.shot_id == target_shot_id
            )
            current_gate = self._gate(
                episode_no=sources["video_plan"].episode_no,
                shot_id=target_shot_id,
                request_fingerprint=request.spec_fingerprint,
            )
        if not adapter.identity_explicit:
            adapter.identity = store.shot_video_adapter_identity_from_gate(
                current_gate
            )
        return store.run_shot_video_attempt_with_adapter(
            name,
            shot_id=target_shot_id,
            capability=sources["capability"],
            submission_gate=current_gate,
            mode="reference_to_video",
            output_width=16,
            output_height=16,
            adapter=adapter,
            expected_manifest_fingerprint=sources[
                "video_candidate_manifest"
            ].manifest_fingerprint,
            start_new_attempt=start_new_attempt,
        )

    def test_success_submits_once_bridges_candidate_and_replay_is_zero_submit(self) -> None:
        name = "video-attempt-store-success"
        sources = self._seed_video_attempt_sources(name)
        adapter = _FakeAdapter()
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            record = self._run(name, sources, adapter)
            replay = self._run(name, sources, adapter)
        self.assertEqual(record, replay)
        self.assertEqual(record.status, "succeeded")
        self.assertEqual((adapter.submits, adapter.polls, adapter.downloads), (1, 1, 1))
        manifest = drama_shot_video_candidate_store.load_fresh_episode_shot_video_candidates(
            name
        )
        pool = next(item for item in manifest.shots if item.shot_id == sources["shot_id"])
        self.assertEqual([item.candidate_id for item in pool.candidates], [record.candidate_id])
        self.assertIsNone(pool.selected)
        self.assertEqual(
            drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(
                name
            ).coverage.status,
            "incomplete",
        )
        self.assertTrue((paths.workspace_root(name) / record.staging_path).is_file())

    def test_pending_resume_only_polls_and_downloads(self) -> None:
        name = "video-attempt-store-pending"
        sources = self._seed_video_attempt_sources(name)
        adapter = _FakeAdapter(
            polls=[
                store.ShotVideoPollResult("pending"),
                store.ShotVideoPollResult(
                    "succeeded",
                    result_token="result-1",
                    cost_reported=False,
                    actual_cost_microunits=None,
                ),
            ]
        )
        submitted = self._run(name, sources, adapter)
        self.assertEqual(submitted.status, "submitted")
        completed = store.resume_shot_video_attempt(
            name,
            shot_id=sources["shot_id"],
            capability=sources["capability"],
            submission_gate=sources["gate"],
            adapter=adapter,
        )
        self.assertEqual(completed.status, "succeeded")
        self.assertEqual((adapter.submits, adapter.polls, adapter.downloads), (1, 2, 1))

    def test_not_sent_is_durable_and_resume_never_submits(self) -> None:
        name = "video-attempt-store-not-sent"
        sources = self._seed_video_attempt_sources(name)
        adapter = _FakeAdapter(submit_error=RequestNotSentError("secret not sent"))
        with self.assertRaisesRegex(ValueError, "proven not sent"):
            self._run(name, sources, adapter)
        ledger = store.load_episode_shot_video_attempts(name)
        self.assertEqual(ledger.attempts[-1].status, "not_sent")
        safe = _FakeAdapter(
            identity=store.shot_video_adapter_identity_from_gate(sources["gate"])
        )
        with self.assertRaises(store.ShotVideoAttemptReconciliationRequired):
            store.resume_shot_video_attempt(
                name,
                shot_id=sources["shot_id"],
                capability=sources["capability"],
                submission_gate=sources["gate"],
                adapter=safe,
            )
        with self.assertRaises(store.ShotVideoAttemptReconciliationRequired):
            self._run(name, sources, safe)
        self.assertEqual((adapter.submits, safe.submits), (1, 0))
        retried = self._run(
            name,
            sources,
            safe,
            start_new_attempt=True,
        )
        self.assertEqual(retried.status, "succeeded")
        self.assertEqual((adapter.submits, safe.submits), (1, 1))

    def test_unknown_submission_is_durable_and_zero_auto_resubmit(self) -> None:
        name = "video-attempt-store-unknown"
        sources = self._seed_video_attempt_sources(name)
        adapter = _FakeAdapter(submit_error=store.ShotVideoProviderNetworkError("secret"))
        with self.assertRaises(store.ShotVideoAttemptReconciliationRequired):
            self._run(name, sources, adapter)
        safe = _FakeAdapter()
        with self.assertRaises(store.ShotVideoAttemptReconciliationRequired):
            self._run(name, sources, safe)
        ledger = store.load_episode_shot_video_attempts(name)
        self.assertEqual(ledger.attempts[-1].status, "submission_unknown")
        self.assertEqual((adapter.submits, safe.submits), (1, 0))
        inspection = store.inspect_episode_shot_video_attempts(name)
        self.assertEqual(inspection.state, "reconciliation_required")
        self.assertEqual(inspection.unknown_attempt_ids, [ledger.attempts[-1].attempt_id])

    def test_provider_failure_is_terminal_and_never_downloads(self) -> None:
        name = "video-attempt-store-provider-failed"
        sources = self._seed_video_attempt_sources(name)
        adapter = _FakeAdapter(
            polls=[
                store.ShotVideoPollResult(
                    "failed",
                    cost_reported=True,
                    actual_cost_microunits=12,
                )
            ]
        )
        record = self._run(name, sources, adapter)
        self.assertEqual(record.status, "provider_failed")
        self.assertEqual((adapter.submits, adapter.polls, adapter.downloads), (1, 1, 0))
        inspection = store.inspect_episode_shot_video_attempts(name)
        self.assertEqual(inspection.state, "needs_attempts")
        self.assertEqual(inspection.terminal_attempt_ids, [record.attempt_id])

        replay = self._run(name, sources, adapter)
        self.assertEqual(replay, record)
        self.assertEqual((adapter.submits, adapter.polls, adapter.downloads), (1, 1, 0))

    def test_once_authorization_is_request_bound_and_wrong_adapter_is_zero_call(self) -> None:
        name = "video-attempt-store-once-binding"
        sources = self._seed_video_attempt_sources(name)
        wrong_identity = store.ShotVideoAdapterIdentity(
            **{
                **store.shot_video_adapter_identity_from_gate(sources["gate"]).__dict__,
                "model_fingerprint": "9" * 64,
            }
        )
        wrong = _FakeAdapter(identity=wrong_identity)
        with self.assertRaises(store.ShotVideoAttemptReconciliationRequired):
            self._run(name, sources, wrong)
        self.assertEqual((wrong.submits, wrong.polls, wrong.downloads), (0, 0, 0))
        self.assertFalse(store.shot_video_attempt_ledger_path(name).exists())

        other_shot = sources["video_plan"].shot_specs[1].shot_id
        bound_elsewhere = _FakeAdapter()
        with self.assertRaisesRegex(ValueError, "rejected"):
            self._run(
                name,
                sources,
                bound_elsewhere,
                shot_id=other_shot,
                gate=sources["gate"],
            )
        self.assertEqual(bound_elsewhere.submits, 0)

    def test_wrong_adapter_blocks_resume_before_poll_or_download(self) -> None:
        name = "video-attempt-store-wrong-resume-adapter"
        sources = self._seed_video_attempt_sources(name)
        pending = _FakeAdapter(polls=[store.ShotVideoPollResult("pending")])
        self.assertEqual(self._run(name, sources, pending).status, "submitted")
        wrong_identity = store.ShotVideoAdapterIdentity(
            **{
                **store.shot_video_adapter_identity_from_gate(sources["gate"]).__dict__,
                "backend_id": "other-backend",
            }
        )
        wrong = _FakeAdapter(identity=wrong_identity)
        with self.assertRaises(store.ShotVideoAttemptReconciliationRequired):
            store.resume_shot_video_attempt(
                name,
                shot_id=sources["shot_id"],
                capability=sources["capability"],
                submission_gate=sources["gate"],
                adapter=wrong,
            )
        self.assertEqual((wrong.submits, wrong.polls, wrong.downloads), (0, 0, 0))

    def test_provider_task_and_result_collisions_fail_closed(self) -> None:
        name = "video-attempt-store-provider-collisions"
        sources = self._seed_video_attempt_sources(name)
        first, second, third = sources["video_plan"].shot_specs[:3]
        first_adapter = _FakeAdapter(
            fixed_task_id="shared-task",
            fixed_result_token="shared-result",
        )
        self.assertEqual(
            self._run(name, sources, first_adapter, shot_id=first.shot_id).status,
            "succeeded",
        )
        sources["video_candidate_manifest"] = (
            drama_shot_video_candidate_store.load_fresh_episode_shot_video_candidates(
                name
            )
        )

        task_collision = _FakeAdapter(fixed_task_id="shared-task")
        with self.assertRaises(store.ShotVideoAttemptReconciliationRequired):
            self._run(name, sources, task_collision, shot_id=second.shot_id)
        self.assertEqual(
            (task_collision.submits, task_collision.polls, task_collision.downloads),
            (1, 0, 0),
        )

        sources["video_candidate_manifest"] = (
            drama_shot_video_candidate_store.load_fresh_episode_shot_video_candidates(
                name
            )
        )
        result_collision = _FakeAdapter(fixed_result_token="shared-result")
        with self.assertRaises(store.DramaShotVideoAttemptStoreError):
            self._run(name, sources, result_collision, shot_id=third.shot_id)
        self.assertEqual(
            (result_collision.submits, result_collision.polls, result_collision.downloads),
            (1, 1, 0),
        )

    def test_unknown_can_be_explicitly_closed_then_only_new_authorization_retries(self) -> None:
        name = "video-attempt-store-close-unknown"
        sources = self._seed_video_attempt_sources(name)
        failed = _FakeAdapter(submit_error=OSError("response lost"))
        with self.assertRaises(store.ShotVideoAttemptReconciliationRequired):
            self._run(name, sources, failed)
        unknown = store.load_episode_shot_video_attempts(name).attempts[-1]
        closed = store.close_unknown_shot_video_attempt_in_store(
            name,
            shot_id=sources["shot_id"],
            expected_record_fingerprint=unknown.record_fingerprint,
            resolution="provider_case_closed",
            evidence_fingerprint="8" * 64,
        )
        self.assertEqual(closed.status, "closed_unknown")
        self.assertEqual(
            store.inspect_episode_shot_video_attempts(name).terminal_attempt_ids,
            [closed.attempt_id],
        )
        same_gate = _FakeAdapter()
        self.assertEqual(self._run(name, sources, same_gate), closed)
        self.assertEqual(same_gate.submits, 0)

        request = sources["video_plan"].shot_specs[0]
        new_gate = self._gate(
            episode_no=1,
            shot_id=request.shot_id,
            request_fingerprint=request.spec_fingerprint,
            authorization_nonce="operator-approved-retry",
        )
        retried = _FakeAdapter()
        record = self._run(
            name,
            sources,
            retried,
            gate=new_gate,
            start_new_attempt=True,
        )
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(retried.submits, 1)

    def test_local_fake_adapter_is_offline_and_submit_once(self) -> None:
        name = "video-attempt-store-local-fake"
        sources = self._seed_video_attempt_sources(name)
        request = sources["video_plan"].shot_specs[0]
        adapter = store.LocalFakeShotVideoAdapter(
            identity=store.shot_video_adapter_identity_from_gate(sources["gate"]),
            output_bytes=self._mp4_for_duration(request.target_duration_seconds),
        )
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            record = store.run_shot_video_attempt_with_adapter(
                name,
                shot_id=request.shot_id,
                capability=sources["capability"],
                submission_gate=sources["gate"],
                mode="reference_to_video",
                output_width=16,
                output_height=16,
                adapter=adapter,
                expected_manifest_fingerprint=sources[
                    "video_candidate_manifest"
                ].manifest_fingerprint,
            )
        self.assertEqual(record.status, "succeeded")
        self.assertEqual(
            (adapter.submit_calls, adapter.poll_calls, adapter.download_calls),
            (1, 1, 1),
        )

    def test_episode_two_store_bridge_reaches_explicit_selection_coverage(self) -> None:
        name = "video-attempt-store-episode-two"
        sources = self._seed_video_attempt_sources(name)
        plan = self._episode_plan_variant(sources["video_plan"], 2)
        manifest_ref = {
            "value": drama_shot_video_candidates.build_episode_shot_video_candidate_manifest(
                plan
            )
        }
        capability = self._capability(
            [item.target_duration_seconds for item in plan.shot_specs]
        )

        def append_in_memory(
            _workspace,
            *,
            shot_id,
            mp4_bytes,
            episode_no,
            expected_manifest_fingerprint,
        ):
            self.assertEqual(episode_no, 2)
            identity = drama_shot_video_candidate_store._candidate_payload_identity(
                mp4_bytes
            )
            candidate = drama_shot_video_candidates.build_shot_video_candidate(
                plan,
                shot_id=shot_id,
                artifact_sha256=identity[0],
                artifact_size_bytes=identity[1],
                duration_milliseconds=identity[2],
                width=identity[3],
                height=identity[4],
                has_audio_track=identity[5],
            )
            manifest_ref["value"] = drama_shot_video_candidates.append_shot_video_candidate(
                manifest_ref["value"],
                plan,
                candidate,
                expected_manifest_fingerprint=expected_manifest_fingerprint,
            )
            return manifest_ref["value"], candidate

        with (
            patch.object(
                store,
                "load_fresh_episode_shot_video_plan",
                side_effect=lambda _workspace, episode_no=1: (
                    plan if episode_no == 2 else sources["video_plan"]
                ),
            ),
            patch.object(
                store,
                "load_fresh_episode_shot_video_candidates",
                side_effect=lambda _workspace, episode_no=1: (
                    manifest_ref["value"]
                    if episode_no == 2
                    else sources["video_candidate_manifest"]
                ),
            ),
            patch.object(
                store,
                "_input_bytes",
                side_effect=lambda _workspace, spec: (
                    (b"synthetic-frame",),
                    tuple(b"synthetic-reference" for _ in spec.ordered_references),
                ),
            ),
            patch.object(
                store,
                "append_local_shot_video_candidate",
                side_effect=append_in_memory,
            ),
            patch.object(store, "_validate_exact_candidate_artifact", return_value=None),
            patch.object(socket, "socket", side_effect=AssertionError("network")),
        ):
            records = []
            for index, request in enumerate(plan.shot_specs):
                gate = self._gate(
                    episode_no=2,
                    shot_id=request.shot_id,
                    request_fingerprint=request.spec_fingerprint,
                    authorization_nonce=f"episode-two-{index}",
                )
                adapter = store.LocalFakeShotVideoAdapter(
                    identity=store.shot_video_adapter_identity_from_gate(gate),
                    output_bytes=self._mp4_for_duration(
                        request.target_duration_seconds,
                        marker=index,
                    ),
                )
                records.append(
                    store.run_shot_video_attempt_with_adapter(
                        name,
                        episode_no=2,
                        shot_id=request.shot_id,
                        capability=capability,
                        submission_gate=gate,
                        mode="reference_to_video",
                        output_width=16,
                        output_height=16,
                        adapter=adapter,
                        expected_manifest_fingerprint=manifest_ref[
                            "value"
                        ].manifest_fingerprint,
                    )
                )

        self.assertTrue(all(item.status == "succeeded" for item in records))
        self.assertTrue(
            all(item.spec.episode_no == 2 for item in records)
        )
        self.assertEqual(
            drama_shot_video_candidates.shot_video_coverage(
                manifest_ref["value"], plan
            ).status,
            "incomplete",
        )
        for pool in list(manifest_ref["value"].shots):
            candidate = pool.candidates[0]
            manifest_ref["value"] = drama_shot_video_candidates.select_shot_video_candidate(
                manifest_ref["value"],
                plan,
                shot_id=pool.shot_id,
                selection={
                    "candidate_id": candidate.candidate_id,
                    "candidate_fingerprint": candidate.candidate_fingerprint,
                },
                expected_selection_revision=pool.selection_revision,
                expected_current_selection=None,
                expected_manifest_fingerprint=manifest_ref["value"].manifest_fingerprint,
            )
        self.assertEqual(
            drama_shot_video_candidates.shot_video_coverage(
                manifest_ref["value"], plan
            ).status,
            "ready",
        )

    def test_capability_and_manifest_gates_block_before_submit(self) -> None:
        name = "video-attempt-store-gate"
        sources = self._seed_video_attempt_sources(name)
        adapter = _FakeAdapter()
        sources["capability"] = self._capability(
            [item.target_duration_seconds for item in sources["video_plan"].shot_specs],
            max_references=0,
        )
        with self.assertRaisesRegex(ValueError, "rejected"):
            self._run(name, sources, adapter)
        self.assertEqual(adapter.submits, 0)
        self.assertFalse(store.shot_video_attempt_ledger_path(name).exists())

    def test_download_failure_retries_download_without_resubmit(self) -> None:
        name = "video-attempt-store-download-retry"
        sources = self._seed_video_attempt_sources(name)
        adapter = _FakeAdapter(download_error=OSError("secret signed url"))
        with self.assertRaisesRegex(ValueError, "download failed"):
            self._run(name, sources, adapter)
        ledger = store.load_episode_shot_video_attempts(name)
        self.assertEqual(ledger.attempts[-1].status, "provider_succeeded")
        adapter.download_error = None
        record = store.resume_shot_video_attempt(
            name,
            shot_id=sources["shot_id"],
            capability=sources["capability"],
            submission_gate=sources["gate"],
            adapter=adapter,
        )
        self.assertEqual(record.status, "succeeded")
        self.assertEqual((adapter.submits, adapter.polls, adapter.downloads), (1, 1, 2))

    def test_submitted_attempt_finishes_paid_recovery_before_source_reconciliation(self) -> None:
        name = "video-attempt-store-source-drift"
        sources = self._seed_video_attempt_sources(name)
        adapter = _FakeAdapter(
            polls=[
                store.ShotVideoPollResult("pending"),
                store.ShotVideoPollResult(
                    "succeeded",
                    result_token="result-1",
                    cost_reported=False,
                    actual_cost_microunits=None,
                ),
            ]
        )
        self.assertEqual(self._run(name, sources, adapter).status, "submitted")
        drama_shot_video_store.shot_video_plan_path(name).unlink()
        with self.assertRaisesRegex(ValueError, "resume was rejected"):
            store.resume_shot_video_attempt(
                name,
                shot_id=sources["shot_id"],
                capability=sources["capability"],
                submission_gate=sources["gate"],
                adapter=adapter,
            )
        ledger = store.load_episode_shot_video_attempts(name)
        self.assertEqual(ledger.attempts[-1].status, "artifact_received")
        self.assertEqual((adapter.submits, adapter.polls, adapter.downloads), (1, 2, 1))

    def test_provider_or_authorization_drift_blocks_poll(self) -> None:
        name = "video-attempt-store-provider-drift"
        sources = self._seed_video_attempt_sources(name)
        adapter = _FakeAdapter(polls=[store.ShotVideoPollResult("pending")])
        self.assertEqual(self._run(name, sources, adapter).status, "submitted")
        changed = _FakeAdapter()
        with self.assertRaises(store.ShotVideoAttemptReconciliationRequired):
            store.resume_shot_video_attempt(
                name,
                shot_id=sources["shot_id"],
                capability=sources["capability"],
                submission_gate=self._gate(provider="e"),
                adapter=changed,
            )
        self.assertEqual((adapter.submits, changed.submits, changed.polls), (1, 0, 0))

    def test_all_shots_require_explicit_d2_selection_before_ready_coverage(self) -> None:
        name = "video-attempt-store-coverage"
        sources = self._seed_video_attempt_sources(name)
        records = []
        for index, spec in enumerate(sources["video_plan"].shot_specs):
            sources["video_candidate_manifest"] = (
                drama_shot_video_candidate_store.load_fresh_episode_shot_video_candidates(name)
            )
            records.append(
                self._run(name, sources, _FakeAdapter(marker=index), shot_id=spec.shot_id)
            )
        inspection = drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(name)
        self.assertEqual(inspection.coverage.status, "incomplete")
        manifest = inspection.manifest
        for record in records:
            candidate = next(
                item
                for pool in manifest.shots
                for item in pool.candidates
                if item.candidate_id == record.candidate_id
            )
            manifest = self._select_video_candidate(name, manifest, candidate)
        self.assertEqual(
            drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(
                name
            ).coverage.status,
            "ready",
        )
        self.assertEqual(store.inspect_episode_shot_video_attempts(name).state, "fresh")

    def test_ledger_is_redacted_and_special_files_fail_closed(self) -> None:
        name = "video-attempt-store-redacted"
        sources = self._seed_video_attempt_sources(name)
        record = self._run(name, sources, _FakeAdapter())
        raw = store.shot_video_attempt_ledger_path(name).read_text(encoding="utf-8")
        request = sources["video_plan"].shot_specs[0]
        self.assertNotIn(request.visual_action, raw)
        self.assertNotIn("api_key", raw.lower())
        self.assertNotIn("://", raw)
        self.assertEqual(record.status, "succeeded")

        invalid_name = "video-attempt-store-invalid"
        invalid_sources = self._seed_video_attempt_sources(invalid_name)
        path = store.shot_video_attempt_ledger_path(invalid_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        self.assertEqual(store.inspect_episode_shot_video_attempts(invalid_name).state, "invalid")
        path.unlink()
        os.mkfifo(path)
        self.assertEqual(store.inspect_episode_shot_video_attempts(invalid_name).state, "invalid")
        with self.assertRaises(ValueError):
            self._run(invalid_name, invalid_sources, _FakeAdapter())

    def test_staging_symlink_fifo_directory_and_partial_write_fail_closed(self) -> None:
        for kind in ("symlink", "fifo", "directory", "partial"):
            with self.subTest(kind=kind):
                name = f"video-attempt-staging-{kind}"
                sources = self._seed_video_attempt_sources(name)
                spec = drama_shot_video_attempts.build_shot_video_attempt_spec(
                    sources["video_plan"],
                    sources["video_candidate_manifest"],
                    shot_id=sources["shot_id"],
                    capability=sources["capability"],
                    submission_gate=sources["gate"],
                    mode="reference_to_video",
                    output_width=16,
                    output_height=16,
                )
                ledger = drama_shot_video_attempts.build_empty_shot_video_attempt_ledger(
                    sources["video_plan"]
                )
                _ledger, record = drama_shot_video_attempts.start_shot_video_attempt(
                    ledger,
                    spec,
                    expected_ledger_fingerprint=ledger.ledger_fingerprint,
                )
                target = paths.workspace_root(name) / record.staging_path
                target.parent.mkdir(parents=True, exist_ok=True)
                if kind == "symlink":
                    target.symlink_to("missing.mp4")
                elif kind == "fifo":
                    os.mkfifo(target)
                elif kind == "directory":
                    target.mkdir()
                data = self._mp4_for_duration(spec.target_duration_seconds)
                if kind == "partial":
                    real_write = os.write
                    calls = 0

                    def short_then_fail(fd, payload):
                        nonlocal calls
                        calls += 1
                        if calls == 1:
                            return real_write(fd, payload[: max(1, len(payload) // 2)])
                        raise OSError("simulated short write")

                    with patch.object(os, "write", side_effect=short_then_fail):
                        with self.assertRaisesRegex(ValueError, "written safely"):
                            store._write_staging_create_only(name, record, data)
                    self.assertFalse(target.exists())
                else:
                    with self.assertRaisesRegex(ValueError, "target is invalid"):
                        store._write_staging_create_only(name, record, data)

    def test_partial_ledger_write_keeps_target_missing_and_cleans_owned_temp(self) -> None:
        name = "video-attempt-ledger-partial"
        sources = self._seed_video_attempt_sources(name)
        ledger = drama_shot_video_attempts.build_empty_shot_video_attempt_ledger(
            sources["video_plan"]
        )
        path = store.shot_video_attempt_ledger_path(name)
        real_write = os.write
        calls = 0

        def short_then_fail(fd, payload):
            nonlocal calls
            calls += 1
            if calls == 1:
                return real_write(fd, payload[: max(1, len(payload) // 2)])
            raise OSError("simulated short write")

        with patch.object(os, "write", side_effect=short_then_fail):
            with self.assertRaisesRegex(ValueError, "written safely"):
                store._write_ledger(name, ledger, expected_target_token=("missing",))
        self.assertFalse(path.exists())
        self.assertFalse(list(path.parent.glob(f".{path.name}.tmp.*")))

    def test_real_process_crash_windows_never_repeat_submit(self) -> None:
        driver = Path(__file__).parent / "support" / "drama_shot_video_attempt_driver.py"
        for mode in (
            "after_started",
            "after_submit",
            "after_submitted",
            "after_terminal",
            "after_download",
            "after_staging",
            "after_artifact",
            "after_candidate",
            "after_succeeded",
        ):
            with self.subTest(mode=mode):
                name = f"video-attempt-crash-{mode.replace('_', '-')}"
                sources = self._seed_video_attempt_sources(name)
                counter = Path(self._tmp.name) / f"{mode}.json"
                counter.write_text(
                    json.dumps({"submit": 0, "poll": 0, "download": 0}),
                    encoding="utf-8",
                )
                env = os.environ.copy()
                env.update(
                    {
                        "DRAGON_RAJA_SKIP_DOTENV": "1",
                        "PYTHON_DOTENV_DISABLED": "1",
                        "OPENAI_MODEL": "mock",
                    }
                )
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(driver),
                        str(paths.WORKSPACE_DIR),
                        name,
                        mode,
                        str(counter),
                    ],
                    cwd=Path(__file__).resolve().parents[1],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertNotEqual(completed.returncode, 0, completed.stderr)
                before = json.loads(counter.read_text(encoding="utf-8"))
                self.assertLessEqual(before["submit"], 1)
                adapter = _FakeAdapter(
                    identity=store.shot_video_adapter_identity_from_gate(
                        sources["gate"]
                    )
                )
                if mode in {"after_started", "after_submit"}:
                    with self.assertRaises(store.ShotVideoAttemptReconciliationRequired):
                        store.resume_shot_video_attempt(
                            name,
                            shot_id=sources["shot_id"],
                            capability=sources["capability"],
                            submission_gate=sources["gate"],
                            adapter=adapter,
                        )
                else:
                    record = store.resume_shot_video_attempt(
                        name,
                        shot_id=sources["shot_id"],
                        capability=sources["capability"],
                        submission_gate=sources["gate"],
                        adapter=adapter,
                    )
                    self.assertEqual(record.status, "succeeded")
                after = json.loads(counter.read_text(encoding="utf-8"))
                self.assertEqual(after["submit"], before["submit"])
                self.assertEqual(adapter.submits, 0)
