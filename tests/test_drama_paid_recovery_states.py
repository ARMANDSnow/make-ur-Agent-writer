from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import drama_multimodal_smoke as multimodal
from src import drama_video, paths
from src.paid_recovery_states import (
    IMAGE_ATTEMPT_STATUSES,
    IMAGE_RECEIPT_STATUSES,
    SHOT_IMAGE_ATTEMPT_STATUSES,
    SHOT_IMAGE_RECEIPT_STATUSES,
    SHOT_VIDEO_ATTEMPT_STATUSES,
    SHOT_VIDEO_NOT_SENT_STATUSES,
    SHOT_VIDEO_SUBMITTED_STATUSES,
    SHOT_VIDEO_TERMINAL_STATUSES,
    SHOT_VIDEO_UNKNOWN_STATUSES,
    TEXT_ATTEMPT_STATUSES,
    TEXT_CANONICAL_RECOVERY_STATUSES,
    TEXT_RECONCILIATION_REQUIRED_STATUSES,
    VIDEO_INCOMPLETE_STATUSES,
    VIDEO_LEDGER_STATUSES,
    VIDEO_NON_RESUMABLE_STATUSES,
    VIDEO_PAID_SUBMISSION_STATUSES,
    VIDEO_TASK_ID_STATUSES,
)
from src.web import jobs


class PaidRecoveryStateVocabularyTests(unittest.TestCase):
    def test_text_statuses_are_exhaustive_and_classified(self) -> None:
        self.assertEqual(
            TEXT_ATTEMPT_STATUSES,
            frozenset({
                "submitting",
                "response_received",
                "failed_after_submission",
                "succeeded",
                "budget_exceeded",
            }),
        )
        self.assertEqual(
            TEXT_CANONICAL_RECOVERY_STATUSES | TEXT_RECONCILIATION_REQUIRED_STATUSES,
            TEXT_ATTEMPT_STATUSES,
        )
        self.assertEqual(
            TEXT_CANONICAL_RECOVERY_STATUSES & TEXT_RECONCILIATION_REQUIRED_STATUSES,
            frozenset({"response_received"}),
        )

    def test_image_statuses_are_exhaustive_and_receipts_are_a_subset(self) -> None:
        self.assertEqual(
            IMAGE_ATTEMPT_STATUSES,
            frozenset({
                "started",
                "artifact_received",
                "succeeded",
                "timeout",
                "network_error",
                "provider_error",
                "local_error",
            }),
        )
        self.assertEqual(
            IMAGE_RECEIPT_STATUSES,
            frozenset({"artifact_received", "succeeded"}),
        )
        self.assertLessEqual(IMAGE_RECEIPT_STATUSES, IMAGE_ATTEMPT_STATUSES)
        self.assertIs(SHOT_IMAGE_ATTEMPT_STATUSES, IMAGE_ATTEMPT_STATUSES)
        self.assertIs(SHOT_IMAGE_RECEIPT_STATUSES, IMAGE_RECEIPT_STATUSES)

    def test_video_statuses_are_exhaustive_and_classified(self) -> None:
        self.assertEqual(
            VIDEO_LEDGER_STATUSES,
            frozenset({"submitting", "submitted", "failed", "succeeded"}),
        )
        self.assertEqual(VIDEO_TASK_ID_STATUSES, VIDEO_PAID_SUBMISSION_STATUSES)
        self.assertEqual(
            VIDEO_TASK_ID_STATUSES | frozenset({"submitting"}),
            VIDEO_LEDGER_STATUSES,
        )
        self.assertEqual(
            VIDEO_INCOMPLETE_STATUSES | frozenset({"succeeded"}),
            VIDEO_LEDGER_STATUSES,
        )
        self.assertLessEqual(VIDEO_NON_RESUMABLE_STATUSES, VIDEO_INCOMPLETE_STATUSES)
        self.assertEqual(
            VIDEO_NON_RESUMABLE_STATUSES & VIDEO_TASK_ID_STATUSES,
            frozenset({"failed"}),
        )

    def test_shot_video_attempt_statuses_have_one_four_way_classification(self) -> None:
        groups = (
            SHOT_VIDEO_NOT_SENT_STATUSES,
            SHOT_VIDEO_UNKNOWN_STATUSES,
            SHOT_VIDEO_SUBMITTED_STATUSES,
            SHOT_VIDEO_TERMINAL_STATUSES,
        )
        self.assertEqual(frozenset().union(*groups), SHOT_VIDEO_ATTEMPT_STATUSES)
        for left in range(len(groups)):
            for right in range(left + 1, len(groups)):
                self.assertFalse(groups[left] & groups[right])
        self.assertEqual(SHOT_VIDEO_NOT_SENT_STATUSES, frozenset({"not_sent"}))
        self.assertEqual(
            SHOT_VIDEO_UNKNOWN_STATUSES,
            frozenset({"started", "submission_unknown"}),
        )


class PaidRecoveryValidatorBoundaryTests(unittest.TestCase):
    _SHA = "a" * 64

    def test_text_ledger_validator_accepts_every_declared_status_and_rejects_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "text-attempts.json"
            with patch.object(jobs, "_drama_text_attempt_path", return_value=ledger_path):
                for status in TEXT_ATTEMPT_STATUSES:
                    payload = {
                        "schema_version": 1,
                        "attempts": {
                            "drama-plan:1": {
                                "status": status,
                                "step": "drama-plan",
                                "episode_no": 1,
                                "attempt_count": 1,
                                "provider_fingerprint": self._SHA,
                                "input_fingerprint": self._SHA,
                            }
                        },
                    }
                    ledger_path.write_text(json.dumps(payload), encoding="utf-8")
                    self.assertEqual(
                        jobs._load_drama_text_attempts("synthetic")["attempts"]["drama-plan:1"]["status"],
                        status,
                    )
                payload["attempts"]["drama-plan:1"]["status"] = "unknown"
                ledger_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "ledger row is invalid"):
                    jobs._load_drama_text_attempts("synthetic")

    def test_image_state_validator_accepts_every_declared_status_and_rejects_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_dir = Path(tmp) / "workspaces"
            root = workspace_dir / "synthetic"
            (root / "logs").mkdir(parents=True)
            with patch.object(multimodal.paths, "WORKSPACE_DIR", workspace_dir):
                for status in IMAGE_ATTEMPT_STATUSES:
                    state = multimodal._new_state("synthetic")
                    attempt = {
                        "attempt": 1,
                        "timeout_seconds": 1.0,
                        "estimated_cost_cny": 1.0,
                        "status": status,
                    }
                    if status in IMAGE_RECEIPT_STATUSES:
                        artifact_path = "data/character_refs/c001/reference.png"
                        attempt.update({
                            "artifact_path": artifact_path,
                            "artifact_sha256": self._SHA,
                            "artifact_record": {"path": artifact_path},
                        })
                    state["image_attempts"] = {"c001": [attempt]}
                    state["image_estimated_spend_cny"] = 1.0
                    multimodal.state_path("synthetic").write_text(
                        json.dumps(state), encoding="utf-8"
                    )
                    self.assertEqual(
                        multimodal.load_state("synthetic")["image_attempts"]["c001"][0]["status"],
                        status,
                    )
                attempt["status"] = "unknown"
                state["image_attempts"] = {"c001": [attempt]}
                multimodal.state_path("synthetic").write_text(
                    json.dumps(state), encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, "image attempt billing state is invalid"):
                    multimodal.load_state("synthetic")

    def test_video_ledger_validator_accepts_every_declared_status_and_rejects_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = "synthetic"
            with patch.object(paths, "WORKSPACE_DIR", Path(tmp)):
                ledger_path = drama_video.video_submission_path(workspace)
                ledger_path.parent.mkdir(parents=True)
                for status in VIDEO_LEDGER_STATUSES:
                    payload = {
                        "schema_version": 1,
                        "episode_no": 1,
                        "status": status,
                        "input_fingerprint": self._SHA,
                        "provider_fingerprint": self._SHA,
                        "submission_count": 1,
                    }
                    if status in VIDEO_TASK_ID_STATUSES:
                        payload["task_id"] = "task-1"
                    if status == "submitted":
                        payload["result_hosts_fingerprint"] = self._SHA
                    ledger_path.write_text(json.dumps(payload), encoding="utf-8")
                    self.assertEqual(
                        drama_video.read_video_submission(workspace)["status"],
                        status,
                    )
                payload["status"] = "unknown"
                ledger_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "ledger status is invalid"):
                    drama_video.read_video_submission(workspace)


if __name__ == "__main__":
    unittest.main()
