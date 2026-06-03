"""iter 033: soft-delete unit tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src import paths
from src.web.trash import (
    TRASH_DIR_NAME,
    _safe_entry_path,
    list_trash_entries,
    purge_trash_entry,
    restore_trash_entry,
    soft_delete_workspace,
)


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

    def test_list_trash_entries_after_soft_delete(self) -> None:
        soft_delete_workspace("alpha")
        entries = list_trash_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["original_name"], "alpha")
        self.assertGreaterEqual(entries[0]["file_count"], 1)

    def test_restore_renames_back(self) -> None:
        ok, msg = soft_delete_workspace("alpha")
        self.assertTrue(ok)
        entry = msg.split("/")[-1]
        ok, restored = restore_trash_entry(entry)
        self.assertTrue(ok)
        self.assertEqual(restored, "alpha")
        self.assertTrue((paths.WORKSPACE_DIR / "alpha" / "marker.txt").exists())

    def test_restore_name_collision(self) -> None:
        ok, msg = soft_delete_workspace("alpha")
        self.assertTrue(ok)
        entry = msg.split("/")[-1]
        (paths.WORKSPACE_DIR / "alpha").mkdir()
        ok, msg = restore_trash_entry(entry)
        self.assertFalse(ok)
        self.assertEqual(msg, "name_collision")

    def test_purge_removes_from_disk(self) -> None:
        ok, msg = soft_delete_workspace("alpha")
        self.assertTrue(ok)
        entry = msg.split("/")[-1]
        ok, _ = purge_trash_entry(entry)
        self.assertTrue(ok)
        self.assertFalse((paths.WORKSPACE_DIR / "_trash" / entry).exists())

    def test_restore_preserves_workspace_names_with_double_underscore(self) -> None:
        (paths.WORKSPACE_DIR / "foo__bar" / "data").mkdir(parents=True)
        (paths.WORKSPACE_DIR / "foo__bar" / "marker.txt").write_text("ok", encoding="utf-8")
        ok, msg = soft_delete_workspace("foo__bar")
        self.assertTrue(ok)
        entry = msg.split("/")[-1]
        self.assertEqual(list_trash_entries()[0]["original_name"], "foo__bar")
        ok, restored = restore_trash_entry(entry)
        self.assertTrue(ok)
        self.assertEqual(restored, "foo__bar")
        self.assertTrue((paths.WORKSPACE_DIR / "foo__bar" / "marker.txt").exists())

    def test_safe_entry_path_rejects_path_traversal(self) -> None:
        for bad in (
            "../alpha",
            "../../etc",
            "alpha/../beta",
            "a\\b__20260101_120000",
            "alpha__20260101_120000\n",
            "alpha__20260101_120000\r",
        ):
            ok, reason = _safe_entry_path(bad)
            self.assertFalse(ok, f"{bad!r} should be rejected")
            self.assertEqual(reason, "malformed_entry")

    def test_safe_entry_path_rejects_reserved_names(self) -> None:
        for bad in ("legacy__20260101_120000", "_trash__20260603_000000"):
            ok, reason = _safe_entry_path(bad)
            self.assertFalse(ok, f"{bad!r} should be rejected")
            self.assertEqual(reason, "reserved_name")

    def test_safe_entry_path_accepts_well_formed(self) -> None:
        for good in ("alpha__20260101_120000", "alpha__20260101_120000_2", "龙族__20260101_120000"):
            ok, reason = _safe_entry_path(good)
            self.assertTrue(ok, f"{good!r} should be accepted; got {reason}")

    def test_safe_entry_path_rejects_empty_string(self) -> None:
        ok, reason = _safe_entry_path("")
        self.assertFalse(ok)
        self.assertEqual(reason, "malformed_entry")

    def test_safe_entry_path_rejects_null_byte(self) -> None:
        ok, reason = _safe_entry_path("alpha\x00__20260101_120000")
        self.assertFalse(ok)
        self.assertEqual(reason, "malformed_entry")

    def test_safe_entry_path_rejects_too_long(self) -> None:
        ok, reason = _safe_entry_path("a" * 200 + "__20260101_120000")
        self.assertFalse(ok)
        self.assertEqual(reason, "malformed_entry")

    def test_safe_entry_path_accepts_unicode_nfc(self) -> None:
        ok, reason = _safe_entry_path("龙族__20260101_120000")
        self.assertTrue(ok, f"reason: {reason}")


if __name__ == "__main__":
    unittest.main()
