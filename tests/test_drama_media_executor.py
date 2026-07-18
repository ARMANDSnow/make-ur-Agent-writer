"""iter137 G5 owner-guarded provider execution loop."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

from src import (
    drama_media_executor,
    drama_media_queue_client,
    drama_media_tasks,
    drama_media_worker,
    paths,
)
from tests._drama_base import DramaTestBase
from tests._drama_media_backend_fixture import (
    MODEL_ID,
    PROVIDER_ID,
    build_registry,
)


class _Bridge(drama_media_executor.DramaMediaPaidEvidenceBridge):
    def __init__(
        self,
        identity: drama_media_executor.DramaMediaExecutionIdentity,
        *,
        outcomes: dict[str, list[str]] | None = None,
        submit_error: Exception | None = None,
        mutate_identity_after_submit: bool = False,
    ) -> None:
        self._identity = identity
        self.outcomes = {
            key: list(value) for key, value in (outcomes or {}).items()
        }
        self.submit_error = submit_error
        self.mutate_identity_after_submit = mutate_identity_after_submit
        self.calls: dict[str, int] = defaultdict(int)
        self.contexts = []

    @property
    def identity(self):
        return self._identity

    def _result(self, phase, context):
        self.calls[phase] += 1
        self.contexts.append(context)
        queue = self.outcomes.get(phase, [])
        defaults = {
            "submit": "submitted",
            "poll": "ready",
            "download": "ready",
            "validate": "succeeded",
        }
        outcome = queue.pop(0) if queue else defaults[phase]
        return drama_media_executor.build_media_execution_observation(
            context=context,
            phase=phase,
            outcome=outcome,
            paid_evidence_fingerprint={
                "submit": "a",
                "poll": "b",
                "download": "c",
                "validate": "d",
            }[phase]
            * 64,
            artifact_evidence_fingerprint=(
                "e" * 64 if outcome == "succeeded" else None
            ),
        )

    def submit(self, context):
        if self.submit_error is not None:
            raise self.submit_error
        result = self._result("submit", context)
        if self.mutate_identity_after_submit:
            self._identity = drama_media_executor.DramaMediaExecutionIdentity(
                **{
                    **self._identity.__dict__,
                    "account_fingerprint": "9" * 64,
                }
            )
        return result

    def poll(self, context):
        return self._result("poll", context)

    def download(self, context):
        return self._result("download", context)

    def validate(self, context):
        return self._result("validate", context)


class DramaMediaExecutorTests(DramaTestBase):
    _TASK_IDENTITY = {
        "backend_id": "local-fixture",
        "provider_fingerprint": "1" * 64,
        "model_fingerprint": "2" * 64,
        "account_fingerprint": "3" * 64,
        "endpoint_fingerprint": "4" * 64,
    }
    _WORKER = "5" * 64
    _TOKEN = "6" * 64

    def setUp(self) -> None:
        super().setUp()
        self.name = "media-executor"
        self._make_drama_workspace(self.name, episode_count=2)
        self.now = 1_700_000_000_000

    def _ledger(self):
        return drama_media_tasks.load_media_task_ledger(
            self.name, episode_no=1
        )

    def _create_and_claim(self, media_kind="image"):
        stage = {
            "image": "image-generate",
            "video": "video-generate",
            "audio": "tts-synthesize",
        }[media_kind]
        with patch.object(
            drama_media_tasks, "_clock_ms", return_value=self.now
        ):
            task, binding = drama_media_tasks.enqueue_bound_media_task(
                self.name,
                episode_no=1,
                media_kind=media_kind,
                stage=stage,
                subject_id="subject_001",
                input_fingerprint="0" * 64,
                provider_id=PROVIDER_ID,
                model_id=MODEL_ID,
                registry=build_registry(
                    media_kind=media_kind,
                    backend_id=self._TASK_IDENTITY["backend_id"],
                    provider_fingerprint=self._TASK_IDENTITY[
                        "provider_fingerprint"
                    ],
                    model_fingerprint=self._TASK_IDENTITY["model_fingerprint"],
                ),
                dependency_task_ids=(),
                attempt_no=1,
                now_ms=self.now,
                expected_ledger_fingerprint=None,
                **self._TASK_IDENTITY,
            )
        with patch.object(
            drama_media_worker, "_clock_ms", return_value=self.now + 1
        ):
            drama_media_worker.claim_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint=self._WORKER,
                lease_token_fingerprint=self._TOKEN,
                expected_task_revision=task.revision,
                expected_ledger_fingerprint=self._ledger().ledger_fingerprint,
                lease_duration_ms=60_000,
                lane_capacity=1,
            )
        identity = drama_media_executor.DramaMediaExecutionIdentity(
            bridge_id=self._TASK_IDENTITY["backend_id"],
            backend_id=self._TASK_IDENTITY["backend_id"],
            provider_fingerprint=self._TASK_IDENTITY[
                "provider_fingerprint"
            ],
            model_fingerprint=self._TASK_IDENTITY["model_fingerprint"],
            account_fingerprint=self._TASK_IDENTITY[
                "account_fingerprint"
            ],
            endpoint_fingerprint=self._TASK_IDENTITY[
                "endpoint_fingerprint"
            ],
            source_capability_fingerprint=(
                binding.source_capability_fingerprint
            ),
        )
        return task, _Bridge(identity)

    def _run(self, task, bridge, **kwargs):
        with (
            patch.object(
                socket, "socket", side_effect=AssertionError("network forbidden")
            ),
            patch.object(
                drama_media_tasks, "_clock_ms", return_value=self.now + 10
            ),
            patch.object(
                drama_media_worker, "_clock_ms", return_value=self.now + 10
            ),
        ):
            return drama_media_executor.run_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint=self._WORKER,
                lease_token_fingerprint=self._TOKEN,
                bridge=bridge,
                lease_duration_ms=60_000,
                timeout_ms=30_000,
                **kwargs,
            )

    def test_sync_image_uses_submit_and_validate_without_download(self) -> None:
        task, bridge = self._create_and_claim("image")
        with patch.object(
            socket, "socket", side_effect=AssertionError("network forbidden")
        ):
            result = self._run(task, bridge)
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(
            dict(bridge.calls),
            {"submit": 1, "validate": 1},
        )
        self.assertEqual(self._ledger().tasks[0].result_fingerprint, "e" * 64)
        rendered = json.dumps(result)
        for secret in (
            PROVIDER_ID,
            MODEL_ID,
            "fixture-bridge",
            "a" * 64,
            "3" * 64,
            "4" * 64,
        ):
            self.assertNotIn(secret, rendered)

    def test_async_video_stops_on_pending_then_resumes_without_resubmit(
        self,
    ) -> None:
        task, bridge = self._create_and_claim("video")
        bridge.outcomes["poll"] = ["pending", "ready"]
        first = self._run(task, bridge)
        self.assertEqual(first["state"], "polling")
        self.assertEqual(first["execution_status"], "pending")
        second = self._run(task, bridge)
        self.assertEqual(second["state"], "succeeded")
        self.assertEqual(bridge.calls["submit"], 1)
        self.assertEqual(bridge.calls["poll"], 2)
        self.assertEqual(bridge.calls["download"], 1)
        self.assertEqual(bridge.calls["validate"], 1)

    def test_audio_keeps_synthesis_and_download_separate(self) -> None:
        task, bridge = self._create_and_claim("audio")
        result = self._run(task, bridge)
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(
            dict(bridge.calls),
            {"submit": 1, "download": 1, "validate": 1},
        )

    def test_submission_unknown_is_terminal_and_never_resubmitted(self) -> None:
        task, bridge = self._create_and_claim("video")
        bridge.outcomes["submit"] = ["submission_unknown"]
        first = self._run(task, bridge)
        self.assertEqual(first["state"], "submission_unknown")
        second = self._run(task, bridge)
        self.assertEqual(second["state"], "submission_unknown")
        self.assertEqual(bridge.calls["submit"], 1)
        self.assertEqual(self._ledger().leases, [])

    def test_submit_exception_becomes_unknown(self) -> None:
        task, bridge = self._create_and_claim("video")
        bridge.submit_error = RuntimeError("provider response with secret")
        with self.assertRaises(drama_media_executor.DramaMediaExecutorError) as caught:
            self._run(task, bridge)
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(self._ledger().tasks[0].state, "submission_unknown")

    def test_post_call_identity_drift_becomes_unknown(self) -> None:
        task, bridge = self._create_and_claim("video")
        bridge.mutate_identity_after_submit = True
        with self.assertRaises(drama_media_executor.DramaMediaExecutorError):
            self._run(task, bridge)
        self.assertEqual(self._ledger().tasks[0].state, "submission_unknown")

    def test_proven_not_sent_is_failed_without_paid_receipt_projection(self) -> None:
        task, bridge = self._create_and_claim("image")
        bridge.outcomes["submit"] = ["not_sent"]
        result = self._run(task, bridge)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["outcome_code"], "local_failure")
        self.assertEqual(self._ledger().leases, [])

    def test_poll_failure_does_not_resubmit(self) -> None:
        task, bridge = self._create_and_claim("video")
        bridge.outcomes["poll"] = ["poll_failed"]
        result = self._run(task, bridge)
        self.assertEqual(result["outcome_code"], "poll_failed")
        self.assertEqual(bridge.calls["submit"], 1)

    def test_download_failure_does_not_resubmit(self) -> None:
        task, bridge = self._create_and_claim("audio")
        bridge.outcomes["download"] = ["download_failed"]
        result = self._run(task, bridge)
        self.assertEqual(result["outcome_code"], "download_failed")
        self.assertEqual(bridge.calls["submit"], 1)

    def test_download_exception_retries_without_audio_resynthesis(
        self,
    ) -> None:
        task, bridge = self._create_and_claim("audio")

        class FlakyDownload(_Bridge):
            def __init__(self, identity):
                super().__init__(identity)
                self.failed_once = False

            def download(self, context):
                if not self.failed_once:
                    self.failed_once = True
                    self.calls["download"] += 1
                    raise RuntimeError("bounded provider download failure")
                return super().download(context)

        flaky = FlakyDownload(bridge.identity)
        with self.assertRaises(drama_media_executor.DramaMediaExecutorError):
            self._run(task, flaky)
        self.assertEqual(self._ledger().tasks[0].state, "downloading")
        result = self._run(task, flaky)
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(flaky.calls["submit"], 1)
        self.assertEqual(flaky.calls["download"], 2)
        self.assertEqual(flaky.calls["validate"], 1)

    def test_validation_failure_is_terminal_and_bounded(self) -> None:
        task, bridge = self._create_and_claim("image")
        bridge.outcomes["validate"] = ["validation_failed"]
        result = self._run(task, bridge)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["outcome_code"], "validation_failed")

    def test_wrong_owner_or_bridge_identity_never_invokes_bridge(self) -> None:
        task, bridge = self._create_and_claim("image")
        with self.assertRaises(drama_media_executor.DramaMediaExecutorError):
            with (
                patch.object(
                    drama_media_tasks,
                    "_clock_ms",
                    return_value=self.now + 10,
                ),
                patch.object(
                    drama_media_worker,
                    "_clock_ms",
                    return_value=self.now + 10,
                ),
            ):
                drama_media_executor.run_media_task(
                    self.name,
                    episode_no=1,
                    task_id=task.task_id,
                    worker_fingerprint="7" * 64,
                    lease_token_fingerprint=self._TOKEN,
                    bridge=bridge,
                    lease_duration_ms=60_000,
                    timeout_ms=30_000,
                )
        self.assertEqual(dict(bridge.calls), {})

        bridge._identity = drama_media_executor.DramaMediaExecutionIdentity(
            **{
                **bridge.identity.__dict__,
                "endpoint_fingerprint": "8" * 64,
            }
        )
        with self.assertRaises(drama_media_executor.DramaMediaExecutorError):
            self._run(task, bridge)
        self.assertEqual(dict(bridge.calls), {})

    def test_bridge_identity_error_is_redacted_before_any_action(self) -> None:
        task, bridge = self._create_and_claim("image")

        class BrokenIdentity(_Bridge):
            @property
            def identity(self):
                raise RuntimeError("credential and provider response")

        broken = BrokenIdentity(bridge.identity)
        with self.assertRaises(
            drama_media_executor.DramaMediaExecutorError
        ) as caught:
            self._run(task, broken)
        self.assertNotIn("credential", str(caught.exception))
        self.assertNotIn("provider response", str(caught.exception))
        self.assertEqual(dict(broken.calls), {})

    def test_cancel_request_stops_without_faking_provider_confirmation(self) -> None:
        task, bridge = self._create_and_claim("video")
        with patch.object(
            drama_media_queue_client,
            "_wall_clock_ms",
            return_value=self.now + 2,
        ):
            drama_media_queue_client.request_media_task_cancel(
                self.name, episode_no=1, task_id=task.task_id
            )
        result = self._run(task, bridge)
        self.assertEqual(result["state"], "cancelling")
        self.assertEqual(result["execution_status"], "cancel_requested")
        self.assertEqual(dict(bridge.calls), {})

    def test_cancel_racing_with_submit_rejects_stale_result(self) -> None:
        task, bridge = self._create_and_claim("video")

        class CancellingBridge(_Bridge):
            def submit(inner_self, context):
                with patch.object(
                    drama_media_queue_client,
                    "_wall_clock_ms",
                    return_value=self.now + 11,
                ):
                    drama_media_queue_client.request_media_task_cancel(
                        self.name,
                        episode_no=1,
                        task_id=task.task_id,
                    )
                return inner_self._result("submit", context)

        cancelling = CancellingBridge(bridge.identity)
        with self.assertRaises(drama_media_executor.DramaMediaExecutorError):
            self._run(task, cancelling)
        current = self._ledger().tasks[0]
        self.assertEqual(current.state, "cancelling")
        self.assertIsNone(current.outcome_code)
        self.assertEqual(cancelling.calls["submit"], 1)

    def test_zero_deadline_and_step_cap_are_strict(self) -> None:
        task, bridge = self._create_and_claim("image")
        with self.assertRaises(drama_media_executor.DramaMediaExecutorDeadline):
            with (
                patch.object(
                    drama_media_tasks,
                    "_clock_ms",
                    return_value=self.now + 10,
                ),
                patch.object(
                    drama_media_worker,
                    "_clock_ms",
                    return_value=self.now + 10,
                ),
            ):
                drama_media_executor.run_media_task(
                    self.name,
                    episode_no=1,
                    task_id=task.task_id,
                    worker_fingerprint=self._WORKER,
                    lease_token_fingerprint=self._TOKEN,
                    bridge=bridge,
                    lease_duration_ms=60_000,
                    timeout_ms=0,
                )
        self.assertEqual(dict(bridge.calls), {})
        with self.assertRaises(drama_media_executor.DramaMediaExecutorError):
            self._run(task, bridge, max_steps=17)

    def test_deadline_rechecked_after_heartbeat_before_bridge(self) -> None:
        task, bridge = self._create_and_claim("video")
        with (
            patch.object(
                drama_media_executor.time,
                "monotonic_ns",
                side_effect=[100, 110, 200],
            ),
            patch.object(
                drama_media_tasks, "_clock_ms", return_value=self.now + 10
            ),
            patch.object(
                drama_media_worker, "_clock_ms", return_value=self.now + 10
            ),
        ):
            with self.assertRaises(
                drama_media_executor.DramaMediaExecutorDeadline
            ):
                drama_media_executor.execute_media_task_step(
                    self.name,
                    episode_no=1,
                    task_id=task.task_id,
                    worker_fingerprint=self._WORKER,
                    lease_token_fingerprint=self._TOKEN,
                    bridge=bridge,
                    lease_duration_ms=60_000,
                    deadline_monotonic_ns=150,
                )
        self.assertEqual(dict(bridge.calls), {})
        self.assertEqual(self._ledger().tasks[0].state, "submitting")

    def test_plain_duck_bridge_and_malformed_observation_are_blocked(
        self,
    ) -> None:
        task, bridge = self._create_and_claim("image")

        class Duck:
            identity = bridge.identity

        with self.assertRaises(drama_media_executor.DramaMediaExecutorError):
            self._run(task, Duck())

        class Malformed(_Bridge):
            def submit(self, context):
                result = super().submit(context)
                return drama_media_executor.DramaMediaExecutionObservation(
                    **{
                        **result.__dict__,
                        "observation_fingerprint": "f" * 64,
                    }
                )

        malformed = Malformed(bridge.identity)
        with self.assertRaises(drama_media_executor.DramaMediaExecutorError):
            self._run(task, malformed)
        self.assertEqual(self._ledger().tasks[0].state, "submission_unknown")

    def test_cross_context_paid_observation_is_blocked(self) -> None:
        task, bridge = self._create_and_claim("video")

        class CrossContext(_Bridge):
            def submit(self, context):
                stale = drama_media_executor.DramaMediaExecutionContext(
                    **{
                        **context.__dict__,
                        "lease_revision": context.lease_revision + 1,
                    }
                )
                return drama_media_executor.build_media_execution_observation(
                    context=stale,
                    phase="submit",
                    outcome="submitted",
                    paid_evidence_fingerprint="a" * 64,
                )

        crossed = CrossContext(bridge.identity)
        with self.assertRaises(drama_media_executor.DramaMediaExecutorError):
            self._run(task, crossed)
        self.assertEqual(self._ledger().tasks[0].state, "submission_unknown")

    def test_expired_post_call_owner_cannot_commit_and_takeover_resumes(
        self,
    ) -> None:
        task, bridge = self._create_and_claim("video")
        clock = [self.now + 10]

        class DurableBridge(_Bridge):
            def __init__(self, identity):
                super().__init__(identity)
                self.external_submissions = 0
                self.paid_submitted = False

            def submit(self, context):
                if not self.paid_submitted:
                    self.external_submissions += 1
                    self.paid_submitted = True
                    clock[0] = self.now_after_expiry
                return self._result("submit", context)

        durable = DurableBridge(bridge.identity)
        durable.now_after_expiry = self.now + 70_000
        with (
            patch.object(
                drama_media_tasks, "_clock_ms", side_effect=lambda: clock[0]
            ),
            patch.object(
                drama_media_worker, "_clock_ms", side_effect=lambda: clock[0]
            ),
        ):
            with self.assertRaises(
                drama_media_executor.DramaMediaExecutorError
            ):
                drama_media_executor.run_media_task(
                    self.name,
                    episode_no=1,
                    task_id=task.task_id,
                    worker_fingerprint=self._WORKER,
                    lease_token_fingerprint=self._TOKEN,
                    bridge=durable,
                    lease_duration_ms=60_000,
                    timeout_ms=30_000,
                )
            stalled = self._ledger()
            current = stalled.tasks[0]
            lease = stalled.leases[0]
            self.assertEqual(current.state, "submitting")
            new_worker = "7" * 64
            new_token = "8" * 64
            drama_media_worker.takeover_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint=new_worker,
                lease_token_fingerprint=new_token,
                expected_task_revision=current.revision,
                expected_lease_revision=lease.lease_revision,
                expected_ledger_fingerprint=stalled.ledger_fingerprint,
                lease_duration_ms=60_000,
                lane_capacity=1,
            )
            result = drama_media_executor.run_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint=new_worker,
                lease_token_fingerprint=new_token,
                bridge=durable,
                lease_duration_ms=60_000,
                timeout_ms=30_000,
            )
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(durable.external_submissions, 1)
        self.assertEqual(durable.calls["submit"], 2)

    def test_real_process_crash_resumes_from_durable_paid_evidence(
        self,
    ) -> None:
        task, _bridge = self._create_and_claim("video")
        driver = (
            Path(__file__).parent
            / "support"
            / "drama_media_executor_driver.py"
        )
        counter = Path(self._tmp.name) / "media-executor-counter.json"
        counter.write_text(
            json.dumps(
                {
                    "paid_submitted": False,
                    "submit": 0,
                    "poll": 0,
                    "download": 0,
                    "validate": 0,
                },
                sort_keys=True,
            ),
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
        first = subprocess.run(
            [
                sys.executable,
                str(driver),
                str(paths.WORKSPACE_DIR),
                self.name,
                task.task_id,
                self._WORKER,
                self._TOKEN,
                "crash_after_paid_submit",
                str(counter),
                str(self.now + 10),
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(first.returncode, 91, first.stderr)
        crashed = self._ledger()
        self.assertEqual(crashed.tasks[0].state, "submitting")
        self.assertEqual(json.loads(counter.read_text())["submit"], 1)
        new_worker = "7" * 64
        new_token = "8" * 64
        with patch.object(
            drama_media_worker,
            "_clock_ms",
            return_value=self.now + 70_000,
        ):
            drama_media_worker.takeover_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint=new_worker,
                lease_token_fingerprint=new_token,
                expected_task_revision=crashed.tasks[0].revision,
                expected_lease_revision=crashed.leases[0].lease_revision,
                expected_ledger_fingerprint=crashed.ledger_fingerprint,
                lease_duration_ms=60_000,
                lane_capacity=1,
            )

        second = subprocess.run(
            [
                sys.executable,
                str(driver),
                str(paths.WORKSPACE_DIR),
                self.name,
                task.task_id,
                new_worker,
                new_token,
                "resume",
                str(counter),
                str(self.now + 70_010),
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        counts = json.loads(counter.read_text())
        self.assertEqual(counts["submit"], 1)
        self.assertEqual(counts["poll"], 1)
        self.assertEqual(counts["download"], 1)
        self.assertEqual(counts["validate"], 1)
        self.assertEqual(self._ledger().tasks[0].state, "succeeded")

    def test_real_process_pre_submit_crash_resumes_with_one_submit(
        self,
    ) -> None:
        task, _bridge = self._create_and_claim("video")
        driver = (
            Path(__file__).parent
            / "support"
            / "drama_media_executor_driver.py"
        )
        counter = Path(self._tmp.name) / "media-executor-pre-submit.json"
        counter.write_text(
            json.dumps(
                {
                    "paid_submitted": False,
                    "submit": 0,
                    "poll": 0,
                    "download": 0,
                    "validate": 0,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "DRAGON_RAJA_SKIP_DOTENV": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "OPENAI_MODEL": "mock",
        }
        command = [
            sys.executable,
            str(driver),
            str(paths.WORKSPACE_DIR),
            self.name,
            task.task_id,
            self._WORKER,
            self._TOKEN,
            "crash_before_paid_submit",
            str(counter),
            str(self.now + 10),
        ]
        first = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(first.returncode, 90, first.stderr)
        crashed = self._ledger()
        self.assertEqual(crashed.tasks[0].state, "submitting")
        self.assertEqual(json.loads(counter.read_text())["submit"], 0)
        new_worker = "7" * 64
        new_token = "8" * 64
        with patch.object(
            drama_media_worker,
            "_clock_ms",
            return_value=self.now + 70_000,
        ):
            drama_media_worker.takeover_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint=new_worker,
                lease_token_fingerprint=new_token,
                expected_task_revision=crashed.tasks[0].revision,
                expected_lease_revision=crashed.leases[0].lease_revision,
                expected_ledger_fingerprint=crashed.ledger_fingerprint,
                lease_duration_ms=60_000,
                lane_capacity=1,
            )
        command[5] = new_worker
        command[6] = new_token
        command[7] = "resume"
        command[9] = str(self.now + 70_010)
        second = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(counter.read_text())["submit"], 1)
        self.assertEqual(self._ledger().tasks[0].state, "succeeded")

    def test_real_process_post_commit_lost_response_skips_submit(
        self,
    ) -> None:
        task, _bridge = self._create_and_claim("video")
        driver = (
            Path(__file__).parent
            / "support"
            / "drama_media_executor_driver.py"
        )
        counter = Path(self._tmp.name) / "media-executor-post-commit.json"
        counter.write_text(
            json.dumps(
                {
                    "paid_submitted": False,
                    "submit": 0,
                    "poll": 0,
                    "download": 0,
                    "validate": 0,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "DRAGON_RAJA_SKIP_DOTENV": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "OPENAI_MODEL": "mock",
        }
        command = [
            sys.executable,
            str(driver),
            str(paths.WORKSPACE_DIR),
            self.name,
            task.task_id,
            self._WORKER,
            self._TOKEN,
            "crash_after_generic_submitted",
            str(counter),
            str(self.now + 10),
        ]
        first = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(first.returncode, 92, first.stderr)
        crashed = self._ledger()
        self.assertEqual(crashed.tasks[0].state, "submitted")
        self.assertEqual(json.loads(counter.read_text())["submit"], 1)
        new_worker = "7" * 64
        new_token = "8" * 64
        with patch.object(
            drama_media_worker,
            "_clock_ms",
            return_value=self.now + 70_000,
        ):
            drama_media_worker.takeover_media_task(
                self.name,
                episode_no=1,
                task_id=task.task_id,
                worker_fingerprint=new_worker,
                lease_token_fingerprint=new_token,
                expected_task_revision=crashed.tasks[0].revision,
                expected_lease_revision=crashed.leases[0].lease_revision,
                expected_ledger_fingerprint=crashed.ledger_fingerprint,
                lease_duration_ms=60_000,
                lane_capacity=1,
            )
        command[5] = new_worker
        command[6] = new_token
        command[7] = "resume"
        command[9] = str(self.now + 70_010)
        second = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        counts = json.loads(counter.read_text())
        self.assertEqual(counts["submit"], 1)
        self.assertEqual(counts["poll"], 1)
        self.assertEqual(self._ledger().tasks[0].state, "succeeded")
