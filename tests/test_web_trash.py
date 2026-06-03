"""iter 033: soft-delete unit tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src import paths
from src.web.trash import TRASH_DIR_NAME, soft_delete_workspace


class TrashTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = paths.WORKSPACE_DIR
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        (paths.WORKSPACE_DIR / "alpha" / "data").mkdir(parents=True)
        (paths.WORKSPACE_DIR / "alpha" / "marker.txt").write_text("hi", encoding="utf-8")

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved
        self._tmp.cleanup()

    def test_moves_directory_into_trash(self) -> None:
        ok, msg = soft_delete_workspace("alpha")
        self.assertTrue(ok)
        self.assertTrue(msg.startswith(TRASH_DIR_NAME + "/alpha__"))
        self.assertFalse((paths.WORKSPACE_DIR / "alpha").exists())
        moved = paths.WORKSPACE_DIR / msg
        self.assertTrue((moved / "marker.txt").exists())

    def test_missing_workspace_reports_failure(self) -> None:
        ok, msg = soft_delete_workspace("nope")
        self.assertFalse(ok)
        self.assertEqual(msg, "workspace_not_found")

    def test_same_second_collision_appends_counter(self) -> None:
        ok1, msg1 = soft_delete_workspace("alpha")
        (paths.WORKSPACE_DIR / "alpha").mkdir()
        ok2, msg2 = soft_delete_workspace("alpha")
        self.assertTrue(ok1 and ok2)
        self.assertNotEqual(msg1, msg2)


if __name__ == "__main__":
    unittest.main()
