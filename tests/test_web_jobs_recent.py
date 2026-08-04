from __future__ import annotations

import json
import os
import hashlib
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


class Iter073RecentAndProjectionTests(unittest.TestCase):
    """iter073 (codex C + D): recent_jobs reconciles lost-ness BEFORE sorting so
    a stale lost row can't pin above a newer success (the overview limit=1 bug);
    finite-JSON sanitize on both response + persistence; explicit list/detail
    field projections."""

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

    def test_local_demo_target_context_is_persisted_but_not_retryable(self) -> None:
        source_hash = hashlib.sha256(b"alpha").hexdigest()[:8]
        target = f"localdemo_{source_hash}_2_deadbeef"
        record = jobs._new_job_record(
            "alpha",
            "drama-local-demo",
            {"episode_no": 2, "demo_workspace": target},
        )
        record.update(status="succeeded", started_at=10.0, finished_at=11.0)
        jobs._persist_job(record)
        jobs.reset_for_tests()

        restored = jobs.recent_jobs("alpha", limit=5)[0]
        for view in (
            jobs.public_job_view(restored),
            jobs.public_job_summary_view(restored),
            jobs.public_job_detail_view(restored),
        ):
            self.assertEqual(view["target_workspace"], target)
            self.assertEqual(view["source_episode_no"], 2)
            self.assertEqual(view["target_episode_no"], 1)
            self.assertEqual(
                view["result_context"],
                {"workspace": target, "episode_no": 1},
            )
        summary = jobs.public_job_summary_view(restored)
        self.assertEqual(summary["params"], {})
        self.assertFalse(summary["retryable"])

    def test_local_demo_target_context_rejects_tampered_persisted_values(self) -> None:
        record = {
            **jobs._new_job_record(
                "alpha",
                "drama-local-demo",
                {
                    "episode_no": 1,
                    "demo_workspace": "localdemo_8ed3f6ad_1_deadbeef",
                },
            ),
            "target_workspace": "../../outside",
            "source_episode_no": 1,
            "target_episode_no": 1,
        }
        for view in (
            jobs.public_job_view(record),
            jobs.public_job_summary_view(record),
            jobs.public_job_detail_view(record),
        ):
            self.assertNotIn("target_workspace", view)
            self.assertNotIn("source_episode_no", view)
            self.assertNotIn("target_episode_no", view)
            self.assertNotIn("result_context", view)

    def test_global_job_lookup_rejects_row_claiming_another_workspace(self) -> None:
        _stub_workspace(paths.WORKSPACE_DIR, "zzz")
        job_id = "c" * 32
        forged = {
            "job_id": job_id,
            "workspace": "alpha",
            "step": "drama-local-demo",
            "status": "succeeded",
            "target_workspace": "localdemo_8ed3f6ad_1_deadbeef",
            "source_episode_no": 1,
            "target_episode_no": 1,
        }
        (paths.WORKSPACE_DIR / "zzz" / "logs" / "web_jobs.jsonl").write_text(
            json.dumps(forged) + "\n", encoding="utf-8"
        )
        self.assertIsNone(jobs.get_job(job_id))

    def _log_path(self, workspace: str) -> Path:
        return paths.WORKSPACE_DIR / workspace / "logs" / "web_jobs.jsonl"

    def _write_rows(self, rows) -> None:
        self._log_path("alpha").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )

    def _lost_then_succeeded_rows(self):
        # An old running row with no live _JOBS record (worker gone) + a newer
        # succeeded row. Pre-iter073, the running row sorted active=1 above the
        # success, got sliced into the top, THEN relabelled lost → the overview
        # (limit=1) showed a stale lost task forever.
        self._write_rows([
            {"job_id": "L" * 32, "workspace": "alpha", "step": "write-book",
             "status": "running", "started_at": 10.0, "finished_at": None},
            {"job_id": "S" * 32, "workspace": "alpha", "step": "write-book",
             "status": "succeeded", "started_at": 50.0, "finished_at": 60.0},
        ])

    def test_lost_row_does_not_outrank_newer_succeeded(self) -> None:
        self._lost_then_succeeded_rows()  # no _JOBS seed → L reconciles to lost
        recent = jobs.recent_jobs("alpha", limit=10)
        self.assertEqual(recent[0]["job_id"], "S" * 32)
        by_id = {j["job_id"]: j for j in recent}
        self.assertEqual(by_id["L" * 32]["status"], "lost")

    def test_overview_limit1_picks_newer_succeeded_over_lost(self) -> None:
        self._lost_then_succeeded_rows()
        recent = jobs.recent_jobs("alpha", limit=1)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["job_id"], "S" * 32)

    def test_finite_json_safe(self) -> None:
        self.assertIsNone(jobs._finite_json_safe(float("nan")))
        self.assertIsNone(jobs._finite_json_safe(float("inf")))
        self.assertIsNone(jobs._finite_json_safe(float("-inf")))
        self.assertEqual(
            jobs._finite_json_safe({"a": float("nan"), "b": [float("inf"), 1.5]}),
            {"a": None, "b": [None, 1.5]},
        )
        self.assertEqual(jobs._finite_json_safe("x"), "x")
        self.assertEqual(jobs._finite_json_safe(5), 5)
        self.assertEqual(jobs._finite_json_safe(2.5), 2.5)

    def test_persist_job_sanitizes_non_finite(self) -> None:
        rec = jobs._new_job_record("alpha", "write-book", {})
        rec["progress"] = float("nan")
        rec["result_summary"] = {"cost_cny": float("inf")}
        jobs._persist_job(rec)
        text = self._log_path("alpha").read_text(encoding="utf-8")
        # bare NaN/Infinity tokens are invalid JSON; a strict parser would choke
        self.assertNotIn("NaN", text)
        self.assertNotIn("Infinity", text)
        row = json.loads(text)
        self.assertIsNone(row["progress"])
        self.assertIsNone(row["result_summary"]["cost_cny"])

    def test_public_job_summary_view_keeps_params_drops_cancel(self) -> None:
        rec = jobs._new_job_record("alpha", "write-book", {"chapters": 1})
        rec["trace_id"] = "tid"
        rec["result_summary"] = {"k": 1}
        rec["error"] = "boom"
        rec["cancel_reason"] = "user"
        rec["_secret"] = "nope"
        view = jobs.public_job_summary_view(rec)
        # the jobs-table retry reposts {step, params}, so params MUST survive
        for kept in ("params", "error", "result_summary", "trace_id", "step", "status"):
            self.assertIn(kept, view)
        for dropped in ("cancel_requested", "cancel_reason", "_secret"):
            self.assertNotIn(dropped, view)

    def test_public_job_detail_view_allowlist(self) -> None:
        rec = jobs._new_job_record("alpha", "write-book", {"chapters": 1})
        rec["trace_id"] = "tid"
        rec["result_summary"] = {"k": 1}
        rec["_secret"] = "nope"
        view = jobs.public_job_detail_view(rec)
        for kept in ("params", "trace_id", "result_summary", "cancel_requested", "cancel_reason", "error"):
            self.assertIn(kept, view)
        # a future internal field added to the record must NOT auto-leak
        self.assertNotIn("_secret", view)

    def test_public_and_durable_job_views_redact_sensitive_fields(self) -> None:
        marker = "SENSITIVE_MARKER"
        rec = jobs._new_job_record(
            "alpha",
            "write-book",
            {
                "chapters": 2,
                "api_key": marker,
                "topic": f"private prompt {marker}",
                "callback_url": f"https://example.invalid/?token={marker}",
                "confirm_real_text": True,
            },
        )
        rec["error"] = f"Bearer {marker}"
        rec["result_summary"] = {
            "status": "failed",
            "error": f"provider response {marker}",
            "snapshot_path": f"/private/{marker}",
            "provider": "sk-secret-value",
        }

        view = jobs.public_job_detail_view(rec)
        jobs._persist_job(rec)
        durable = self._log_path("alpha").read_text(encoding="utf-8")
        rendered = json.dumps(view, ensure_ascii=False) + durable

        self.assertEqual(view["params"], {"chapters": 2})
        self.assertEqual(view["error"], "job_failed")
        self.assertNotIn(marker, rendered)
        self.assertNotIn("sk-secret-value", rendered)
        self.assertNotIn("snapshot_path", rendered)

    def test_retry_projection_is_step_aware_and_disables_unsafe_replay(self) -> None:
        normalize = jobs._new_job_record(
            "alpha",
            "normalize",
            {"lang": "zh", "name": "Bearer-secret", "chapters": 99},
        )
        normalize_view = jobs.public_job_detail_view(normalize)
        self.assertEqual(normalize_view["params"], {"lang": "zh"})
        self.assertFalse(normalize_view["retryable"])
        safe_normalize = jobs._new_job_record(
            "alpha",
            "normalize",
            {"lang": "zh"},
        )
        self.assertTrue(
            jobs.public_job_detail_view(safe_normalize)["retryable"]
        )
        spaced_normalize = jobs._new_job_record(
            "alpha",
            "normalize",
            {"lang": " zh "},
        )
        self.assertFalse(
            jobs.public_job_detail_view(spaced_normalize)["retryable"]
        )
        secret_apply = jobs._new_job_record(
            "alpha",
            "apply-bootstrap",
            {"name": "sk-secret-value", "apply": True},
        )
        secret_view = jobs.public_job_detail_view(secret_apply)
        self.assertNotIn("name", secret_view["params"])
        self.assertFalse(secret_view["retryable"])

        for credential in (
            "AIzaSyDUMMYEXAMPLEVALUE123456789",
            "AKIA1234567890ABCDEF",
            "eyJabcdefgh.ijklmnop.qrstuvwx",
        ):
            credential_view = jobs.public_job_detail_view(
                {
                    **safe_normalize,
                    "result_summary": {"task_id": credential},
                }
            )
            self.assertNotIn("task_id", credential_view["result_summary"])

        debate = jobs._new_job_record(
            "alpha",
            "debate",
            {"topic": "private premise", "force": True},
        )
        debate_view = jobs.public_job_detail_view(debate)
        self.assertEqual(debate_view["params"], {"force": True})
        self.assertFalse(debate_view["retryable"])

        style = jobs._new_job_record(
            "alpha",
            "extract-style",
            {"sample_token": "a" * 32, "force": True},
        )
        style_view = jobs.public_job_detail_view(style)
        self.assertEqual(style_view["params"], {})
        self.assertFalse(style_view["retryable"])

        write = jobs._new_job_record(
            "alpha",
            "write-book",
            {"chapters": 2, "max_retries": 7},
        )
        write_view = jobs.public_job_detail_view(write)
        self.assertEqual(write_view["params"], {"chapters": 2})
        self.assertFalse(write_view["retryable"])

    def test_job_log_symlink_is_neither_read_nor_appended(self) -> None:
        outside = Path(self._tmp.name) / "outside.jsonl"
        outside.write_text(
            json.dumps(
                {
                    "job_id": "x" * 32,
                    "workspace": "alpha",
                    "status": "succeeded",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        log = self._log_path("alpha")
        log.unlink(missing_ok=True)
        log.symlink_to(outside)
        before = outside.read_bytes()

        rec = jobs._new_job_record("alpha", "write-book", {"chapters": 1})
        jobs._persist_job(rec)

        self.assertEqual(jobs.recent_jobs("alpha"), [])
        self.assertEqual(outside.read_bytes(), before)

    def test_job_log_with_giant_integer_fails_closed(self) -> None:
        log = self._log_path("alpha")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_bytes(b'{"progress":' + (b"9" * 5000) + b"}\n")

        self.assertEqual(jobs.recent_jobs("alpha"), [])

    def test_job_log_fifo_is_rejected_without_blocking(self) -> None:
        log = self._log_path("alpha")
        log.unlink(missing_ok=True)
        os.mkfifo(log)
        rec = jobs._new_job_record("alpha", "write-book", {"chapters": 1})

        jobs._persist_job(rec)

        self.assertTrue(log.exists())
        self.assertEqual(jobs.recent_jobs("alpha"), [])

    def test_oversized_or_malformed_job_log_fails_closed(self) -> None:
        self._log_path("alpha").write_bytes(b"x" * (jobs._MAX_JOB_LOG_BYTES + 1))
        self.assertEqual(jobs.recent_jobs("alpha"), [])
        self._log_path("alpha").write_text(
            json.dumps(
                {
                    "job_id": "x" * 32,
                    "workspace": "alpha",
                    "status": "succeeded",
                }
            )
            + "\n{bad-json\n",
            encoding="utf-8",
        )
        self.assertEqual(jobs.recent_jobs("alpha"), [])


if __name__ == "__main__":
    unittest.main()
