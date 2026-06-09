"""iter 048b: four-stage workbench end-to-end.

premise开书 → /w/<name>/workbench page → stage jobs (prepare-greenfield →
debate → plan-chapters → write-book) gated by GET /workbench → editable
outline (PUT /outline). Mock-only: no network, no real model.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from src import paths
from src.web import jobs, routes


class WorkbenchE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        jobs.reset_for_tests()
        self._tmp.cleanup()

    # ---- helpers ----------------------------------------------------------

    def _premise(self, ws: str, premise: str = "少年觉醒上古血脉，逆天改命。") -> None:
        status, _ct, resp = routes.dispatch(
            "POST",
            "/api/wizard/premise-start",
            json.dumps({"workspace": ws, "premise": premise}, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 202, resp.decode("utf-8"))

    def _wait_for_done(self, ws: str, job_id: str, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, _, body = routes.dispatch("GET", f"/api/workspace/{ws}/job/{job_id}")
            rec = json.loads(body)
            if rec.get("status") in ("succeeded", "blocked", "failed", "aborted", "lost"):
                return rec
            time.sleep(0.05)
        self.fail("job did not finish")

    def _run_step(self, ws: str, step: str, params: dict | None = None) -> dict:
        status, _ct, resp = routes.dispatch(
            "POST",
            f"/api/workspace/{ws}/run",
            json.dumps({"step": step, "params": params or {}}).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 202, resp.decode("utf-8"))
        return self._wait_for_done(ws, json.loads(resp)["job_id"])

    def _status(self, ws: str) -> dict:
        st, _ct, body = routes.dispatch("GET", f"/api/workspace/{ws}/workbench")
        self.assertEqual(st, 200, body.decode("utf-8"))
        return json.loads(body)

    # ---- page + navigation ------------------------------------------------

    def test_workbench_page_renders_with_nav(self) -> None:
        self._premise("pagebook")
        st, _ct, body = routes.dispatch("GET", "/w/pagebook/workbench")
        self.assertEqual(st, 200, body.decode("utf-8"))
        html = body.decode("utf-8")
        self.assertIn('window.PAGE_KIND = "workbench"', html)
        self.assertIn("四阶段写书台", html)
        self.assertIn("/w/pagebook/workbench", html)  # sidebar entry present

    def test_workbench_page_is_novel_only(self) -> None:
        routes.dispatch(
            "POST",
            "/api/wizard/drama-start",
            json.dumps(
                {
                    "workspace": "dramaws",
                    "topic": "x",
                    "track": "霸总",
                    "episode_count": 12,
                    "episode_duration_seconds": 60,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            {"content-type": "application/json"},
        )
        st, _ct, body = routes.dispatch("GET", "/w/dramaws/workbench")
        # novel-only guard renders the "not a novel workspace" page, not the workbench.
        self.assertEqual(st, 200)
        self.assertNotIn("四阶段写书台", body.decode("utf-8"))

    # ---- stage gate progression ------------------------------------------

    def test_status_progresses_prepare_to_done(self) -> None:
        self._premise("stagebook")
        s0 = self._status("stagebook")
        self.assertEqual(s0["stage"], "prepare")
        self.assertFalse(s0["has_kb"])

        self._run_step("stagebook", "prepare-greenfield", {"force": True})
        s1 = self._status("stagebook")
        self.assertTrue(s1["has_kb"])
        self.assertEqual(s1["stage"], "outline")

        self._run_step("stagebook", "debate")
        s2 = self._status("stagebook")
        self.assertTrue(s2["has_outline"])
        self.assertEqual(s2["stage"], "plan")

        self._run_step("stagebook", "plan-chapters", {"require_start_point": False})
        s3 = self._status("stagebook")
        self.assertTrue(s3["has_plan"])
        self.assertEqual(s3["stage"], "write")

        rec = self._run_step(
            "stagebook", "write-book", {"require_start_point": False, "require_plan": True}
        )
        # The mock reviewer defaults to Reject (reviewer.py:68), so write-book
        # hits retry_exhausted under mock — the chapter draft IS written, just
        # not strict-approved (real models can approve). Reaching a terminal
        # state (succeeded OR blocked) proves the stage④ wiring; the draft
        # landing + stage="done" proves the workbench reflects it.
        self.assertIn(rec["status"], ("succeeded", "blocked"), f"rec={json.dumps(rec, ensure_ascii=False)[:500]}")
        ch1 = paths.WORKSPACE_DIR / "stagebook" / "outputs" / "drafts" / "chapter_01.md"
        self.assertTrue(ch1.exists(), f"missing {ch1}")
        s4 = self._status("stagebook")
        self.assertGreaterEqual(s4["draft_count"], 1)
        self.assertEqual(s4["stage"], "done")

    # ---- outline PUT ------------------------------------------------------

    def test_outline_put_and_readback(self) -> None:
        self._premise("outbook")
        self._run_step("outbook", "prepare-greenfield", {"force": True})
        self._run_step("outbook", "debate")
        new_outline = "# 我的大纲\n\n第一卷：觉醒。\n第二卷：历练。\n"
        st, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/outbook/outline",
            json.dumps({"outline": new_outline}, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(st, 200, body.decode("utf-8"))
        _, _, plan_body = routes.dispatch("GET", "/api/workspace/outbook/plan")
        self.assertIn("我的大纲", json.loads(plan_body)["outline_md"])

    def test_outline_put_empty_400(self) -> None:
        self._premise("emptyout")
        st, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/emptyout/outline",
            json.dumps({"outline": "   "}).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(st, 400, body.decode("utf-8"))

    def test_outline_put_busy_409(self) -> None:
        self._premise("busyout")
        with jobs._WORKSPACE_LOCK:
            jobs._WORKSPACE_JOBS["busyout"] = "f" * 32
        try:
            st, _ct, body = routes.dispatch(
                "PUT",
                "/api/workspace/busyout/outline",
                json.dumps({"outline": "x"}).encode("utf-8"),
                {"content-type": "application/json"},
            )
            self.assertEqual(st, 409, body.decode("utf-8"))
            self.assertEqual(json.loads(body)["running_job_id"], "f" * 32)
        finally:
            with jobs._WORKSPACE_LOCK:
                jobs._WORKSPACE_JOBS.pop("busyout", None)

    # ---- stale-artifact gating (red-team finding) -------------------------

    def test_stale_outline_invalidated_when_kb_newer(self) -> None:
        """Re-running stage ① (which refreshes the KB) must invalidate a
        stale outline/plan from a prior run, so the gate falls back to the
        outline stage instead of letting old artifacts masquerade as new."""
        self._premise("stalebook")
        self._run_step("stalebook", "prepare-greenfield", {"force": True})
        self._run_step("stalebook", "debate")
        self._run_step("stalebook", "plan-chapters", {"require_start_point": False})
        self.assertEqual(self._status("stalebook")["stage"], "write")

        # Simulate a stage-① re-run by bumping the KB mtime past outline/plan.
        kb = paths.WORKSPACE_DIR / "stalebook" / "data" / "knowledge_base" / "global_knowledge.md"
        self.assertTrue(kb.exists(), f"missing {kb}")
        future = time.time() + 100
        os.utime(kb, (future, future))

        s = self._status("stalebook")
        self.assertEqual(s["stage"], "outline")
        self.assertFalse(s["has_outline"])
        self.assertFalse(s["has_plan"])


if __name__ == "__main__":
    unittest.main()
