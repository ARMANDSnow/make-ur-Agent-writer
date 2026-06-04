from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src import paths
from src.web import jobs, routes


def _stub_workspace(root: Path, name: str) -> None:
    ws = root / name
    for sub in ("小说txt", "data", "outputs", "logs"):
        (ws / sub).mkdir(parents=True)


class JobCancelRouteTests(unittest.TestCase):
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

    def _cancel(self, job_id: str, workspace: str = "alpha") -> tuple[int, dict]:
        status, _ct, body = routes.dispatch("POST", f"/api/workspace/{workspace}/job/{job_id}/cancel")
        return status, json.loads(body)

    def _wait_for_status(self, job_id: str, statuses: set[str], timeout: float = 5.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            record = jobs.get_job(job_id)
            if record and record.get("status") in statuses:
                return record
            time.sleep(0.02)
        self.fail(f"job {job_id} did not reach {statuses} in {timeout}s")

    def test_cancel_pending_job_sets_flag(self) -> None:
        with patch("threading.Thread.start", return_value=None):
            record = jobs.start_job("alpha", "normalize", {})

        status, data = self._cancel(record["job_id"])
        self.assertEqual(status, 202, data)
        self.assertEqual(data["status"], "pending")
        self.assertTrue(data["cancel_requested"])
        self.assertIn("requested_at", data)
        self.assertTrue(jobs.get_job(record["job_id"])["cancel_requested"])

    def test_cancel_running_job_then_worker_aborts(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def blocking_handler(params, progress_cb):
            entered.set()
            release.wait(timeout=2)
            progress_cb("after-cancel", 0.5)
            return {"status": "succeeded"}

        with patch.dict(jobs.STEP_HANDLERS, {"normalize": blocking_handler}):
            record = jobs.start_job("alpha", "normalize", {})
            self.assertTrue(entered.wait(timeout=2))
            status, data = self._cancel(record["job_id"])
            self.assertEqual(status, 202, data)
            self.assertEqual(data["status"], "running")
            release.set()
            terminal = self._wait_for_status(record["job_id"], {"aborted"})

        self.assertEqual(terminal["current_step"], "cancelled")
        self.assertIsNone(jobs.workspace_busy("alpha"))

    def test_cancel_succeeded_job_returns_409(self) -> None:
        with patch.dict(
            jobs.STEP_HANDLERS,
            {"normalize": lambda params, progress_cb: {"status": "succeeded"}},
        ):
            record = jobs.start_job("alpha", "normalize", {})
            self._wait_for_status(record["job_id"], {"succeeded"})

        status, data = self._cancel(record["job_id"])
        self.assertEqual(status, 409)
        self.assertEqual(data["status"], "succeeded")
        self.assertIn("not cancellable", data["error"])

    def test_cancel_unknown_job_returns_404(self) -> None:
        status, data = self._cancel("f" * 32)
        self.assertEqual(status, 404)
        self.assertEqual(data["error"], "job not found")


if __name__ == "__main__":
    unittest.main()
