import tempfile
import unittest
from pathlib import Path

from src.entities import load_entity_graph, render_active_state


class EntityGraphTests(unittest.TestCase):
    def test_load_entity_graph_returns_empty_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_entity_graph(Path(tmp)), {})

    def test_render_active_state_only_includes_active_timeline_entries(self) -> None:
        graph = {
            "entities": [
                {"id": "a", "name": "甲", "type": "character", "aliases": ["别名甲"], "key_facts": ["事实甲"]},
                {"id": "b", "name": "乙", "type": "character", "key_facts": ["事实乙"]},
            ],
            "relationships": [
                {
                    "src_id": "a",
                    "dst_id": "b",
                    "relation_type": "同盟",
                    "timeline": [
                        {"anchor_chapter": "early", "state": "过去状态不应出现", "active": False},
                        {"anchor_chapter": "now", "state": "当前必须互相信任", "active": True},
                    ],
                }
            ],
        }
        text = render_active_state(graph)
        self.assertIn("当前续写起点的实体关系状态", text)
        self.assertIn("甲", text)
        self.assertIn("乙", text)
        self.assertIn("当前必须互相信任", text)
        self.assertNotIn("过去状态不应出现", text)


if __name__ == "__main__":
    unittest.main()
