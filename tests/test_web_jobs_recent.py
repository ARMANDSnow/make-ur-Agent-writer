from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.web import jobs


def _stub_workspace(root: Path, name: str) -> None:
    for sub in ("小说txt", "data", "outputs", "logs"):
        (root / name / sub).mkdir(parents=True, exist_ok=True)


class RecentJobsLostStatusTests(unittest.TestCase):
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
        jobs.reset_for_tests()
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _write_job_log(self, row: dict) -> None:
        path = paths.WORKSPACE_DIR / "alpha" / "logs" / "web_jobs.jsonl"
        path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    def test_live_running_job_stays_running_when_memory_record_exists(self) -> None:
        row = {
            "job_id": "a" * 32,
            "workspace": "alpha",
            "step": "write-book",
            "params": {"chapters": 1},
            "status": "running",
            "started_at": 10.0,
            "progress": 0.25,
            "current_step": "chapter-1/write-attempt-1",
        }
        self._write_job_log(row)
        with jobs._JOBS_LOCK:
            jobs._JOBS[row["job_id"]] = {**row, "progress": 0.42}

        recent = jobs.recent_jobs("alpha", limit=5)

        self.assertEqual(recent[0]["status"], "running")
        self.assertEqual(recent[0]["progress"], 0.42)
        self.assertNotEqual(recent[0].get("error"), "worker process restarted before this job reached a terminal state")

    def test_running_job_becomes_lost_after_memory_state_is_cleared(self) -> None:
        row = {
            "job_id": "b" * 32,
            "workspace": "alpha",
            "step": "write-book",
            "params": {"chapters": 1},
            "status": "running",
            "started_at": 10.0,
            "progress": 0.25,
        }
        self._write_job_log(row)
        jobs.reset_for_tests()

        recent = jobs.recent_jobs("alpha", limit=5)

        self.assertEqual(recent[0]["status"], "lost")
        self.assertIn("worker process restarted", recent[0]["error"])


if __name__ == "__main__":
    unittest.main()
