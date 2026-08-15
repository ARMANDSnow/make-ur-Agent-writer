"""Iter166: fail-closed dual-mode write recovery protocol."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from src import paths
from src.book_runner import BookRunBlocked, run_write_book
from src.plot_planner import chapter_plan_item_fingerprint, plan_fingerprint
from src.start_point import start_point_fingerprint
from src.utils import write_json
from src.web import jobs, routes, workspace_meta
from src.web.workspace_ctx import use_workspace


def _stub_workspace(root: Path, name: str, *, mode: str) -> Path:
    workspace = root / name
    for sub in (
        "novel",
        "data/manual_overrides",
        "data/knowledge_base",
        "outputs/debate",
        "outputs/drafts",
        "outputs/reviews",
        "logs",
    ):
        (workspace / sub).mkdir(parents=True, exist_ok=True)
    workspace_meta.write(name, type="novel", creation_mode=mode)
    return workspace


class WriteRecoveryRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        jobs.reset_for_tests()
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _eligible(self, name: str, *, mode: str = "greenfield") -> Path:
        workspace = _stub_workspace(paths.WORKSPACE_DIR, name, mode=mode)
        if mode == "continuation":
            write_json(
                workspace / "data/chapter_manifest.json",
                [
                    {
                        "chapter_id": "synthetic_ch003",
                        "volume_id": "synthetic_v1",
                        "source_file": "synthetic.txt",
                    }
                ],
            )
            write_json(
                workspace / "data/manual_overrides/start_chapter.json",
                {"start_chapter_id": "synthetic_ch003"},
            )
        kb = workspace / "data/knowledge_base/global_knowledge.md"
        outline = workspace / "outputs/debate/outline.md"
        plan = workspace / "outputs/debate/chapter_plan.json"
        kb.write_text("synthetic knowledge\n", encoding="utf-8")
        outline.write_text("synthetic outline\n", encoding="utf-8")
        item = {"chapter_no": 1, "title": "synthetic"}
        item["chapter_plan_item_fingerprint"] = chapter_plan_item_fingerprint(item)
        plan_data = {"chapters": [item]}
        if mode == "continuation":
            with use_workspace(name):
                plan_data["start_chapter_id"] = "synthetic_ch003"
                plan_data["start_point_fingerprint"] = start_point_fingerprint()
        plan_data["plan_fingerprint"] = plan_fingerprint(plan_data)
        write_json(plan, plan_data)
        # Make the server-authoritative freshness chain deterministic even on
        # filesystems whose ordinary writes share a coarse timestamp.
        base_ns = time.time_ns()
        if mode == "continuation":
            start = workspace / "data/manual_overrides/start_chapter.json"
            os.utime(start, ns=(base_ns, base_ns))
        os.utime(kb, ns=(base_ns + 1_000_000, base_ns + 1_000_000))
        os.utime(outline, ns=(base_ns + 2_000_000, base_ns + 2_000_000))
        os.utime(plan, ns=(base_ns + 3_000_000, base_ns + 3_000_000))
        (workspace / "outputs/drafts/chapter_01.md").write_text(
            "synthetic failed draft", encoding="utf-8"
        )
        write_json(
            workspace / "outputs/drafts/chapter_01.meta.json",
            {
                "verdict": "Reject",
                "panel_halted": {"reason": "retry_exhausted", "at": "synthetic"},
            },
        )
        write_json(
            workspace / "outputs/reviews/chapter_01.review.json",
            {"verdict": "Reject", "needs_human_review": True},
        )
        return workspace

    def _get(self, name: str) -> tuple[int, dict]:
        status, _ct, body = routes.dispatch(
            "GET", f"/api/workspace/{name}/write-recovery?chapter=1"
        )
        return status, json.loads(body)

    def _post(self, name: str, fingerprint: str, **updates: object) -> tuple[int, dict]:
        payload = {
            "chapter": 1,
            "tier": "mid",
            "budget_cny": 6,
            "timeout_minutes": 45,
            "max_model_requests": 20,
            "state_fingerprint": fingerprint,
            "confirm_archive_and_regenerate": True,
        }
        payload.update(updates)
        status, _ct, body = routes.dispatch(
            "POST",
            f"/api/workspace/{name}/write-recovery",
            json.dumps(payload).encode("utf-8"),
        )
        return status, json.loads(body)

    def _wait(self, name: str, job_id: str, timeout: float = 20.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status, _ct, body = routes.dispatch(
                "GET", f"/api/workspace/{name}/job/{job_id}"
            )
            self.assertEqual(status, 200, body.decode("utf-8"))
            job = json.loads(body)
            if job.get("status") in {
                "succeeded", "blocked", "failed", "aborted", "lost", "budget_exceeded"
            }:
                return job
            time.sleep(0.02)
        self.fail(f"job {job_id} did not finish")

    def _run(self, name: str, step: str, params: dict | None = None) -> dict:
        status, _ct, body = routes.dispatch(
            "POST",
            f"/api/workspace/{name}/run",
            json.dumps({"step": step, "params": params or {}}).encode("utf-8"),
        )
        self.assertEqual(status, 202, body.decode("utf-8"))
        return self._wait(name, json.loads(body)["job_id"])

    def test_get_eligible_is_content_free_for_both_creation_modes(self) -> None:
        for name, mode in (("green", "greenfield"), ("continued", "continuation")):
            with self.subTest(mode=mode):
                self._eligible(name, mode=mode)
                status, data = self._get(name)
                self.assertEqual(status, 200)
                self.assertEqual(data["state"], "eligible")
                self.assertTrue(data["draft_available"])
                self.assertEqual(data["review_state"], "rejected")
                self.assertRegex(data["state_fingerprint"], r"^[0-9a-f]{64}$")
                self.assertEqual(
                    set(data),
                    {"state", "chapter", "draft_available", "review_state", "state_fingerprint"},
                )
                serialized = json.dumps(data)
                self.assertNotIn("synthetic failed draft", serialized)
                self.assertNotIn("outputs/", serialized)


    def test_only_exact_retry_exhausted_is_eligible(self) -> None:
        workspace = self._eligible("hard")
        write_json(
            workspace / "outputs/drafts/chapter_01.meta.json",
            {"panel_halted": {"reason": "hard_reject"}},
        )
        _status, data = self._get("hard")
        self.assertEqual(data["state"], "needs_review")
        self.assertIsNone(data["state_fingerprint"])

        write_json(
            workspace / "outputs/drafts/chapter_01.meta.json",
            {"verdict": "Reject"},
        )
        write_json(workspace / "outputs/drafts/chapter_01.failure.json", {"error": "lint"})
        _status, data = self._get("hard")
        self.assertEqual(data["state"], "blocked")
        self.assertIsNone(data["state_fingerprint"])

    def test_legacy_or_tampered_plan_never_advertises_recovery(self) -> None:
        workspace = self._eligible("bad-plan")
        _status, original = self._get("bad-plan")
        plan_path = workspace / "outputs/debate/chapter_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan.pop("plan_fingerprint")
        write_json(plan_path, plan)

        status, blocked = self._get("bad-plan")
        self.assertEqual(status, 200)
        self.assertEqual(blocked["state"], "blocked")
        self.assertIsNone(blocked["state_fingerprint"])
        with patch("src.web.routes.jobs.start_job") as start:
            status, data = self._post("bad-plan", original["state_fingerprint"])
        self.assertEqual(status, 409)
        self.assertEqual(data["code"], "write_recovery_state_changed")
        start.assert_not_called()

    def test_post_requires_one_shot_confirmation_and_does_not_persist_it(self) -> None:
        self._eligible("submit")
        _status, state = self._get("submit")
        fingerprint = state["state_fingerprint"]
        status, data = self._post(
            "submit", fingerprint, confirm_archive_and_regenerate=False
        )
        self.assertEqual(status, 400)
        self.assertEqual(data["code"], "write_recovery_confirmation_required")

        captured: dict = {}

        def fake_start(workspace: str, step: str, params: dict) -> dict:
            captured.update(workspace=workspace, step=step, params=dict(params))
            return {"job_id": "a" * 32, "status": "pending"}

        with patch("src.web.routes.jobs.start_job", side_effect=fake_start):
            status, data = self._post("submit", fingerprint)
        self.assertEqual(status, 202, data)
        params = captured["params"]
        self.assertEqual(captured["step"], "write-book")
        self.assertEqual(params["chapters"], 1)
        self.assertEqual(params["resume_from"], 1)
        self.assertTrue(params["force"])
        self.assertEqual(params["max_retries"], 0)
        self.assertFalse(params["require_start_point"])
        self.assertTrue(params["require_plan"])
        self.assertTrue(params["require_external_review"])
        self.assertNotIn("confirm_archive_and_regenerate", params)

    def test_continuation_policy_is_server_derived(self) -> None:
        self._eligible("continuation", mode="continuation")
        _status, state = self._get("continuation")
        captured: dict = {}

        def fake_start(_workspace: str, _step: str, params: dict) -> dict:
            captured.update(params)
            return {"job_id": "b" * 32, "status": "pending"}

        with patch("src.web.routes.jobs.start_job", side_effect=fake_start):
            status, _data = self._post("continuation", state["state_fingerprint"])
        self.assertEqual(status, 202)
        self.assertTrue(captured["require_start_point"])

    def test_fingerprint_drift_returns_409_without_starting_job(self) -> None:
        workspace = self._eligible("drift")
        _status, state = self._get("drift")
        (workspace / "outputs/drafts/chapter_01.md").write_text(
            "synthetic changed generation", encoding="utf-8"
        )
        with patch("src.web.routes.jobs.start_job") as start:
            status, data = self._post("drift", state["state_fingerprint"])
        self.assertEqual(status, 409)
        self.assertEqual(data["code"], "write_recovery_state_changed")
        start.assert_not_called()

    def test_stale_plan_chain_blocks_post_and_worker_precondition(self) -> None:
        workspace = self._eligible("stale-plan")
        _status, state = self._get("stale-plan")
        fingerprint = state["state_fingerprint"]
        outline = workspace / "outputs/debate/outline.md"
        plan = workspace / "outputs/debate/chapter_plan.json"
        outline.write_text("synthetic changed outline\n", encoding="utf-8")
        plan_mtime = plan.stat().st_mtime_ns
        os.utime(outline, ns=(plan_mtime + 1_000_000, plan_mtime + 1_000_000))

        _status, stale = self._get("stale-plan")
        self.assertEqual(stale["state"], "blocked")
        self.assertIsNone(stale["state_fingerprint"])
        with patch("src.web.routes.jobs.start_job") as start:
            status, data = self._post("stale-plan", fingerprint)
        self.assertEqual(status, 409)
        self.assertEqual(data["code"], "write_recovery_state_changed")
        start.assert_not_called()

        with patch("src.web.jobs.paths.workspace_name", return_value="stale-plan"), patch(
            "src.web.jobs.run_write_book"
        ) as runner:
            def invoke_precondition(**kwargs: object) -> object:
                precondition = kwargs.get("precondition")
                self.assertTrue(callable(precondition))
                precondition()  # type: ignore[operator]
                self.fail("stale recovery reached the underlying runner")

            runner.side_effect = invoke_precondition
            with self.assertRaisesRegex(BookRunBlocked, "write_recovery_state_changed"):
                jobs._step_write_book(
                    {
                        "chapters": 1,
                        "resume_from": 1,
                        "force": True,
                        "expected_recovery_fingerprint": fingerprint,
                        "recovery_chapter": 1,
                    },
                    lambda _step, _progress: None,
                )

    def test_continuation_start_must_resolve_and_manifest_drift_invalidates_token(self) -> None:
        workspace = self._eligible("start-drift", mode="continuation")
        _status, state = self._get("start-drift")
        fingerprint = state["state_fingerprint"]
        manifest = workspace / "data/chapter_manifest.json"

        write_json(
            manifest,
            [
                {
                    "chapter_id": "synthetic_ch004",
                    "volume_id": "synthetic_v1",
                    "source_file": "synthetic.txt",
                }
            ],
        )
        _status, changed = self._get("start-drift")
        self.assertEqual(changed["state"], "blocked")
        self.assertIsNone(changed["state_fingerprint"])
        with patch("src.web.routes.jobs.start_job") as start:
            status, data = self._post("start-drift", fingerprint)
        self.assertEqual(status, 409)
        self.assertEqual(data["code"], "write_recovery_state_changed")
        start.assert_not_called()

    def test_symlinked_generation_fails_closed_without_content_leak(self) -> None:
        workspace = self._eligible("nofollow")
        external = Path(self._tmp.name) / "outside-secret.txt"
        external.write_text("must-never-cross-http", encoding="utf-8")
        draft = workspace / "outputs/drafts/chapter_01.md"
        draft.unlink()
        draft.symlink_to(external)
        status, data = self._get("nofollow")
        self.assertEqual(status, 200)
        self.assertEqual(data["state"], "blocked")
        self.assertIsNone(data["state_fingerprint"])
        self.assertNotIn("must-never-cross-http", json.dumps(data))

    def test_busy_lost_unknown_and_general_failure_have_no_force_entry(self) -> None:
        self._eligible("guarded")
        cases = (
            ({"status": "lost"}, "reconciliation_required"),
            ({"status": "new_future_state"}, "reconciliation_required"),
            ({"status": "failed"}, "blocked"),
            ({"status": "budget_exceeded"}, "blocked"),
            (
                {
                    "step": "write-book",
                    "status": "blocked",
                    "result_summary": {
                        "first_blocked": {"reason": "workspace_locked", "chapter": 1}
                    },
                },
                "blocked",
            ),
            (
                {
                    "step": "write-book",
                    "status": "blocked",
                    "result_summary": {
                        "first_blocked": {"reason": "retry_exhausted", "chapter": 2}
                    },
                },
                "blocked",
            ),
        )
        for latest, expected in cases:
            with self.subTest(latest=latest):
                with patch(
                    "src.web.routes.jobs.write_recovery_job_claim",
                    return_value=("ok", latest, "a" * 64),
                ):
                    _status, data = self._get("guarded")
                self.assertEqual(data["state"], expected)
                self.assertIsNone(data["state_fingerprint"])

        with jobs._WORKSPACE_LOCK:
            jobs._WORKSPACE_JOBS["guarded"] = "c" * 32
        try:
            _status, data = self._get("guarded")
            self.assertEqual(data["state"], "busy")
            self.assertIsNone(data["state_fingerprint"])
        finally:
            with jobs._WORKSPACE_LOCK:
                jobs._WORKSPACE_JOBS.pop("guarded", None)

    def test_indeterminate_or_malformed_ledger_requires_reconciliation(self) -> None:
        workspace = self._eligible("ledger-guard")
        with patch(
            "src.web.routes.jobs.write_recovery_job_claim",
            return_value=("indeterminate", None, None),
        ):
            _status, data = self._get("ledger-guard")
        self.assertEqual(data["state"], "reconciliation_required")
        self.assertIsNone(data["state_fingerprint"])

        ledger = workspace / "logs/web_jobs.jsonl"
        ledger.write_text("{broken-json\n", encoding="utf-8")
        _status, data = self._get("ledger-guard")
        self.assertEqual(data["state"], "reconciliation_required")
        self.assertIsNone(data["state_fingerprint"])

    def test_oversized_row_count_ledger_requires_reconciliation(self) -> None:
        workspace = self._eligible("ledger-long")
        ledger = workspace / "logs/web_jobs.jsonl"
        ledger.write_text("{}\n" * (jobs._MAX_JOB_LOG_ROWS + 1), encoding="utf-8")
        _status, data = self._get("ledger-long")
        self.assertEqual(data["state"], "reconciliation_required")
        self.assertIsNone(data["state_fingerprint"])

    def test_worker_ledger_claim_rejects_foreign_job_on_either_side_of_self(self) -> None:
        workspace = self._eligible("ledger-cas")
        _status, state = self._get("ledger-cas")
        ledger_state, _latest, baseline_claim = jobs.write_recovery_job_claim(
            "ledger-cas", 1
        )
        self.assertEqual(ledger_state, "absent")
        self.assertIsInstance(baseline_claim, str)
        foreign_id = "d" * 32
        current_id = "e" * 32
        foreign = {
            "workspace": "ledger-cas",
            "job_id": foreign_id,
            "step": "write-book",
            "params": {"resume_from": 1, "chapters": 1},
            "status": "pending",
        }
        current = {
            "workspace": "ledger-cas",
            "job_id": current_id,
            "step": "write-book",
            "params": {"resume_from": 1, "chapters": 1},
            "status": "running",
        }

        def invoke_precondition(**kwargs: object) -> object:
            precondition = kwargs.get("precondition")
            self.assertTrue(callable(precondition))
            precondition()  # type: ignore[operator]
            self.fail("foreign ledger insertion reached the underlying runner")

        for order in ([foreign, current], [current, foreign]):
            with self.subTest(order=[row["job_id"] for row in order]):
                (workspace / "logs/web_jobs.jsonl").write_text(
                    "".join(json.dumps(row) + "\n" for row in order),
                    encoding="utf-8",
                )
                with patch(
                    "src.web.jobs.paths.workspace_name", return_value="ledger-cas"
                ), patch("src.web.jobs.run_write_book", side_effect=invoke_precondition):
                    with self.assertRaisesRegex(
                        BookRunBlocked, "write_recovery_state_changed"
                    ):
                        jobs._step_write_book(
                            {
                                "chapters": 1,
                                "resume_from": 1,
                                "force": True,
                                "max_retries": 0,
                                "auto_advance": True,
                                "require_start_point": False,
                                "require_plan": True,
                                "require_external_review": True,
                                "expected_recovery_fingerprint": state["state_fingerprint"],
                                "expected_recovery_ledger_claim": baseline_claim,
                                "expected_recovery_prior_job_id": "",
                                "recovery_chapter": 1,
                                "_active_job_id": current_id,
                            },
                            lambda _step, _progress: None,
                        )

    def test_worker_requires_its_own_durable_active_row(self) -> None:
        def invoke_precondition(**kwargs: object) -> object:
            precondition = kwargs.get("precondition")
            self.assertTrue(callable(precondition))
            precondition()  # type: ignore[operator]
            self.fail("missing own ledger row reached the underlying runner")

        def worker_params(state: dict, claim: str, current_id: str, prior_id: str = "") -> dict:
            return {
                "chapters": 1,
                "resume_from": 1,
                "force": True,
                "max_retries": 0,
                "auto_advance": True,
                "require_start_point": False,
                "require_plan": True,
                "require_external_review": True,
                "expected_recovery_fingerprint": state["state_fingerprint"],
                "expected_recovery_ledger_claim": claim,
                "expected_recovery_prior_job_id": prior_id,
                "recovery_chapter": 1,
                "_active_job_id": current_id,
            }

        workspace = self._eligible("ledger-own-missing")
        _status, state = self._get("ledger-own-missing")
        _ledger_state, _latest, empty_claim = jobs.write_recovery_job_claim(
            "ledger-own-missing", 1
        )
        self.assertIsInstance(empty_claim, str)
        with patch(
            "src.web.jobs.paths.workspace_name", return_value="ledger-own-missing"
        ), patch("src.web.jobs.run_write_book", side_effect=invoke_precondition) as runner:
            with self.assertRaisesRegex(BookRunBlocked, "write_recovery_state_changed"):
                jobs._step_write_book(
                    worker_params(state, empty_claim, "a" * 32),
                    lambda _step, _progress: None,
                )
        runner.assert_called_once()

        workspace = self._eligible("ledger-own-removed")
        prior_id = "b" * 32
        prior = {
            "workspace": "ledger-own-removed",
            "job_id": prior_id,
            "step": "write-book",
            "params": {"resume_from": 1, "chapters": 1},
            "status": "blocked",
            "result_summary": {
                "first_blocked": {"reason": "retry_exhausted", "chapter": 1}
            },
        }
        ledger = workspace / "logs/web_jobs.jsonl"
        ledger.write_text(json.dumps(prior) + "\n", encoding="utf-8")
        _status, state = self._get("ledger-own-removed")
        _ledger_state, _latest, prior_claim = jobs.write_recovery_job_claim(
            "ledger-own-removed", 1
        )
        self.assertIsInstance(prior_claim, str)
        # Simulate truncation that removes only the admitted recovery rows;
        # the predecessor and its claim remain byte-identical.
        ledger.write_text(json.dumps(prior) + "\n", encoding="utf-8")
        with patch(
            "src.web.jobs.paths.workspace_name", return_value="ledger-own-removed"
        ), patch("src.web.jobs.run_write_book", side_effect=invoke_precondition) as runner:
            with self.assertRaisesRegex(BookRunBlocked, "write_recovery_state_changed"):
                jobs._step_write_book(
                    worker_params(state, prior_claim, "c" * 32, prior_id),
                    lambda _step, _progress: None,
                )
        runner.assert_called_once()

    def test_newer_untimestamped_pending_row_wins_over_old_terminal(self) -> None:
        rows = [
            {
                "workspace": "ledger",
                "job_id": "old",
                "step": "write-book",
                "params": {"resume_from": 1, "chapters": 1},
                "status": "blocked",
                "finished_at": 999.0,
            },
            {
                "workspace": "ledger",
                "job_id": "new",
                "step": "write-book",
                "params": {"resume_from": 1, "chapters": 1},
                "status": "pending",
                "started_at": None,
                "finished_at": None,
            },
        ]
        with patch("src.web.jobs._read_job_rows", return_value=rows):
            latest = jobs.latest_write_job_for_chapter("ledger", 1)
        self.assertEqual(latest["job_id"], "new")
        self.assertEqual(latest["status"], "lost")

    def test_recovery_uses_single_chapter_hard_caps(self) -> None:
        self._eligible("caps")
        _status, state = self._get("caps")
        for updates in (
            {"budget_cny": 6.1},
            {"timeout_minutes": 45.1},
            {"max_model_requests": 21},
        ):
            with self.subTest(updates=updates), patch("src.web.routes.jobs.start_job") as start:
                status, _data = self._post("caps", state["state_fingerprint"], **updates)
                self.assertEqual(status, 400)
                start.assert_not_called()

    def test_generic_run_and_direct_start_cannot_force_write(self) -> None:
        self._eligible("no-bypass")
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/no-bypass/run",
            json.dumps(
                {"step": "write-book", "params": {"force": True, "chapters": 1}}
            ).encode("utf-8"),
        )
        self.assertEqual(status, 400)
        self.assertIn("dedicated write-recovery", json.loads(body)["error"])
        with self.assertRaisesRegex(RuntimeError, "write_recovery_state_changed"):
            jobs.start_job(
                "no-bypass", "write-book", {"force": True, "chapters": 1}
            )

    def test_mock_e2e_archives_old_generation_and_creates_new_job(self) -> None:
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/wizard/premise-start",
            json.dumps(
                {"workspace": "e2erecovery", "premise": "少年觉醒上古血脉，逆天改命。"},
                ensure_ascii=False,
            ).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 202, body.decode("utf-8"))
        self._run("e2erecovery", "prepare-greenfield", {"force": True})
        self._run("e2erecovery", "debate")
        self._run(
            "e2erecovery", "plan-chapters", {"require_start_point": False}
        )
        first = self._run(
            "e2erecovery",
            "write-book",
            {"require_start_point": False, "require_plan": True},
        )
        self.assertEqual(first["status"], "blocked")
        draft = (
            paths.WORKSPACE_DIR
            / "e2erecovery/outputs/drafts/chapter_01.md"
        )
        old_generation = draft.read_bytes()
        status, state = self._get("e2erecovery")
        self.assertEqual(status, 200)
        self.assertEqual(state["state"], "eligible")

        status, started = self._post("e2erecovery", state["state_fingerprint"])
        self.assertEqual(status, 202, started)
        self.assertNotEqual(started["job_id"], first["job_id"])
        raw = jobs.get_job(started["job_id"])
        self.assertIsNotNone(raw)
        self.assertNotIn("confirm_archive_and_regenerate", raw["params"])
        recovered = self._wait("e2erecovery", started["job_id"])
        self.assertIn(recovered["status"], {"blocked", "succeeded"})
        archived = list(
            (
                paths.WORKSPACE_DIR
                / "e2erecovery/outputs/drafts/snapshots"
            ).glob("stale_chapter_01_*/chapter_01.md")
        )
        self.assertTrue(
            any(path.read_bytes() == old_generation for path in archived),
            "the confirmed generation was not archived before rewrite",
        )
        self.assertTrue(draft.exists())


class WriteRecoveryLockPreconditionTests(unittest.TestCase):
    def test_precondition_runs_inside_lock_before_runner(self) -> None:
        events: list[str] = []

        @contextmanager
        def fake_lock(**_kwargs):
            events.append("lock-enter")
            try:
                yield
            finally:
                events.append("lock-exit")

        def reject_drift() -> None:
            events.append("precondition")
            raise BookRunBlocked("write_recovery_state_changed")

        with patch("src.book_runner.acquire_write_lock", side_effect=fake_lock), patch(
            "src.book_runner._run_write_book_unlocked"
        ) as unlocked:
            with self.assertRaisesRegex(BookRunBlocked, "write_recovery_state_changed"):
                run_write_book(chapters=1, precondition=reject_drift)
        unlocked.assert_not_called()
        self.assertEqual(events, ["lock-enter", "precondition", "lock-exit"])


if __name__ == "__main__":
    unittest.main()
