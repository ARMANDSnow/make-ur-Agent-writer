"""Iter104 paid-state matrix and representative real process-death recovery."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from src.paid_recovery_states import (
    IMAGE_ATTEMPT_STATUSES,
    IMAGE_RECEIPT_STATUSES,
    TEXT_ATTEMPT_STATUSES,
    TEXT_CANONICAL_RECOVERY_STATUSES,
    TEXT_RECONCILIATION_REQUIRED_STATUSES,
    VIDEO_INCOMPLETE_STATUSES,
    VIDEO_LEDGER_STATUSES,
    VIDEO_NON_RESUMABLE_STATUSES,
    VIDEO_PAID_SUBMISSION_STATUSES,
    VIDEO_TASK_ID_STATUSES,
)


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests" / "support" / "drama_crash_driver.py"
CRASH_EXIT = 86
TEXT_STATIONS = (
    "drama-plan",
    "drama-hooks",
    "drama-storyboard",
    "drama-characters",
    "drama-review-assemble",
)


# These tables are acceptance policy, not a second serialization vocabulary.
# Every durable status below is imported from src.paid_recovery_states and the
# equality assertions make additions fail until their recovery semantics are
# explicitly classified.
TEXT_POLICY = {
    "submitting": {"automatic_paid_calls": 0, "requires_reconciliation": True},
    "response_received": {"automatic_paid_calls": 0, "requires_reconciliation": True},
    "failed_after_submission": {"automatic_paid_calls": 0, "requires_reconciliation": True},
    "succeeded": {"automatic_paid_calls": 0, "requires_reconciliation": False},
    "budget_exceeded": {"automatic_paid_calls": 0, "requires_reconciliation": True},
}

IMAGE_PHASE_POLICY = {
    "not_sent": {"durable_status": None, "generate_total": 1, "response_total": 0, "generate_delta": 1, "outcome": "submit_once"},
    "submission_unknown": {"durable_status": "started", "generate_total": 1, "response_total": 0, "generate_delta": 0, "outcome": "block"},
    "response_received": {"durable_status": "started", "generate_total": 1, "response_total": 1, "generate_delta": 0, "outcome": "block"},
    "staging_written": {"durable_status": "started", "generate_total": 1, "response_total": 0, "generate_delta": 0, "outcome": "adopt"},
    "receipt_written": {"durable_status": "artifact_received", "generate_total": 1, "response_total": 0, "generate_delta": 0, "outcome": "commit"},
    "canonical_promoted": {"durable_status": "artifact_received", "generate_total": 1, "response_total": 0, "generate_delta": 0, "outcome": "verify"},
}

IMAGE_STATUS_POLICY = {
    "started": "inspect_staging_else_reconcile",
    "artifact_received": "commit_without_provider",
    "succeeded": "verify_lineage_without_provider",
    "timeout": "reconcile_before_retry",
    "network_error": "reconcile_before_retry",
    "provider_error": "reconcile_before_retry",
    "local_error": "reconcile_before_retry",
}

VIDEO_PHASE_POLICY = {
    "pre_submit": {"ledger": None, "create": 1, "poll": 1, "download": 1},
    "submitting": {"ledger": "submitting", "create": 0, "poll": 0, "download": 0},
    "submitted": {"ledger": "submitted", "create": 0, "poll": 1, "download": 1},
    "media_written": {"ledger": "submitted", "create": 0, "poll": 1, "download": 1},
    "meta_written": {"ledger": "submitted", "create": 0, "poll": 0, "download": 0},
    "succeeded": {"ledger": "succeeded", "create": 0, "poll": 0, "download": 0},
}

VIDEO_STATUS_POLICY = {
    "submitting": "block_unknown_outcome",
    "submitted": "resume_poll_without_create",
    "failed": "block_consumed_submission",
    "succeeded": "verify_lineage_without_network",
}


class PaidRecoveryPolicyMatrixTests(unittest.TestCase):
    def test_all_five_text_stations_share_one_exhaustive_zero_automatic_retry_policy(self) -> None:
        self.assertEqual(set(TEXT_POLICY), set(TEXT_ATTEMPT_STATUSES))
        self.assertEqual(
            {status for status, row in TEXT_POLICY.items() if row["requires_reconciliation"]},
            set(TEXT_RECONCILIATION_REQUIRED_STATUSES),
        )
        self.assertEqual(TEXT_CANONICAL_RECOVERY_STATUSES, {"response_received", "succeeded"})
        station_policies = {station: dict(TEXT_POLICY) for station in TEXT_STATIONS}
        self.assertEqual(set(station_policies), set(TEXT_STATIONS))
        for station, policy in station_policies.items():
            with self.subTest(station=station):
                self.assertEqual(policy, TEXT_POLICY)
                self.assertTrue(all(row["automatic_paid_calls"] == 0 for row in policy.values()))

    def test_six_image_crash_phases_explicitly_cover_request_and_lineage_strategy(self) -> None:
        self.assertEqual(set(IMAGE_PHASE_POLICY), {
            "not_sent", "submission_unknown", "response_received",
            "staging_written", "receipt_written", "canonical_promoted",
        })
        persisted = {
            row["durable_status"] for row in IMAGE_PHASE_POLICY.values()
            if row["durable_status"] is not None
        }
        self.assertTrue(persisted <= set(IMAGE_ATTEMPT_STATUSES))
        self.assertEqual(set(IMAGE_STATUS_POLICY), set(IMAGE_ATTEMPT_STATUSES))
        self.assertEqual(IMAGE_RECEIPT_STATUSES, {"artifact_received", "succeeded"})
        self.assertEqual(
            [name for name, row in IMAGE_PHASE_POLICY.items() if row["generate_delta"] == 1],
            ["not_sent"],
        )
        for name in ("submission_unknown", "response_received"):
            self.assertEqual(IMAGE_PHASE_POLICY[name]["outcome"], "block")

    def test_six_video_crash_phases_distinguish_paid_create_from_safe_poll_download(self) -> None:
        self.assertEqual(set(VIDEO_PHASE_POLICY), {
            "pre_submit", "submitting", "submitted", "media_written",
            "meta_written", "succeeded",
        })
        persisted = {
            row["ledger"] for row in VIDEO_PHASE_POLICY.values() if row["ledger"] is not None
        }
        self.assertTrue(persisted <= set(VIDEO_LEDGER_STATUSES))
        self.assertEqual(set(VIDEO_STATUS_POLICY), set(VIDEO_LEDGER_STATUSES))
        self.assertEqual(VIDEO_TASK_ID_STATUSES, {"submitted", "failed", "succeeded"})
        self.assertEqual(VIDEO_PAID_SUBMISSION_STATUSES, VIDEO_TASK_ID_STATUSES)
        self.assertEqual(VIDEO_NON_RESUMABLE_STATUSES, {"submitting", "failed"})
        self.assertEqual(VIDEO_INCOMPLETE_STATUSES, {"submitting", "submitted", "failed"})
        self.assertEqual(
            [name for name, row in VIDEO_PHASE_POLICY.items() if row["create"] == 1],
            ["pre_submit"],
        )
        self.assertEqual(VIDEO_PHASE_POLICY["submitted"]["create"], 0)
        self.assertGreater(VIDEO_PHASE_POLICY["submitted"]["poll"], 0)


class CrossProcessCrashRestartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "workspaces"
        self.root.mkdir()
        (self.root / ".dragon-raja-crash-matrix").write_text("iter104\n", encoding="utf-8")
        self.events = Path(self.temporary.name) / "provider-events.log"
        self.tmpdir = Path(self.temporary.name) / "tmp"
        self.tmpdir.mkdir()

    def _env(self) -> dict[str, str]:
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.temporary.name,
            "LANG": "C.UTF-8",
            "TMPDIR": str(self.tmpdir),
            "DRAGON_RAJA_SKIP_DOTENV": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "OPENAI_MODEL": "mock",
            "DRAMA_MODEL": "mock",
            "LITELLM_LOCAL_MODEL_COST_MAP": "true",
            "PYTHONPYCACHEPREFIX": str(self.tmpdir / "pycache"),
        }

    def _run(
        self,
        scenario: str,
        *,
        marker: Path | None = None,
        expected: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(DRIVER),
            scenario,
            "--workspace-root",
            str(self.root),
            "--events",
            str(self.events),
        ]
        if marker is not None:
            command.extend(("--marker", str(marker)))
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=self._env(),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def _events(self) -> Counter[str]:
        if not self.events.exists():
            return Counter()
        return Counter(self.events.read_text(encoding="ascii").splitlines())

    def test_five_text_stations_execute_real_recovery_entry_for_every_paid_state(self) -> None:
        marker = Path(self.temporary.name) / "text-matrix.json"
        self._run("text-matrix", marker=marker)
        rows = json.loads(marker.read_text(encoding="utf-8"))["results"]
        self.assertEqual(len(rows), len(TEXT_STATIONS) * 9)
        for row in rows:
            with self.subTest(station=row["station"], case=row["case"]):
                self.assertIn(row["station"], TEXT_STATIONS)
                self.assertEqual(row["paid_calls"], 0)
                if row["case"] in {"response_canonical", "succeeded_canonical"}:
                    self.assertEqual(row["outcome"], "recovered")
                else:
                    self.assertEqual(row["outcome"], "blocked")
                if row["case"] in {"model_drift", "endpoint_drift", "input_drift"}:
                    self.assertTrue(row["error"])

    def test_image_canonical_projection_crash_recovers_in_fresh_process_without_provider(self) -> None:
        crash_marker = Path(self.temporary.name) / "image-crash.json"
        resume_marker = Path(self.temporary.name) / "image-resume.json"
        self._run("prepare-image")
        self._run("crash-image", marker=crash_marker, expected=CRASH_EXIT)
        crashed = json.loads(crash_marker.read_text(encoding="utf-8"))
        self.assertEqual(crashed["durable_status"], "artifact_received")
        self.assertTrue(crashed["canonical_exists"])
        self.assertTrue(crashed["staging_exists"])
        self.assertEqual(self._events()["image_generate"], 1)

        self._run("resume-image", marker=resume_marker)
        resumed = json.loads(resume_marker.read_text(encoding="utf-8"))
        self.assertNotEqual(crashed["pid"], resumed["pid"])
        self.assertNotEqual(crashed["import_nonce"], resumed["import_nonce"])
        self.assertEqual(resumed["durable_status"], "succeeded")
        self.assertEqual(resumed["phase_status"], "succeeded")
        self.assertEqual(resumed["canonical_sha256"], resumed["receipt_sha256"])
        self.assertEqual(resumed["projection_sha256"], resumed["record_sha256"])
        self.assertFalse(resumed["staging_exists"])
        self.assertEqual(self._events()["image_generate"], 1)

    def test_six_image_stages_execute_production_recovery_with_exact_provider_delta(self) -> None:
        marker = Path(self.temporary.name) / "image-matrix.json"
        self._run("image-matrix", marker=marker)
        rows = json.loads(marker.read_text(encoding="utf-8"))["results"]
        self.assertEqual([row["stage"] for row in rows], list(IMAGE_PHASE_POLICY))
        for row in rows:
            expected = IMAGE_PHASE_POLICY[row["stage"]]
            with self.subTest(stage=row["stage"]):
                self.assertEqual(row["generate_delta"], expected["generate_delta"])
                self.assertEqual(row["generate_total"], expected["generate_total"])
                self.assertEqual(row["response_received_total"], expected["response_total"])
                if expected["outcome"] == "block":
                    self.assertFalse(row["completed"])
                    self.assertEqual(row["durable_status"], "started")
                    self.assertEqual(row["phase_status"], "awaiting_retry_authorization")
                else:
                    self.assertTrue(row["completed"])
                    self.assertEqual(row["durable_status"], "succeeded")
                    self.assertEqual(row["phase_status"], "succeeded")
                    self.assertEqual(row["canonical_sha256"], row["receipt_sha256"])
                    self.assertEqual(row["projection_sha256"], row["record_sha256"])
                    self.assertFalse(row["staging_exists"])
                if row["stage"] == "canonical_promoted":
                    self.assertEqual(row["pre_recovery_status"], "artifact_received")
                    self.assertFalse(row["pre_recovery_staging_exists"])
                    self.assertTrue(row["pre_recovery_canonical_exists"])

    def test_video_create_response_loss_crash_blocks_fresh_process_without_second_create(self) -> None:
        crash_marker = Path(self.temporary.name) / "video-submitting-crash.json"
        resume_marker = Path(self.temporary.name) / "video-submitting-resume.json"
        self._run("prepare-video")
        self._run(
            "crash-video-submitting", marker=crash_marker, expected=CRASH_EXIT
        )
        crashed = json.loads(crash_marker.read_text(encoding="utf-8"))
        self.assertEqual(crashed["ledger_status"], "submitting")
        self.assertEqual(crashed["create_count"], 1)

        self._run("resume-video-submitting", marker=resume_marker)
        resumed = json.loads(resume_marker.read_text(encoding="utf-8"))
        self.assertNotEqual(crashed["import_nonce"], resumed["import_nonce"])
        self.assertEqual(resumed["ledger_status"], "submitting")
        self.assertTrue(resumed["blocked"])
        self.assertEqual(resumed["create_count"], 1)
        self.assertEqual(resumed["poll_count"], 0)
        self.assertEqual(resumed["download_count"], 0)

    def test_video_torn_pair_crash_recovers_in_fresh_process_without_second_create(self) -> None:
        crash_marker = Path(self.temporary.name) / "video-crash.json"
        resume_marker = Path(self.temporary.name) / "video-resume.json"
        self._run("prepare-video")
        self.assertEqual(self._events()["video_create"], 0)
        self._run("crash-video", marker=crash_marker, expected=CRASH_EXIT)
        crashed = json.loads(crash_marker.read_text(encoding="utf-8"))
        self.assertTrue(crashed["media_exists"])
        self.assertFalse(crashed["meta_exists"])
        self.assertEqual(crashed["ledger_status"], "submitted")
        self.assertEqual(self._events()["video_create"], 1)

        self._run("resume-video", marker=resume_marker)
        resumed = json.loads(resume_marker.read_text(encoding="utf-8"))
        self.assertNotEqual(crashed["pid"], resumed["pid"])
        self.assertNotEqual(crashed["import_nonce"], resumed["import_nonce"])
        self.assertEqual(resumed["result_status"], "succeeded")
        self.assertEqual(resumed["ledger_status"], "succeeded")
        self.assertEqual(resumed["task_id"], "task-matrix-1")
        self.assertEqual(resumed["media_sha256"], resumed["meta_sha256"])
        counts = self._events()
        self.assertEqual(counts["video_create"], 1)
        self.assertEqual(counts["asset_upload"], 2)
        self.assertEqual(counts["asset_poll"], 2)
        self.assertEqual(counts["video_poll"], 2)
        self.assertEqual(counts["video_download"], 2)

    def test_six_video_stages_execute_status_and_job_entries_with_exact_network_delta(self) -> None:
        marker = Path(self.temporary.name) / "video-matrix.json"
        self._run("video-matrix", marker=marker)
        rows = json.loads(marker.read_text(encoding="utf-8"))["results"]
        self.assertEqual([row["stage"] for row in rows], list(VIDEO_PHASE_POLICY))
        for row in rows:
            policy = VIDEO_PHASE_POLICY[row["stage"]]
            deltas = row["deltas"]
            with self.subTest(stage=row["stage"]):
                self.assertEqual(deltas["video_create"], policy["create"])
                self.assertEqual(deltas["video_poll"], policy["poll"])
                self.assertEqual(deltas["video_download"], policy["download"])
                self.assertLessEqual(deltas["video_create"], 1)
                if row["stage"] == "pre_submit":
                    self.assertEqual(deltas["asset_upload"], 2)
                    self.assertEqual(deltas["asset_poll"], 2)
                else:
                    self.assertEqual(deltas["asset_upload"], 0)
                    self.assertEqual(deltas["asset_poll"], 0)
                if row["stage"] == "submitting":
                    self.assertEqual(row["outcome"], "blocked")
                    self.assertEqual(row["ledger_status"], "submitting")
                    self.assertEqual(row["status_after"], "submission_unknown")
                else:
                    self.assertEqual(row["outcome"], "succeeded")
                    self.assertEqual(row["ledger_status"], "succeeded")
                    self.assertEqual(row["status_after"], "succeeded")
                    self.assertEqual(row["media_sha256"], row["meta_sha256"])


if __name__ == "__main__":
    unittest.main()
