"""Iter 021: tests for src/start_point.py.

Covers:
* get_start_chapter_id round-trip with set/clear
* is_after_start strict ordering (start itself returns False)
* chapters_before_start window math
* load_chapter_text reads source_file by line range
* set_start_point accepts both chapter_id and volume_id
* unknown name → ValueError
* All functions degrade gracefully when no start set
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class StartPointTests(unittest.TestCase):
    def setUp(self) -> None:
        # Build a self-contained workspace under a tempdir so we can mutate
        # start_chapter.json + chapter_manifest without polluting any real
        # book workspace.
        self.tmpdir = tempfile.mkdtemp(prefix="iter021_start_point_")
        self._old_ws_env = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter021test"
        # Build workspace tree: workspaces/iter021test/data/...
        repo_root = Path(__file__).resolve().parent.parent
        self.ws_root = repo_root / "workspaces" / "iter021test"
        (self.ws_root / "data" / "manual_overrides").mkdir(parents=True, exist_ok=True)
        (self.ws_root / "小说txt").mkdir(parents=True, exist_ok=True)

        # Synthesise 5 chapters across 2 volumes
        source_path = self.ws_root / "小说txt" / "iter021test_v1.txt"
        source_path.write_text(
            "\n".join(f"line {i}" for i in range(1, 31)) + "\n", encoding="utf-8"
        )
        source_v2 = self.ws_root / "小说txt" / "iter021test_v2.txt"
        source_v2.write_text(
            "\n".join(f"v2 line {i}" for i in range(1, 21)) + "\n", encoding="utf-8"
        )

        manifest = [
            {"chapter_id": "v1_ch001", "volume_id": "v1",
             "source_file": str(source_path), "title": "first",
             "start_line": 1, "end_line": 5, "char_count": 30},
            {"chapter_id": "v1_ch002", "volume_id": "v1",
             "source_file": str(source_path), "title": "second",
             "start_line": 6, "end_line": 10, "char_count": 30},
            {"chapter_id": "v1_ch003", "volume_id": "v1",
             "source_file": str(source_path), "title": "third",
             "start_line": 11, "end_line": 15, "char_count": 30},
            {"chapter_id": "v2_ch001", "volume_id": "v2",
             "source_file": str(source_v2), "title": "v2-first",
             "start_line": 1, "end_line": 5, "char_count": 30},
            {"chapter_id": "v2_ch002", "volume_id": "v2",
             "source_file": str(source_v2), "title": "v2-second",
             "start_line": 6, "end_line": 10, "char_count": 30},
        ]
        (self.ws_root / "data" / "chapter_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )

        from src import start_point
        self.start_point = start_point

    def tearDown(self) -> None:
        # Remove temp workspace tree
        if self.ws_root.exists():
            shutil.rmtree(self.ws_root)
        if self._old_ws_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old_ws_env
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_default_no_start_returns_none(self) -> None:
        self.assertIsNone(self.start_point.get_start_chapter_id())
        self.assertFalse(self.start_point.is_after_start("v1_ch003"))
        self.assertEqual(self.start_point.chapters_before_start(3), [])

    def test_set_chapter_id_round_trip(self) -> None:
        self.start_point.set_start_point("v1_ch003")
        self.assertEqual(self.start_point.get_start_chapter_id(), "v1_ch003")

    def test_set_volume_id_resolves_to_last_chapter(self) -> None:
        self.start_point.set_start_point("v1")
        # Should resolve to v1_ch003 (last chapter of v1)
        self.assertEqual(self.start_point.get_start_chapter_id(), "v1_ch003")

    def test_unknown_name_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.start_point.set_start_point("bogus_id")

    def test_is_after_start_is_strict(self) -> None:
        self.start_point.set_start_point("v1_ch003")
        # Start itself is NOT after start
        self.assertFalse(self.start_point.is_after_start("v1_ch003"))
        # Before start
        self.assertFalse(self.start_point.is_after_start("v1_ch001"))
        # After start
        self.assertTrue(self.start_point.is_after_start("v2_ch001"))
        # Unknown chapter id → False
        self.assertFalse(self.start_point.is_after_start("nonexistent"))

    def test_chapters_before_start_and_load_text(self) -> None:
        self.start_point.set_start_point("v2_ch001")
        before = self.start_point.chapters_before_start(3)
        self.assertEqual([c["chapter_id"] for c in before],
                         ["v1_ch001", "v1_ch002", "v1_ch003"])
        # load_chapter_text reads source_file by line range
        body = self.start_point.load_chapter_text("v1_ch001")
        # 5 lines from "line 1" to "line 5"
        self.assertIn("line 1\n", body)
        self.assertIn("line 5\n", body)
        # Line 6 (next chapter) should NOT appear
        self.assertNotIn("line 6\n", body)

    def test_clear_restores_default(self) -> None:
        self.start_point.set_start_point("v1_ch003")
        self.assertIsNotNone(self.start_point.get_start_chapter_id())
        self.start_point.clear_start_point()
        self.assertIsNone(self.start_point.get_start_chapter_id())
        # idempotent — second clear doesn't raise
        self.start_point.clear_start_point()


if __name__ == "__main__":
    unittest.main()
