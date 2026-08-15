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
from src.web import workspace_meta
from src.utils import read_json, write_json


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
        jobs.reset_for_tests()
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
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
        self.assertIn("单章创作工作台", html)
        self.assertIn('<span class="sidebar-item active" aria-current="page"><span><span class="dot"></span> 创作工作台</span></span>', html)


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
        # state (succeeded OR blocked) proves the stage④ wiring. A rejected
        # draft must stay recoverable instead of masquerading as stage="done".
        self.assertIn(rec["status"], ("succeeded", "blocked"), f"rec={json.dumps(rec, ensure_ascii=False)[:500]}")
        ch1 = paths.WORKSPACE_DIR / "stagebook" / "outputs" / "drafts" / "chapter_01.md"
        self.assertTrue(ch1.exists(), f"missing {ch1}")
        s4 = self._status("stagebook")
        self.assertGreaterEqual(s4["draft_count"], 1)
        self.assertEqual(s4["stage"], "write")
        self.assertEqual(s4["write_state"], "retry_required")
        self.assertEqual(s4["retry_chapter"], 1)
        # A newly regenerated strict plan does not erase the durable failed
        # chapter.  The recovery CTA must remain reachable until that exact
        # generation is explicitly archived or otherwise resolved.
        plan = paths.WORKSPACE_DIR / "stagebook" / "outputs" / "debate" / "chapter_plan.json"
        future = max(time.time_ns(), ch1.stat().st_mtime_ns + 1_000_000)
        os.utime(plan, ns=(future, future))
        refreshed = self._status("stagebook")
        self.assertEqual(refreshed["write_state"], "retry_required")
        self.assertEqual(refreshed["retry_chapter"], 1)

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

    def test_changing_continuation_start_invalidates_kb_chain(self) -> None:
        """A different source anchor changes every downstream semantic input.

        The workbench must therefore fall back to preparation instead of
        presenting an outline/plan built for the previous continuation point.
        """
        self._premise("anchorbook")
        self._run_step("anchorbook", "prepare-greenfield", {"force": True})
        self._run_step("anchorbook", "debate")
        self._run_step("anchorbook", "plan-chapters", {"require_start_point": False})
        self.assertEqual(self._status("anchorbook")["stage"], "write")

        workspace_meta.write("anchorbook", type="novel", creation_mode="continuation")
        with routes.use_workspace("anchorbook"):
            start_file = paths.manual_overrides_dir() / "start_chapter.json"
            start_file.parent.mkdir(parents=True, exist_ok=True)
            write_json(start_file, {"start_chapter_id": "source_ch001"})
            # Once the workspace is declared a continuation, its existing plan
            # must carry the same anchor identity; the workbench now shares the
            # runner's strict metadata gate instead of accepting mtime alone.
            from src.plot_planner import plan_fingerprint
            from src.start_point import start_point_fingerprint

            plan_file = paths.chapter_plan_path()
            plan_data = read_json(plan_file, {})
            plan_data["start_chapter_id"] = "source_ch001"
            plan_data["start_point_fingerprint"] = start_point_fingerprint()
            plan_data["plan_fingerprint"] = plan_fingerprint(plan_data)
            write_json(plan_file, plan_data)

        # Model an existing anchor that predates the derived artifacts.
        past = time.time() - 100
        os.utime(start_file, (past, past))
        self.assertEqual(self._status("anchorbook")["stage"], "write")

        # Selecting a new anchor is authoritative input and must stale the KB,
        # outline and chapter-plan chain in one projection refresh.
        future = time.time() + 100
        os.utime(start_file, (future, future))
        status = self._status("anchorbook")
        self.assertEqual(status["stage"], "prepare")
        self.assertFalse(status["has_kb"])
        self.assertFalse(status["has_outline"])
        self.assertFalse(status["has_plan"])


if __name__ == "__main__":
    unittest.main()
