"""iter 080: short-drama fixture lint."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.drama_schemas import CharacterSheet, DramaReview, DramaStoryboard, StoryboardShot


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "drama"
TRACKS = ("bazhong", "chongsheng", "tuili", "xitong", "juexing")
DRAGON_RAJA_TERMS = ("龙族", "路明非", "楚子航", "凯撒", "诺诺", "卡塞尔", "江南")
SUBJECTIVE_PROMPT_TERMS = ("漂亮", "帅气", "高级感", "好看")


class DramaFixtureLintTests(unittest.TestCase):
    def _load(self, track: str) -> dict:
        return json.loads((FIXTURE_DIR / f"track_{track}_storyboard.json").read_text(encoding="utf-8"))

    def test_storyboard_fixtures_match_machine_rules(self) -> None:
        for track in TRACKS:
            with self.subTest(track=track):
                data = self._load(track)
                board = DramaStoryboard(**{k: v for k, v in data.items() if k != "alt_shots"})
                self.assertGreaterEqual(len(board.shots), 6)
                self.assertLessEqual(len(board.shots), 9)
                self.assertEqual(sum(s.duration_seconds for s in board.shots), 60)
                self.assertIn(board.shots[0].duration_seconds, (2, 3))
                self.assertIn(board.shots[0].shot_size, ("特写", "近景"))
                self.assertEqual(sum(1 for s in board.shots if s.is_highlight), 1)
                self.assertGreaterEqual(board.shots[-1].duration_seconds, 8)
                self.assertLessEqual(board.shots[-1].duration_seconds, 10)
                for shot in board.shots:
                    lines = [
                        p.strip()
                        for p in shot.dialogue.replace("；", "。").replace("！", "。").replace("？", "。").split("。")
                    ]
                    self.assertTrue(all(len(line) <= 15 for line in lines if line), shot.dialogue)

    def test_storyboard_fixtures_do_not_contain_forbidden_source_terms(self) -> None:
        combined = "\n".join(
            (FIXTURE_DIR / f"track_{track}_storyboard.json").read_text(encoding="utf-8")
            for track in TRACKS
        )
        for term in DRAGON_RAJA_TERMS:
            self.assertNotIn(term, combined)

    def test_ai_draw_prompts_avoid_subjective_shortcuts(self) -> None:
        for track in TRACKS:
            data = self._load(track)
            for raw in data["shots"]:
                prompt = raw.get("ai_draw_prompt", "")
                for term in SUBJECTIVE_PROMPT_TERMS:
                    self.assertNotIn(term, prompt)

    def test_alt_shots_are_valid_single_shot_payloads(self) -> None:
        for track in TRACKS:
            data = self._load(track)
            alt = data.get("alt_shots")
            self.assertIsInstance(alt, list)
            self.assertGreaterEqual(len(alt), 1)
            for raw in alt:
                StoryboardShot(**raw)

    def test_character_fixtures_match_machine_rules(self) -> None:
        for track in TRACKS:
            with self.subTest(track=track):
                data = json.loads((FIXTURE_DIR / f"track_{track}_characters.json").read_text(encoding="utf-8"))
                sheet = CharacterSheet(**data)
                self.assertGreaterEqual(len(sheet.characters), 2)
                by_id = {character.id: character for character in sheet.characters}
                for character in sheet.characters:
                    self.assertTrue(character.lora_token.isascii())
                    self.assertRegex(character.lora_token, r"^[a-z][a-z0-9_]*$")
                    target = character.visual_contrast_with.get("target_id")
                    self.assertIn(target, by_id)
                    self.assertEqual(by_id[target].visual_contrast_with.get("target_id"), character.id)
                    for term in SUBJECTIVE_PROMPT_TERMS:
                        self.assertNotIn(term, character.prompt_template_sd)

    def test_character_fixtures_do_not_contain_forbidden_source_terms(self) -> None:
        combined = "\n".join(
            (FIXTURE_DIR / f"track_{track}_characters.json").read_text(encoding="utf-8")
            for track in TRACKS
        )
        for term in DRAGON_RAJA_TERMS:
            self.assertNotIn(term, combined)

    def test_review_fixtures_match_machine_rules(self) -> None:
        for track in TRACKS:
            with self.subTest(track=track):
                data = json.loads((FIXTURE_DIR / f"track_{track}_review.json").read_text(encoding="utf-8"))
                review = DramaReview(**data)
                self.assertEqual(review.verdict, "Approve")
                self.assertFalse(review.needs_human_review)
                self.assertGreaterEqual(review.score, 7)

    def test_review_fixtures_do_not_contain_forbidden_source_terms(self) -> None:
        combined = "\n".join(
            (FIXTURE_DIR / f"track_{track}_review.json").read_text(encoding="utf-8")
            for track in TRACKS
        )
        for term in DRAGON_RAJA_TERMS:
            self.assertNotIn(term, combined)

    def test_episode_two_hook_fixtures_are_three_fresh_original_candidates(self) -> None:
        for track in TRACKS:
            with self.subTest(track=track):
                first = json.loads((FIXTURE_DIR / f"track_{track}_hooks.json").read_text(encoding="utf-8"))["hooks"]
                second = json.loads((FIXTURE_DIR / f"track_{track}_hooks_ep2.json").read_text(encoding="utf-8"))["hooks"]
                self.assertEqual(len(second), 3)
                self.assertEqual([item["type"] for item in second], ["情绪钩", "悬念钩", "反差钩"])
                first_keys = {(item["type"], item["content"]) for item in first}
                self.assertTrue(all((item["type"], item["content"]) not in first_keys for item in second))
                for item in second:
                    self.assertTrue(item["content"])
                    for term in DRAGON_RAJA_TERMS:
                        self.assertNotIn(term, item["content"])


if __name__ == "__main__":
    unittest.main()
