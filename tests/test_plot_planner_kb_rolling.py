"""Iter 021: tests for plot_planner KB + rolling_summary injection (A3).

Verifies that ``src.plot_planner._build_planner_prompt`` includes "全局知识"
when KB is non-empty and "已写章节滚动摘要" when rolling_summary is
non-empty; also verifies both blocks are absent when those inputs are
empty (backward-compat).
"""

import unittest


class PlotPlannerKBRollingTests(unittest.TestCase):
    def test_empty_kb_and_rolling_omits_blocks(self) -> None:
        from src.plot_planner import _build_planner_prompt
        prompt = _build_planner_prompt(
            target_chapters=3,
            outline="outline only",
            entity_state="",
            style_examples="",
            facts="",
        )
        self.assertNotIn("# 全局知识", prompt)
        self.assertNotIn("# 已写章节滚动摘要", prompt)
        # New rule #8 (rolling > debate) must be present in spec text
        self.assertIn("已发生", prompt)

    def test_kb_only_injects_kb_block(self) -> None:
        from src.plot_planner import _build_planner_prompt
        prompt = _build_planner_prompt(
            target_chapters=3,
            outline="outline",
            entity_state="",
            style_examples="",
            facts="",
            knowledge="KB CONTENT HERE",
        )
        self.assertIn("# 全局知识", prompt)
        self.assertIn("KB CONTENT HERE", prompt)
        self.assertNotIn("# 已写章节滚动摘要", prompt)

    def test_kb_and_rolling_both_injected(self) -> None:
        from src.plot_planner import _build_planner_prompt
        prompt = _build_planner_prompt(
            target_chapters=3,
            outline="outline",
            entity_state="",
            style_examples="",
            facts="",
            knowledge="KB CONTENT HERE",
            rolling_summary="### ch1\nrolling summary text",
        )
        self.assertIn("# 全局知识", prompt)
        self.assertIn("KB CONTENT HERE", prompt)
        self.assertIn("# 已写章节滚动摘要", prompt)
        self.assertIn("rolling summary text", prompt)
        # The "已发生 > 计划" guidance is appended after rolling block
        self.assertIn("不与已发生事件冲突", prompt)


if __name__ == "__main__":
    unittest.main()
