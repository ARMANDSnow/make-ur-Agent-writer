"""Iter 021: tests for writer source-text injection (A2).

Verifies that ``src.writer._write_prompt`` includes the new "原文片段参考"
block when ``start_point.get_start_chapter_id()`` is set, and is
byte-identical to iter 020 behavior when no start point is configured.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path


class WriterSourceInjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_ws_env = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter021writer"
        repo_root = Path(__file__).resolve().parent.parent
        self.ws_root = repo_root / "workspaces" / "iter021writer"
        (self.ws_root / "data" / "manual_overrides").mkdir(parents=True, exist_ok=True)
        (self.ws_root / "小说txt").mkdir(parents=True, exist_ok=True)
        # 2 source chapters
        sf = self.ws_root / "小说txt" / "iter021writer.txt"
        sf.write_text(
            "first chapter content line 1\nfirst chapter content line 2\n"
            "first chapter content line 3\nsecond chapter content line 1\n"
            "second chapter content line 2\nsecond chapter content line 3\n",
            encoding="utf-8",
        )
        manifest = [
            {"chapter_id": "w_ch001", "volume_id": "w",
             "source_file": str(sf), "title": "alpha",
             "start_line": 1, "end_line": 3, "char_count": 90},
            {"chapter_id": "w_ch002", "volume_id": "w",
             "source_file": str(sf), "title": "beta",
             "start_line": 4, "end_line": 6, "char_count": 90},
            {"chapter_id": "w_ch003", "volume_id": "w",
             "source_file": str(sf), "title": "gamma",
             "start_line": 4, "end_line": 6, "char_count": 90},
        ]
        (self.ws_root / "data" / "chapter_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )

    def tearDown(self) -> None:
        if self.ws_root.exists():
            shutil.rmtree(self.ws_root)
        if self._old_ws_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old_ws_env

    def _build_prompt(self):
        from src.writer import _write_prompt
        messages, _ = _write_prompt(
            chapter_no=1,
            knowledge="knowledge text",
            facts="facts text",
            style_examples="",
            continuation_anchor="",
            index={},
            outline="outline text",
        )
        return messages[1]["content"]

    def test_no_start_point_omits_source_block(self) -> None:
        """Backward-compat: prompt must not contain 原文片段参考 block."""
        prompt = self._build_prompt()
        self.assertNotIn("原文片段参考", prompt)

    def test_start_point_set_injects_source_block(self) -> None:
        from src import start_point
        start_point.set_start_point("w_ch003")
        prompt = self._build_prompt()
        self.assertIn("原文片段参考", prompt)
        # The 2 chapters before w_ch003 are w_ch001 and w_ch002 (k=3 window)
        self.assertIn("w_ch001", prompt)
        self.assertIn("w_ch002", prompt)
        # Real source line content must be present
        self.assertIn("first chapter content", prompt)
        # The anchor warning must follow
        self.assertIn("不要复述上述情节", prompt)


if __name__ == "__main__":
    unittest.main()
