import json
import os
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.web import routes, workspace_meta


def _stub_workspace(root: Path, name: str) -> Path:
    ws = root / name
    for sub in ("小说txt", "data", "outputs/episodes", "outputs/drafts", "outputs/reviews", "logs"):
        (ws / sub).mkdir(parents=True)
    return ws


class WorkspaceOverviewDramaTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def test_drama_overview_returns_drama_progress(self) -> None:
        ws = _stub_workspace(paths.WORKSPACE_DIR, "drama")
        workspace_meta.write("drama", type="drama", created_at="2026-06-05T00:00:00+08:00")
        (ws / "outputs" / "episodes" / "episode_01.setup.json").write_text(
            json.dumps(
                {
                    "core_setup": {"protagonist": "主角"},
                    "hook": {"type": "反差钩", "content": "示例"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        status, ct, body = routes.dispatch("GET", "/api/workspaces/overview")
        self.assertEqual(status, 200)
        self.assertIn("json", ct)
        data = json.loads(body.decode("utf-8"))
        item = data["workspaces"][0]

        self.assertEqual(item["type"], "drama")
        self.assertIn("drama_progress", item)
        self.assertEqual(item["drama_progress"]["station1"]["status"], "done")
        self.assertEqual(item["drama_progress"]["station2"]["status"], "done")
        self.assertEqual(item["drama_progress"]["station3"]["status"], "locked")
        self.assertEqual(item["readiness"]["blockers"], [])
        self.assertNotIn("start_point_missing", item["readiness"]["blockers"])


if __name__ == "__main__":
    unittest.main()
