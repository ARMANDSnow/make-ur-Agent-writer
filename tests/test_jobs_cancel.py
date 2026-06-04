from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src import paths
from src.web import jobs


def _stub_workspace(root: Path, name: str) -> None:
    ws = root / name
    for sub in ("小说txt", "data", "outputs", "logs"):
        (ws / sub).mkdir(parents=True)


class JobCancelTests(unittest.TestCase):
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

    def _wait_for_terminal(self, job_id: str, timeout: float = 5.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            record = jobs.get_job(job_id)
            if record and record.get("status") in jobs.TERMINAL_STATUSES:
                return record
            time.sleep(0.02)
        self.fail(f"job {job_id} did not finish in {timeout}s")

    def test_request_cancel_sets_flag_atomically(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def blocking_handler(params, progress_cb):
            entered.set()
            release.wait(timeout=2)
            return {"status": "succeeded"}

        with patch.dict(jobs.STEP_HANDLERS, {"normalize": blocking_handler}):
            record = jobs.start_job("alpha", "normalize", {})
            self.assertTrue(entered.wait(timeout=2))
            snapshot = jobs.request_cancel(record["job_id"], "test requested cancel")
            self.assertIsNotNone(snapshot)
            self.assertTrue(snapshot["cancel_requested"])
            self.assertEqual(snapshot["cancel_reason"], "test requested cancel")
            release.set()
            terminal = self._wait_for_terminal(record["job_id"])

        self.assertEqual(terminal["status"], "aborted")
        self.assertEqual(terminal["current_step"], "cancelled")

    def test_worker_progress_checkpoint_detects_cancel(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def checkpoint_handler(params, progress_cb):
            entered.set()
            release.wait(timeout=2)
            progress_cb("after-release", 0.5)
            return {"status": "succeeded"}

        with patch.dict(jobs.STEP_HANDLERS, {"normalize": checkpoint_handler}):
            record = jobs.start_job("alpha", "normalize", {})
            self.assertTrue(entered.wait(timeout=2))
            jobs.request_cancel(record["job_id"])
            release.set()
            terminal = self._wait_for_terminal(record["job_id"])

        self.assertEqual(terminal["status"], "aborted")
        self.assertEqual(terminal["current_step"], "cancelled")
        self.assertIn("user requested cancel", terminal["error"])
        self.assertIsNone(jobs.workspace_busy("alpha"))

    def test_timeout_uses_aborted_path(self) -> None:
        def slow_checkpoint_handler(params, progress_cb):
            time.sleep(0.02)
            progress_cb("late-progress", 0.5)
            return {"status": "succeeded"}

        with patch.dict(jobs.STEP_HANDLERS, {"normalize": slow_checkpoint_handler}):
            record = jobs.start_job("alpha", "normalize", {"timeout_minutes": 0.000001})
            terminal = self._wait_for_terminal(record["job_id"])

        self.assertEqual(terminal["status"], "aborted")
        self.assertEqual(terminal["current_step"], "timeout")
        self.assertIn("timeout after", terminal["error"])
        self.assertTrue(terminal["cancel_requested"])
        self.assertIsNone(jobs.workspace_busy("alpha"))


if __name__ == "__main__":
    unittest.main()
