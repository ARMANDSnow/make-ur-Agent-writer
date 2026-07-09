"""iter 082: drama reviewer tests."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src import character_designer, drama_reviewer, storyboard_builder
from src.drama_schemas import (
    DramaReview,
    DramaSubScores,
    derive_verdict,
    episode_paths,
    character_paths,
)
from tests._drama_base import DramaTestBase


TRACKS = ("霸总", "重生", "推理", "系统", "觉醒")


class DramaReviewerTests(DramaTestBase):
    def _workspace(self, name: str, track: str = "霸总") -> None:
        self._make_drama_workspace(name, track)
        self._write_setup(name, hook=True)
        board = storyboard_builder.run(name, mock=True)
        ep = episode_paths(name)
        ep.storyboard_path.parent.mkdir(parents=True, exist_ok=True)
        ep.storyboard_path.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
        sheet = character_designer.run(name, mock=True)
        cp = character_paths(name)
        cp.sheet_path.parent.mkdir(parents=True, exist_ok=True)
        cp.sheet_path.write_text(json.dumps(sheet, ensure_ascii=False), encoding="utf-8")

    def test_mock_returns_valid_approve_review_per_track(self) -> None:
        for idx, track in enumerate(TRACKS):
            with self.subTest(track=track):
                name = f"review{idx}"
                self._workspace(name, track)
                result = drama_reviewer.run(name, mock=True)
                review = DramaReview(**result)
                self.assertEqual(review.verdict, "Approve")
                self.assertFalse(review.needs_human_review)
                self.assertGreaterEqual(review.score, 7)

    def test_requires_character_sheet(self) -> None:
        self._make_drama_workspace("missing_chars", "霸总")
        self._write_setup("missing_chars", hook=True)
        board = storyboard_builder.run("missing_chars", mock=True)
        p = episode_paths("missing_chars").storyboard_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(FileNotFoundError, "station 4"):
            drama_reviewer.run("missing_chars", mock=True)

    def test_real_path_uses_drama_review_task(self) -> None:
        self._workspace("real_review", "霸总")
        captured = {}
        expected = DramaReview(
            episode_no=1,
            season_no=1,
            sub_scores={"hook": 8, "pace": 8, "ai_friendly": 8, "character_consistency": 8, "cliffhanger": 8},
        )

        class FakeClient:
            is_mock = False

            def __init__(self, task: str) -> None:
                captured["task"] = task

            def complete_json(self, messages, response_model):
                captured["messages"] = messages
                captured["response_model"] = response_model
                return expected

        with patch.object(drama_reviewer, "LLMClient", FakeClient):
            result = drama_reviewer.run("real_review", mock=False)

        self.assertEqual(captured["task"], "drama_review")
        self.assertIs(captured["response_model"], DramaReview)
        self.assertIn("短剧整集评审", captured["messages"][0]["content"])
        self.assertEqual(result["verdict"], "Approve")

    def test_real_path_parse_failure_returns_abstain(self) -> None:
        self._workspace("parse_failed_review", "霸总")

        class RaisingClient:
            is_mock = False

            def __init__(self, task: str) -> None:
                self.task = task

            def complete_json(self, messages, response_model):
                raise ValueError("bad model json")

        with patch.object(drama_reviewer, "LLMClient", RaisingClient):
            result = drama_reviewer.run("parse_failed_review", mock=False)

        self.assertEqual(result["verdict"], "Abstain")
        self.assertTrue(result["needs_human_review"])
        self.assertTrue(result["parse_failed"])

    def test_derive_verdict_three_branches(self) -> None:
        self.assertEqual(
            derive_verdict({"hook": 4, "pace": 8, "ai_friendly": 8, "character_consistency": 8, "cliffhanger": 8}),
            "Reject",
        )
        self.assertEqual(
            derive_verdict({"hook": 7, "pace": 7, "ai_friendly": 7, "character_consistency": 7, "cliffhanger": 7}),
            "Approve",
        )
        self.assertEqual(
            derive_verdict({"hook": 6, "pace": 7, "ai_friendly": 7, "character_consistency": 7, "cliffhanger": 7}),
            "Abstain",
        )

    def test_score_guards_reject_bool_nonfinite_and_clamp(self) -> None:
        scores = DramaSubScores(
            hook="8",
            pace=True,
            ai_friendly="NaN",
            character_consistency=15,
            cliffhanger=-3,
        )
        self.assertEqual(scores.hook, 8)
        self.assertEqual(scores.pace, 0)
        self.assertEqual(scores.ai_friendly, 0)
        self.assertEqual(scores.character_consistency, 10)
        self.assertEqual(scores.cliffhanger, 0)
        self.assertIn("pace:invalid_bool", scores.score_warnings)
        self.assertIn("ai_friendly:invalid_nonfinite", scores.score_warnings)
        self.assertIn("character_consistency:clamped_high", scores.score_warnings)
        self.assertIn("cliffhanger:clamped_low", scores.score_warnings)

    def test_parse_failed_review_is_abstain(self) -> None:
        result = drama_reviewer.parse_failed_review()
        self.assertEqual(result["verdict"], "Abstain")
        self.assertTrue(result["needs_human_review"])
        self.assertTrue(result["parse_failed"])


if __name__ == "__main__":
    unittest.main()
