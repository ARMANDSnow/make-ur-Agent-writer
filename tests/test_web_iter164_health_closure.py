from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import paths
from src.web import jobs, routes, static


def _stub_workspace(root: Path, name: str) -> None:
    for sub in ("小说txt", "data", "outputs", "logs"):
        (root / name / sub).mkdir(parents=True, exist_ok=True)


class Iter164JobContextAndLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        for name in ("alpha", "beta", "gamma"):
            _stub_workspace(paths.WORKSPACE_DIR, name)
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        jobs.reset_for_tests()
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _log(self, workspace: str) -> Path:
        return paths.WORKSPACE_DIR / workspace / "logs" / "web_jobs.jsonl"

    def _write_rows(self, workspace: str, rows: list[dict]) -> None:
        self._log(workspace).write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )

    def test_episode_two_context_survives_all_terminal_states_and_restart(self) -> None:
        statuses = ("succeeded", "blocked", "failed", "aborted", "budget_exceeded")
        records = []
        for index, status in enumerate(statuses, start=1):
            record = jobs._new_job_record("alpha", "drama-storyboard", {"episode_no": 2})
            record.update(
                job_id=f"{index:032x}",
                status=status,
                started_at=float(index),
                finished_at=float(index + 10),
            )
            self.assertTrue(jobs._persist_job(record))
            records.append(record)
        running = jobs._new_job_record("alpha", "drama-storyboard", {"episode_no": 2})
        running.update(job_id="f" * 32, status="running", started_at=99.0)
        self.assertTrue(jobs._persist_job(running))
        jobs.reset_for_tests()

        restored = {row["job_id"]: row for row in jobs.recent_jobs("alpha", limit=10)}
        self.assertEqual(restored[running["job_id"]]["status"], "lost")
        for record in (*records, running):
            for view in (
                jobs.public_job_view(restored[record["job_id"]]),
                jobs.public_job_summary_view(restored[record["job_id"]]),
                jobs.public_job_detail_view(restored[record["job_id"]]),
            ):
                self.assertEqual(
                    view["result_context"],
                    {"workspace": "alpha", "episode_no": 2},
                )

    def test_local_demo_context_points_to_validated_target_episode_one(self) -> None:
        source_hash = hashlib.sha256(b"alpha").hexdigest()[:8]
        target = f"localdemo_{source_hash}_2_deadbeef"
        record = jobs._new_job_record(
            "alpha",
            "drama-local-demo",
            {"episode_no": 2, "demo_workspace": target},
        )
        self.assertEqual(
            jobs.public_job_detail_view(record)["result_context"],
            {"workspace": target, "episode_no": 1},
        )
        self.assertTrue(jobs._persist_job(record))
        jobs.reset_for_tests()
        restored = jobs.get_job_for_workspace("alpha", record["job_id"])
        self.assertEqual(
            jobs.public_job_detail_view(restored)["result_context"],
            {"workspace": target, "episode_no": 1},
        )

    def test_explicit_tamper_fails_closed_and_historical_rows_degrade_safely(self) -> None:
        record = jobs._new_job_record("alpha", "drama-plan", {"episode_no": 2})
        for bad_context in (
            {"workspace": "beta", "episode_no": 2},
            {"workspace": "alpha", "episode_no": 3},
            {"workspace": "alpha", "episode_no": 0},
            {"workspace": "alpha", "episode_no": True},
            {"workspace": "alpha", "episode_no": 2, "extra": "x"},
            "alpha:2",
        ):
            tampered = {**record, "result_context": bad_context}
            self.assertNotIn("result_context", jobs.public_job_detail_view(tampered))
            self.assertFalse(jobs._persist_job(tampered))

        historical = {
            **record,
            "result_context": None,
            "params": {"episode_no": 2},
            "result_summary": {"episode_no": 2},
        }
        historical.pop("result_context")
        historical.pop("source_episode_no")
        self.assertEqual(
            jobs.public_job_detail_view(historical)["result_context"],
            {"workspace": "alpha", "episode_no": 2},
        )
        historical.update(job_id="d" * 32, status="succeeded")
        self.assertTrue(jobs._persist_job(historical))
        jobs.reset_for_tests()
        restored = jobs.get_job_for_workspace("alpha", historical["job_id"])
        self.assertEqual(
            jobs.public_job_detail_view(restored)["result_context"],
            {"workspace": "alpha", "episode_no": 2},
        )
        historical["result_summary"] = {"episode_no": 3}
        self.assertNotIn("result_context", jobs.public_job_detail_view(historical))
        historical["params"] = {"episode_no": "2"}
        historical["result_summary"] = {}
        self.assertNotIn("result_context", jobs.public_job_detail_view(historical))

    def test_scoped_lookup_reads_only_target_ledger_for_restart_and_unknown(self) -> None:
        alpha = {
            "job_id": "a" * 32,
            "workspace": "alpha",
            "step": "drama-plan",
            "status": "running",
            "params": {"episode_no": 2},
        }
        beta = {**alpha, "workspace": "beta", "job_id": "b" * 32}
        self._write_rows("alpha", [alpha])
        self._write_rows("beta", [beta])

        original = jobs._read_job_rows
        calls: list[str] = []

        def tracked(workspace: str):
            calls.append(workspace)
            return original(workspace)

        with mock.patch.object(jobs, "_read_job_rows", side_effect=tracked):
            restored = jobs.get_job_for_workspace("alpha", alpha["job_id"])
            self.assertEqual(restored["status"], "lost")
            self.assertIsNone(jobs.get_job_for_workspace("alpha", beta["job_id"]))
            self.assertIsNone(jobs.get_job_for_workspace("alpha", "c" * 32))
        self.assertEqual(calls, ["alpha", "alpha", "alpha"])

    def test_cross_workspace_live_lookup_and_cancel_fail_closed_under_lock(self) -> None:
        record = jobs._new_job_record("beta", "drama-plan", {"episode_no": 2})
        with jobs._JOBS_LOCK:
            jobs._JOBS[record["job_id"]] = record
        with mock.patch.object(jobs, "_read_job_rows") as read_rows:
            self.assertIsNone(jobs.get_job_for_workspace("alpha", record["job_id"]))
            read_rows.assert_not_called()
        self.assertIsNone(jobs.request_cancel(record["job_id"], workspace="alpha"))
        self.assertFalse(jobs.get_job(record["job_id"])["cancel_requested"])

        status, _ct, body = routes.dispatch(
            "GET", f"/api/workspace/alpha/job/{record['job_id']}"
        )
        self.assertEqual(status, 404, body.decode("utf-8"))

    def test_http_detail_uses_scoped_lookup_and_cancel_passes_workspace_recheck(self) -> None:
        record = jobs._new_job_record("alpha", "drama-plan", {"episode_no": 2})
        with jobs._JOBS_LOCK:
            jobs._JOBS[record["job_id"]] = record
        with mock.patch.object(
            jobs,
            "get_job",
            side_effect=AssertionError("global lookup must not serve HTTP"),
        ), mock.patch.object(jobs, "request_cancel", wraps=jobs.request_cancel) as cancel:
            status, _ct, body = routes.dispatch(
                "GET", f"/api/workspace/alpha/job/{record['job_id']}"
            )
            self.assertEqual(status, 200, body.decode("utf-8"))
            self.assertEqual(
                json.loads(body)["result_context"],
                {"workspace": "alpha", "episode_no": 2},
            )
            status, _ct, body = routes.dispatch(
                "POST", f"/api/workspace/alpha/job/{record['job_id']}/cancel"
            )
            self.assertEqual(status, 202, body.decode("utf-8"))
            cancel.assert_called_once_with(record["job_id"], workspace="alpha")

    def test_task_links_are_derived_from_result_context(self) -> None:
        js = static.JS_DASHBOARD
        start = js.index("        function resultHref(job) {")
        end = js.index("        function actionFor(job, index) {", start)
        helper = js[start:end]
        self.assertIn("job && job.result_context", helper)
        self.assertIn('encodeURIComponent(contextWorkspace)', helper)
        self.assertIn('job.step === "drama-local-demo" ? "/compose"', helper)
        self.assertNotIn("job.params", helper)
        self.assertIn('const context = job.result_context || {};', js)
        self.assertIn(
            'if (status === "lost") return href',
            js,
        )
        self.assertIn(
            '>查看恢复条件</a>',
            js,
        )
        self.assertNotIn(
            'status === "lost" || status === "submission_unknown"',
            js,
        )
        self.assertIn(
            'if (status === "lost") return "任务因服务重启中断；',
            js,
        )
        self.assertIn(
            'if (status === "succeeded") return \'<span class="muted">任务已完成，但结果上下文不可用</span>\';',
            js,
        )


if __name__ == "__main__":
    unittest.main()
