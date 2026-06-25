import tempfile
import unittest
from pathlib import Path

from src.entities import (
    PROMPT_ENTITY_STATE_LIMIT,
    load_entity_graph,
    render_active_state,
)


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


    def test_render_active_state_no_cap_is_byte_identical(self) -> None:
        """Default (max_chars=None) must be byte-identical to legacy render."""
        graph = {
            "entities": [
                {"id": "a", "name": "甲", "type": "character", "key_facts": ["事实甲"]},
            ],
            "relationships": [],
        }
        self.assertEqual(
            render_active_state(graph),
            render_active_state(graph, max_chars=None),
        )
        self.assertEqual(
            render_active_state(graph),
            render_active_state(graph, max_chars=PROMPT_ENTITY_STATE_LIMIT),
        )

    def test_render_active_state_caps_pathological_growth(self) -> None:
        """A graph far larger than the cap is truncated at a line boundary
        with a marker, instead of returning an unbounded string that would
        overflow the writer/reviewer prompt context (LLMContextOverflowError).
        """
        entities = [
            {
                "id": f"e{i}",
                "name": f"角色{i}",
                "type": "character",
                "key_facts": [f"这是角色{i}的一条比较长的关键事实用于把渲染撑大" for _ in range(4)],
                "description": f"角色{i}的当前状态描述也写得稍微长一点点占字数。",
            }
            for i in range(400)
        ]
        graph = {"entities": entities, "relationships": []}
        capped = render_active_state(graph, max_chars=2000)
        self.assertLessEqual(len(capped), 2000)
        self.assertIn("已按预算截断", capped)
        # 截断保留前部（实体起首）、丢弃尾部
        self.assertIn("角色0", capped)
        self.assertNotIn("角色399", capped)
        # 无 marker 的全量渲染应远超 cap（证明确实发生了截断）
        full = render_active_state(graph)
        self.assertGreater(len(full), 2000)

    def test_render_active_state_tiny_cap_still_respects_limit(self) -> None:
        graph = {
            "entities": [
                {"id": "a", "name": "甲", "type": "character", "key_facts": ["事实甲"]},
                {"id": "b", "name": "乙", "type": "character", "key_facts": ["事实乙"]},
            ],
            "relationships": [],
        }
        self.assertLessEqual(len(render_active_state(graph, max_chars=8)), 8)
        self.assertEqual(render_active_state(graph, max_chars=0), "")


if __name__ == "__main__":
    unittest.main()
