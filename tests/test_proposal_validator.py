"""Iter 024 P4: tests for src/proposal_validator.py.

Verifies hard-conflict detection (proposal would change pair to
敌对/已死/etc but next chapter plan expects active interaction).
Conservative default: when in doubt, mark SAFE (matches iter 023
behavior of always auto-applying).
"""

import unittest


class ProposalValidatorTests(unittest.TestCase):
    @staticmethod
    def _graph():
        return {
            "entities": [
                {"id": "a", "name": "路明非"},
                {"id": "b", "name": "楚子航"},
                {"id": "c", "name": "康斯坦丁"},
            ]
        }

    @staticmethod
    def _plan_with_next_chapter():
        return {
            "chapters": [
                {"chapter_no": 1, "relationships_in_play": []},
                {
                    "chapter_no": 2,
                    "relationships_in_play": [
                        "路明非 ↔ 楚子航：高架路并肩对话",
                        "路明非 ↔ 康斯坦丁：胸口梦境羁绊",
                    ],
                },
            ]
        }

    def test_no_hard_conflict_safe(self) -> None:
        """proposals without hard-conflict keywords → always SAFE."""
        from src.proposal_validator import validate_proposals_against_plan
        proposals = [
            {"src_id": "a", "dst_id": "b", "new_state": "变得熟悉", "confidence": 0.8},
            {"src_id": "a", "dst_id": "c", "new_state": "记忆更清晰", "confidence": 0.9},
        ]
        out = validate_proposals_against_plan(proposals, 1, self._plan_with_next_chapter(), self._graph())
        self.assertEqual(out, [])

    def test_hard_conflict_with_planned_interaction_blocks(self) -> None:
        """proposal sets 路明非↔楚子航 to '已背叛', but next chapter plan
        explicitly says they have active dialogue → CONFLICT."""
        from src.proposal_validator import validate_proposals_against_plan
        proposals = [
            {"src_id": "a", "dst_id": "b", "new_state": "已背叛，决裂", "confidence": 0.95},
        ]
        out = validate_proposals_against_plan(proposals, 1, self._plan_with_next_chapter(), self._graph())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["proposal_index"], 0)
        self.assertEqual(out[0]["src_name"], "路明非")
        self.assertEqual(out[0]["dst_name"], "楚子航")
        self.assertIn("背叛", " ".join(out[0]["markers"]))
        self.assertIn("路明非", out[0]["reason"])

    def test_no_next_chapter_default_safe(self) -> None:
        """When target_chapter_no+1 is past plan end → SAFE (no plan to compare)."""
        from src.proposal_validator import validate_proposals_against_plan
        proposals = [
            {"src_id": "a", "dst_id": "b", "new_state": "已死亡", "confidence": 0.9},
        ]
        # Plan has only ch1+ch2; target=5 means next=6 doesn't exist
        out = validate_proposals_against_plan(proposals, 5, self._plan_with_next_chapter(), self._graph())
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
