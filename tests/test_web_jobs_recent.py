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


class ActiveJobsTests(unittest.TestCase):
    """iter071 (codex F2): active_jobs() is the leave-guard's authoritative,
    untruncated source of in-flight jobs. recent_jobs() can drop a just-enqueued
    pending job (started_at=None sorts to key 0 → last) once enough terminal rows
    pile up past ?n; active_jobs() reads the in-memory pool directly so it can't."""

    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        _stub_workspace(paths.WORKSPACE_DIR, "alpha")
        _stub_workspace(paths.WORKSPACE_DIR, "beta")
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        jobs.reset_for_tests()
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _seed(self, **fields) -> None:
        with jobs._JOBS_LOCK:
            jobs._JOBS[fields["job_id"]] = dict(fields)

    def _log_path(self, workspace: str) -> Path:
        return paths.WORKSPACE_DIR / workspace / "logs" / "web_jobs.jsonl"

    def test_returns_only_this_workspace_pending_and_running(self) -> None:
        self._seed(job_id="a" * 32, workspace="alpha", step="write-book", status="pending", started_at=None)
        self._seed(job_id="b" * 32, workspace="alpha", step="extract", status="running", started_at=10.0)
        self._seed(job_id="c" * 32, workspace="alpha", step="debate", status="succeeded", started_at=5.0)
        self._seed(job_id="d" * 32, workspace="beta", step="write-book", status="running", started_at=9.0)

        active_ids = {j["job_id"] for j in jobs.active_jobs("alpha")}

        # pending + running for alpha only; terminal (succeeded) and beta excluded
        self.assertEqual(active_ids, {"a" * 32, "b" * 32})

    def test_pending_with_null_started_at_is_immune_to_recent_truncation(self) -> None:
        """Core F2 regression: 12 terminal rows + 1 live pending (started_at=None).
        recent_jobs?n=10 truncates the pending away; active_jobs still reports it."""
        rows = [
            {
                "job_id": f"t{i:031d}",
                "workspace": "alpha",
                "step": "write-book",
                "status": "succeeded",
                "started_at": float(i),
                "finished_at": float(100 + i),
            }
            for i in range(12)
        ]
        pending = {
            "job_id": "p" * 32,
            "workspace": "alpha",
            "step": "write-book",
            "status": "pending",
            "started_at": None,
            "finished_at": None,
        }
        rows.append(pending)
        self._log_path("alpha").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
        )
        self._seed(**pending)

        recent10 = {j["job_id"] for j in jobs.recent_jobs("alpha", limit=10)}
        self.assertNotIn("p" * 32, recent10)  # the bug: truncated out
        active = {j["job_id"] for j in jobs.active_jobs("alpha")}
        self.assertIn("p" * 32, active)  # the fix: always reported

    def test_empty_after_process_restart_fails_open(self) -> None:
        """After a restart _JOBS is empty → [] → leave-guard fails open. The
        log's old 'running' row is no longer actually running."""
        self._log_path("alpha").write_text(
            json.dumps(
                {
                    "job_id": "r" * 32,
                    "workspace": "alpha",
                    "step": "write-book",
                    "status": "running",
                    "started_at": 10.0,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        jobs.reset_for_tests()  # simulate process restart (in-memory pool cleared)

        self.assertEqual(jobs.active_jobs("alpha"), [])


if __name__ == "__main__":
    unittest.main()
