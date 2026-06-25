from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_pending_with_null_started_at_surfaces_in_both_sources(self) -> None:
        """iter071 F2 + iter072 #5: 12 terminal rows + 1 live pending
        (started_at=None). Pre-iter072 recent_jobs?n=10 sorted the pending to key
        0 and truncated it away, which is why active_jobs (in-memory, untruncated)
        was the leave-guard's source. iter072's pending-priority sort now floats
        the pending to the *top* of recent_jobs too, so both sources report it."""
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

        recent10 = jobs.recent_jobs("alpha", limit=10)
        # iter072 #5: pending now sorts to the top instead of being truncated out
        self.assertEqual(recent10[0]["job_id"], "p" * 32)
        active = {j["job_id"] for j in jobs.active_jobs("alpha")}
        self.assertIn("p" * 32, active)  # authoritative in-memory source still reports it

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


class Iter072JobsResidualTests(unittest.TestCase):
    """iter072: recent_jobs robustness (#5) + pending priority (#5),
    public_job_view allowlist (#4), and the start_job write order (#3) that
    closes the /jobs/active publish race."""

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

    def _log_path(self, workspace: str) -> Path:
        return paths.WORKSPACE_DIR / workspace / "logs" / "web_jobs.jsonl"

    def _write_rows(self, rows) -> None:
        self._log_path("alpha").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )

    def test_recent_jobs_tolerates_corrupt_timestamp(self) -> None:
        """iter072 (#5): a hand-edited / truncated jsonl row with a non-numeric
        timestamp must not raise — float('bad') → ValueError used to 500 the jobs
        page, sidebar recent, and overview alike. The bad row sinks to key 0.0."""
        self._write_rows([
            {"job_id": "a" * 32, "workspace": "alpha", "step": "write-book",
             "status": "succeeded", "finished_at": "bad", "started_at": "also-bad"},
            {"job_id": "b" * 32, "workspace": "alpha", "step": "extract",
             "status": "succeeded", "finished_at": 200.0, "started_at": 100.0},
        ])
        recent = jobs.recent_jobs("alpha", limit=10)
        self.assertEqual({j["job_id"] for j in recent}, {"a" * 32, "b" * 32})
        # the good-timestamp row sorts ahead of the corrupt (key 0.0) one
        self.assertEqual(recent[0]["job_id"], "b" * 32)

    def test_as_ts_neutralizes_bad_and_non_finite(self) -> None:
        """iter072 (#5): _as_ts coerces corrupt values to 0.0 — including NaN/inf,
        which survive float() but would silently corrupt the sort order."""
        self.assertEqual(jobs._as_ts(None), 0.0)
        self.assertEqual(jobs._as_ts("bad"), 0.0)
        self.assertEqual(jobs._as_ts(""), 0.0)
        self.assertEqual(jobs._as_ts([]), 0.0)
        self.assertEqual(jobs._as_ts("inf"), 0.0)
        self.assertEqual(jobs._as_ts("nan"), 0.0)
        self.assertEqual(jobs._as_ts(float("inf")), 0.0)
        self.assertEqual(jobs._as_ts(123.5), 123.5)
        self.assertEqual(jobs._as_ts("200"), 200.0)

    def test_recent_jobs_pending_sorts_before_newer_terminal(self) -> None:
        """iter072 (#5): a live pending/running job sorts above a more-recent
        terminal row so it surfaces at the top of the jobs list / sidebar."""
        self._write_rows([
            {"job_id": "t" * 32, "workspace": "alpha", "step": "write-book",
             "status": "succeeded", "finished_at": 999.0, "started_at": 990.0},
            {"job_id": "p" * 32, "workspace": "alpha", "step": "write-book",
             "status": "running", "finished_at": None, "started_at": 10.0},
        ])
        # keep the running row live in memory so it isn't relabelled 'lost'
        with jobs._JOBS_LOCK:
            jobs._JOBS["p" * 32] = {
                "job_id": "p" * 32, "workspace": "alpha", "step": "write-book",
                "status": "running", "started_at": 10.0,
            }
        recent = jobs.recent_jobs("alpha", limit=10)
        self.assertEqual(recent[0]["job_id"], "p" * 32)  # active first despite older ts

    def test_public_job_view_drops_internal_fields(self) -> None:
        """iter072 (#4): the public projection keeps display fields and drops the
        user's params plus internal diagnostics."""
        record = jobs._new_job_record("alpha", "write-book", {"secret": "do-not-leak"})
        record["trace_id"] = "tid"
        record["result_summary"] = {"x": 1}
        view = jobs.public_job_view(record)
        self.assertEqual(
            set(view),
            {"job_id", "workspace", "step", "status", "current_step", "progress",
             "started_at", "finished_at"},
        )
        for leaked in ("params", "trace_id", "result_summary", "cancel_requested", "error"):
            self.assertNotIn(leaked, view)

    def test_start_job_registers_in_jobs_before_reserving_workspace(self) -> None:
        """iter072 (#3): the workspace slot must never be set before the job is
        visible in _JOBS — else a concurrent /jobs/active (scans _JOBS only) sees
        the workspace busy yet reports zero active jobs and the leave-guard slips."""
        saved_ws = jobs._WORKSPACE_JOBS

        class _Probe(dict):
            def __setitem__(self, key, value):
                assert value in jobs._JOBS, "workspace slot reserved before _JOBS write"
                super().__setitem__(key, value)

        class _NoopThread:
            def __init__(self, *a, **k) -> None:
                pass

            def start(self) -> None:
                pass

        jobs._WORKSPACE_JOBS = _Probe()
        jobs.STEP_HANDLERS["_iter072-noop"] = lambda params, progress: {"status": "succeeded"}
        try:
            with mock.patch.object(jobs.threading, "Thread", _NoopThread):
                rec = jobs.start_job("alpha", "_iter072-noop", {})
            # invariant held (no AssertionError) and both tables agree
            self.assertIn(rec["job_id"], jobs._JOBS)
            self.assertEqual(jobs._WORKSPACE_JOBS["alpha"], rec["job_id"])
        finally:
            jobs.STEP_HANDLERS.pop("_iter072-noop", None)
            jobs.reset_for_tests()
            jobs._WORKSPACE_JOBS = saved_ws


if __name__ == "__main__":
    unittest.main()
