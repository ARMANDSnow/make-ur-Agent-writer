"""iter 026: POST/PUT route coverage + method-mismatch handling."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_delete_workspace_happy_path_moves_to_trash(self) -> None:
        src = paths.WORKSPACE_DIR / "alpha"
        self.assertTrue(src.is_dir())
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/alpha/delete",
            json.dumps({"confirm": "alpha"}).encode(),
        )
        self.assertEqual(status, 200, body.decode())
        data = json.loads(body)
        self.assertIn("trashed_to", data)
        self.assertFalse(src.is_dir())
        trash_entries = list((paths.WORKSPACE_DIR / "_trash").iterdir())
        self.assertEqual(len(trash_entries), 1)
        self.assertTrue(trash_entries[0].name.startswith("alpha__"))

    def test_delete_workspace_requires_confirm_match(self) -> None:
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/alpha/delete",
            json.dumps({"confirm": "wrong"}).encode(),
        )
        self.assertEqual(status, 400)
        self.assertIn("confirm", json.loads(body)["error"])
        self.assertTrue((paths.WORKSPACE_DIR / "alpha").is_dir())

    def test_delete_workspace_unknown_404(self) -> None:
        status, _ct, _body = routes.dispatch(
            "POST",
            "/api/workspace/never-existed/delete",
            json.dumps({"confirm": "never-existed"}).encode(),
        )
        self.assertEqual(status, 404)

    def test_delete_workspace_rejects_invalid_name(self) -> None:
        status, _ct, _body = routes.dispatch(
            "POST",
            "/api/workspace/-bad-/delete",
            json.dumps({"confirm": "-bad-"}).encode(),
        )
        self.assertEqual(status, 400)

    def test_delete_workspace_rejects_running_job(self) -> None:
        with patch.object(jobs, "workspace_running_job", return_value="job123"):
            status, _ct, body = routes.dispatch(
                "POST",
                "/api/workspace/alpha/delete",
                json.dumps({"confirm": "alpha"}).encode(),
            )
        self.assertEqual(status, 409)
        data = json.loads(body)
        self.assertEqual(data["running_job_id"], "job123")
        self.assertTrue((paths.WORKSPACE_DIR / "alpha").is_dir())


if __name__ == "__main__":
    unittest.main()
