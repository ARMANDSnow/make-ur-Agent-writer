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

    def test_render_active_state_includes_tag_reverse_index_for_shared_tags(self) -> None:
        graph = {
            "entities": [
                {"id": "a", "name": "A", "type": "character", "tags": ["#X", "#soloA"]},
                {"id": "b", "name": "B", "type": "character", "tags": ["#X"]},
                {"id": "c", "name": "C", "type": "character", "tags": ["#soloC"]},
            ],
            "relationships": [],
        }
        text = render_active_state(graph)
        self.assertIn("tag 反向索引", text)
        self.assertIn("#X -> A / B", text)
        self.assertNotIn("#soloA ->", text)
        self.assertNotIn("#soloC ->", text)

    def test_render_active_state_includes_description_when_present(self) -> None:
        graph = {
            "entities": [
                {
                    "id": "a",
                    "name": "A",
                    "type": "character",
                    "tags": ["#X"],
                    "key_facts": ["事实A"],
                    "description": "这是一段用户自己的当前状态描述。",
                }
            ],
            "relationships": [],
        }
        text = render_active_state(graph)
        self.assertIn("tags: #X", text)
        self.assertIn("这是一段用户自己的当前状态描述。", text)


if __name__ == "__main__":
    unittest.main()
