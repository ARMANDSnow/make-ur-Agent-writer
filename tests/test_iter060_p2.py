"""iter060 P2 收官 (docs/FRONTEND_BUG_AUDIT_2026-06.md §4 iter 060):

  #7  起点保存无 workspace reservation —— reserved 时 PUT /start-point 仍穿过，
      绕过 409 互斥。
  #11 writer-style 样本固定临时文件 + 写在抢锁前 —— 并发 extract 互相覆盖样本。
  #14 drama 写端点非原子 + 无 reservation。
  #12 cancel/timeout 仅在 progress checkpoint 检查 —— 长 step 内不可中断。

Mock-only; no network, no real workspace data. 每个 fix 一个 TestCase。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

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
        self.addCleanup(jobs.reset_for_tests)
        self.addCleanup(self._restore_env)
        for sub in ("小说txt", "data", "outputs/drafts", "outputs/episodes", "logs"):
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


if __name__ == "__main__":
    unittest.main()
