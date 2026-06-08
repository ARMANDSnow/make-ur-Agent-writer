"""iter 047b: tests for the start-safe KB view.

A workspace with a 3-chapter manifest + a knowledge_index.json whose entries
carry chapter_id (s_ch001 early / s_ch003 late). With a start point at s_ch002:
* entries from chapters AFTER the start are dropped (spoiler-safe),
* entries at/before the start are kept,
* entries with no chapter_id are kept (fail-open).
With no start point / no index / respect_start_point=False, the raw prose KB is
returned verbatim (byte-identical to pre-047b).
"""

import json
import os
import shutil
import unittest
from pathlib import Path

RAW_KB = "RAW PROSE KB 全书压缩知识，含 LATE_RULE_SPOILER 等起点之后的内容。\n"


class StartSafeKnowledgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_ws_env = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter047bkb"
        repo_root = Path(__file__).resolve().parent.parent
        self.ws_root = repo_root / "workspaces" / "iter047bkb"
        (self.ws_root / "data" / "manual_overrides").mkdir(parents=True, exist_ok=True)
        (self.ws_root / "data" / "knowledge_base").mkdir(parents=True, exist_ok=True)

        manifest = [
            {"chapter_id": "s_ch001", "volume_id": "s", "title": "1"},
            {"chapter_id": "s_ch002", "volume_id": "s", "title": "2"},
            {"chapter_id": "s_ch003", "volume_id": "s", "title": "3"},
        ]
        (self.ws_root / "data" / "chapter_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )

        self.kb_path = self.ws_root / "data" / "knowledge_base" / "global_knowledge.md"
        self.kb_path.write_text(RAW_KB, encoding="utf-8")

        self.index_path = self.ws_root / "data" / "knowledge_base" / "knowledge_index.json"
        index = {
            "characters": {
                "甲": [
                    {"chapter_id": "s_ch001", "character": "甲", "after": "EARLY_CHAR_STATE"},
                    {"chapter_id": "s_ch003", "character": "甲", "after": "LATE_CHAR_SPOILER"},
                ]
            },
            "relationships": [
                {"chapter_id": "s_ch001", "characters": ["甲", "乙"], "after": "EARLY_BOND"},
                {"chapter_id": "s_ch003", "characters": ["甲", "丙"], "after": "LATE_RIVALRY_SPOILER"},
            ],
            "foreshadowing": [
                {"chapter_id": "s_ch001", "kind": "clue", "status": "open", "description": "EARLY_CLUE"},
                {"chapter_id": "s_ch003", "kind": "payoff", "status": "resolved", "description": "LATE_PAYOFF_SPOILER"},
                {"kind": "clue", "status": "open", "description": "NO_CHAPTER_CLUE"},
            ],
            "worldbuilding": [
                {"chapter_id": "s_ch001", "topic": "规则一", "detail": "EARLY_RULE"},
                {"chapter_id": "s_ch003", "topic": "规则二", "detail": "LATE_RULE_SPOILER"},
            ],
            "style_samples": [],
            "chapters": {},
            "manual_global_facts": [],
        }
        self.index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        if self.ws_root.exists():
            shutil.rmtree(self.ws_root)
        if self._old_ws_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old_ws_env

    def test_no_start_point_returns_raw_kb_verbatim(self) -> None:
        from src.kb_view import start_safe_knowledge

        self.assertEqual(start_safe_knowledge(), RAW_KB)

    def test_no_index_returns_raw_kb(self) -> None:
        from src import start_point
        from src.kb_view import start_safe_knowledge

        start_point.set_start_point("s_ch002")
        self.index_path.unlink()
        self.assertEqual(start_safe_knowledge(), RAW_KB)

    def test_respect_start_point_false_returns_raw_kb(self) -> None:
        from src import start_point
        from src.kb_view import start_safe_knowledge

        start_point.set_start_point("s_ch002")
        self.assertEqual(start_safe_knowledge(respect_start_point=False), RAW_KB)

    def test_filters_entries_after_start(self) -> None:
        from src import start_point
        from src.kb_view import start_safe_knowledge

        start_point.set_start_point("s_ch002")
        out = start_safe_knowledge()
        # start-safe structured block, not the raw prose KB
        self.assertIn("起点安全", out)
        self.assertNotIn("RAW PROSE KB", out)
        # entries at/before the start are kept
        for kept in ("EARLY_CHAR_STATE", "EARLY_BOND", "EARLY_CLUE", "EARLY_RULE"):
            self.assertIn(kept, out)
        # entries strictly after the start are dropped
        for spoiler in (
            "LATE_CHAR_SPOILER",
            "LATE_RIVALRY_SPOILER",
            "LATE_PAYOFF_SPOILER",
            "LATE_RULE_SPOILER",
        ):
            self.assertNotIn(spoiler, out)

    def test_entry_without_chapter_id_is_kept(self) -> None:
        from src import start_point
        from src.kb_view import start_safe_knowledge

        start_point.set_start_point("s_ch002")
        out = start_safe_knowledge()
        self.assertIn("NO_CHAPTER_CLUE", out)  # fail-open

    def test_injected_kb_path_overrides_default(self) -> None:
        # The KB source is an injected seam: callers pass their own kb_path so
        # test patches stay effective and we never read the real repo data.
        from src.kb_view import start_safe_knowledge

        alt = self.ws_root / "alt_kb.md"
        alt.write_text("ALT_KB_CONTENT", encoding="utf-8")
        # no start point here -> raw KB of the INJECTED path (not the default)
        out = start_safe_knowledge(kb_path=alt, index_path=self.ws_root / "nope.json")
        self.assertEqual(out, "ALT_KB_CONTENT")
        self.assertEqual(start_safe_knowledge(), RAW_KB)  # default still reads ws KB

    def test_book_runner_external_review_context_is_start_safe(self) -> None:
        # iter 047b H1: the external-review chain must also get start-safe KB.
        from src import start_point
        from src.book_runner import _build_review_context

        start_point.set_start_point("s_ch002")
        kb = _build_review_context(None).get("knowledge", "")
        self.assertIn("起点安全", kb)
        self.assertIn("EARLY_BOND", kb)
        for spoiler in (
            "LATE_CHAR_SPOILER",
            "LATE_RIVALRY_SPOILER",
            "LATE_PAYOFF_SPOILER",
            "LATE_RULE_SPOILER",
            "RAW PROSE KB",
        ):
            self.assertNotIn(spoiler, kb)


if __name__ == "__main__":
    unittest.main()
