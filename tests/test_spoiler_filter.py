"""Iter 021: tests for spoiler filter on global_facts + entity_graph (A4).

Verifies that:
* ``manual_facts.global_facts_summary`` drops facts whose evidence_spans
  cite chapters strictly after the configured start point
* ``entities.render_active_state`` drops relationships whose active
  timeline entry has a chapter_id strictly after the start
* Both filters are no-ops when no start point is set
* Both have ``respect_start_point=False`` escape hatch
"""

import json
import os
import shutil
import unittest
from pathlib import Path


class SpoilerFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_ws_env = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter021spoiler"
        repo_root = Path(__file__).resolve().parent.parent
        self.ws_root = repo_root / "workspaces" / "iter021spoiler"
        (self.ws_root / "data" / "manual_overrides").mkdir(parents=True, exist_ok=True)
        (self.ws_root / "小说txt").mkdir(parents=True, exist_ok=True)

        # 3 dummy chapters
        sf = self.ws_root / "小说txt" / "spoiler.txt"
        sf.write_text("a\nb\nc\nd\ne\nf\n", encoding="utf-8")
        manifest = [
            {"chapter_id": "s_ch001", "volume_id": "s", "source_file": str(sf),
             "title": "1", "start_line": 1, "end_line": 2, "char_count": 4},
            {"chapter_id": "s_ch002", "volume_id": "s", "source_file": str(sf),
             "title": "2", "start_line": 3, "end_line": 4, "char_count": 4},
            {"chapter_id": "s_ch003", "volume_id": "s", "source_file": str(sf),
             "title": "3", "start_line": 5, "end_line": 6, "char_count": 4},
        ]
        (self.ws_root / "data" / "chapter_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )

        # 2 facts: one from ch001 (early), one from ch003 (late spoiler)
        facts = {
            "facts": [
                {
                    "fact_id": "early",
                    "statement": "early world rule",
                    "confidence": 1.0,
                    "scope": "global",
                    "evidence_spans": [
                        {"source_file": str(sf), "chapter_id": "s_ch001",
                         "start_line": 1, "end_line": 2, "quote": "", "note": ""}
                    ],
                    "applies_to": ["x"],
                },
                {
                    "fact_id": "late_spoiler",
                    "statement": "late reveal — DO NOT LEAK",
                    "confidence": 1.0,
                    "scope": "global",
                    "evidence_spans": [
                        {"source_file": str(sf), "chapter_id": "s_ch003",
                         "start_line": 5, "end_line": 6, "quote": "", "note": ""}
                    ],
                    "applies_to": ["y"],
                },
            ]
        }
        (self.ws_root / "data" / "manual_overrides" / "global_facts.json").write_text(
            json.dumps(facts, ensure_ascii=False), encoding="utf-8"
        )

    def tearDown(self) -> None:
        if self.ws_root.exists():
            shutil.rmtree(self.ws_root)
        if self._old_ws_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old_ws_env

    def test_facts_filter_drops_post_start_evidence(self) -> None:
        from src import start_point
        from src.manual_facts import global_facts_summary

        start_point.set_start_point("s_ch002")
        out = global_facts_summary(respect_start_point=True)
        self.assertIn("early", out)
        self.assertNotIn("late_spoiler", out)
        self.assertNotIn("DO NOT LEAK", out)
        # Escape hatch
        out_no_filter = global_facts_summary(respect_start_point=False)
        self.assertIn("late_spoiler", out_no_filter)

    def test_entity_relationship_filter_with_chapter_id(self) -> None:
        from src import start_point
        from src.entities import render_active_state

        start_point.set_start_point("s_ch001")
        # Synthesize a tiny graph with two relationships — one active in
        # s_ch001 (before-or-at start, kept), one in s_ch003 (spoiler)
        graph = {
            "entities": [
                {"id": "a", "name": "alpha", "type": "char"},
                {"id": "b", "name": "beta", "type": "char"},
                {"id": "c", "name": "gamma", "type": "char"},
            ],
            "relationships": [
                {
                    "src_id": "a", "dst_id": "b", "relation_type": "early",
                    "timeline": [{
                        "active": True, "state": "early bond",
                        "chapter_id": "s_ch001",
                    }],
                },
                {
                    "src_id": "a", "dst_id": "c", "relation_type": "late",
                    "timeline": [{
                        "active": True, "state": "future rivalry",
                        "chapter_id": "s_ch003",
                    }],
                },
            ],
        }
        out = render_active_state(graph, respect_start_point=True)
        self.assertIn("early bond", out)
        self.assertNotIn("future rivalry", out)
        # Escape hatch
        out_no_filter = render_active_state(graph, respect_start_point=False)
        self.assertIn("future rivalry", out_no_filter)


if __name__ == "__main__":
    unittest.main()
