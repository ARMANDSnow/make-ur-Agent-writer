"""iter060 P2 收官 (docs/FRONTEND_BUG_AUDIT_2026-06.md §4 iter 060):

  #7  起点保存无 workspace reservation —— reserved 时 PUT /start-point 仍穿过，
      绕过 409 互斥。
  #11 writer-style 样本固定临时文件 + 写在抢锁前 —— 并发 extract 互相覆盖样本。
  #14 历史 Web 写端点非原子 + 无 reservation。
  #12 cancel/timeout 仅在 progress checkpoint 检查 —— 长 step 内不可中断。

Mock-only; no network, no real workspace data. 每个 fix 一个 TestCase。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from src import paths
from src.web import jobs, routes


class _IsolatedWorkspaceCase(unittest.TestCase):
    """Temp WORKSPACE_DIR + WORKSPACE_NAME=alpha + jobs reset, like the other
    web tests."""

    workspace = "alpha"

    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        os.environ["WORKSPACE_NAME"] = self.workspace
        jobs.reset_for_tests()
        self.addCleanup(self._restore_env)
        self.addCleanup(jobs.reset_for_tests)
        for sub in ("小说txt", "data", "outputs/drafts", "logs"):
            (paths.WORKSPACE_DIR / self.workspace / sub).mkdir(parents=True, exist_ok=True)

    def _restore_env(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env


class StartPointReservationTests(_IsolatedWorkspaceCase):
    """#7: PUT /start-point must honor the same workspace_reserved 409 mutex as
    the other destructive write endpoints, so it can't flip the start point
    under a running pipeline."""

    def setUp(self) -> None:
        super().setUp()
        # set_start_point validates against chapter_manifest, so seed one entry.
        paths.chapter_manifest_path().write_text(
            json.dumps([{"chapter_id": "chapter_001", "volume_id": "vol_1"}]),
            encoding="utf-8",
        )

    def _put(self) -> tuple:
        body = json.dumps({"start_point": "chapter_001"}).encode()
        return routes.dispatch("POST", f"/api/workspace/{self.workspace}/start-point", body)

    def test_reserved_returns_409(self) -> None:
        with jobs.workspace_reserved(self.workspace):
            status, _ct, body = self._put()
        self.assertEqual(status, 409, body.decode("utf-8"))
        self.assertIn("running_job_id", json.loads(body))

    def test_not_reserved_succeeds_200(self) -> None:
        # Negative control: the 409 is specifically from the reservation, not a
        # spurious reject — a free workspace sets the start point cleanly.
        status, _ct, body = self._put()
        self.assertEqual(status, 200, body.decode("utf-8"))
        data = json.loads(body)
        self.assertEqual(data["start_point"].get("start_chapter_id"), "chapter_001")


class DebateCancelCheckpointTests(unittest.TestCase):
    """#12: run_debate calls the progress/cancel checkpoint BEFORE each LLM call,
    so a cancel mid-debate aborts between calls instead of after the whole step
    (~52s/call, audit §3.3). The checkpoint sits OUTSIDE the per-agent
    try/except, so the cancellation propagates rather than being swallowed."""

    def _harness(self, complete_text, progress_cb):
        from src.debater import run_debate
        from src.llm_client import LLMClient

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "global_knowledge.md").write_text("# kb", encoding="utf-8")
            (Path(tmp) / "knowledge_index.json").write_text("{}", encoding="utf-8")
            with patch("src.debater.KB_PATH", Path(tmp) / "global_knowledge.md"), patch(
                "src.debater.INDEX_PATH", Path(tmp) / "knowledge_index.json"
            ), patch("src.debater.DEBATE_DIR", Path(tmp)), patch.object(
                LLMClient, "complete_text", side_effect=complete_text
            ):
                return run_debate(progress_cb=progress_cb)

    def test_cancel_at_first_checkpoint_propagates_and_makes_no_llm_call(self) -> None:
        from src.web.jobs import JobCancelled

        calls = {"llm": 0}

        def complete_text(*_a, **_kw):
            calls["llm"] += 1
            return "ok"

        def cancel_now(_step, _fraction):
            raise JobCancelled("user requested cancel")

        # If the checkpoint were INSIDE the agent try, `except Exception` would
        # swallow JobCancelled and the debate would run to completion. It raises,
        # and before any LLM call → the checkpoint is correctly placed/propagated.
        with self.assertRaises(JobCancelled):
            self._harness(complete_text, cancel_now)
        self.assertEqual(calls["llm"], 0)

    def test_no_cancel_completes_and_calls_llm(self) -> None:
        # Control: a non-raising progress_cb must not perturb the happy path —
        # the debate completes and makes its LLM calls (mocked).
        calls = {"llm": 0, "ckpt": 0}

        def complete_text(*_a, **_kw):
            calls["llm"] += 1
            return "ok"

        def noop(_step, _fraction):
            calls["ckpt"] += 1

        result = self._harness(complete_text, noop)
        self.assertIsInstance(result, dict)
        self.assertGreater(calls["llm"], 0)
        self.assertGreater(calls["ckpt"], 0)


if __name__ == "__main__":
    unittest.main()
