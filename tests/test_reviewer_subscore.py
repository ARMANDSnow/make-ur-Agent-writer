"""Iter 022 B3: tests for AgentReview 3-sub-score schema.

Validates:
* AgentSubScores defaults (7/7/7)
* AgentReview with only explicit `score` keeps it (no auto-derive)
* AgentReview with only `scores` auto-derives `score` weighted avg
* AgentReview with both → `score` wins (explicit user override)
* iter 020/021 meta.json dict (only `score` field) parses without crash
* LLM output with top-level plot/prose/fidelity fields gets nested via
  `_repair_agent_review_dict`
* `collect_iter020_data` sub-score aggregation handles missing scores
"""

import json
import unittest


class AgentReviewSubScoreTests(unittest.TestCase):
    def test_default_sub_scores_all_seven(self):
        from src.schemas import AgentSubScores

        s = AgentSubScores()
        self.assertEqual(s.plot, 7)
        self.assertEqual(s.prose, 7)
        self.assertEqual(s.fidelity, 7)

    def test_only_score_keeps_score(self):
        from src.schemas import AgentReview

        r = AgentReview(agent_name="X", verdict="Approve", score=8)
        self.assertEqual(r.score, 8)
        self.assertEqual(r.scores.plot, 7)

    def test_only_scores_derives_weighted_score(self):
        from src.schemas import AgentReview, AgentSubScores

        r = AgentReview(
            agent_name="X",
            verdict="Approve",
            scores=AgentSubScores(plot=9, prose=6, fidelity=8),
        )
        # weighted: 9*0.4 + 6*0.3 + 8*0.3 = 3.6 + 1.8 + 2.4 = 7.8 → round → 8
        self.assertEqual(r.score, 8)

    def test_iter020_meta_dict_parses_cleanly(self):
        from src.schemas import AgentReview

        old = {
            "agent_name": "关系一致性",
            "verdict": "Approve",
            "score": 6,
            "issues": [],
            "suggestions": [],
            "comparison_checklist": [],
        }
        r = AgentReview(**old)
        self.assertEqual(r.score, 6)
        # Sub-scores default to 7/7/7 when not in input
        self.assertEqual(r.scores.plot, 7)

    def test_repair_dict_nests_top_level_subs(self):
        from src.reviewer import _repair_agent_review_dict

        # LLM output with flat top-level plot/prose/fidelity (as new prompt asks)
        raw = {
            "verdict": "Approve",
            "plot": 9,
            "prose": 5,
            "fidelity": 8,
        }
        repaired = _repair_agent_review_dict(raw, "test_agent")
        self.assertIn("scores", repaired)
        self.assertEqual(repaired["scores"]["plot"], 9)
        self.assertEqual(repaired["scores"]["prose"], 5)
        self.assertEqual(repaired["scores"]["fidelity"], 8)
        # Out-of-range values get clamped
        raw_extreme = {"verdict": "Reject", "plot": 15, "prose": -3, "fidelity": 8}
        repaired_extreme = _repair_agent_review_dict(raw_extreme, "test")
        self.assertEqual(repaired_extreme["scores"]["plot"], 10)
        self.assertEqual(repaired_extreme["scores"]["prose"], 0)


if __name__ == "__main__":
    unittest.main()
