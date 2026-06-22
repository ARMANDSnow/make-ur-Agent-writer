"""iter059 P1: corrupt JSON state files must degrade / surface clean blockers,
not crash with a raw JSONDecodeError traceback.

Covers the bad-JSON cluster from docs/FRONTEND_BUG_AUDIT_2026-06.md §4:
  #10 rolling summary, #5 draft meta/review, #13 driver state/pid, #4 chapter_plan.

The common root cause was key state files read with the strict ``read_json``
(exists-but-corrupt -> JSONDecodeError) instead of the degrade-safe
``read_json_optional``. iter059 converts each hot read at the call site.

Mock-only; no network, no real workspace data.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


class RollingSummaryCorruptTests(unittest.TestCase):
    """#10: load_rolling_summary degrades a malformed file to empty state,
    honoring its docstring (was: raised JSONDecodeError mid-write)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "rolling.json"

    def test_corrupt_rolling_summary_degrades_to_empty(self) -> None:
        from src import chapter_summary

        self.path.write_text("{not valid json", encoding="utf-8")
        data = chapter_summary.load_rolling_summary(self.path)
        self.assertEqual(data, {"chapters": [], "compressed_older": []})

    def test_valid_rolling_summary_still_loads(self) -> None:
        from src import chapter_summary

        self.path.write_text(
            json.dumps({"chapters": [{"chapter": 1}], "compressed_older": ["x"]}),
            encoding="utf-8",
        )
        data = chapter_summary.load_rolling_summary(self.path)
        self.assertEqual(data["chapters"], [{"chapter": 1}])
        self.assertEqual(data["compressed_older"], ["x"])


class ChapterStatusCorruptTests(unittest.TestCase):
    """#5: corrupt chapter_NN.meta.json / review JSON must not crash
    resume/status; they degrade or surface a clean strict-failure."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # review_path = drafts_dir.parent / "reviews"; mirror that layout.
        self.drafts = Path(self._tmp.name) / "outputs" / "drafts"
        self.drafts.mkdir(parents=True)
        (self.drafts / "chapter_01.md").write_text("正文内容。", encoding="utf-8")

    def test_corrupt_meta_degrades_not_crash(self) -> None:
        from src.chapter_status import chapter_status

        (self.drafts / "chapter_01.meta.json").write_text("{bad json", encoding="utf-8")
        status = chapter_status(1, self.drafts)
        self.assertTrue(status["exists"])
        self.assertFalse(status["approved"])
        self.assertIsNone(status["verdict"])
        self.assertEqual(status["rewrite_count"], 0)

    def test_corrupt_review_yields_external_review_invalid(self) -> None:
        from src.chapter_status import chapter_status

        reviews = self.drafts.parent / "reviews"
        reviews.mkdir()
        (reviews / "chapter_01.review.json").write_text("{bad json", encoding="utf-8")
        status = chapter_status(
            1, self.drafts, validate_context=True, require_external_review=True
        )
        self.assertIn("external_review_invalid", status["strict_failures"])
        self.assertFalse(status["approved"])


class DriverStateCorruptTests(unittest.TestCase):
    """#13: corrupt driver_state.json / driver.pid must not crash
    status/resume/stop; cmd_status reports a driver_state_invalid diagnostic."""

    def setUp(self) -> None:
        from src import book_driver, paths

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        os.environ["WORKSPACE_NAME"] = "alpha"
        self.addCleanup(self._restore)
        book_driver.driver_dir().mkdir(parents=True, exist_ok=True)

    def _restore(self) -> None:
        from src import paths

        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env

    def test_corrupt_driver_state_returns_none(self) -> None:
        from src import book_driver

        book_driver.state_path().write_text("{bad json", encoding="utf-8")
        self.assertIsNone(book_driver.load_state())

    def test_corrupt_pid_treated_as_no_driver(self) -> None:
        from src import book_driver

        book_driver.pid_path().write_text("{bad json", encoding="utf-8")
        self.assertIsNone(book_driver._another_driver_running())

    def test_cmd_status_reports_invalid_when_state_corrupt(self) -> None:
        from src import book_driver

        book_driver.state_path().write_text("{bad json", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = book_driver.cmd_status(SimpleNamespace(json=False))
        self.assertEqual(rc, 2)
        self.assertIn("driver_state_invalid", buf.getvalue())

    def test_cmd_status_reports_absent_when_state_missing(self) -> None:
        from src import book_driver

        # No state file at all -> the plain "no driver state" message, not the
        # invalid diagnostic (existence-vs-parse disambiguation).
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = book_driver.cmd_status(SimpleNamespace(json=False))
        self.assertEqual(rc, 2)
        self.assertIn("no driver state", buf.getvalue())
        self.assertNotIn("driver_state_invalid", buf.getvalue())


class ChapterPlanInvalidTests(unittest.TestCase):
    """#4 (Option B): corrupt / wrong-schema chapter_plan.json surfaces a
    distinct chapter_plan_invalid blocker, never a raw JSONDecodeError that
    fails the job or leaks through GET /readiness as readiness_error:..."""

    def setUp(self) -> None:
        from src import paths

        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        os.environ["WORKSPACE_NAME"] = "alpha"
        self.addCleanup(self._restore)
        for sub in ("小说txt", "data", "outputs/debate", "outputs/drafts", "logs"):
            (paths.WORKSPACE_DIR / "alpha" / sub).mkdir(parents=True, exist_ok=True)

    def _restore(self) -> None:
        from src import paths

        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env

    def _write_plan(self, text: str) -> None:
        from src import paths

        paths.chapter_plan_path().write_text(text, encoding="utf-8")

    def test_load_chapter_plan_raises_on_corrupt_json(self) -> None:
        from src.writer import ChapterPlanInvalid, _load_chapter_plan

        self._write_plan("{not valid json")
        with self.assertRaises(ChapterPlanInvalid):
            _load_chapter_plan()

    def test_load_chapter_plan_raises_on_wrong_schema(self) -> None:
        from src.writer import ChapterPlanInvalid, _load_chapter_plan

        for bad in ('{"foo": 1}', "[1, 2, 3]"):
            self._write_plan(bad)
            with self.assertRaises(ChapterPlanInvalid):
                _load_chapter_plan()

    def test_blocker_kind_and_label_distinct_from_missing(self) -> None:
        from src.book_runner import _blocker_kind, _primary_blocker

        self.assertEqual(_blocker_kind("chapter_plan_invalid"), "chapter_plan_invalid")
        pb = _primary_blocker(["chapter_plan_invalid"])
        self.assertEqual(pb["kind"], "chapter_plan_invalid")
        self.assertEqual(pb["label"], "章节计划文件损坏")
        self.assertEqual(pb["cta_action"], "run_plan_chapters")

    def test_readiness_surfaces_chapter_plan_invalid(self) -> None:
        from src.book_runner import check_write_readiness

        self._write_plan("{not valid json")
        result = check_write_readiness(
            chapters=1, require_start_point=False, require_plan=True
        )
        self.assertEqual(result["status"], "blocked")
        self.assertIn("chapter_plan_invalid", result["blockers"])
        for blocker in result["blockers"]:
            self.assertFalse(blocker.startswith("readiness_error:"), blocker)
        self.assertEqual(result["primary_blocker"]["kind"], "chapter_plan_invalid")

    def test_readiness_endpoint_no_raw_jsondecodeerror_leak(self) -> None:
        # The headline #4 symptom: GET /readiness used to leak
        # "readiness_error:JSONDecodeError: ..." via _safe_readiness.
        from src.web import routes

        self._write_plan("{not valid json")
        status, _ct, body = routes.dispatch("GET", "/api/workspace/alpha/readiness")
        self.assertEqual(status, 200, body.decode("utf-8"))
        data = json.loads(body)
        self.assertEqual(data["status"], "blocked")
        self.assertIn("chapter_plan_invalid", data["blockers"])
        for blocker in data["blockers"]:
            self.assertFalse(blocker.startswith("readiness_error:"), blocker)


class AutoAdvanceCorruptTests(unittest.TestCase):
    """#8: a corrupt proposal / entity_graph encountered AFTER a chapter is
    approved+persisted must make auto-advance a clean no-op, not raise an
    uncaught JSONDecodeError that fails the job with content already on disk."""

    def setUp(self) -> None:
        from src import paths

        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        os.environ["WORKSPACE_NAME"] = "alpha"
        self.addCleanup(self._restore)
        for sub in ("data", "outputs/drafts", "outputs/debate"):
            (paths.WORKSPACE_DIR / "alpha" / sub).mkdir(parents=True, exist_ok=True)

    def _restore(self) -> None:
        from src import paths

        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env

    def test_corrupt_proposal_and_graph_no_op_not_crash(self) -> None:
        from src import book_runner, paths
        from src.entity_advance import proposal_path

        proposal_path(1, paths.drafts_dir()).write_text("{bad json", encoding="utf-8")
        paths.entity_graph_path().write_text("{bad json", encoding="utf-8")
        # Must not raise; degrades to a no-op result.
        result = book_runner._auto_apply_advances(1, min_confidence=0.7)
        self.assertEqual(result["applied_count"], 0)
        self.assertTrue(result["auto_apply"])


if __name__ == "__main__":
    unittest.main()
