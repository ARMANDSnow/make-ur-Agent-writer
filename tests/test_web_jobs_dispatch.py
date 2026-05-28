"""iter 026: src/web/jobs.py threading worker + step dispatch."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
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
            if rec.get("status") in ("done", "error"):
                return rec
            time.sleep(0.05)
        self.fail(f"job {job_id} did not finish in {timeout}s")

    def test_unknown_step_400(self) -> None:
        status, data = self._post_run("alpha", {"step": "no-such-step"})
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

    def test_concurrent_same_workspace_409(self) -> None:
        # The first job must remain in flight when we fire the second
        # call, so we use a long-ish step. ``auto-pipeline`` needs a
        # seeded raw txt to make progress; we don't care about its
        # outcome, only that it occupies the slot.
        (paths.WORKSPACE_DIR / "alpha" / "小说txt" / "sample.txt").write_text(
            "第一章\n测试。\n" * 50, encoding="utf-8"
        )
        s1, d1 = self._post_run(
            "alpha",
            {"step": "auto-pipeline", "params": {"chapters": 1, "extract_limit": 1, "force": True}},
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


if __name__ == "__main__":
    unittest.main()
