from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

from src import drama_video, drama_video_reconciliation as reconciliation
from tests._drama_base import DramaTestBase


class DramaVideoReconciliationTests(DramaTestBase):
    def _prepare_unknown(
        self,
        workspace: str,
        *,
        sample_id: str | None = None,
    ) -> dict:
        from src import drama_video_smoke

        drama_video_smoke._prepare_mock_inputs(workspace)
        inputs = drama_video.load_video_inputs(workspace)
        payload = {
            "status": "submitting",
            "input_fingerprint": inputs.fingerprint,
            "provider_fingerprint": "a" * 64,
            "result_hosts_fingerprint": drama_video.sha256_data(
                ["result.example.test"]
            ),
            "submission_count": 1,
            "updated_at": 1,
        }
        if sample_id == drama_video.ITER143_QUALITY20_SAMPLE_ID:
            prompt_sha256 = hashlib.sha256(
                drama_video._video_prompt(
                    inputs,
                    duration_seconds=drama_video.ITER143_QUALITY20_DURATION_SECONDS,
                ).encode("utf-8")
            ).hexdigest()
            payload.update(
                drama_video._video_authorization(
                    80.0,
                    30.0,
                    80.0,
                    duration_seconds=drama_video.ITER143_QUALITY20_DURATION_SECONDS,
                    sample_id=sample_id,
                    prompt_sha256=prompt_sha256,
                )
            )
        else:
            payload.update(drama_video._video_authorization(3.0, 1.0, 2.0))
        drama_video._write_video_submission(
            workspace,
            payload,
            sample_id=sample_id,
        )
        submission_path = drama_video.video_submission_path(
            workspace, sample_id=sample_id
        )
        before = submission_path.read_bytes()
        inspection = reconciliation.inspect_video_reconciliation(
            workspace,
            sample_id=sample_id,
        )
        self.assertEqual(submission_path.read_bytes(), before)
        return inspection

    def _append(
        self,
        workspace: str,
        inspection: dict,
        *,
        sample_id: str | None = None,
        evidence_fingerprint: str = "c" * 64,
        observed_outcome: str = "still_unknown",
        evidence_kind: str = "task_list_observation",
        recorded_at_ms: int = 1,
        **kwargs,
    ) -> dict:
        return reconciliation.append_video_reconciliation_receipt(
            workspace,
            sample_id=sample_id,
            expected_submission_fingerprint=inspection["submission_fingerprint"],
            expected_reconciliation_generation=inspection["reconciliation_generation"],
            expected_source_revision_fingerprint=inspection["source_revision_fingerprint"],
            expected_revision=inspection["revision"],
            expected_ledger_fingerprint=inspection["ledger_fingerprint"],
            evidence_fingerprint=evidence_fingerprint,
            observed_outcome=observed_outcome,
            evidence_kind=evidence_kind,
            recorded_at_ms=recorded_at_ms,
            **kwargs,
        )

    def test_iter143_task_list_absence_stays_unknown_and_never_unlocks_create(self) -> None:
        workspace = drama_video.ITER143_QUALITY20_AUTHORIZED_WORKSPACE
        sample_id = drama_video.ITER143_QUALITY20_SAMPLE_ID
        inspection = self._prepare_unknown(workspace, sample_id=sample_id)
        self.assertEqual(inspection["observed_outcome"], "still_unknown")
        self.assertEqual(
            drama_video.video_status(workspace, sample_id=sample_id)["state"],
            "submission_unknown",
        )

        ledger = self._append(
            workspace,
            inspection,
            sample_id=sample_id,
            evidence_fingerprint="d" * 64,
            recorded_at_ms=2,
        )
        self.assertEqual(ledger["receipts"][-1]["observed_outcome"], "still_unknown")
        self.assertEqual(
            drama_video.video_status(workspace, sample_id=sample_id)["state"],
            "submission_unknown",
        )

        class NoProviderCalls:
            base_url = "https://video.example.test"
            api_key = "unused"

            def __getattr__(self, _name):
                raise AssertionError("reconciliation must not call provider")

        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "80",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        }
        with patch.dict("os.environ", env, clear=False), patch(
            "src.drama_video._video_provider_fingerprint",
            return_value="a" * 64,
        ):
            with self.assertRaises(drama_video.DramaVideoSubmissionUnknown):
                drama_video.run_video_job(
                    workspace,
                    {
                        "confirm_real_video": True,
                        "budget_cny": 80,
                        "timeout_minutes": 30,
                        "authorization_profile": drama_video.ITER143_QUALITY20_PROFILE,
                    },
                    lambda *_: None,
                    client=NoProviderCalls(),
                )

        refreshed = reconciliation.inspect_video_reconciliation(
            workspace,
            sample_id=sample_id,
        )
        with self.assertRaisesRegex(
            reconciliation.DramaVideoReconciliationError,
            "classification|cannot resolve",
        ):
            self._append(
                workspace,
                refreshed,
                sample_id=sample_id,
                evidence_fingerprint="e" * 64,
                observed_outcome="request_not_sent",
                evidence_kind="task_list_observation",
                recorded_at_ms=3,
            )

    def test_legacy_first_run_stays_unknown_without_source_write_or_provider_call(self) -> None:
        workspace = "video-recon-legacy-first-run"
        self._prepare_unknown(workspace)
        path = drama_video.video_submission_path(workspace)
        before = path.read_bytes()

        class NoProviderCalls:
            base_url = "https://video.example.test"
            api_key = "unused"

            def __getattr__(self, _name):
                raise AssertionError("legacy unknown must not call provider")

        with patch.dict(
            "os.environ",
            {"SD_VIDEO_MODE": "real"},
            clear=False,
        ):
            with self.assertRaises(drama_video.DramaVideoSubmissionUnknown):
                drama_video.run_video_job(
                    workspace,
                    {"resume_submitted": True},
                    lambda *_: None,
                    client=NoProviderCalls(),
                )
        self.assertEqual(path.read_bytes(), before)

    def test_receipts_are_append_only_cas_guarded_and_exact_replay_is_idempotent(self) -> None:
        workspace = "video-reconciliation-cas"
        inspection = self._prepare_unknown(workspace)
        first = self._append(workspace, inspection)
        replay = self._append(workspace, inspection)
        self.assertEqual(replay, first)
        self.assertEqual(replay["revision"], 1)

        with self.assertRaisesRegex(
            reconciliation.DramaVideoReconciliationError,
            "conflicts",
        ):
            self._append(
                workspace,
                inspection,
                evidence_fingerprint="c" * 64,
                observed_outcome="provider_rejected",
                evidence_kind="provider_rejection",
                http_status=400,
                rejection_class="gate_rejected",
            )

        current = reconciliation.inspect_video_reconciliation(workspace)
        second = self._append(
            workspace,
            current,
            evidence_fingerprint="d" * 64,
            evidence_kind="billing_query",
            billing_state="no_record",
            recorded_at_ms=2,
        )
        self.assertEqual(second["revision"], 2)
        with self.assertRaisesRegex(
            reconciliation.DramaVideoReconciliationError,
            "refresh before append",
        ):
            self._append(
                workspace,
                current,
                evidence_fingerprint="e" * 64,
                recorded_at_ms=3,
            )
        latest = reconciliation.inspect_video_reconciliation(workspace)
        with self.assertRaisesRegex(
            reconciliation.DramaVideoReconciliationError,
            "out of order",
        ):
            self._append(
                workspace,
                latest,
                evidence_fingerprint="f" * 64,
                recorded_at_ms=2,
            )

    def test_authoritative_task_or_rejection_resolves_without_exposing_identity(self) -> None:
        submitted_workspace = "video-reconciliation-task"
        inspection = self._prepare_unknown(submitted_workspace)
        self._append(
            submitted_workspace,
            inspection,
            observed_outcome="submitted",
            evidence_kind="task_query",
            provider_task_id="provider-task-private",
        )
        public = drama_video.video_status(submitted_workspace)
        self.assertEqual(public["state"], "submitted")
        self.assertNotIn("provider-task-private", json.dumps(public))
        self.assertNotIn("fingerprint", json.dumps(public))

        class PollOnlyClient:
            base_url = "https://video.example.test"
            api_key = "private-account"

            def __init__(self) -> None:
                self.polls = 0

            def upload_asset(self, **_kwargs):
                raise AssertionError("reconciled task must not upload")

            def create_video_task(self, **_kwargs):
                raise AssertionError("reconciled task must not create")

            def get_task(self, task_id):
                self.polls += 1
                self.assert_task = task_id
                return {"task": {
                    "id": task_id,
                    "status": "completed",
                    "video_url": "https://result.example.test/reconciled.mp4",
                    "cost_cny": 1.0,
                }}

        client = PollOnlyClient()
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_ASSET_PUBLIC_BASE_URL": "https://assets.example.test",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
        }
        with patch.dict("os.environ", env, clear=False), patch(
            "src.drama_video._video_provider_fingerprint",
            return_value="a" * 64,
        ), patch(
            "src.drama_video.download_video",
            return_value=(drama_video._MOCK_MP4, "video/mp4"),
        ), patch(
            "src.drama_video._probe_mp4",
            return_value=drama_video.VideoSpec(5.0, 720, 1280),
        ):
            result = drama_video.run_video_job(
                submitted_workspace,
                {"resume_submitted": True},
                lambda *_: None,
                client=client,
                sleep=lambda _seconds: None,
            )
        self.assertTrue(result["committed"])
        self.assertEqual(client.polls, 1)
        self.assertEqual(client.assert_task, "provider-task-private")

        rejected_workspace = "video-reconciliation-rejected"
        inspection = self._prepare_unknown(rejected_workspace)
        self._append(
            rejected_workspace,
            inspection,
            observed_outcome="provider_rejected",
            evidence_kind="provider_rejection",
            provider_request_id="request-private",
            http_status=400,
            rejection_class="gate_rejected",
        )
        public = drama_video.video_status(rejected_workspace)
        self.assertEqual(public["state"], "provider_rejected")
        rendered = json.dumps(public)
        self.assertNotIn("request-private", rendered)
        self.assertNotIn("fingerprint", rendered)

    def test_resolution_identity_is_frozen_after_first_authoritative_receipt(self) -> None:
        submitted_workspace = "video-reconciliation-frozen-task"
        inspection = self._prepare_unknown(submitted_workspace)
        self._append(
            submitted_workspace,
            inspection,
            observed_outcome="submitted",
            evidence_kind="task_query",
            provider_task_id="provider-task-a",
        )
        resolved = reconciliation.inspect_video_reconciliation(
            submitted_workspace
        )
        with self.assertRaisesRegex(
            reconciliation.DramaVideoReconciliationError,
            "cannot append after resolution",
        ):
            self._append(
                submitted_workspace,
                resolved,
                evidence_fingerprint="d" * 64,
                observed_outcome="submitted",
                evidence_kind="task_query",
                provider_task_id="provider-task-b",
                recorded_at_ms=2,
            )

        rejected_workspace = "video-recon-frozen-rejection"
        inspection = self._prepare_unknown(rejected_workspace)
        self._append(
            rejected_workspace,
            inspection,
            observed_outcome="provider_rejected",
            evidence_kind="provider_rejection",
            provider_request_id="request-a",
            http_status=400,
            rejection_class="gate_rejected",
        )
        resolved = reconciliation.inspect_video_reconciliation(
            rejected_workspace
        )
        with self.assertRaisesRegex(
            reconciliation.DramaVideoReconciliationError,
            "cannot append after resolution",
        ):
            self._append(
                rejected_workspace,
                resolved,
                evidence_fingerprint="e" * 64,
                observed_outcome="provider_rejected",
                evidence_kind="provider_rejection",
                provider_request_id="request-b",
                http_status=409,
                rejection_class="policy_rejected",
                recorded_at_ms=2,
            )

    def test_tamper_and_submission_source_drift_fail_closed(self) -> None:
        workspace = "video-reconciliation-tamper"
        inspection = self._prepare_unknown(workspace)
        self._append(workspace, inspection)
        path = drama_video.video_submission_path(workspace).with_name(
            "reconciliation.json"
        )
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["receipts"][0]["observed_outcome"] = "submitted"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(
            reconciliation.DramaVideoReconciliationError,
            "invalid|fingerprint|cannot resolve",
        ):
            reconciliation.read_video_reconciliation(workspace)

        drift_workspace = "video-reconciliation-drift"
        inspection = self._prepare_unknown(drift_workspace)
        submission = drama_video.read_video_submission(drift_workspace)
        submission["updated_at"] = 2
        drama_video._write_video_submission(drift_workspace, submission)
        with self.assertRaisesRegex(
            reconciliation.DramaVideoReconciliationError,
            "changed",
        ):
            self._append(drift_workspace, inspection)

    def test_source_revision_rejects_aba_restore_with_stale_inspection(self) -> None:
        workspace = "video-reconciliation-aba"
        inspection = self._prepare_unknown(workspace)
        original = drama_video.read_video_submission(workspace)
        mutated = dict(original)
        mutated["updated_at"] = 2
        drama_video._write_video_submission(workspace, mutated)
        drama_video._write_video_submission(workspace, original)
        restored = drama_video.read_video_submission(workspace)
        self.assertEqual(restored, original)
        self.assertNotEqual(
            reconciliation.inspect_video_reconciliation(workspace)[
                "source_revision_fingerprint"
            ],
            inspection["source_revision_fingerprint"],
        )
        with self.assertRaisesRegex(
            reconciliation.DramaVideoReconciliationError,
            "changed",
        ):
            self._append(workspace, inspection)

    def test_reconciliation_read_is_bound_to_the_same_submission_snapshot(self) -> None:
        workspace = "video-reconciliation-read-race"
        self._prepare_unknown(workspace)
        raced = {
            "submission_fingerprint": "f" * 64,
            "revision": 1,
            "ledger_fingerprint": "e" * 64,
            "observed_outcome": "submitted",
            "provider_task_id": "wrong-snapshot-task",
        }
        with patch(
            "src.drama_video_reconciliation.inspect_video_reconciliation",
            return_value=raced,
        ):
            status = drama_video.video_status(workspace)
        self.assertEqual(status["state"], "blocked")
        self.assertEqual(
            status["error_code"],
            "video_reconciliation_source_changed",
        )

        with patch.dict("os.environ", {"SD_VIDEO_MODE": "real"}, clear=False), patch(
            "src.drama_video_reconciliation.inspect_video_reconciliation",
            return_value=raced,
        ):
            with self.assertRaisesRegex(
                drama_video.DramaVideoProviderError,
                "changed while reading",
            ):
                drama_video.run_video_job(
                    workspace,
                    {"resume_submitted": True},
                    lambda *_: None,
                )
