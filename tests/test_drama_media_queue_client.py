"""iter136 G4 persistent backend bindings and pure-local queue client."""

from __future__ import annotations

import importlib
import socket
from unittest.mock import patch

from src import (
    drama_media_queue_client,
    drama_media_tasks,
    drama_media_worker,
    drama_shot_image_attempts,
)
from src.drama_media_backends import base, registry
from src.drama_schemas import (
    DramaMediaTaskLedgerV2,
    DramaMediaTaskLedgerV3,
    _canonical_sha256,
)
from src.schemas import model_to_dict
from tests._drama_base import DramaTestBase
from tests._drama_media_backend_fixture import (
    MODEL_ID,
    PROVIDER_ID,
    build_registry,
)


class DramaMediaQueueClientTests(DramaTestBase):
    _IDENTITY = {
        "backend_id": "local-fixture",
        "provider_fingerprint": "1" * 64,
        "model_fingerprint": "2" * 64,
        "account_fingerprint": "3" * 64,
        "endpoint_fingerprint": "4" * 64,
    }

    def setUp(self) -> None:
        super().setUp()
        self.name = "media-queue"
        self._make_drama_workspace(self.name, episode_count=2)
        self.now = 1_700_000_000_000
        self.registry = build_registry(
            media_kind="image",
            backend_id=self._IDENTITY["backend_id"],
            provider_fingerprint=self._IDENTITY["provider_fingerprint"],
            model_fingerprint=self._IDENTITY["model_fingerprint"],
        )

    def _enqueue(self, *, subject_id: str = "shot_001"):
        with patch.object(
            drama_media_queue_client,
            "_wall_clock_ms",
            return_value=self.now,
        ):
            return drama_media_queue_client.enqueue_media_task(
                self.name,
                episode_no=1,
                media_kind="image",
                stage="image-generate",
                subject_id=subject_id,
                input_fingerprint="a" * 64,
                provider_id=PROVIDER_ID,
                model_id=MODEL_ID,
                registry=self.registry,
                **self._IDENTITY,
            )

    def _ledger(self):
        return drama_media_tasks.load_media_task_ledger(
            self.name, episode_no=1
        )

    def test_enqueue_commits_task_and_binding_atomically(self) -> None:
        projected = self._enqueue()
        ledger = self._ledger()
        self.assertEqual(ledger.schema_version, 3)
        self.assertEqual(len(ledger.tasks), 1)
        self.assertEqual(len(ledger.backend_bindings), 1)
        self.assertEqual(
            ledger.backend_bindings[0].task_id,
            projected["task_id"],
        )
        self.assertEqual(projected["backend_binding_status"], "frozen")

    def test_failed_atomic_commit_leaves_no_half_bound_task(self) -> None:
        with patch.object(
            drama_media_tasks,
            "_write_ledger",
            side_effect=drama_media_tasks.DramaMediaTaskError("blocked"),
        ):
            with self.assertRaises(drama_media_queue_client.DramaMediaQueueClientError):
                self._enqueue()
        with self.assertRaises(FileNotFoundError):
            self._ledger()

    def test_exact_replay_uses_persisted_binding_not_current_registry(self) -> None:
        first = self._enqueue()
        source = (
            drama_shot_image_attempts.build_shot_image_provider_capability(
                backend_id=self._IDENTITY["backend_id"],
                capability_version="v1",
                max_reference_images=5,
            )
        )
        changed = registry.build_backend_registry(
            [
                base.registration_from_shot_image_capability(
                    source,
                    provider_id=PROVIDER_ID,
                    model_id=MODEL_ID,
                    provider_fingerprint=self._IDENTITY[
                        "provider_fingerprint"
                    ],
                    model_fingerprint=self._IDENTITY[
                        "model_fingerprint"
                    ],
                )
            ]
        )
        before = self._ledger()
        task, binding = drama_media_tasks.enqueue_bound_media_task(
            self.name,
            episode_no=1,
            media_kind="image",
            stage="image-generate",
            subject_id="shot_001",
            input_fingerprint="a" * 64,
            provider_id=PROVIDER_ID,
            model_id=MODEL_ID,
            registry=changed,
            dependency_task_ids=(),
            attempt_no=1,
            now_ms=self.now,
            expected_ledger_fingerprint=before.ledger_fingerprint,
            **self._IDENTITY,
        )
        self.assertEqual(task.task_id, first["task_id"])
        self.assertEqual(
            binding.registry_fingerprint,
            self.registry.registry_fingerprint,
        )
        self.assertEqual(self._ledger(), before)

    def test_replay_rejects_provider_id_drift(self) -> None:
        first = self._enqueue()
        ledger = self._ledger()
        with self.assertRaises(drama_media_tasks.DramaMediaTaskError):
            drama_media_tasks.enqueue_bound_media_task(
                self.name,
                episode_no=1,
                media_kind="image",
                stage="image-generate",
                subject_id="shot_001",
                input_fingerprint="a" * 64,
                provider_id="other-provider",
                model_id=MODEL_ID,
                registry=self.registry,
                dependency_task_ids=(),
                attempt_no=1,
                now_ms=self.now,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
                **self._IDENTITY,
            )
        self.assertEqual(self._ledger().tasks[0].task_id, first["task_id"])

    def test_v2_migration_is_explicitly_unbound_and_unclaimable(self) -> None:
        projected = self._enqueue()
        current = self._ledger()
        payload = {
            "schema_version": 2,
            "episode_no": 1,
            "revision": current.revision,
            "tasks": [model_to_dict(item) for item in current.tasks],
            "leases": [],
            "release_receipts": [],
            "transition_receipts": [],
        }
        payload["ledger_fingerprint"] = _canonical_sha256(payload)
        legacy = DramaMediaTaskLedgerV2(**payload)
        drama_media_tasks.media_task_ledger_path(
            self.name, episode_no=1
        ).write_bytes(drama_media_tasks._ledger_bytes(legacy))
        migrated = self._ledger()
        self.assertIsInstance(migrated, DramaMediaTaskLedgerV3)
        self.assertEqual(migrated.backend_bindings, [])
        safe = drama_media_queue_client.get_media_task(
            self.name,
            episode_no=1,
            task_id=projected["task_id"],
        )
        self.assertEqual(safe["backend_binding_status"], "legacy_unbound")
        with patch.object(
            drama_media_worker, "_clock_ms", return_value=self.now + 1
        ):
            with self.assertRaises(drama_media_worker.DramaMediaWorkerError):
                drama_media_worker.claim_media_task(
                    self.name,
                    episode_no=1,
                    task_id=projected["task_id"],
                    worker_fingerprint="5" * 64,
                    lease_token_fingerprint="6" * 64,
                    expected_task_revision=0,
                    expected_ledger_fingerprint=(
                        migrated.ledger_fingerprint
                    ),
                    lease_duration_ms=60_000,
                    lane_capacity=1,
                )

    def test_cancel_retains_binding_and_safe_projection(self) -> None:
        task = self._enqueue()
        with patch.object(
            drama_media_queue_client,
            "_wall_clock_ms",
            return_value=self.now + 1,
        ):
            affected = drama_media_queue_client.request_media_task_cancel(
                self.name,
                episode_no=1,
                task_id=task["task_id"],
            )
        self.assertEqual(affected[0]["state"], "cancelling")
        ledger = self._ledger()
        self.assertEqual(len(ledger.backend_bindings), 1)
        safe = drama_media_queue_client.get_media_task(
            self.name, episode_no=1, task_id=task["task_id"]
        )
        serialized = repr(safe)
        self.assertNotIn(PROVIDER_ID, serialized)
        self.assertNotIn(MODEL_ID, serialized)
        self.assertNotIn("1" * 64, serialized)

    def test_wait_returns_terminal_and_times_out_without_busy_loop(self) -> None:
        task = self._enqueue()
        cancelling = drama_media_tasks.cancel_media_task_cascade(
            self.name,
            episode_no=1,
            task_id=task["task_id"],
            expected_task_revision=0,
            expected_ledger_fingerprint=self._ledger().ledger_fingerprint,
            now_ms=self.now + 1,
        )[0]
        with patch.object(
            drama_media_tasks, "_clock_ms", return_value=self.now + 2
        ):
            drama_media_tasks.transition_media_task(
                self.name,
                episode_no=1,
                task_id=task["task_id"],
                target_state="cancelled",
                expected_task_revision=cancelling.revision,
                expected_ledger_fingerprint=self._ledger().ledger_fingerprint,
                outcome_code="cancel_confirmed",
            )
        terminal = drama_media_queue_client.wait_for_media_task(
            self.name,
            episode_no=1,
            task_id=task["task_id"],
            timeout_ms=0,
        )
        self.assertEqual(terminal["state"], "cancelled")

        active = self._enqueue(subject_id="shot_002")
        with patch.object(
            drama_media_queue_client,
            "_monotonic_ns",
            side_effect=[100, 100, 10_000_100],
        ), patch.object(drama_media_queue_client, "_sleep") as sleeper:
            with self.assertRaises(
                drama_media_queue_client.DramaMediaQueueTimeout
            ):
                drama_media_queue_client.wait_for_media_task(
                    self.name,
                    episode_no=1,
                    task_id=active["task_id"],
                    timeout_ms=10,
                    poll_interval_ms=10,
                )
        sleeper.assert_called_once()

    def test_wait_bounds_are_strict(self) -> None:
        task = self._enqueue()
        for timeout in (-1, True, 300_001):
            with self.assertRaises(
                drama_media_queue_client.DramaMediaQueueClientError
            ):
                drama_media_queue_client.wait_for_media_task(
                    self.name,
                    episode_no=1,
                    task_id=task["task_id"],
                    timeout_ms=timeout,
                )
        with self.assertRaises(
            drama_media_queue_client.DramaMediaQueueClientError
        ):
            drama_media_queue_client.wait_for_media_task(
                self.name,
                episode_no=1,
                task_id=task["task_id"],
                timeout_ms=0,
                poll_interval_ms=0,
            )

    def test_wait_does_not_accept_completion_observed_after_deadline(
        self,
    ) -> None:
        task = self._enqueue()
        active = drama_media_queue_client.get_media_task(
            self.name, episode_no=1, task_id=task["task_id"]
        )
        terminal = {**active, "state": "succeeded"}
        with patch.object(
            drama_media_queue_client,
            "get_media_task",
            side_effect=[active, terminal],
        ), patch.object(
            drama_media_queue_client,
            "_monotonic_ns",
            side_effect=[0, 0, 10_000_000],
        ), patch.object(drama_media_queue_client, "_sleep"):
            with self.assertRaises(
                drama_media_queue_client.DramaMediaQueueTimeout
            ):
                drama_media_queue_client.wait_for_media_task(
                    self.name,
                    episode_no=1,
                    task_id=task["task_id"],
                    timeout_ms=10,
                    poll_interval_ms=10,
                )

    def test_new_client_instance_reads_restart_durable_state(self) -> None:
        task = self._enqueue()
        module = importlib.reload(drama_media_queue_client)
        loaded = module.get_media_task(
            self.name,
            episode_no=1,
            task_id=task["task_id"],
        )
        self.assertEqual(loaded["task_id"], task["task_id"])
        self.assertEqual(loaded["backend_binding_status"], "frozen")

    def test_ledger_rejects_binding_task_identity_mismatch(self) -> None:
        self._enqueue()
        ledger = self._ledger()
        payload = ledger.model_dump(mode="json")
        payload["backend_bindings"][0]["task_input_fingerprint"] = "9" * 64
        payload["ledger_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in payload.items()
                if key != "ledger_fingerprint"
            }
        )
        with self.assertRaises(ValueError):
            DramaMediaTaskLedgerV3(**payload)

    def test_client_paths_are_strictly_zero_network(self) -> None:
        with patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("network forbidden"),
        ), patch.object(
            socket.socket,
            "connect",
            side_effect=AssertionError("network forbidden"),
        ):
            task = self._enqueue()
            loaded = drama_media_queue_client.get_media_task(
                self.name,
                episode_no=1,
                task_id=task["task_id"],
            )
        self.assertEqual(loaded["task_id"], task["task_id"])
