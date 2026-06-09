"""iter 026: src/web/jobs.py threading worker + step dispatch."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

from src import paths
from src.web import jobs, routes


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
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        jobs.reset_for_tests()
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

    def test_plan_chapters_missing_start_point_is_blocked(self) -> None:
        status, data = self._post_run(
            "alpha",
            {"step": "plan-chapters", "params": {"target_chapters": 3}},
        )
        self.assertEqual(status, 202)
        job = self._wait_for_done("alpha", data["job_id"], timeout=10.0)
        self.assertEqual(job["status"], "blocked")
        self.assertEqual(job["result_summary"]["first_blocked"]["reason"], "start_point_missing")

    def test_plan_chapters_forces_force_but_honors_require_start_point(self) -> None:
        # iter 048b: force is always overridden to True (a re-plan overwrites),
        # but require_start_point is now HONORED from params (was forced True
        # pre-048b) so the greenfield workbench can pass False. Default stays
        # True for safety — see test_plan_chapters_missing_start_point_is_blocked.
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

    def test_concurrent_same_workspace_409(self) -> None:
        # The first job must remain in flight when we fire the second
        # call, so we use a long-ish step. ``auto-pipeline-greenfield`` needs a
        # seeded raw txt to make progress; we don't care about its
        # outcome, only that it occupies the slot.
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
        finally:
            threading.Thread.start = original_start

        # After restore, a normal start_job should succeed and slot up
        # for a real workspace_busy reading.
        record = jobs.start_job("alpha", "normalize", {})
        self.assertEqual(jobs.workspace_busy("alpha"), record["job_id"])
        self._wait_for_done("alpha", record["job_id"], timeout=10.0)
        self.assertIsNone(jobs.workspace_busy("alpha"))

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
        self.assertIn("snapshot_path", job["result_summary"])

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
