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


class Iter078ScoreGuardTests(unittest.TestCase):
    """iter078 P1-1: NaN/Inf crash + string-score fail-open guards."""

    def test_coerce_score_matrix(self):
        from src.reviewer import _coerce_score

        self.assertEqual(_coerce_score(8), 8.0)
        self.assertEqual(_coerce_score(7.5), 7.5)
        self.assertEqual(_coerce_score("8"), 8.0)
        self.assertEqual(_coerce_score(" 7.5 "), 7.5)
        # clamp to 0-10
        self.assertEqual(_coerce_score(15), 10.0)
        self.assertEqual(_coerce_score(-3), 0.0)
        # rejected shapes → None
        self.assertIsNone(_coerce_score(True))
        self.assertIsNone(_coerce_score(False))
        self.assertIsNone(_coerce_score(float("nan")))
        self.assertIsNone(_coerce_score(float("inf")))
        self.assertIsNone(_coerce_score("nan"))
        self.assertIsNone(_coerce_score("high"))
        self.assertIsNone(_coerce_score("8/10"))
        self.assertIsNone(_coerce_score(None))
        self.assertIsNone(_coerce_score([8]))

    def test_repair_dict_nan_inf_subscores_do_not_crash(self):
        from src.reviewer import _repair_agent_review_dict

        # pre-iter078: isinstance(float) passed and int(nan) raised
        # ValueError / int(inf) raised OverflowError, crashing the review.
        for bad in (float("nan"), float("inf"), float("-inf")):
            raw = {"verdict": "Approve", "plot": bad, "prose": 7, "fidelity": 8}
            repaired = _repair_agent_review_dict(raw, "test_agent")
            scores = repaired.get("scores") or {}
            self.assertNotIn("plot", scores)
            self.assertEqual(scores.get("prose"), 7)
            self.assertEqual(scores.get("fidelity"), 8)

    def test_repair_dict_accepts_string_number_subscores(self):
        from src.reviewer import _repair_agent_review_dict

        # pre-iter078: string numbers were dropped and score defaulted to 7
        # (fail-open toward the neutral pass value).
        raw = {"verdict": "Approve", "plot": "9", "prose": "5", "fidelity": "8"}
        repaired = _repair_agent_review_dict(raw, "test_agent")
        self.assertEqual(repaired["scores"], {"plot": 9, "prose": 5, "fidelity": 8})

    def test_repair_dict_sanitizes_nested_scores(self):
        from src.reviewer import _repair_agent_review_dict

        raw = {
            "verdict": "Approve",
            "scores": {"plot": float("nan"), "prose": "6", "fidelity": 8},
        }
        repaired = _repair_agent_review_dict(raw, "test_agent")
        # NaN entry dropped (degrades to AgentSubScores default at model
        # construction), string number kept, int kept.
        self.assertEqual(repaired["scores"], {"prose": 6, "fidelity": 8})

    def test_weighted_score_never_returns_non_finite(self):
        import math

        from src.reviewer import _agent_weighted_score, _weighted_panel_score

        nan_review = {"verdict": "Approve", "scores": {"plot": float("nan"), "prose": 7, "fidelity": 7}, "score": 6}
        # NaN sub-score → whole group abandoned → falls back to score field
        self.assertEqual(_agent_weighted_score(nan_review), 6.0)
        # score itself NaN → 0.0 (fail-closed)
        self.assertEqual(_agent_weighted_score({"verdict": "Approve", "score": float("nan")}), 0.0)
        # bool score rejected (float(True) == 1.0 poisoning)
        self.assertEqual(_agent_weighted_score({"verdict": "Approve", "score": True}), 0.0)
        # string score accepted
        self.assertEqual(_agent_weighted_score({"verdict": "Approve", "score": "8"}), 8.0)
        panel = [nan_review, {"verdict": "Approve", "score": 8}]
        self.assertTrue(math.isfinite(_weighted_panel_score(panel)))
        self.assertEqual(_weighted_panel_score(panel), 7.0)


if __name__ == "__main__":
    unittest.main()
