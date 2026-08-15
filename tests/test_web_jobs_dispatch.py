"""iter 026: src/web/jobs.py threading worker + step dispatch."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

from src import paths, start_point
from src.web import jobs, routes, workspace_meta
from src.web.workspace_ctx import use_workspace
from src.workspace_lock import acquire_write_lock
from src.utils import write_json


def _stub_workspace(root: Path, name: str) -> None:
    ws = root / name
    for sub in ("小说txt", "data", "outputs", "logs"):
        (ws / sub).mkdir(parents=True)


class JobsDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        _stub_workspace(paths.WORKSPACE_DIR, "alpha")
        # Most dispatcher tests exercise handler behaviour rather than the
        # continuation admission gate.  Make that intent explicit so the
        # schema-v2 default does not accidentally turn unrelated tests into
        # "missing continuation start point" cases.
        workspace_meta.write("alpha", type="novel", creation_mode="greenfield")
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        jobs.reset_for_tests()
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _post_run(self, workspace: str, payload: dict) -> tuple[int, dict]:
        status, _ct, body = routes.dispatch(
            "POST", f"/api/workspace/{workspace}/run", json.dumps(payload).encode("utf-8")
        )
        return status, json.loads(body)

    def _wait_for_done(self, workspace: str, job_id: str, timeout: float = 8.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status, _, body = routes.dispatch(
                "GET", f"/api/workspace/{workspace}/job/{job_id}"
            )
            rec = json.loads(body)
            if rec.get("status") in ("succeeded", "blocked", "failed", "aborted", "lost", "budget_exceeded"):
                return rec
            time.sleep(0.05)
        self.fail(f"job {job_id} did not finish in {timeout}s")

    def test_unknown_step_400(self) -> None:
        status, data = self._post_run("alpha", {"step": "no-such-step"})
        self.assertEqual(status, 400)
        self.assertIn("unknown step", data["error"])

    def test_timeout_terminal_is_not_reported_as_user_cancel(self) -> None:
        def timed_out(_params, _progress):
            raise jobs.JobTimeout("private timeout detail")

        with unittest.mock.patch.dict(jobs.STEP_HANDLERS, {"normalize": timed_out}):
            status, data = self._post_run("alpha", {"step": "normalize"})
            self.assertEqual(status, 202)
            job = self._wait_for_done("alpha", data["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["current_step"], "timeout")
        self.assertEqual(job["error"], "job timed out")
        self.assertEqual(job["result_summary"]["failure_reason"], "job_timeout")
        self.assertFalse(job["cancel_requested"])
        self.assertIsNone(job["cancel_reason"])

    def test_creation_mode_conflicts_are_rejected_before_job_allocation(self) -> None:
        workspace_meta.write("alpha", type="novel", creation_mode="continuation")
        with self.assertRaisesRegex(RuntimeError, "creation_mode_conflict"):
            jobs.start_job("alpha", "prepare-greenfield", {})
        self.assertFalse(jobs._JOBS)
        self.assertIsNone(jobs.workspace_busy("alpha"))
        self.assertFalse((paths.WORKSPACE_DIR / "alpha" / "logs" / "web_jobs.jsonl").exists())

        status, data = self._post_run(
            "alpha",
            {"step": "write-book", "params": {"require_start_point": False}},
        )
        self.assertEqual(status, 409)
        self.assertEqual(data["code"], "creation_mode_conflict")
        self.assertFalse(jobs._JOBS)

    def test_invalid_metadata_is_rejected_before_job_allocation(self) -> None:
        workspace_meta.workspace_meta_path("alpha").write_bytes(b"{")
        status, data = self._post_run("alpha", {"step": "normalize", "params": {}})
        self.assertEqual(status, 409)
        self.assertEqual(data["code"], "workspace_metadata_invalid")
        with self.assertRaisesRegex(RuntimeError, "workspace_metadata_invalid"):
            jobs.start_job("alpha", "normalize", {})
        self.assertFalse(jobs._JOBS)
        self.assertIsNone(jobs.workspace_busy("alpha"))
        self.assertFalse((paths.WORKSPACE_DIR / "alpha" / "logs" / "web_jobs.jsonl").exists())

    def test_metadata_invalidated_between_route_and_job_returns_friendly_409(self) -> None:
        with unittest.mock.patch(
            "src.web.routes.jobs.start_job",
            side_effect=RuntimeError("workspace_metadata_invalid"),
        ):
            status, data = self._post_run("alpha", {"step": "normalize", "params": {}})
        self.assertEqual(status, 409)
        self.assertEqual(data["code"], "workspace_metadata_invalid")
        self.assertIn("没有启动任务", data["error"])


    def test_run_injects_authoritative_start_policy_when_omitted(self) -> None:
        workspace_meta.write("alpha", type="novel", creation_mode="continuation")
        with use_workspace("alpha"):
            write_json(
                paths.chapter_manifest_path(),
                [{"chapter_id": "alpha_ch001", "volume_id": "v1", "title": "one"}],
            )
            start_point.set_start_point("alpha_ch001")
        fake = {"job_id": "job-authoritative", "status": "pending"}
        with unittest.mock.patch("src.web.routes.jobs.start_job", return_value=fake) as start:
            status, data = self._post_run(
                "alpha", {"step": "plan-chapters", "params": {"target_chapters": 1}}
            )
        self.assertEqual(status, 202)
        self.assertEqual(data["job_id"], "job-authoritative")
        self.assertTrue(start.call_args.args[2]["require_start_point"])

        workspace_meta.write("alpha", type="novel", creation_mode="greenfield")
        with unittest.mock.patch("src.web.routes.jobs.start_job", return_value=fake) as start:
            status, _data = self._post_run(
                "alpha", {"step": "write-book", "params": {"chapters": 1}}
            )
        self.assertEqual(status, 202)
        self.assertFalse(start.call_args.args[2]["require_start_point"])

    def test_greenfield_rejects_import_and_rebuild_steps(self) -> None:
        workspace_meta.write("alpha", type="novel", creation_mode="greenfield")
        for step in ("prepare-import", "rebuild-for-start"):
            status, data = self._post_run("alpha", {"step": step, "params": {}})
            self.assertEqual(status, 409, step)
            self.assertEqual(data["creation_mode"], "greenfield")
        self.assertFalse(jobs._JOBS)

    def test_start_job_rejects_symlink_workspace_without_allocating(self) -> None:
        with tempfile.TemporaryDirectory() as outside_tmp:
            outside = Path(outside_tmp)
            _stub_workspace(outside, "target")
            (paths.WORKSPACE_DIR / "linked").symlink_to(
                outside / "target", target_is_directory=True
            )
            with self.assertRaisesRegex(RuntimeError, "workspace_not_found"):
                jobs.start_job("linked", "normalize", {})
            self.assertIsNone(jobs.workspace_busy("linked"))
            self.assertFalse(jobs._WORKER_THREADS)

    def test_start_job_rechecks_before_persist_and_does_not_write_replacement(self) -> None:
        workspace = paths.WORKSPACE_DIR / "alpha"
        original = paths.WORKSPACE_DIR / "alpha.original"
        real_matches = paths.workspace_identity_matches

        def replace_then_check(identity):
            workspace.rename(original)
            _stub_workspace(paths.WORKSPACE_DIR, "alpha")
            return real_matches(identity)

        try:
            with unittest.mock.patch(
                "src.web.jobs.paths.workspace_identity_matches",
                side_effect=replace_then_check,
            ):
                with self.assertRaisesRegex(RuntimeError, "workspace_not_found"):
                    jobs.start_job("alpha", "normalize", {})
            self.assertFalse((workspace / "logs" / "web_jobs.jsonl").exists())
            self.assertIsNone(jobs.workspace_busy("alpha"))
            self.assertFalse(jobs._JOBS)
        finally:
            if workspace.exists():
                shutil.rmtree(workspace)
            original.rename(workspace)

    def test_start_job_allows_missing_optional_logs_directory(self) -> None:
        workspace = paths.WORKSPACE_DIR / "alpha"
        shutil.rmtree(workspace / "logs")
        called = threading.Event()

        def handler(_params, _progress):
            called.set()
            return {"status": "succeeded"}

        jobs.STEP_HANDLERS["_iter151-partial"] = handler
        try:
            record = jobs.start_job("alpha", "_iter151-partial", {})
            terminal = self._wait_for_done("alpha", record["job_id"])
            self.assertEqual(terminal["status"], "succeeded")
            self.assertTrue(called.is_set())
            self.assertTrue((workspace / "logs" / "web_jobs.jsonl").is_file())
        finally:
            jobs.STEP_HANDLERS.pop("_iter151-partial", None)

    def test_worker_rechecks_identity_before_handler_after_root_swap(self) -> None:
        workspace = paths.WORKSPACE_DIR / "alpha"
        identity = paths.probe_workspace_identity("alpha")
        self.assertIsNotNone(identity)
        original = paths.WORKSPACE_DIR / "alpha.original"
        outside_marker = Path(self._tmp.name) / "handler-was-called"
        seeded = jobs._new_job_record("alpha", "normalize", {})
        job_id = seeded["job_id"]
        jobs._JOBS[job_id] = seeded
        jobs._WORKSPACE_JOBS["alpha"] = job_id
        workspace.rename(original)
        _stub_workspace(paths.WORKSPACE_DIR, "alpha")
        try:
            with unittest.mock.patch.dict(
                jobs.STEP_HANDLERS,
                {"normalize": lambda _params: outside_marker.write_text("called", encoding="utf-8")},
            ):
                jobs._worker(job_id, identity)
            self.assertFalse(outside_marker.exists())
            public = jobs.public_job_detail_view(jobs.get_job(job_id))
            self.assertEqual(public["status"], "failed")
            self.assertNotIn("inode", json.dumps(public))
            self.assertNotIn(str(original), json.dumps(public))
        finally:
            if workspace.exists():
                shutil.rmtree(workspace)
            original.rename(workspace)

    def test_write_guard_rechecks_identity_after_lock_before_body(self) -> None:
        marker = paths.WORKSPACE_DIR / "guard-body-ran"
        with unittest.mock.patch(
            "src.web.routes.paths.workspace_identity_matches", return_value=False
        ):
            with self.assertRaisesRegex(RuntimeError, "workspace_not_found"):
                with routes._workspace_write_guard("alpha", "test-identity-swap"):
                    marker.write_text("unsafe", encoding="utf-8")
        self.assertFalse(marker.exists())

    def test_generic_auto_pipeline_not_in_web_production_whitelist(self) -> None:
        status, data = self._post_run("alpha", {"step": "auto-pipeline"})
        self.assertEqual(status, 400)
        self.assertIn("unknown step", data["error"])

    def test_missing_step_field_400(self) -> None:
        status, data = self._post_run("alpha", {"params": {}})
        self.assertEqual(status, 400)
        self.assertIn("step", data["error"])

    def test_bad_json_body_400(self) -> None:
        status, _ct, body = routes.dispatch(
            "POST", "/api/workspace/alpha/run", b"not json"
        )
        self.assertEqual(status, 400)
        self.assertIn("JSON", json.loads(body)["error"])

    def test_write_book_invalid_params_400_before_worker(self) -> None:
        status, data = self._post_run(
            "alpha",
            {"step": "write-book", "params": {"chapters": 0}},
        )
        self.assertEqual(status, 400)
        self.assertIn("chapters", data["error"])

        status, data = self._post_run(
            "alpha",
            {"step": "write-book", "params": {"min_confidence": 1.2}},
        )
        self.assertEqual(status, 400)
        self.assertIn("min_confidence", data["error"])

    def test_continuation_steps_missing_start_point_are_rejected_before_job(self) -> None:
        workspace_meta.write("alpha", type="novel", creation_mode="continuation")
        gated = (
            "extract",
            "compress",
            "bootstrap",
            "apply-bootstrap",
            "debate",
            "plan-chapters",
            "write-book",
            "review-chapter",
            "draft-once-dev",
            "rebuild-for-start",
        )
        for step in gated:
            status, data = self._post_run("alpha", {"step": step, "params": {}})
            self.assertEqual(status, 409, step)
            self.assertEqual(data["code"], "creation_mode_conflict", step)
            self.assertTrue(data["requires_start_point"], step)
        self.assertFalse(jobs._JOBS)
        self.assertIsNone(jobs.workspace_busy("alpha"))
        self.assertFalse((paths.WORKSPACE_DIR / "alpha" / "logs" / "web_jobs.jsonl").exists())

    def test_plan_chapters_missing_start_point_is_rejected(self) -> None:
        workspace_meta.write("alpha", type="novel", creation_mode="continuation")
        status, data = self._post_run(
            "alpha",
            {"step": "plan-chapters", "params": {"target_chapters": 3}},
        )
        self.assertEqual(status, 409)
        self.assertEqual(data["code"], "creation_mode_conflict")
        self.assertFalse(jobs._JOBS)

    def test_plan_chapters_forces_force_but_honors_require_start_point(self) -> None:
        # iter 048b: force is always overridden to True (a re-plan overwrites),
        # but require_start_point is now HONORED from params (was forced True
        # pre-048b) so the greenfield workbench can pass False. Default stays
        # True for continuation safety; greenfield is authoritatively false.
        workspace_meta.write("alpha", type="novel", creation_mode="greenfield")
        with unittest.mock.patch(
            "src.web.jobs.generate_chapter_plan",
            return_value={"chapters": []},
        ) as planner, unittest.mock.patch(
            "src.web.jobs.start_point.get_start_chapter_id",
            return_value="alpha_ch001",
        ):
            status, data = self._post_run(
                "alpha",
                {"step": "plan-chapters", "params": {"target_chapters": 7, "require_start_point": False, "force": False}},
            )
            self.assertEqual(status, 202)
            self._wait_for_done("alpha", data["job_id"], timeout=10.0)
        self.assertEqual(planner.call_args.kwargs["target_chapters"], 7)
        self.assertTrue(planner.call_args.kwargs["force"])  # always re-plan
        self.assertFalse(planner.call_args.kwargs["require_start_point"])  # honored now

    def test_plan_chapters_stale_outline_is_blocked_not_raw_valueerror(self) -> None:
        # iter063 A1: plot_planner's deliberate hard block (debate outline built
        # against a different start point — the 052 cross-timeline accident) must
        # surface as a blocked readiness card, not a raw ValueError in the UI.
        with unittest.mock.patch(
            "src.web.jobs.generate_chapter_plan",
            side_effect=ValueError(
                "stale debate outline (outline_content_mismatch): outline.md 与 decisions.json 不是同批产物"
            ),
        ), unittest.mock.patch(
            "src.web.jobs.start_point.get_start_chapter_id",
            return_value="alpha_ch001",
        ):
            status, data = self._post_run(
                "alpha",
                {"step": "plan-chapters", "params": {"target_chapters": 5}},
            )
            self.assertEqual(status, 202)
            job = self._wait_for_done("alpha", data["job_id"], timeout=10.0)
        self.assertEqual(job["status"], "blocked")
        self.assertEqual(job["result_summary"]["first_blocked"]["reason"], "outline_stale")
        # Raw planner errors can carry private context and are not public.
        self.assertNotIn("error", job["result_summary"]["first_blocked"])

    def test_plan_chapters_typed_outline_stale_is_blocked(self) -> None:
        # iter064 #2: the real planner now raises the typed OutlineStale; the
        # dispatcher must key on the type and emit the same blocked card.
        from src.plot_planner import OutlineStale

        with unittest.mock.patch(
            "src.web.jobs.generate_chapter_plan",
            side_effect=OutlineStale(["outline_start_chapter_id_mismatch"]),
        ), unittest.mock.patch(
            "src.web.jobs.start_point.get_start_chapter_id",
            return_value="alpha_ch001",
        ):
            status, data = self._post_run(
                "alpha",
                {"step": "plan-chapters", "params": {"target_chapters": 5}},
            )
            self.assertEqual(status, 202)
            job = self._wait_for_done("alpha", data["job_id"], timeout=10.0)
        self.assertEqual(job["status"], "blocked")
        self.assertEqual(job["result_summary"]["first_blocked"]["reason"], "outline_stale")

    def test_concurrent_same_workspace_409(self) -> None:
        # The first job must remain in flight when we fire the second
        # call, so we use a long-ish step. ``auto-pipeline-greenfield`` needs a
        # seeded raw txt to make progress; we don't care about its
        # outcome, only that it occupies the slot.
        workspace_meta.write("alpha", type="novel", creation_mode="greenfield")
        (paths.WORKSPACE_DIR / "alpha" / "小说txt" / "sample.txt").write_text(
            "第一章\n测试。\n" * 50, encoding="utf-8"
        )
        s1, d1 = self._post_run(
            "alpha",
            {"step": "auto-pipeline-greenfield", "params": {"chapters": 1, "extract_limit": 1, "force": True}},
        )
        self.assertEqual(s1, 202)
        s2, d2 = self._post_run("alpha", {"step": "normalize"})
        self.assertEqual(s2, 409)
        self.assertEqual(d2["running_job_id"], d1["job_id"])
        # Drain to keep cleanup clean.
        self._wait_for_done("alpha", d1["job_id"], timeout=30.0)

    def test_job_status_404_for_unknown_id(self) -> None:
        status, _ct, body = routes.dispatch(
            "GET", "/api/workspace/alpha/job/" + "f" * 32
        )
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"], "job not found")

    def test_job_status_404_when_workspace_becomes_unsafe(self) -> None:
        record = jobs._new_job_record("alpha", "normalize", {})
        jobs._JOBS[record["job_id"]] = record
        data = paths.WORKSPACE_DIR / "alpha" / "data"
        saved = paths.WORKSPACE_DIR / "alpha" / "data.safe"
        outside = Path(self._tmp.name) / "outside-data"
        outside.mkdir()
        data.rename(saved)
        data.symlink_to(outside, target_is_directory=True)
        try:
            status, _ct, body = routes.dispatch(
                "GET", f"/api/workspace/alpha/job/{record['job_id']}"
            )
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(body)["error"], "workspace not found: alpha")
        finally:
            data.unlink()
            saved.rename(data)

    def test_job_status_restores_persisted_jsonl_under_patched_workspace_dir(self) -> None:
        job = {
            "job_id": "b" * 32,
            "workspace": "alpha",
            "step": "write-book",
            "params": {"chapters": 1},
            "status": "succeeded",
            "started_at": 10.0,
            "finished_at": 11.0,
            "error": None,
        }
        (paths.WORKSPACE_DIR / "alpha" / "logs" / "web_jobs.jsonl").write_text(
            json.dumps(job, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        jobs.reset_for_tests()

        status, _ct, body = routes.dispatch(
            "GET", f"/api/workspace/alpha/job/{job['job_id']}"
        )
        self.assertEqual(status, 200, body.decode("utf-8"))
        data = json.loads(body)
        self.assertEqual(data["job_id"], job["job_id"])
        self.assertEqual(data["status"], "succeeded")

    def test_start_job_thread_failure_rolls_back_workspace_slot(self) -> None:
        """Iter 027 P2 (review #8 fix): if threading.Thread.start raises
        (OS thread limit, fork restrictions), the _WORKSPACE_JOBS slot
        must be cleared. Otherwise every subsequent POST returns 409
        pointing at a job whose worker never ran."""
        import threading

        original_start = threading.Thread.start
        call_count = {"n": 0}

        def faulty_start(self):
            call_count["n"] += 1
            raise RuntimeError("can't start new thread")

        threading.Thread.start = faulty_start
        try:
            with self.assertRaises(RuntimeError):
                jobs.start_job("alpha", "normalize", {})
            # Workspace slot must be empty — otherwise a retry would
            # see 409 forever.
            self.assertIsNone(jobs.workspace_busy("alpha"))
            # Job record cleaned too.
            self.assertEqual(jobs._JOBS, {})
            self.assertEqual(jobs._WORKER_THREADS, {})
        finally:
            threading.Thread.start = original_start

        # After restore, a normal start_job should succeed and slot up
        # for a real workspace_busy reading.
        record = jobs.start_job("alpha", "normalize", {})
        self.assertEqual(jobs.workspace_busy("alpha"), record["job_id"])
        self._wait_for_done("alpha", record["job_id"], timeout=10.0)
        self.assertIsNone(jobs.workspace_busy("alpha"))

    def test_reset_for_tests_drains_worker_before_workspace_root_changes(self) -> None:
        started = threading.Event()
        release = threading.Event()
        reset_done = threading.Event()
        errors = []
        marker = "late_worker_marker"

        def blocking_handler(_params, progress):
            started.set()
            release.wait(timeout=2.0)
            progress("after-release", 0.5)
            (paths.workspace_root() / marker).write_text("late", encoding="utf-8")
            return {"status": "succeeded"}

        jobs.STEP_HANDLERS["_iter151-blocking"] = blocking_handler
        try:
            jobs.start_job("alpha", "_iter151-blocking", {})
            self.assertTrue(started.wait(timeout=1.0))

            def do_reset() -> None:
                try:
                    jobs.reset_for_tests(timeout_seconds=2.0)
                except BaseException as exc:  # pragma: no cover - asserted below
                    errors.append(exc)
                finally:
                    reset_done.set()

            reset_thread = threading.Thread(target=do_reset)
            reset_thread.start()
            time.sleep(0.05)
            self.assertFalse(reset_done.is_set())
            release.set()
            reset_thread.join(timeout=2.0)
            self.assertTrue(reset_done.is_set())
            self.assertEqual(errors, [])

            next_root = Path(self._tmp.name) / "next"
            next_root.mkdir()
            paths.WORKSPACE_DIR = next_root
            _stub_workspace(next_root, "alpha")
            time.sleep(0.05)
            self.assertFalse((next_root / "alpha" / marker).exists())
        finally:
            release.set()
            jobs.STEP_HANDLERS.pop("_iter151-blocking", None)
            jobs.reset_for_tests()

    def test_reset_timeout_preserves_live_worker_state(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def uncooperative_handler(_params, _progress):
            started.set()
            release.wait(timeout=2.0)
            return {"status": "succeeded"}

        jobs.STEP_HANDLERS["_iter151-uncooperative"] = uncooperative_handler
        try:
            record = jobs.start_job("alpha", "_iter151-uncooperative", {})
            self.assertTrue(started.wait(timeout=1.0))
            with self.assertRaisesRegex(RuntimeError, "workers did not stop"):
                jobs.reset_for_tests(timeout_seconds=0.01)
            self.assertIn(record["job_id"], jobs._JOBS)
            self.assertIn(record["job_id"], jobs._WORKER_THREADS)
        finally:
            release.set()
            deadline = time.time() + 2.0
            while jobs._WORKER_THREADS and time.time() < deadline:
                time.sleep(0.01)
            jobs.STEP_HANDLERS.pop("_iter151-uncooperative", None)
            jobs.reset_for_tests()

    def test_job_404_when_workspace_mismatch(self) -> None:
        """Jobs are namespaced by workspace; asking for a job under the
        wrong workspace returns 404, not the job."""
        # Seed beta so it's a valid workspace too.
        _stub_workspace(paths.WORKSPACE_DIR, "beta")
        (paths.WORKSPACE_DIR / "alpha" / "小说txt" / "sample.txt").write_text(
            "第一章\n", encoding="utf-8"
        )
        _, d1 = self._post_run("alpha", {"step": "normalize"})
        self._wait_for_done("alpha", d1["job_id"], timeout=10.0)
        status, _ct, body = routes.dispatch(
            "GET", f"/api/workspace/beta/job/{d1['job_id']}"
        )
        self.assertEqual(status, 404)

    def test_write_book_job_surfaces_blocked_summary(self) -> None:
        with unittest.mock.patch(
            "src.web.jobs.run_write_book",
            return_value={
                "status": "blocked",
                "chapters": [{"chapter": 1}],
                "blocked": [{"chapter": 1, "reason": "retry_exhausted"}],
                "snapshot_path": "outputs/drafts/snapshots/write_book_blocked.json",
            },
        ):
            status, data = self._post_run("alpha", {"step": "write-book", "params": {"chapters": 1}})
            self.assertEqual(status, 202)
            job = self._wait_for_done("alpha", data["job_id"], timeout=10.0)
        self.assertEqual(job["status"], "blocked")
        self.assertEqual(job["result_summary"]["first_blocked"]["reason"], "retry_exhausted")
        self.assertNotIn("snapshot_path", job["result_summary"])

    def test_write_book_job_surfaces_only_bounded_failure_reason(self) -> None:
        marker = "PRIVATE_PROVIDER_MARKER"
        with unittest.mock.patch(
            "src.web.jobs.run_write_book",
            return_value={
                "status": "failed",
                "chapters": [],
                "blocked": [],
                "failure_reason": "submission_unknown",
                "error": f"provider timeout at https://private.invalid/{marker}",
                "snapshot_path": f"/private/{marker}",
            },
        ):
            status, data = self._post_run(
                "alpha", {"step": "write-book", "params": {"chapters": 1}}
            )
            self.assertEqual(status, 202)
            job = self._wait_for_done("alpha", data["job_id"], timeout=10.0)

        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error"], "job_failed")
        self.assertEqual(job["result_summary"]["failure_reason"], "submission_unknown")
        rendered = json.dumps(job, ensure_ascii=False)
        self.assertNotIn(marker, rendered)
        self.assertNotIn("private.invalid", rendered)
        self.assertNotIn("snapshot_path", job["result_summary"])

    def test_write_book_job_preserves_zero_min_confidence(self) -> None:
        with unittest.mock.patch(
            "src.web.jobs.run_write_book",
            return_value={"status": "succeeded", "chapters": [], "blocked": []},
        ) as run:
            status, data = self._post_run(
                "alpha",
                {"step": "write-book", "params": {"chapters": 1, "min_confidence": 0, "budget_cny": 2.5, "replan_every": 3}},
            )
            self.assertEqual(status, 202)
            self._wait_for_done("alpha", data["job_id"], timeout=10.0)
        self.assertEqual(run.call_args.kwargs["min_confidence"], 0.0)
        self.assertEqual(run.call_args.kwargs["budget_cny"], 2.5)
        self.assertEqual(run.call_args.kwargs["replan_every"], 3)

    def test_write_book_job_passes_web_lock_source(self) -> None:
        # iter078 P1-7: Web job 必须以 lock_source="web-job" 拿 workspace
        # 写锁——被拒的 CLI 侧从 holder 信息能看出持有方是 Web。
        with unittest.mock.patch(
            "src.web.jobs.run_write_book",
            return_value={"status": "succeeded", "chapters": [], "blocked": []},
        ) as run:
            status, data = self._post_run(
                "alpha", {"step": "write-book", "params": {"chapters": 1}}
            )
            self.assertEqual(status, 202)
            self._wait_for_done("alpha", data["job_id"], timeout=10.0)
        self.assertEqual(run.call_args.kwargs["lock_source"], "web-job")

    def test_write_book_workspace_lock_job_json_is_sanitized(self) -> None:
        with use_workspace("alpha"):
            with acquire_write_lock(source="cli-long-run"):
                status, data = self._post_run(
                    "alpha", {"step": "write-book", "params": {"chapters": 1}}
                )
                self.assertEqual(status, 202)
                detail = self._wait_for_done("alpha", data["job_id"], timeout=10.0)

        status, _ct, body = routes.dispatch("GET", "/api/workspace/alpha/jobs/recent")
        self.assertEqual(status, 200)
        combined = json.dumps({"detail": detail, "recent": json.loads(body)}, ensure_ascii=False)
        self.assertEqual(detail.get("status"), "blocked")
        self.assertEqual(detail.get("error"), "workspace locked")
        first = (detail.get("result_summary") or {}).get("first_blocked") or {}
        self.assertTrue(first.get("workspace_locked"), first)
        self.assertEqual(first.get("holder", {}).get("source"), "cli-long-run")
        self.assertNotIn("argv", combined)
        self.assertNotIn("write.lock", combined)
        self.assertNotIn(str(paths.WORKSPACE_DIR / "alpha"), combined)

    def test_review_chapter_workspace_lock_job_json_is_sanitized(self) -> None:
        import tests.test_book_runner as tb
        from src.plot_planner import chapter_plan_item_fingerprint, plan_fingerprint

        root = paths.WORKSPACE_DIR / "alpha"
        drafts = root / "outputs" / "drafts"
        debate = root / "outputs" / "debate"
        drafts.mkdir(parents=True, exist_ok=True)
        debate.mkdir(parents=True, exist_ok=True)
        (drafts / "chapter_01.md").write_text("正文\n", encoding="utf-8")
        plan = tb._strict_plan(chapters=1)
        plan["chapters"][0]["key_events"] = ["事件一", "事件二"]
        plan["chapters"][0]["chapter_plan_item_fingerprint"] = chapter_plan_item_fingerprint(
            plan["chapters"][0]
        )
        plan["plan_fingerprint"] = plan_fingerprint(plan)
        write_json(debate / "chapter_plan.json", plan)

        with use_workspace("alpha"):
            with acquire_write_lock(source="cli-long-run"):
                status, data = self._post_run(
                    "alpha", {"step": "review-chapter", "params": {"chapter": 1}}
                )
                self.assertEqual(status, 202)
                detail = self._wait_for_done("alpha", data["job_id"], timeout=10.0)

        status, _ct, body = routes.dispatch("GET", "/api/workspace/alpha/jobs/recent")
        self.assertEqual(status, 200)
        combined = json.dumps({"detail": detail, "recent": json.loads(body)}, ensure_ascii=False)
        first = (detail.get("result_summary") or {}).get("first_blocked") or {}
        self.assertEqual(detail.get("status"), "blocked")
        self.assertTrue(first.get("workspace_locked"), first)
        self.assertEqual(first.get("holder", {}).get("source"), "cli-long-run")
        self.assertNotIn("argv", combined)
        self.assertNotIn("write.lock", combined)
        self.assertNotIn(str(root), combined)

    def test_draft_once_workspace_lock_job_json_is_sanitized(self) -> None:
        root = paths.WORKSPACE_DIR / "alpha"
        with use_workspace("alpha"):
            with acquire_write_lock(source="cli-long-run"):
                status, data = self._post_run(
                    "alpha", {"step": "draft-once-dev", "params": {"chapters": 1}}
                )
                self.assertEqual(status, 202)
                detail = self._wait_for_done("alpha", data["job_id"], timeout=10.0)

        first = (detail.get("result_summary") or {}).get("first_blocked") or {}
        combined = json.dumps(detail, ensure_ascii=False)
        self.assertEqual(detail.get("status"), "blocked")
        self.assertTrue(first.get("workspace_locked"), first)
        self.assertEqual(first.get("holder", {}).get("source"), "cli-long-run")
        self.assertNotIn("argv", combined)
        self.assertNotIn("write.lock", combined)
        self.assertNotIn(str(root), combined)

    def test_write_book_job_preserves_tier_param(self) -> None:
        with unittest.mock.patch(
            "src.web.jobs.run_write_book",
            return_value={"status": "succeeded", "chapters": [], "blocked": []},
        ) as run:
            status, data = self._post_run(
                "alpha",
                {"step": "write-book", "params": {"chapters": 1, "tier": "low"}},
            )
            self.assertEqual(status, 202)
            self._wait_for_done("alpha", data["job_id"], timeout=10.0)
        self.assertEqual(run.call_args.kwargs["tier"], "low")

        status, data = self._post_run(
            "alpha",
            {"step": "write-book", "params": {"chapters": 1, "tier": "strict"}},
        )
        self.assertEqual(status, 400)
        self.assertIn("WRITE_REVIEW_TIER", data["error"])

    def test_write_book_budget_exceeded_terminal_status(self) -> None:
        with unittest.mock.patch(
            "src.web.jobs.run_write_book",
            return_value={
                "status": "budget_exceeded",
                "chapters": [{"chapter": 1}],
                "blocked": [],
                "budget_cny": 1.0,
                "cost_cny": 1.2,
            },
        ):
            status, data = self._post_run("alpha", {"step": "write-book", "params": {"chapters": 1}})
            self.assertEqual(status, 202)
            job = self._wait_for_done("alpha", data["job_id"], timeout=10.0)
        self.assertEqual(job["status"], "budget_exceeded")
        self.assertEqual(job["result_summary"]["cost_cny"], 1.2)

    # ---- iter 048d A4: prep step readiness blockers ----------------------
    # Each prep step now reports a friendly ``blocked`` dict with a
    # machine-readable ``reason`` when its prerequisite artifact is
    # missing, instead of letting the underlying FileNotFoundError become
    # a job-level ``failed``. The fresh "alpha" workspace from setUp has
    # only the four empty subdirs and no extracted/manifest/KB files, so
    # every prep step starting from split is blocked.

    def _assert_blocked(self, workspace: str, step: str, reason: str, params: dict | None = None) -> dict:
        status, data = self._post_run(workspace, {"step": step, "params": params or {}})
        self.assertEqual(status, 202, data)
        job = self._wait_for_done(workspace, data["job_id"], timeout=10.0)
        self.assertEqual(job["status"], "blocked", f"{step}: {job.get('error')}")
        blocked = (job.get("result_summary") or {}).get("first_blocked") or {}
        # _summarize_result for generic dicts doesn't pull first_blocked,
        # so fall through to the result itself when missing.
        if not blocked:
            keys = (job.get("result_summary") or {}).get("keys") or []
            self.assertIn("blocked", keys, f"{step}: result missing blocked list")
            return job
        self.assertEqual(blocked.get("reason"), reason, f"{step}: {blocked}")
        return job

    def test_split_blocked_when_normalized_missing(self) -> None:
        self._assert_blocked("alpha", "split", "normalized_missing")

    def test_split_runs_when_normalized_txt_present(self) -> None:
        # iter059 #9: normalize_all writes `<volume>.txt`, so the split gate
        # must recognize `.txt` (it globbed `*.md` only and left single-step
        # split permanently blocked as normalized_missing). Seed a normalized
        # `.txt` with chapter headings and assert split runs to success.
        norm_dir = paths.WORKSPACE_DIR / "alpha" / "data" / "normalized_texts"
        norm_dir.mkdir(parents=True, exist_ok=True)
        (norm_dir / "vol1.txt").write_text(
            "第一章 开端\n正文内容一。\n第二章 转折\n正文内容二。\n",
            encoding="utf-8",
        )
        status, data = self._post_run("alpha", {"step": "split"})
        self.assertEqual(status, 202, data)
        job = self._wait_for_done("alpha", data["job_id"], timeout=10.0)
        self.assertEqual(job["status"], "succeeded", job.get("error"))

    def test_extract_blocked_when_manifest_missing(self) -> None:
        self._assert_blocked("alpha", "extract", "manifest_missing")

    def test_compress_blocked_when_extractions_missing(self) -> None:
        self._assert_blocked("alpha", "compress", "extractions_missing")

    def test_bootstrap_blocked_when_extractions_missing(self) -> None:
        self._assert_blocked("alpha", "bootstrap", "extractions_missing")

    def test_apply_bootstrap_blocked_when_proposal_missing(self) -> None:
        self._assert_blocked(
            "alpha", "apply-bootstrap", "proposal_missing", params={"name": "no-such"}
        )

    def test_debate_blocked_when_kb_missing(self) -> None:
        # Red-team flagged this specific path: prior to 048d, debate would
        # raise FileNotFoundError from inside run_debate and the job ended
        # in ``failed`` rather than ``blocked``.
        self._assert_blocked("alpha", "debate", "kb_missing")


if __name__ == "__main__":
    unittest.main()
