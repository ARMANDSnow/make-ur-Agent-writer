"""iter 026: POST/PUT route coverage + method-mismatch handling."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.web import jobs, routes


def _stub_workspace(root: Path, name: str) -> None:
    ws = root / name
    for sub in ("小说txt", "data", "outputs", "logs"):
        (ws / sub).mkdir(parents=True)


class RoutesPostTests(unittest.TestCase):
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

    def test_post_run_happy_returns_202_and_job_id(self) -> None:
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/alpha/run",
            json.dumps({"step": "normalize"}).encode(),
        )
        self.assertEqual(status, 202)
        data = json.loads(body)
        self.assertIn("job_id", data)
        self.assertEqual(len(data["job_id"]), 32)

    def test_post_run_invalid_workspace_400(self) -> None:
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/-illegal-/run",
            json.dumps({"step": "normalize"}).encode(),
        )
        self.assertEqual(status, 400)

    def test_post_run_unknown_workspace_404(self) -> None:
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/no_such_ws/run",
            json.dumps({"step": "normalize"}).encode(),
        )
        self.assertEqual(status, 404)

    def test_put_on_get_route_returns_405(self) -> None:
        status, _ct, body = routes.dispatch("PUT", "/api/workspaces")
        self.assertEqual(status, 405)
        self.assertIn("method PUT not allowed", json.loads(body)["error"])

    def test_post_on_get_only_route_returns_405(self) -> None:
        status, _ct, body = routes.dispatch("POST", "/api/workspace/alpha/status")
        self.assertEqual(status, 405)


if __name__ == "__main__":
    unittest.main()
