"""iter133 G1 persistent media task DAG, transitions, and safe projection."""

from __future__ import annotations

import json
import socket
from unittest.mock import patch

from src import drama_media_tasks, drama_media_worker, paths
from src.cli_workspace import init_workspace
from src.drama_schemas import DramaMediaTaskLedger, _canonical_sha256
from tests._drama_base import DramaTestBase
from tests._drama_media_backend_fixture import (
    MODEL_ID,
    PROVIDER_ID,
    build_registry,
)


class DramaMediaTaskTests(DramaTestBase):
    _IDENTITY = {
        "backend_id": "local-fixture",
        "provider_fingerprint": "1" * 64,
        "model_fingerprint": "2" * 64,
        "account_fingerprint": "3" * 64,
        "endpoint_fingerprint": "4" * 64,
    }

    def setUp(self) -> None:
        super().setUp()
        self.name = "media-task-dag"
        self._make_drama_workspace(self.name, episode_count=2)
        self.now = 1_700_000_000_000

    def _ledger(self, episode_no: int = 1):
        return drama_media_tasks.load_media_task_ledger(
            self.name, episode_no=episode_no
        )

    def _create(
        self,
        *,
        media_kind: str = "image",
        stage: str = "image-generate",
        subject_id: str = "shot_001",
        input_fingerprint: str = "a" * 64,
        dependencies=(),
        attempt_no: int = 1,
        expected: str | None = None,
        episode_no: int = 1,
        now_ms: int | None = None,
    ):
        arguments = {
            "episode_no": episode_no,
            "media_kind": media_kind,
            "stage": stage,
            "subject_id": subject_id,
            "input_fingerprint": input_fingerprint,
            "dependency_task_ids": dependencies,
            "attempt_no": attempt_no,
            "now_ms": self.now if now_ms is None else now_ms,
            "expected_ledger_fingerprint": expected,
            **self._IDENTITY,
        }
        if media_kind == "compose":
            return drama_media_tasks.create_media_task(
                self.name,
                **arguments,
            )
        task, _binding = drama_media_tasks.enqueue_bound_media_task(
            self.name,
            provider_id=PROVIDER_ID,
            model_id=MODEL_ID,
            registry=build_registry(
                media_kind=media_kind,
                backend_id=self._IDENTITY["backend_id"],
                provider_fingerprint=self._IDENTITY[
                    "provider_fingerprint"
                ],
                model_fingerprint=self._IDENTITY["model_fingerprint"],
            ),
            **arguments,
        )
        return task

    def _transition(
        self,
        task,
        target: str,
        *,
        now_delta: int,
        result_fingerprint: str | None = None,
        outcome_code: str | None = None,
    ):
        ledger = self._ledger(task.episode_no)
        current = next(item for item in ledger.tasks if item.task_id == task.task_id)
        if target == "claimed":
            with patch.object(
                drama_media_worker,
                "_clock_ms",
                return_value=self.now + now_delta,
            ):
                drama_media_worker.claim_media_task(
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
            return next(
                item
                for item in self._ledger(task.episode_no).tasks
                if item.task_id == task.task_id
            )
        lease = next(
            (
                item
                for item in ledger.leases
                if item.task_id == task.task_id
            ),
            None,
        )
        with patch.object(
            drama_media_tasks,
            "_clock_ms",
            return_value=self.now + now_delta,
        ):
            return drama_media_tasks.transition_media_task(
                self.name,
                episode_no=task.episode_no,
                task_id=task.task_id,
                target_state=target,
                expected_task_revision=current.revision,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
                worker_fingerprint="5" * 64 if lease is not None else None,
                lease_token_fingerprint="6" * 64 if lease is not None else None,
                expected_lease_revision=(
                    lease.lease_revision if lease is not None else None
                ),
                result_fingerprint=result_fingerprint,
                outcome_code=outcome_code,
            )

    def _succeed(self, task, *, offset: int = 1):
        for index, state in enumerate(
            (
                "claimed",
                "submitting",
                "submitted",
                "polling",
                "downloading",
                "validating",
            ),
            start=offset,
        ):
            task = self._transition(task, state, now_delta=index)
        return self._transition(
            task,
            "succeeded",
            now_delta=offset + 6,
            result_fingerprint="f" * 64,
        )

    def test_missing_projection_and_persistent_create_are_strict(self) -> None:
        empty = drama_media_tasks.build_media_task_projection(self.name)
        self.assertEqual(empty["task_count"], 0)
        self.assertEqual(empty["episode_no"], 1)

        with patch.object(
            socket, "socket", side_effect=AssertionError("network forbidden")
        ):
            created = self._create()
            loaded = self._ledger()
        self.assertEqual(created.state, "ready")
        self.assertEqual(loaded.tasks, [created])
        self.assertEqual(loaded.revision, 1)
        path = drama_media_tasks.media_task_ledger_path(self.name)
        self.assertIn("episode_001.tasks.json", str(path))
        envelope = json.loads(path.read_text("utf-8"))
        self.assertEqual(envelope["ledger_fingerprint"], loaded.ledger_fingerprint)
        self.assertEqual(envelope["ledger"], loaded.model_dump(mode="json"))

    def test_exact_create_replay_and_active_dedupe_do_not_swallow_new_input(self) -> None:
        first = self._create()
        replay = self._create(expected=None)
        self.assertEqual(replay, first)
        current = self._ledger()
        deduped = self._create(
            attempt_no=2, expected=current.ledger_fingerprint
        )
        self.assertEqual(deduped, first)
        self.assertEqual(self._ledger().revision, 1)

        changed = self._create(
            subject_id="shot_002",
            input_fingerprint="b" * 64,
            expected=current.ledger_fingerprint,
        )
        self.assertNotEqual(changed.dedupe_key, first.dedupe_key)
        self.assertEqual(len(self._ledger().tasks), 2)

    def test_terminal_attempt_allows_new_attempt_but_old_attempt_replays(self) -> None:
        first = self._create()
        failed = self._transition(
            self._transition(first, "claimed", now_delta=1),
            "failed",
            now_delta=2,
            outcome_code="local_failure",
        )
        ledger = self._ledger()
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError, "DAG is invalid"
        ):
            self._create(
                attempt_no=3,
                expected=ledger.ledger_fingerprint,
                now_ms=self.now + 3,
            )
        second = self._create(
            attempt_no=2,
            expected=ledger.ledger_fingerprint,
            now_ms=self.now + 3,
        )
        self.assertNotEqual(second.task_id, failed.task_id)
        self.assertEqual(second.dedupe_key, failed.dedupe_key)
        replay = self._create(attempt_no=1, expected=None)
        self.assertEqual(replay, failed)

    def test_failed_dependency_fails_existing_children_and_rejects_new_ones(self) -> None:
        image = self._create()
        ledger = self._ledger()
        video = self._create(
            media_kind="video",
            stage="video-generate",
            dependencies=[image.task_id],
            expected=ledger.ledger_fingerprint,
            now_ms=self.now + 1,
        )
        image = self._transition(image, "claimed", now_delta=2)
        image = self._transition(
            image,
            "failed",
            now_delta=3,
            outcome_code="provider_failed",
        )
        self.assertEqual(image.state, "failed")
        failed_child = next(
            item for item in self._ledger().tasks if item.task_id == video.task_id
        )
        self.assertEqual(failed_child.state, "failed")
        self.assertEqual(failed_child.outcome_code, "dependency_failed")
        replay = self._create(
            media_kind="video",
            stage="video-generate",
            dependencies=[image.task_id],
            expected=None,
            now_ms=self.now + 1,
        )
        self.assertEqual(replay, failed_child)
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError,
            "cannot reach success",
        ):
            self._create(
                media_kind="compose",
                stage="compose",
                subject_id="late_child",
                input_fingerprint="9" * 64,
                dependencies=[image.task_id],
                expected=self._ledger().ledger_fingerprint,
                now_ms=self.now + 4,
            )

    def test_dependency_success_promotes_planned_task_and_persists_after_reload(self) -> None:
        image = self._create()
        ledger = self._ledger()
        video = self._create(
            media_kind="video",
            stage="video-generate",
            dependencies=[image.task_id],
            expected=ledger.ledger_fingerprint,
            now_ms=self.now + 1,
        )
        self.assertEqual(video.state, "planned")
        image = self._succeed(image, offset=2)
        self.assertEqual(image.state, "succeeded")
        loaded = self._ledger()
        promoted = next(item for item in loaded.tasks if item.task_id == video.task_id)
        self.assertEqual(promoted.state, "ready")
        self.assertEqual(promoted.revision, 1)
        self.assertEqual(promoted.updated_at_ms, self.now + 8)

    def test_future_dated_child_promotes_without_reversing_its_time(self) -> None:
        image = self._create()
        ledger = self._ledger()
        video = self._create(
            media_kind="video",
            stage="video-generate",
            dependencies=[image.task_id],
            expected=ledger.ledger_fingerprint,
            now_ms=self.now + 100,
        )
        image = self._succeed(image, offset=1)
        self.assertEqual(image.state, "succeeded")
        promoted = next(
            item
            for item in self._ledger().tasks
            if item.task_id == video.task_id
        )
        self.assertEqual(promoted.state, "ready")
        self.assertEqual(promoted.updated_at_ms, self.now + 100)

    def test_transition_graph_unknown_submission_and_exact_replay_fail_closed(self) -> None:
        task = self._create()
        task = self._transition(task, "claimed", now_delta=1)
        task = self._transition(task, "submitting", now_delta=2)
        before_unknown = self._ledger()
        unknown = self._transition(
            task,
            "submission_unknown",
            now_delta=3,
            outcome_code="transport_unknown",
        )
        ledger = self._ledger()
        replay = drama_media_tasks.transition_media_task(
            self.name,
            episode_no=1,
            task_id=task.task_id,
            target_state="submission_unknown",
            expected_task_revision=task.revision,
            expected_ledger_fingerprint=before_unknown.ledger_fingerprint,
            worker_fingerprint="5" * 64,
            lease_token_fingerprint="6" * 64,
            expected_lease_revision=0,
            outcome_code="transport_unknown",
        )
        self.assertEqual(replay, unknown)
        self.assertEqual(self._ledger(), ledger)
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError, "replay does not match"
        ):
            drama_media_tasks.transition_media_task(
                self.name,
                episode_no=1,
                task_id=unknown.task_id,
                target_state="submission_unknown",
                expected_task_revision=unknown.revision,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
                outcome_code="transport_unknown",
            )
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError, "transition is invalid"
        ):
            drama_media_tasks.transition_media_task(
                self.name,
                episode_no=1,
                task_id=unknown.task_id,
                target_state="submitting",
                expected_task_revision=unknown.revision,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
            )
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError, "outcome is invalid"
        ):
            self._transition(
                unknown,
                "failed",
                now_delta=5,
                outcome_code="transport_unknown",
            )

    def test_unknown_dependency_replays_existing_child_but_rejects_new_child(self) -> None:
        image = self._create()
        child = self._create(
            media_kind="video",
            stage="video-generate",
            dependencies=[image.task_id],
            expected=self._ledger().ledger_fingerprint,
            now_ms=self.now + 1,
        )
        image = self._transition(image, "claimed", now_delta=2)
        image = self._transition(image, "submitting", now_delta=3)
        unknown = self._transition(
            image,
            "submission_unknown",
            now_delta=4,
            outcome_code="transport_unknown",
        )
        replay = self._create(
            media_kind="video",
            stage="video-generate",
            dependencies=[unknown.task_id],
            expected=None,
            now_ms=self.now + 1,
        )
        self.assertEqual(replay, child)
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError,
            "cannot reach success",
        ):
            self._create(
                media_kind="compose",
                stage="compose",
                subject_id="late_unknown_child",
                input_fingerprint="7" * 64,
                dependencies=[unknown.task_id],
                expected=self._ledger().ledger_fingerprint,
                now_ms=self.now + 5,
            )

    def test_cancel_cascade_marks_active_dependents_but_preserves_unknown(self) -> None:
        image = self._create()
        ledger = self._ledger()
        video = self._create(
            media_kind="video",
            stage="video-generate",
            subject_id="shot_001",
            dependencies=[image.task_id],
            expected=ledger.ledger_fingerprint,
            now_ms=self.now + 1,
        )
        ledger = self._ledger()
        compose = self._create(
            media_kind="compose",
            stage="compose",
            subject_id="episode",
            dependencies=[video.task_id],
            expected=ledger.ledger_fingerprint,
            now_ms=self.now + 2,
        )
        ledger = self._ledger()
        affected = drama_media_tasks.cancel_media_task_cascade(
            self.name,
            episode_no=1,
            task_id=image.task_id,
            expected_task_revision=image.revision,
            expected_ledger_fingerprint=ledger.ledger_fingerprint,
            now_ms=self.now + 3,
        )
        self.assertEqual(
            {item.task_id for item in affected},
            {image.task_id, video.task_id, compose.task_id},
        )
        self.assertTrue(all(item.state == "cancelling" for item in affected))
        replay = drama_media_tasks.cancel_media_task_cascade(
            self.name,
            episode_no=1,
            task_id=image.task_id,
            expected_task_revision=image.revision,
            expected_ledger_fingerprint=ledger.ledger_fingerprint,
            now_ms=self.now + 3,
        )
        self.assertEqual(replay, affected)
        cancelling_image = next(
            item for item in affected if item.task_id == image.task_id
        )
        cancelled = self._transition(
            cancelling_image,
            "cancelled",
            now_delta=4,
            outcome_code="cancel_confirmed",
        )
        self.assertEqual(cancelled.state, "cancelled")
        cancelled_child = next(
            item for item in self._ledger().tasks if item.task_id == video.task_id
        )
        replay = self._create(
            media_kind="video",
            stage="video-generate",
            subject_id="shot_001",
            dependencies=[image.task_id],
            expected=None,
            now_ms=self.now + 1,
        )
        self.assertEqual(replay, cancelled_child)
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError,
            "cannot reach success",
        ):
            self._create(
                media_kind="video",
                stage="video-generate",
                subject_id="late_cancel_child",
                input_fingerprint="8" * 64,
                dependencies=[cancelled.task_id],
                expected=self._ledger().ledger_fingerprint,
                now_ms=self.now + 5,
            )

        other = self._create(
            subject_id="shot_unknown",
            input_fingerprint="c" * 64,
            expected=self._ledger().ledger_fingerprint,
            now_ms=self.now + 6,
        )
        other = self._transition(other, "claimed", now_delta=7)
        other = self._transition(other, "submitting", now_delta=8)
        other = self._transition(
            other,
            "submission_unknown",
            now_delta=9,
            outcome_code="transport_unknown",
        )
        ledger = self._ledger()
        preserved = drama_media_tasks.cancel_media_task_cascade(
            self.name,
            episode_no=1,
            task_id=other.task_id,
            expected_task_revision=other.revision,
            expected_ledger_fingerprint=ledger.ledger_fingerprint,
            now_ms=self.now + 10,
        )
        self.assertEqual(preserved, [other])
        self.assertEqual(self._ledger(), ledger)

    def test_terminal_tasks_cannot_be_cancelled(self) -> None:
        failed = self._transition(
            self._transition(self._create(), "claimed", now_delta=1),
            "failed",
            now_delta=2,
            outcome_code="local_failure",
        )
        ledger = self._ledger()
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError,
            "terminal media task cannot be cancelled",
        ):
            drama_media_tasks.cancel_media_task_cascade(
                self.name,
                episode_no=1,
                task_id=failed.task_id,
                expected_task_revision=failed.revision,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
                now_ms=self.now + 3,
            )
        self.assertEqual(self._ledger(), ledger)

        second = self._create(
            subject_id="shot_success",
            input_fingerprint="d" * 64,
            expected=ledger.ledger_fingerprint,
            now_ms=self.now + 3,
        )
        succeeded = self._succeed(second, offset=4)
        ledger = self._ledger()
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError,
            "terminal media task cannot be cancelled",
        ):
            drama_media_tasks.cancel_media_task_cascade(
                self.name,
                episode_no=1,
                task_id=succeeded.task_id,
                expected_task_revision=succeeded.revision,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
                now_ms=self.now + 11,
            )
        self.assertEqual(self._ledger(), ledger)

    def test_stale_cas_cross_episode_and_invalid_numbers_are_rejected(self) -> None:
        first = self._create()
        ledger = self._ledger()
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError, "ledger changed"
        ):
            self._create(
                subject_id="shot_002",
                input_fingerprint="b" * 64,
                expected="0" * 64,
            )
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError, "dependency is missing"
        ):
            self._create(
                episode_no=2,
                media_kind="video",
                stage="video-generate",
                dependencies=[first.task_id],
                expected=None,
            )
        for kwargs in (
            {"attempt_no": True},
            {"now_ms": True},
            {"media_kind": "video", "stage": "image-generate"},
        ):
            with self.assertRaises(drama_media_tasks.DramaMediaTaskError):
                self._create(
                    subject_id="invalid_case",
                    input_fingerprint="e" * 64,
                    expected=ledger.ledger_fingerprint,
                    **kwargs,
                )
        for invalid_revision in (False, 0.0, -1, 10_001):
            with self.assertRaisesRegex(
                drama_media_tasks.DramaMediaTaskError,
                "revision is invalid",
            ):
                drama_media_tasks.transition_media_task(
                    self.name,
                    episode_no=1,
                    task_id=first.task_id,
                    target_state="claimed",
                    expected_task_revision=invalid_revision,
                    expected_ledger_fingerprint=ledger.ledger_fingerprint,
                )
            with self.assertRaisesRegex(
                drama_media_tasks.DramaMediaTaskError,
                "revision is invalid",
            ):
                drama_media_tasks.cancel_media_task_cascade(
                    self.name,
                    episode_no=1,
                    task_id=first.task_id,
                    expected_task_revision=invalid_revision,
                    expected_ledger_fingerprint=ledger.ledger_fingerprint,
                    now_ms=self.now + 1,
                )
        for invalid_time in (False, 0.0, -1, 10_000_000_000_000):
            with self.assertRaisesRegex(
                drama_media_tasks.DramaMediaTaskError,
                "update time is invalid",
            ):
                drama_media_tasks.cancel_media_task_cascade(
                    self.name,
                    episode_no=1,
                    task_id=first.task_id,
                    expected_task_revision=first.revision,
                    expected_ledger_fingerprint=ledger.ledger_fingerprint,
                    now_ms=invalid_time,
                )
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError,
            "creation time is invalid",
        ):
            self._create(
                media_kind="video",
                stage="video-generate",
                subject_id="time_reversal",
                input_fingerprint="f" * 64,
                dependencies=[first.task_id],
                expected=ledger.ledger_fingerprint,
                now_ms=self.now - 1,
            )

    def test_invalid_symlink_duplicate_json_and_tamper_are_preserved(self) -> None:
        name = "media-task-invalid"
        self._make_drama_workspace(name)
        root = paths.workspace_root(name)
        directory = root / "outputs/drama/media_tasks"
        directory.parent.mkdir(parents=True, exist_ok=True)
        owned = root / "owned"
        owned.mkdir()
        directory.symlink_to(owned)
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError, "invalid"
        ):
            drama_media_tasks.create_media_task(
                name,
                episode_no=1,
                media_kind="compose",
                stage="compose",
                subject_id="shot_001",
                input_fingerprint="a" * 64,
                dependency_task_ids=(),
                attempt_no=1,
                now_ms=self.now,
                expected_ledger_fingerprint=None,
                **self._IDENTITY,
            )
        self.assertEqual(list(owned.iterdir()), [])

        path = drama_media_tasks.media_task_ledger_path(self.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        duplicate = (
            '{"schema_version":1,"schema_version":1,'
            '"artifact_type":"drama_media_task_ledger",'
            '"ledger_fingerprint":"' + "0" * 64 + '","ledger":{}}'
        )
        path.write_text(duplicate, encoding="utf-8")
        before = path.read_bytes()
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError, "invalid"
        ):
            self._ledger()
        self.assertEqual(path.read_bytes(), before)

    def test_unbound_provider_tasks_and_unbounded_dependencies_are_rejected(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            drama_media_tasks.DramaMediaTaskError,
            "requires a frozen backend binding",
        ):
            drama_media_tasks.create_media_task(
                self.name,
                episode_no=1,
                media_kind="image",
                stage="image-generate",
                subject_id="shot_unbound",
                input_fingerprint="a" * 64,
                dependency_task_ids=(),
                attempt_no=1,
                now_ms=self.now,
                expected_ledger_fingerprint=None,
                **self._IDENTITY,
            )
        invalid_dependencies = [
            ["dmt_" + f"{index:024x}" for index in range(33)],
            (item for item in ()),
        ]
        with patch.object(
            drama_media_tasks,
            "acquire_write_lock",
            side_effect=AssertionError("lock must not be reached"),
        ):
            for dependencies in invalid_dependencies:
                with self.assertRaisesRegex(
                    drama_media_tasks.DramaMediaTaskError,
                    "dependency list is invalid",
                ):
                    drama_media_tasks.create_media_task(
                        self.name,
                        episode_no=1,
                        media_kind="compose",
                        stage="compose",
                        subject_id="episode_compose",
                        input_fingerprint="b" * 64,
                        dependency_task_ids=dependencies,
                        attempt_no=1,
                        now_ms=self.now,
                        expected_ledger_fingerprint=None,
                        **self._IDENTITY,
                    )

    def test_workspace_metadata_symlink_and_oversize_fail_closed(self) -> None:
        for suffix, content in (
            ("symlink", b'{"type":"drama","created_at":null,"schema_version":1}'),
            ("oversize", b"x" * (drama_media_tasks.MAX_WORKSPACE_METADATA_BYTES + 1)),
            (
                "bool-version",
                b'{"type":"drama","created_at":null,"schema_version":true}',
            ),
        ):
            name = f"media-task-meta-{suffix}"
            self._make_drama_workspace(name)
            metadata = paths.workspace_root(name) / "data/workspace.json"
            if suffix == "symlink":
                external = paths.workspace_root(name) / "metadata-target.json"
                external.write_bytes(content)
                metadata.unlink()
                metadata.symlink_to(external)
            else:
                metadata.write_bytes(content)
            with self.assertRaisesRegex(
                drama_media_tasks.DramaMediaTaskError,
                "media task workspace",
            ):
                drama_media_tasks.build_media_task_projection(name)

    def test_schema_rejects_extra_fields_cycle_and_rehashed_state_spoofing(self) -> None:
        first = self._create()
        with self.assertRaises(ValueError):
            type(first)(**{**first.model_dump(), "secret": "forbidden"})

        ledger = self._ledger()
        second = self._create(
            subject_id="shot_002",
            input_fingerprint="b" * 64,
            expected=ledger.ledger_fingerprint,
        )
        forged_first = first.model_copy(
            update={"dependency_task_ids": [second.task_id]}
        )
        forged_second = second.model_copy(
            update={"dependency_task_ids": [first.task_id]}
        )
        with self.assertRaises(ValueError):
            DramaMediaTaskLedger(
                schema_version=1,
                episode_no=1,
                revision=99,
                tasks=sorted(
                    [forged_first, forged_second], key=lambda item: item.task_id
                ),
                ledger_fingerprint="0" * 64,
            )

        payload = first.model_dump(exclude={"record_fingerprint"})
        payload["state"] = "succeeded"
        payload["result_fingerprint"] = None
        payload["record_fingerprint"] = _canonical_sha256(payload)
        with self.assertRaises(ValueError):
            type(first)(**payload)
        with self.assertRaises(drama_media_tasks.DramaMediaTaskError):
            self._transition(
                first,
                "failed",
                now_delta=1,
                outcome_code="opaque_provider_payload",
            )

    def test_projection_is_bounded_allowlisted_and_paid_evidence_free(self) -> None:
        task = self._create()
        projection = drama_media_tasks.build_media_task_projection(self.name)
        public = projection["tasks"][0]
        self.assertEqual(public["task_id"], task.task_id)
        self.assertEqual(
            set(public),
            {
                "task_id",
                "episode_no",
                "media_kind",
                "stage",
                "subject_id",
                "dependency_task_ids",
                "blocked_dependency_ids",
                "state",
                "revision",
                "created_at_ms",
                "updated_at_ms",
                "result_fingerprint",
                "outcome_code",
                "backend_binding_status",
            },
        )
        rendered = json.dumps(projection, ensure_ascii=False)
        for forbidden in (
            "backend_id",
            "provider_fingerprint",
            "account_fingerprint",
            "endpoint_fingerprint",
            "prompt",
            "provider_task_id",
            "signed_url",
            str(paths.workspace_root(self.name)),
        ):
            self.assertNotIn(forbidden, rendered)

        init_workspace("novel-workspace", type="novel")
        with self.assertRaises(ValueError):
            drama_media_tasks.build_media_task_projection("novel-workspace")
