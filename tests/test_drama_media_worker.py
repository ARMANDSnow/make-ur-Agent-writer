"""iter134 G2 worker lease, takeover, and workspace lane tests."""

from __future__ import annotations

import json
import multiprocessing
import socket
from unittest.mock import patch

from src import drama_media_tasks, drama_media_worker, paths
from src.drama_schemas import DramaMediaTaskLedger, _canonical_sha256
from tests._drama_base import DramaTestBase


def _claim_in_process(
    workspace: str,
    task_id: str,
    ledger_fingerprint: str,
    worker_digit: str,
    token_digit: str,
    start,
    results,
) -> None:
    start.wait()
    try:
        with patch.object(
            drama_media_worker,
            "_clock_ms",
            return_value=1_700_000_000_000,
        ):
            lease = drama_media_worker.claim_media_task(
                workspace,
                episode_no=1,
                task_id=task_id,
                worker_fingerprint=worker_digit * 64,
                lease_token_fingerprint=token_digit * 64,
                expected_task_revision=0,
                expected_ledger_fingerprint=ledger_fingerprint,
                lease_duration_ms=60_000,
                lane_capacity=2,
            )
        results.put(("ok", lease.worker_fingerprint))
    except Exception as exc:
        results.put(("error", type(exc).__name__))


class DramaMediaWorkerTests(DramaTestBase):
    _IDENTITY = {
        "backend_id": "local-fixture",
        "provider_fingerprint": "1" * 64,
        "model_fingerprint": "2" * 64,
        "account_fingerprint": "3" * 64,
        "endpoint_fingerprint": "4" * 64,
    }

    def setUp(self) -> None:
        super().setUp()
        self.name = "media-worker"
        self._make_drama_workspace(self.name, episode_count=3)
        self.now = 1_700_000_000_000

    def _ledger(self, episode_no: int = 1):
        return drama_media_tasks.load_media_task_ledger(
            self.name, episode_no=episode_no
        )

    def _create(
        self,
        *,
        episode_no: int = 1,
        subject_id: str = "shot_001",
        input_fingerprint: str = "a" * 64,
        media_kind: str = "image",
        stage: str = "image-generate",
    ):
        try:
            expected = self._ledger(episode_no).ledger_fingerprint
        except FileNotFoundError:
            expected = None
        return drama_media_tasks.create_media_task(
            self.name,
            episode_no=episode_no,
            media_kind=media_kind,
            stage=stage,
            subject_id=subject_id,
            input_fingerprint=input_fingerprint,
            dependency_task_ids=(),
            attempt_no=1,
            now_ms=self.now,
            expected_ledger_fingerprint=expected,
            **self._IDENTITY,
        )

    def _claim(
        self,
        task,
        *,
        worker: str = "5",
        token: str = "6",
        now_delta: int = 1,
        duration: int = 60_000,
        capacity: int = 2,
    ):
        ledger = self._ledger(task.episode_no)
        current = next(item for item in ledger.tasks if item.task_id == task.task_id)
        with patch.object(
            drama_media_worker,
            "_clock_ms",
            return_value=self.now + now_delta,
        ):
            return drama_media_worker.claim_media_task(
                self.name,
                episode_no=task.episode_no,
                task_id=task.task_id,
                worker_fingerprint=worker * 64,
                lease_token_fingerprint=token * 64,
                expected_task_revision=current.revision,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
                lease_duration_ms=duration,
                lane_capacity=capacity,
            )

    def test_claim_is_persistent_exact_replay_and_projection_is_safe(self) -> None:
        task = self._create()
        with patch.object(
            socket, "socket", side_effect=AssertionError("network forbidden")
        ):
            lease = self._claim(task)
        ledger = self._ledger()
        claimed = next(item for item in ledger.tasks if item.task_id == task.task_id)
        self.assertEqual(claimed.state, "claimed")
        self.assertEqual(lease.task_revision, claimed.revision)
        with patch.object(
            drama_media_worker, "_clock_ms", return_value=self.now + 2
        ):
            replay = drama_media_worker.claim_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint="5" * 64,
                lease_token_fingerprint="6" * 64,
                expected_task_revision=task.revision,
                expected_ledger_fingerprint="0" * 64,
                lease_duration_ms=60_000,
                lane_capacity=2,
            )
        self.assertEqual(replay, lease)
        projection = drama_media_worker.build_media_worker_projection(
            self.name, now_ms=self.now + 2
        )
        self.assertEqual(projection["active_count"], 1)
        rendered = json.dumps(projection)
        for forbidden in (
            "worker_fingerprint",
            "lease_token",
            "lane_key",
            "provider_fingerprint",
            "account_fingerprint",
            str(paths.workspace_root(self.name)),
        ):
            self.assertNotIn(forbidden, rendered)

    def test_workspace_lane_capacity_spans_episodes_and_policy_is_frozen(self) -> None:
        first = self._create(episode_no=1)
        second = self._create(
            episode_no=2,
            subject_id="shot_002",
            input_fingerprint="b" * 64,
        )
        self._claim(first, capacity=1)
        with self.assertRaisesRegex(
            drama_media_worker.DramaMediaWorkerError, "capacity is full"
        ):
            self._claim(second, worker="7", token="8", capacity=1)
        with self.assertRaisesRegex(
            drama_media_worker.DramaMediaWorkerError, "policy changed"
        ):
            self._claim(second, worker="7", token="8", capacity=2)
        self.assertEqual(self._ledger(2).tasks[0].state, "ready")

    def test_heartbeat_is_guarded_exact_and_expired_lease_cannot_revive(self) -> None:
        task = self._create()
        lease = self._claim(task, duration=2_000)
        ledger = self._ledger()
        with patch.object(
            drama_media_worker, "_clock_ms", return_value=self.now + 2
        ):
            renewed = drama_media_worker.heartbeat_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint="5" * 64,
                lease_token_fingerprint="6" * 64,
                expected_task_revision=lease.task_revision,
                expected_lease_revision=lease.lease_revision,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
                lease_duration_ms=3_000,
            )
        self.assertEqual(renewed.lease_revision, 1)
        with patch.object(
            drama_media_worker, "_clock_ms", return_value=self.now + 3
        ):
            replay = drama_media_worker.heartbeat_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint="5" * 64,
                lease_token_fingerprint="6" * 64,
                expected_task_revision=lease.task_revision,
                expected_lease_revision=lease.lease_revision,
                expected_ledger_fingerprint="0" * 64,
                lease_duration_ms=3_000,
            )
        self.assertEqual(replay, renewed)
        with self.assertRaisesRegex(
            drama_media_worker.DramaMediaWorkerError, "expired"
        ):
            current = self._ledger()
            with patch.object(
                drama_media_worker,
                "_clock_ms",
                return_value=renewed.expires_at_ms,
            ):
                drama_media_worker.heartbeat_media_task(
                    self.name,
                    episode_no=1,
                    task_id=task.task_id,
                    worker_fingerprint="5" * 64,
                    lease_token_fingerprint="6" * 64,
                    expected_task_revision=renewed.task_revision,
                    expected_lease_revision=renewed.lease_revision,
                    expected_ledger_fingerprint=current.ledger_fingerprint,
                    lease_duration_ms=3_000,
                )
        with patch.object(
            drama_media_worker,
            "_clock_ms",
            return_value=renewed.expires_at_ms,
        ):
            with self.assertRaises(
                drama_media_worker.DramaMediaWorkerError
            ):
                drama_media_worker.heartbeat_media_task(
                    self.name,
                    episode_no=1,
                    task_id=task.task_id,
                    worker_fingerprint="5" * 64,
                    lease_token_fingerprint="6" * 64,
                    expected_task_revision=lease.task_revision,
                    expected_lease_revision=lease.lease_revision,
                    expected_ledger_fingerprint="0" * 64,
                    lease_duration_ms=3_000,
                )

    def test_release_is_guarded_exact_and_task_can_be_reclaimed(self) -> None:
        task = self._create()
        lease = self._claim(task)
        ledger = self._ledger()
        with patch.object(
            drama_media_worker, "_clock_ms", return_value=self.now + 2
        ):
            ready = drama_media_worker.release_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint="5" * 64,
                lease_token_fingerprint="6" * 64,
                expected_task_revision=lease.task_revision,
                expected_lease_revision=lease.lease_revision,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
            )
        self.assertEqual(ready.state, "ready")
        replay = drama_media_worker.release_media_task(
            self.name,
            episode_no=1,
            task_id=task.task_id,
            worker_fingerprint="5" * 64,
            lease_token_fingerprint="6" * 64,
            expected_task_revision=lease.task_revision,
            expected_lease_revision=lease.lease_revision,
            expected_ledger_fingerprint=ledger.ledger_fingerprint,
        )
        self.assertEqual(replay, ready)
        reclaimed = self._claim(
            ready, worker="7", token="8", now_delta=3
        )
        self.assertEqual(reclaimed.worker_fingerprint, "7" * 64)

    def test_takeover_requires_expiry_and_old_owner_cannot_heartbeat(self) -> None:
        task = self._create()
        lease = self._claim(task, duration=2_000, capacity=1)
        ledger = self._ledger()
        with self.assertRaisesRegex(
            drama_media_worker.DramaMediaWorkerError, "still active"
        ):
            with patch.object(
                drama_media_worker,
                "_clock_ms",
                return_value=self.now + 2,
            ):
                drama_media_worker.takeover_media_task(
                    self.name,
                    episode_no=1,
                    task_id=task.task_id,
                    worker_fingerprint="7" * 64,
                    lease_token_fingerprint="8" * 64,
                    expected_task_revision=lease.task_revision,
                    expected_lease_revision=lease.lease_revision,
                    expected_ledger_fingerprint=ledger.ledger_fingerprint,
                    lease_duration_ms=2_000,
                    lane_capacity=1,
                )
        with patch.object(
            drama_media_worker,
            "_clock_ms",
            return_value=lease.expires_at_ms,
        ):
            takeover = drama_media_worker.takeover_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint="7" * 64,
                lease_token_fingerprint="8" * 64,
                expected_task_revision=lease.task_revision,
                expected_lease_revision=lease.lease_revision,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
                lease_duration_ms=3_000,
                lane_capacity=1,
            )
        self.assertEqual(takeover.lease_revision, 1)
        with self.assertRaises(
            drama_media_worker.DramaMediaWorkerError
        ):
            current = self._ledger()
            with patch.object(
                drama_media_worker,
                "_clock_ms",
                return_value=takeover.heartbeat_at_ms + 1,
            ):
                drama_media_worker.heartbeat_media_task(
                    self.name,
                    episode_no=1,
                    task_id=task.task_id,
                    worker_fingerprint="5" * 64,
                    lease_token_fingerprint="6" * 64,
                    expected_task_revision=takeover.task_revision,
                    expected_lease_revision=takeover.lease_revision,
                    expected_ledger_fingerprint=current.ledger_fingerprint,
                    lease_duration_ms=3_000,
                )

    def test_terminal_unknown_and_cancel_remove_or_preserve_correct_ownership(self) -> None:
        task = self._create()
        lease = self._claim(task)
        claimed = next(
            item for item in self._ledger().tasks if item.task_id == task.task_id
        )
        with patch.object(
            drama_media_tasks, "_clock_ms", return_value=self.now + 2
        ):
            submitted = drama_media_tasks.transition_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                target_state="submitting",
                expected_task_revision=claimed.revision,
                expected_ledger_fingerprint=self._ledger().ledger_fingerprint,
                worker_fingerprint="5" * 64,
                lease_token_fingerprint="6" * 64,
                expected_lease_revision=lease.lease_revision,
            )
        with patch.object(
            drama_media_tasks, "_clock_ms", return_value=self.now + 3
        ):
            unknown = drama_media_tasks.transition_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                target_state="submission_unknown",
                expected_task_revision=submitted.revision,
                expected_ledger_fingerprint=self._ledger().ledger_fingerprint,
                worker_fingerprint="5" * 64,
                lease_token_fingerprint="6" * 64,
                expected_lease_revision=lease.lease_revision,
                outcome_code="transport_unknown",
            )
        self.assertEqual(unknown.state, "submission_unknown")
        self.assertEqual(self._ledger().leases, [])
        with self.assertRaisesRegex(
            drama_media_worker.DramaMediaWorkerError, "not claimable"
        ):
            self._claim(unknown, worker="7", token="8", now_delta=4)

        second = self._create(
            subject_id="shot_cancel",
            input_fingerprint="c" * 64,
        )
        second_lease = self._claim(second, worker="7", token="8", now_delta=5)
        current = self._ledger()
        drama_media_tasks.cancel_media_task_cascade(
            self.name,
            episode_no=1,
            task_id=second.task_id,
            expected_task_revision=second_lease.task_revision,
            expected_ledger_fingerprint=current.ledger_fingerprint,
            now_ms=self.now + 6,
        )
        self.assertFalse(
            any(item.task_id == second.task_id for item in self._ledger().leases)
        )

    def test_direct_claim_bypass_and_strict_numeric_inputs_are_rejected(self) -> None:
        task = self._create()
        ledger = self._ledger()
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError, "worker lease API"
        ):
            drama_media_tasks.transition_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                target_state="claimed",
                expected_task_revision=task.revision,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
            )
        for field, value in (
            ("expected_task_revision", False),
            ("lease_duration_ms", True),
            ("lane_capacity", 0),
        ):
            kwargs = {
                "episode_no": 1,
                "task_id": task.task_id,
                "worker_fingerprint": "5" * 64,
                "lease_token_fingerprint": "6" * 64,
                "expected_task_revision": task.revision,
                "expected_ledger_fingerprint": ledger.ledger_fingerprint,
                "lease_duration_ms": 60_000,
                "lane_capacity": 2,
            }
            kwargs[field] = value
            with self.assertRaises(drama_media_worker.DramaMediaWorkerError):
                drama_media_worker.claim_media_task(self.name, **kwargs)
        with patch.object(
            drama_media_worker, "_clock_ms", return_value=1.0
        ):
            with self.assertRaises(drama_media_worker.DramaMediaWorkerError):
                drama_media_worker.claim_media_task(
                    self.name,
                    episode_no=1,
                    task_id=task.task_id,
                    worker_fingerprint="5" * 64,
                    lease_token_fingerprint="6" * 64,
                    expected_task_revision=task.revision,
                    expected_ledger_fingerprint=ledger.ledger_fingerprint,
                    lease_duration_ms=60_000,
                    lane_capacity=2,
                )

    def test_execution_transition_requires_current_live_owner(self) -> None:
        task = self._create()
        lease = self._claim(task, duration=2_000)
        ledger = self._ledger()
        claimed = ledger.tasks[0]
        kwargs = {
            "episode_no": 1,
            "task_id": task.task_id,
            "target_state": "submitting",
            "expected_task_revision": claimed.revision,
            "expected_ledger_fingerprint": ledger.ledger_fingerprint,
            "expected_lease_revision": lease.lease_revision,
        }
        with patch.object(
            drama_media_tasks, "_clock_ms", return_value=self.now + 2
        ):
            with self.assertRaisesRegex(
                drama_media_tasks.DramaMediaTaskError, "ownership"
            ):
                drama_media_tasks.transition_media_task(
                    self.name,
                    worker_fingerprint="7" * 64,
                    lease_token_fingerprint="8" * 64,
                    **kwargs,
                )
            with self.assertRaisesRegex(
                drama_media_tasks.DramaMediaTaskError, "ownership"
            ):
                drama_media_tasks.transition_media_task(self.name, **kwargs)
        with patch.object(
            drama_media_tasks,
            "_clock_ms",
            return_value=lease.expires_at_ms,
        ):
            with self.assertRaisesRegex(
                drama_media_tasks.DramaMediaTaskError, "expired"
            ):
                drama_media_tasks.transition_media_task(
                    self.name,
                    worker_fingerprint="5" * 64,
                    lease_token_fingerprint="6" * 64,
                    **kwargs,
                )
        with patch.object(
            drama_media_tasks, "_clock_ms", return_value=self.now + 2
        ):
            submitting = drama_media_tasks.transition_media_task(
                self.name,
                worker_fingerprint="5" * 64,
                lease_token_fingerprint="6" * 64,
                **kwargs,
            )
        self.assertEqual(submitting.state, "submitting")
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError, "changed"
        ):
            drama_media_tasks.transition_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                target_state="submitting",
                expected_task_revision=claimed.revision,
                expected_ledger_fingerprint="0" * 64,
            )
        replay_kwargs = {
            "episode_no": 1,
            "task_id": task.task_id,
            "target_state": "submitting",
            "expected_task_revision": claimed.revision,
            "expected_ledger_fingerprint": ledger.ledger_fingerprint,
            "worker_fingerprint": "5" * 64,
            "lease_token_fingerprint": "6" * 64,
            "expected_lease_revision": lease.lease_revision,
        }
        with patch.object(
            drama_media_tasks, "_clock_ms", return_value=self.now + 3
        ):
            replay = drama_media_tasks.transition_media_task(
                self.name, **replay_kwargs
            )
        self.assertEqual(replay, submitting)
        with patch.object(
            drama_media_tasks,
            "_clock_ms",
            return_value=lease.expires_at_ms,
        ):
            with self.assertRaisesRegex(
                drama_media_tasks.DramaMediaTaskError, "replay is expired"
            ):
                drama_media_tasks.transition_media_task(
                    self.name, **replay_kwargs
                )

    def test_expired_lease_api_replays_never_return_success(self) -> None:
        task = self._create()
        lease = self._claim(task, duration=1_000)
        with patch.object(
            drama_media_worker,
            "_clock_ms",
            return_value=lease.expires_at_ms,
        ):
            with self.assertRaises(
                drama_media_worker.DramaMediaWorkerError
            ):
                drama_media_worker.claim_media_task(
                    self.name,
                    episode_no=1,
                    task_id=task.task_id,
                    worker_fingerprint="5" * 64,
                    lease_token_fingerprint="6" * 64,
                    expected_task_revision=task.revision,
                    expected_ledger_fingerprint="0" * 64,
                    lease_duration_ms=1_000,
                    lane_capacity=2,
                )
        ledger = self._ledger()
        with patch.object(
            drama_media_worker,
            "_clock_ms",
            return_value=lease.expires_at_ms,
        ):
            takeover = drama_media_worker.takeover_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint="7" * 64,
                lease_token_fingerprint="8" * 64,
                expected_task_revision=lease.task_revision,
                expected_lease_revision=lease.lease_revision,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
                lease_duration_ms=1_000,
                lane_capacity=2,
            )
        with patch.object(
            drama_media_worker,
            "_clock_ms",
            return_value=takeover.expires_at_ms,
        ):
            with self.assertRaises(
                drama_media_worker.DramaMediaWorkerError
            ):
                drama_media_worker.takeover_media_task(
                    self.name,
                    episode_no=1,
                    task_id=task.task_id,
                    worker_fingerprint="7" * 64,
                    lease_token_fingerprint="8" * 64,
                    expected_task_revision=lease.task_revision,
                    expected_lease_revision=lease.lease_revision,
                    expected_ledger_fingerprint=ledger.ledger_fingerprint,
                    lease_duration_ms=1_000,
                    lane_capacity=2,
                )

    def test_release_receipt_authenticates_replay_and_expired_release_fails(
        self,
    ) -> None:
        task = self._create()
        lease = self._claim(task, duration=2_000)
        before = self._ledger()
        with patch.object(
            drama_media_worker, "_clock_ms", return_value=self.now + 2
        ):
            ready = drama_media_worker.release_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint="5" * 64,
                lease_token_fingerprint="6" * 64,
                expected_task_revision=lease.task_revision,
                expected_lease_revision=lease.lease_revision,
                expected_ledger_fingerprint=before.ledger_fingerprint,
            )
        self.assertEqual(len(self._ledger().release_receipts), 1)
        for worker, token, ledger_fingerprint in (
            ("7", "6", before.ledger_fingerprint),
            ("5", "8", before.ledger_fingerprint),
            ("5", "6", "0" * 64),
        ):
            with self.assertRaises(
                drama_media_worker.DramaMediaWorkerError
            ):
                drama_media_worker.release_media_task(
                    self.name,
                    episode_no=1,
                    task_id=task.task_id,
                    worker_fingerprint=worker * 64,
                    lease_token_fingerprint=token * 64,
                    expected_task_revision=lease.task_revision,
                    expected_lease_revision=lease.lease_revision,
                    expected_ledger_fingerprint=ledger_fingerprint,
                )
        replay = drama_media_worker.release_media_task(
            self.name,
            episode_no=1,
            task_id=task.task_id,
            worker_fingerprint="5" * 64,
            lease_token_fingerprint="6" * 64,
            expected_task_revision=lease.task_revision,
            expected_lease_revision=lease.lease_revision,
            expected_ledger_fingerprint=before.ledger_fingerprint,
        )
        self.assertEqual(replay, ready)

        second = self._create(
            subject_id="expired_release",
            input_fingerprint="e" * 64,
        )
        expired = self._claim(
            second, worker="7", token="8", now_delta=3, duration=1_000
        )
        current = self._ledger()
        with patch.object(
            drama_media_worker,
            "_clock_ms",
            return_value=expired.expires_at_ms,
        ):
            with self.assertRaisesRegex(
                drama_media_worker.DramaMediaWorkerError, "cannot be released"
            ):
                drama_media_worker.release_media_task(
                    self.name,
                    episode_no=1,
                    task_id=second.task_id,
                    worker_fingerprint="7" * 64,
                    lease_token_fingerprint="8" * 64,
                    expected_task_revision=expired.task_revision,
                    expected_lease_revision=expired.lease_revision,
                    expected_ledger_fingerprint=current.ledger_fingerprint,
                )

    def test_takeover_rotates_token_and_claim_time_never_rewinds(self) -> None:
        task = self._create()
        lease = self._claim(task, duration=1_000)
        ledger = self._ledger()
        with patch.object(
            drama_media_worker,
            "_clock_ms",
            return_value=lease.expires_at_ms,
        ):
            with self.assertRaisesRegex(
                drama_media_worker.DramaMediaWorkerError, "new lease token"
            ):
                drama_media_worker.takeover_media_task(
                    self.name,
                    episode_no=1,
                    task_id=task.task_id,
                    worker_fingerprint="7" * 64,
                    lease_token_fingerprint="6" * 64,
                    expected_task_revision=lease.task_revision,
                    expected_lease_revision=lease.lease_revision,
                    expected_ledger_fingerprint=ledger.ledger_fingerprint,
                    lease_duration_ms=1_000,
                    lane_capacity=2,
                )
        with patch.object(
            drama_media_worker,
            "_clock_ms",
            return_value=lease.expires_at_ms,
        ):
            takeover = drama_media_worker.takeover_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint="7" * 64,
                lease_token_fingerprint="8" * 64,
                expected_task_revision=lease.task_revision,
                expected_lease_revision=lease.lease_revision,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
                lease_duration_ms=1_000,
                lane_capacity=2,
            )
        self.assertEqual(takeover.task_revision, lease.task_revision + 1)

        released_task = self._create(
            subject_id="monotonic",
            input_fingerprint="f" * 64,
        )
        released_lease = self._claim(
            released_task, worker="9", token="a", now_delta=10
        )
        before_release = self._ledger()
        with patch.object(
            drama_media_worker, "_clock_ms", return_value=self.now + 20
        ):
            ready = drama_media_worker.release_media_task(
                self.name,
                episode_no=1,
                task_id=released_task.task_id,
                worker_fingerprint="9" * 64,
                lease_token_fingerprint="a" * 64,
                expected_task_revision=released_lease.task_revision,
                expected_lease_revision=released_lease.lease_revision,
                expected_ledger_fingerprint=before_release.ledger_fingerprint,
            )
        with patch.object(
            drama_media_worker, "_clock_ms", return_value=self.now + 15
        ):
            with self.assertRaisesRegex(
                drama_media_worker.DramaMediaWorkerError, "time is invalid"
            ):
                drama_media_worker.claim_media_task(
                    self.name,
                    episode_no=1,
                    task_id=ready.task_id,
                    worker_fingerprint="b" * 64,
                    lease_token_fingerprint="c" * 64,
                    expected_task_revision=ready.revision,
                    expected_ledger_fingerprint=self._ledger().ledger_fingerprint,
                    lease_duration_ms=60_000,
                    lane_capacity=2,
                )

    def test_legacy_v1_ledger_upgrades_without_task_identity_drift(self) -> None:
        task = self._create()
        current = self._ledger()
        legacy_payload = {
            "schema_version": 1,
            "episode_no": 1,
            "revision": current.revision,
            "tasks": [item.model_dump() for item in current.tasks],
        }
        legacy = DramaMediaTaskLedger(
            **legacy_payload,
            ledger_fingerprint=_canonical_sha256(legacy_payload),
        )
        path = drama_media_tasks.media_task_ledger_path(self.name)
        path.write_bytes(drama_media_tasks._ledger_bytes(legacy))
        upgraded = self._ledger()
        self.assertEqual(upgraded.schema_version, 2)
        self.assertEqual(upgraded.tasks, [task])
        self.assertEqual(upgraded.leases, [])
        self.assertEqual(upgraded.release_receipts, [])
        self.assertEqual(upgraded.transition_receipts, [])
        self._claim(task)
        envelope = json.loads(path.read_text("utf-8"))
        self.assertEqual(envelope["ledger"]["schema_version"], 2)

    def test_legacy_v1_inflight_states_require_reconciliation(self) -> None:
        task = self._create()
        path = drama_media_tasks.media_task_ledger_path(self.name)
        for index, state in enumerate(
            (
                "claimed",
                "submitting",
                "submitted",
                "polling",
                "downloading",
                "validating",
            ),
            start=1,
        ):
            active = drama_media_tasks._replace_task(
                task, state=state, now_ms=self.now + index
            )
            payload = {
                "schema_version": 1,
                "episode_no": 1,
                "revision": index,
                "tasks": [active.model_dump()],
            }
            legacy = DramaMediaTaskLedger(
                **payload, ledger_fingerprint=_canonical_sha256(payload)
            )
            path.write_bytes(drama_media_tasks._ledger_bytes(legacy))
            with self.assertRaisesRegex(
                drama_media_tasks.DramaMediaTaskError, "reconciliation"
            ):
                self._ledger()

    def test_two_processes_cannot_claim_same_task_for_different_workers(self) -> None:
        if "fork" not in multiprocessing.get_all_start_methods():
            self.skipTest("fork start method unavailable")
        task = self._create()
        ledger = self._ledger()
        context = multiprocessing.get_context("fork")
        start = context.Event()
        results = context.Queue()
        processes = [
            context.Process(
                target=_claim_in_process,
                args=(
                    self.name,
                    task.task_id,
                    ledger.ledger_fingerprint,
                    worker,
                    token,
                    start,
                    results,
                ),
            )
            for worker, token in (("5", "6"), ("7", "8"))
        ]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(5)
            self.assertEqual(process.exitcode, 0)
        outcomes = [results.get(timeout=1)[0] for _ in processes]
        self.assertEqual(outcomes.count("ok"), 1)
        self.assertEqual(len(self._ledger().leases), 1)
