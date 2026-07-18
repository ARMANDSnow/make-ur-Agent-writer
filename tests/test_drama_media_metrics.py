"""iter139 durable media lifecycle metrics and Insights projection."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from unittest.mock import patch

from src import (
    drama_media_metrics,
    drama_media_tasks,
    drama_media_worker,
)
from src.drama_schemas import (
    DramaMediaTaskLedgerV3,
    DramaMediaTaskLedgerV4,
    _canonical_sha256,
)
from src.web.drama_insights import collect_drama_insights
from tests._drama_base import DramaTestBase
from tests._drama_media_backend_fixture import (
    MODEL_ID,
    PROVIDER_ID,
    build_registry,
)


class DramaMediaMetricsTests(DramaTestBase):
    _IDENTITY = {
        "backend_id": "local-fixture",
        "provider_fingerprint": "1" * 64,
        "model_fingerprint": "2" * 64,
        "account_fingerprint": "3" * 64,
        "endpoint_fingerprint": "4" * 64,
    }

    def setUp(self) -> None:
        super().setUp()
        self.name = "media-metrics"
        self._make_drama_workspace(self.name, episode_count=2)
        self.now = 1_700_000_000_000

    def _ledger(self, episode_no: int = 1):
        return drama_media_tasks.load_media_task_ledger(
            self.name, episode_no=episode_no
        )

    def _create(
        self,
        subject_id: str,
        input_digit: str,
        *,
        episode_no: int = 1,
    ):
        try:
            expected = self._ledger(episode_no).ledger_fingerprint
        except FileNotFoundError:
            expected = None
        with patch.object(
            drama_media_tasks, "_clock_ms", return_value=self.now
        ):
            task, _binding = drama_media_tasks.enqueue_bound_media_task(
                self.name,
                episode_no=episode_no,
                media_kind="image",
                stage="image-generate",
                subject_id=subject_id,
                input_fingerprint=input_digit * 64,
                dependency_task_ids=(),
                attempt_no=1,
                now_ms=self.now,
                expected_ledger_fingerprint=expected,
                provider_id=PROVIDER_ID,
                model_id=MODEL_ID,
                registry=build_registry(
                    media_kind="image",
                    backend_id=self._IDENTITY["backend_id"],
                    provider_fingerprint=self._IDENTITY[
                        "provider_fingerprint"
                    ],
                    model_fingerprint=self._IDENTITY["model_fingerprint"],
                ),
                **self._IDENTITY,
            )
        return task

    def _claim(self, task, at: int):
        ledger = self._ledger(task.episode_no)
        current = next(
            item for item in ledger.tasks if item.task_id == task.task_id
        )
        with patch.object(
            drama_media_worker, "_clock_ms", return_value=self.now + at
        ):
            return drama_media_worker.claim_media_task(
                self.name,
                episode_no=task.episode_no,
                task_id=task.task_id,
                worker_fingerprint="5" * 64,
                lease_token_fingerprint="6" * 64,
                expected_task_revision=current.revision,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
                lease_duration_ms=60_000,
                lane_capacity=8,
            )

    def _transition(
        self,
        task_id: str,
        target: str,
        at: int,
        *,
        result: str | None = None,
        outcome: str | None = None,
    ):
        ledger = self._ledger()
        task = next(item for item in ledger.tasks if item.task_id == task_id)
        lease = next(
            item for item in ledger.leases if item.task_id == task_id
        )
        with patch.object(
            drama_media_tasks, "_clock_ms", return_value=self.now + at
        ):
            return drama_media_tasks.transition_media_task(
                self.name,
                episode_no=1,
                task_id=task_id,
                target_state=target,
                expected_task_revision=task.revision,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
                worker_fingerprint="5" * 64,
                lease_token_fingerprint="6" * 64,
                expected_lease_revision=lease.lease_revision,
                result_fingerprint=result,
                outcome_code=outcome,
            )

    def test_lifecycle_metrics_use_proved_ready_claim_and_terminal_times(
        self,
    ) -> None:
        succeeded = self._create("shot_001", "a")
        failed = self._create("shot_002", "b")
        self._create("shot_003", "c")

        self._claim(succeeded, 10)
        self._transition(succeeded.task_id, "validating", 20)
        self._transition(
            succeeded.task_id,
            "succeeded",
            30,
            result="f" * 64,
        )
        self._claim(failed, 40)
        self._transition(
            failed.task_id,
            "failed",
            55,
            outcome="local_failure",
        )

        data = collect_drama_insights(self.name)["media_metrics"]
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["task_count"], 3)
        self.assertEqual(data["terminal_count"], 2)
        self.assertEqual(data["succeeded_count"], 1)
        self.assertEqual(data["failed_count"], 1)
        self.assertEqual(data["pending_count"], 1)
        self.assertEqual(data["success_rate"], "0.500000")
        self.assertEqual(data["queue_wait_known_samples"], 2)
        self.assertEqual(data["queue_wait_unknown_samples"], 1)
        self.assertEqual(data["queue_wait_sum_ms"], 50)
        self.assertEqual(data["queue_wait_average_ms"], "25.000000")
        self.assertEqual(data["run_known_samples"], 2)
        self.assertEqual(data["run_sum_ms"], 35)
        self.assertEqual(data["run_average_ms"], "17.500000")
        self.assertEqual(len(data["rows"]), 3)
        self.assertEqual(data["rows"][0]["provider_id"], PROVIDER_ID)
        self.assertEqual(data["rows"][0]["model_id"], MODEL_ID)
        lifecycle = {
            item.task_id: item for item in self._ledger().lifecycle
        }
        self.assertIsNotNone(
            lifecycle[succeeded.task_id].first_claim_evidence
        )
        self.assertEqual(
            lifecycle[succeeded.task_id].first_claim_evidence.first_claimed_at_ms,
            self.now + 10,
        )

        rendered = json.dumps(data, ensure_ascii=False)
        for private in (
            self._IDENTITY["account_fingerprint"],
            self._IDENTITY["endpoint_fingerprint"],
            self._IDENTITY["provider_fingerprint"],
            self._IDENTITY["model_fingerprint"],
            "worker_fingerprint",
            "lease_token",
            "record_fingerprint",
            "backend_binding_fingerprint",
            "source_evidence_fingerprint",
            "prompt",
            "response",
        ):
            self.assertNotIn(private, rendered)

    def test_v3_migration_keeps_historical_wait_unknown(self) -> None:
        task = self._create("shot_001", "a")
        ledger = self._ledger()
        payload = ledger.model_dump(mode="json")
        payload["schema_version"] = 3
        payload.pop("lifecycle")
        payload.pop("legacy_migration_evidence")
        payload_without_fingerprint = {
            key: value
            for key, value in payload.items()
            if key != "ledger_fingerprint"
        }
        payload["ledger_fingerprint"] = _canonical_sha256(
            payload_without_fingerprint
        )
        legacy = DramaMediaTaskLedgerV3(**payload)
        drama_media_tasks.media_task_ledger_path(
            self.name, episode_no=1
        ).write_bytes(drama_media_tasks._ledger_bytes(legacy))

        migrated = self._ledger()
        self.assertEqual(migrated.schema_version, 4)
        self.assertEqual(migrated.tasks[0].task_id, task.task_id)
        self.assertEqual(len(migrated.lifecycle), 1)
        self.assertTrue(migrated.lifecycle[0].legacy_unknown)
        self.assertIsNone(migrated.lifecycle[0].ready_at_ms)
        data = drama_media_metrics.collect_workspace_media_metrics(self.name)
        self.assertEqual(data["task_count"], 1)
        self.assertEqual(data["queue_wait_known_samples"], 0)
        self.assertEqual(data["queue_wait_unknown_samples"], 1)
        self.assertIsNone(data["queue_wait_average_ms"])
        self.assertNotEqual(
            data["queue_wait_average_ms"],
            str(
                migrated.tasks[0].updated_at_ms
                - migrated.tasks[0].created_at_ms
            ),
        )

    def test_invalid_namespace_and_workspace_cap_return_no_partial_metrics(
        self,
    ) -> None:
        self._create("shot_001", "a")
        directory = drama_media_tasks.media_task_ledger_path(
            self.name, episode_no=1
        ).parent
        (directory / "episode_1.tasks.json").write_text(
            "private-provider-response", encoding="utf-8"
        )
        invalid = drama_media_metrics.collect_workspace_media_metrics(
            self.name
        )
        self.assertEqual(invalid["status"], "degraded")
        self.assertEqual(invalid["task_count"], 0)
        self.assertEqual(invalid["rows"], [])
        (directory / "episode_1.tasks.json").unlink()
        with patch.object(
            drama_media_metrics,
            "MAX_MEDIA_METRICS_TASKS",
            0,
        ):
            capped = drama_media_metrics.collect_workspace_media_metrics(
                self.name
            )
        self.assertEqual(capped["status"], "degraded")
        self.assertEqual(capped["task_count"], 0)
        self.assertEqual(capped["rows"], [])

    def test_v3_released_task_does_not_treat_reclaim_as_first_claim(
        self,
    ) -> None:
        task = self._create("shot_001", "a")
        lease = self._claim(task, 10)
        claimed_ledger = self._ledger()
        claimed = next(
            item for item in claimed_ledger.tasks
            if item.task_id == task.task_id
        )
        with patch.object(
            drama_media_worker, "_clock_ms", return_value=self.now + 20
        ):
            drama_media_worker.release_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint="5" * 64,
                lease_token_fingerprint="6" * 64,
                expected_task_revision=claimed.revision,
                expected_lease_revision=lease.lease_revision,
                expected_ledger_fingerprint=(
                    claimed_ledger.ledger_fingerprint
                ),
            )
        released = self._ledger()
        payload = released.model_dump(mode="json")
        payload["schema_version"] = 3
        payload.pop("lifecycle")
        payload.pop("legacy_migration_evidence")
        payload["ledger_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in payload.items()
                if key != "ledger_fingerprint"
            }
        )
        legacy = DramaMediaTaskLedgerV3(**payload)
        drama_media_tasks.media_task_ledger_path(
            self.name, episode_no=1
        ).write_bytes(drama_media_tasks._ledger_bytes(legacy))

        current = self._ledger().tasks[0]
        self._claim(current, 30)
        migrated = self._ledger().lifecycle[0]
        self.assertTrue(migrated.legacy_unknown)
        self.assertIsNone(migrated.ready_at_ms)
        self.assertIsNone(migrated.first_claimed_at_ms)
        legacy_sidecar = (
            self._ledger()._legacy_source_ledger.ledger_fingerprint
        )
        self.assertTrue(
            (
                drama_media_tasks.paths.workspace_root(self.name)
                / drama_media_tasks.MEDIA_TASK_EVIDENCE_DIRECTORY
                / f"legacy_{legacy_sidecar}.json"
            ).is_file()
        )

    def test_schema_tamper_and_all_metrics_operations_are_zero_network(
        self,
    ) -> None:
        task = self._create("shot_001", "a")
        original = self._ledger().lifecycle[0].model_dump(mode="json")
        for changes in (
            {"ready_at_ms": True},
            {"first_claimed_at_ms": self.now - 1},
            {"unexpected": "private"},
        ):
            payload = {**original, **changes}
            content = {
                key: value
                for key, value in payload.items()
                if key != "record_fingerprint"
            }
            payload["record_fingerprint"] = _canonical_sha256(content)
            with self.assertRaises(ValueError):
                type(self._ledger().lifecycle[0])(**payload)

        with patch.object(
            socket, "socket", side_effect=AssertionError("network forbidden")
        ):
            self._claim(task, 10)
            data = drama_media_metrics.collect_workspace_media_metrics(
                self.name
            )
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["queue_wait_sum_ms"], 10)

        ledger_payload = self._ledger().model_dump(mode="json")
        ledger_payload["lifecycle"] = []
        content = {
            key: value
            for key, value in ledger_payload.items()
            if key != "ledger_fingerprint"
        }
        ledger_payload["ledger_fingerprint"] = _canonical_sha256(content)
        with self.assertRaises(ValueError):
            DramaMediaTaskLedgerV4(**ledger_payload)

        claimed_ledger = self._ledger()
        forged = claimed_ledger.model_dump(mode="json")
        lifecycle_payload = forged["lifecycle"][0]
        lifecycle_payload["first_claimed_at_ms"] = self.now + 5
        lifecycle_payload["record_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in lifecycle_payload.items()
                if key != "record_fingerprint"
            }
        )
        forged["ledger_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in forged.items()
                if key != "ledger_fingerprint"
            }
        )
        with self.assertRaises(ValueError):
            DramaMediaTaskLedgerV4.model_validate(
                forged,
                context={
                    "verified_claim_evidence": frozenset(
                        {
                            lifecycle_payload[
                                "first_claim_evidence"
                            ]["record_fingerprint"]
                        }
                    ),
                    "verified_legacy_migration_evidence": frozenset(),
                },
            )

        self._transition(
            task.task_id,
            "failed",
            20,
            outcome="local_failure",
        )
        terminal = self._ledger().model_dump(mode="json")
        terminal_lifecycle = terminal["lifecycle"][0]
        terminal_lifecycle["terminal_at_ms"] = self.now + 19
        terminal_lifecycle["record_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in terminal_lifecycle.items()
                if key != "record_fingerprint"
            }
        )
        terminal["ledger_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in terminal.items()
                if key != "ledger_fingerprint"
            }
        )
        with self.assertRaises(ValueError):
            DramaMediaTaskLedgerV4.model_validate(
                terminal,
                context={
                    "verified_claim_evidence": frozenset(
                        {
                            terminal_lifecycle[
                                "first_claim_evidence"
                            ]["record_fingerprint"]
                        }
                    ),
                    "verified_legacy_migration_evidence": frozenset(),
                },
            )

        missing = self._ledger().model_dump(mode="json")
        missing_lifecycle = missing["lifecycle"][0]
        missing_lifecycle["ready_at_ms"] = None
        missing_lifecycle["first_claimed_at_ms"] = None
        missing_lifecycle["first_claim_evidence"] = None
        missing_lifecycle["record_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in missing_lifecycle.items()
                if key != "record_fingerprint"
            }
        )
        missing["ledger_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in missing.items()
                if key != "ledger_fingerprint"
            }
        )
        with self.assertRaises(ValueError):
            DramaMediaTaskLedgerV4.model_validate(
                missing,
                context={
                    "verified_claim_evidence": frozenset(),
                    "verified_legacy_migration_evidence": frozenset(),
                },
            )

    def test_claim_evidence_sidecar_is_required_after_commit(self) -> None:
        task = self._create("shot_001", "a")
        self._claim(task, 10)
        lifecycle = self._ledger().lifecycle[0]
        fingerprint = lifecycle.first_claim_evidence.record_fingerprint
        sidecar = (
            drama_media_tasks.paths.workspace_root(self.name)
            / drama_media_tasks.MEDIA_TASK_EVIDENCE_DIRECTORY
            / f"claim_{fingerprint}.json"
        )
        self.assertTrue(sidecar.is_file())
        sidecar.unlink()
        with self.assertRaises(drama_media_tasks.DramaMediaTaskError):
            self._ledger()

    def test_symlink_and_bad_canonical_ledger_degrade_without_following(
        self,
    ) -> None:
        directory = drama_media_tasks.media_task_ledger_path(
            self.name, episode_no=1
        ).parent
        external = Path(self._tmp.name) / "outside-media-tasks"
        external.mkdir()
        (external / "episode_001.tasks.json").write_text(
            "private-provider-response", encoding="utf-8"
        )
        directory.parent.mkdir(parents=True, exist_ok=True)
        directory.symlink_to(external, target_is_directory=True)
        data = drama_media_metrics.collect_workspace_media_metrics(
            self.name
        )
        self.assertEqual(data["status"], "degraded")
        self.assertEqual(data["task_count"], 0)
        self.assertNotIn(
            "private-provider-response",
            json.dumps(data, ensure_ascii=False),
        )
        directory.unlink()
        directory.mkdir()
        (directory / "episode_001.tasks.json").write_text(
            "{bad", encoding="utf-8"
        )
        bad = drama_media_metrics.collect_workspace_media_metrics(self.name)
        self.assertEqual(bad["status"], "degraded")
        self.assertEqual(bad["rows"], [])

    def test_namespace_change_between_scan_and_projection_degrades(
        self,
    ) -> None:
        self._create("shot_001", "a", episode_no=1)
        self._create("shot_002", "b", episode_no=2)
        real_scan = drama_media_metrics._scan_episode_numbers
        calls = 0

        def changing_scan(root):
            nonlocal calls
            calls += 1
            numbers, invalid = real_scan(root)
            if calls == 1:
                return [number for number in numbers if number != 2], invalid
            return numbers, invalid

        with patch.object(
            drama_media_metrics,
            "_scan_episode_numbers",
            side_effect=changing_scan,
        ):
            result = drama_media_metrics.collect_workspace_media_metrics(
                self.name
            )
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["task_count"], 0)
        self.assertEqual(result["rows"], [])

    def test_loaded_source_token_must_match_initial_snapshot(self) -> None:
        self._create("shot_001", "a")
        real_read = drama_media_tasks._read_ledger

        def mismatched_read(*args, **kwargs):
            ledger, _token = real_read(*args, **kwargs)
            return ledger, ("file", 1, "0" * 64)

        with patch.object(
            drama_media_tasks,
            "_read_ledger",
            side_effect=mismatched_read,
        ):
            result = drama_media_metrics.collect_workspace_media_metrics(
                self.name
            )
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["task_count"], 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
