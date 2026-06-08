"""Iter 046: AgentWrite 配额循环 — planner side.

Covers the optional ``segments`` field on ChapterPlanItem: schema round-trip,
default-empty, the planner prompt documenting it, and the backward-compat
guarantee that segments are excluded from the chapter fingerprint.
"""

import unittest

from src.plot_planner import _build_planner_prompt, chapter_plan_item_fingerprint
from src.schemas import ChapterPlan, ChapterPlanItem, ChapterSegment, model_to_dict


class PlannerSegmentsTests(unittest.TestCase):
    def test_planner_prompt_documents_optional_segments(self) -> None:
        prompt = _build_planner_prompt(
            target_chapters=3,
            outline="outline",
            entity_state="",
            style_examples="",
            facts="",
        )
        # The auto-injected ChapterPlan JSON schema documents the new fields...
        self.assertIn("segments", prompt)
        self.assertIn("is_final", prompt)
        # ...and the explicit hard-requirement bullet describes the quota loop.
        self.assertIn("配额", prompt)

    def test_chapter_plan_round_trips_segments(self) -> None:
        item = ChapterPlanItem(
            chapter_no=1,
            title="t",
            opening_scene="s",
            key_events=["a", "b"],
            ending_hook="h",
            target_chinese_chars=4000,
            plot_purpose="p",
            segments=[
                ChapterSegment(segment_no=1, beat="b1", target_chinese_chars=1500),
                ChapterSegment(segment_no=2, beat="b2", target_chinese_chars=1500),
                ChapterSegment(segment_no=3, beat="b3", target_chinese_chars=1000, is_final=True),
            ],
        )
        plan = ChapterPlan(target_chapters=1, overall_arc="arc", chapters=[item])
        dumped = model_to_dict(plan)
        seg = dumped["chapters"][0]["segments"]
        self.assertEqual(len(seg), 3)
        self.assertTrue(seg[2]["is_final"])
        self.assertFalse(seg[0]["is_final"])
        self.assertEqual(seg[0]["target_chinese_chars"], 1500)

    def test_segments_default_to_empty(self) -> None:
        item = ChapterPlanItem(
            chapter_no=1,
            title="t",
            opening_scene="s",
            key_events=["a", "b"],
            ending_hook="h",
            target_chinese_chars=4000,
            plot_purpose="p",
        )
        self.assertEqual(item.segments, [])

    def test_fingerprint_excludes_segments(self) -> None:
        # Backward compat: adding segments must NOT change a chapter's
        # fingerprint, otherwise every pre-046 on-disk plan would trip the
        # fail-closed plan_fingerprint_mismatch guard in book_runner.
        base = {
            "chapter_no": 1,
            "title": "t",
            "opening_scene": "s",
            "key_events": ["a", "b"],
            "relationships_in_play": [],
            "ending_hook": "h",
            "target_chinese_chars": 4000,
            "plot_purpose": "p",
        }
        with_segs = dict(
            base,
            segments=[
                {"segment_no": 1, "beat": "x", "target_chinese_chars": 1200, "is_final": True}
            ],
        )
        self.assertEqual(
            chapter_plan_item_fingerprint(base),
            chapter_plan_item_fingerprint(with_segs),
        )


if __name__ == "__main__":
    unittest.main()
