"""Iter 023 P5: tests for src/relationship_auditor.py.

Covers the deterministic (0-LLM) relationship-consistency check that
replaces the iter 022 关系一致性 LLM agent for structural conflicts.
"""

import unittest


class RelationshipAuditorTests(unittest.TestCase):
    def test_empty_inputs_return_empty(self) -> None:
        from src.relationship_auditor import audit_relationships
        self.assertEqual(audit_relationships("", {}), [])
        self.assertEqual(audit_relationships("a sentence here", {}), [])
        self.assertEqual(
            audit_relationships("a", {"entities": [], "relationships": []}), []
        )

    def test_hard_conflict_detected(self) -> None:
        """Draft co-occurs A and B; entity_graph says A-B is 已死亡 → issue."""
        from src.relationship_auditor import audit_relationships
        graph = {
            "entities": [
                {"id": "a", "name": "路明非"},
                {"id": "b", "name": "康斯坦丁"},
            ],
            "relationships": [
                {
                    "src_id": "a",
                    "dst_id": "b",
                    "timeline": [
                        {"active": True, "state": "康斯坦丁已死亡，只在梦境出现"}
                    ],
                }
            ],
        }
        draft = "路明非看见康斯坦丁站在面前。他几乎控制不住伸手抱住康斯坦丁。"
        issues = audit_relationships(draft, graph)
        self.assertEqual(len(issues), 1)
        self.assertIn("已死亡", issues[0]["graph_active_state"])
        self.assertIn("路明非", issues[0]["src_name"])
        self.assertIn("康斯坦丁", issues[0]["dst_name"])

    def test_soft_state_no_issue(self) -> None:
        """No hard-conflict keyword → no issue even though pair co-occurs."""
        from src.relationship_auditor import audit_relationships
        graph = {
            "entities": [
                {"id": "a", "name": "路明非"},
                {"id": "b", "name": "楚子航"},
            ],
            "relationships": [
                {
                    "src_id": "a",
                    "dst_id": "b",
                    "timeline": [{"active": True, "state": "从同学到队友"}],
                }
            ],
        }
        draft = "路明非和楚子航并肩作战。"
        self.assertEqual(audit_relationships(draft, graph), [])

    def test_multi_pair_dedup(self) -> None:
        """Same conflicting pair appearing in 5 sentences → 1 issue (dedup)."""
        from src.relationship_auditor import audit_relationships
        graph = {
            "entities": [
                {"id": "a", "name": "甲"},
                {"id": "b", "name": "乙"},
            ],
            "relationships": [
                {
                    "src_id": "a",
                    "dst_id": "b",
                    "timeline": [{"active": True, "state": "甲已背叛乙，决裂"}],
                }
            ],
        }
        # 5 sentences each mentioning both
        draft = "甲对乙说话。乙看着甲。甲笑了。乙也笑。甲转身走开。"
        # Note: above sentences each have 甲 and 乙 substrings
        issues = audit_relationships(draft, graph)
        self.assertEqual(len(issues), 1, f"Expected dedup to 1 issue, got {len(issues)}")


if __name__ == "__main__":
    unittest.main()
