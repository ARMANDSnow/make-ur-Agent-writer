"""iter 036: workspace type metadata."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src import paths
from src.cli_workspace import init_workspace
from src.web import workspace_meta


class WorkspaceMetaTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        paths.WORKSPACE_DIR = Path(self._tmp.name)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        self._tmp.cleanup()

    def test_write_read_drama_round_trip(self) -> None:
        workspace_meta.write("drama_one", type="drama", created_at="2026-06-03T00:00:00+00:00")
        meta = workspace_meta.read("drama_one")
        self.assertEqual(meta["type"], "drama")
        self.assertEqual(meta["created_at"], "2026-06-03T00:00:00+00:00")
        self.assertEqual(meta["schema_version"], 1)

    def test_missing_workspace_json_defaults_to_legacy_novel(self) -> None:
        (paths.WORKSPACE_DIR / "old" / "data").mkdir(parents=True)
        meta = workspace_meta.read("old")
        self.assertEqual(meta, {"type": "novel", "created_at": None, "schema_version": 0})

    def test_non_dict_workspace_json_defaults_to_novel(self) -> None:
        path = paths.WORKSPACE_DIR / "bad" / "data" / "workspace.json"
        path.parent.mkdir(parents=True)
        path.write_text('"not an object"', encoding="utf-8")
        meta = workspace_meta.read("bad")
        self.assertEqual(meta["type"], "novel")
        self.assertEqual(meta["schema_version"], 0)

    def test_unknown_workspace_type_is_treated_as_novel(self) -> None:
        path = paths.WORKSPACE_DIR / "unknown" / "data" / "workspace.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"type":"unknown","schema_version":1}', encoding="utf-8")
        meta = workspace_meta.read("unknown")
        self.assertEqual(meta["type"], "novel")
        self.assertEqual(meta["schema_version"], 1)

    def test_init_workspace_drama_creates_empty_skeleton(self) -> None:
        result = init_workspace("drama_box", type="drama")
        self.assertEqual(result["type"], "drama")
        self.assertEqual(workspace_meta.read("drama_box")["type"], "drama")
        for rel in (
            "小说txt",
            "data",
            "outputs",
            "logs",
            "data/tables",
            "outputs/debate",
            "outputs/episodes",
            "outputs/reviews",
        ):
            self.assertTrue((paths.WORKSPACE_DIR / "drama_box" / rel).is_dir(), rel)

    def test_init_workspace_duplicate_raises(self) -> None:
        init_workspace("dup", type="drama")
        with self.assertRaises(FileExistsError):
            init_workspace("dup", type="drama")

    def test_init_workspace_defaults_to_novel_type(self) -> None:
        init_workspace("novel_box")
        self.assertEqual(workspace_meta.read("novel_box")["type"], "novel")


if __name__ == "__main__":
    unittest.main()
