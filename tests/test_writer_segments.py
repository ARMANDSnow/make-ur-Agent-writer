"""Iter 046: AgentWrite 配额循环 — writer side.

Asserts the segmented write loop: one LLM call per segment, non-final segments
suppress wrap-up while the final one writes the ending hook, segment N>1 carries
prior text and does not re-open, and the toggle/empty-segments paths stay
single-shot (byte-identical to pre-046).
"""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from src.writer import write_chapters


def _agent_config(**overrides: Any) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "max_review_attempts": 1,
        "polish_pass": False,
        "review_during_lint_block": False,
        "continuation_anchor": "",
        "segmented_write": True,
    }
    cfg.update(overrides)
    return cfg


def _plan_with_segments(n_segments: int = 3) -> Dict[str, Any]:
    return {
        "target_chapters": 1,
        "overall_arc": "arc",
        "generated_by": "test",
        "chapters": [
            {
                "chapter_no": 1,
                "title": "分段测试章",
                "opening_scene": "主角在码头等船。",
                "key_events": ["事件一", "事件二"],
                "relationships_in_play": [],
                "ending_hook": "船笛响起。",
                "target_chinese_chars": 4000,
                "plot_purpose": "测试分段写作。",
                "segments": [
                    {
                        "segment_no": i,
                        "beat": f"第 {i} 段 beat",
                        "target_chinese_chars": 1300,
                        "is_final": i == n_segments,
                    }
                    for i in range(1, n_segments + 1)
                ],
            }
        ],
    }


class WriterSegmentedTests(unittest.TestCase):
    def _run(
        self,
        *,
        plan: Dict[str, Any],
        agent_overrides: Optional[Dict[str, Any]] = None,
    ) -> tuple[List[str], str]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            drafts = tmp / "drafts"
            drafts.mkdir(parents=True)
            outline = tmp / "outline.md"
            outline.write_text("# outline", encoding="utf-8")
            kb = tmp / "kb.md"
            kb.write_text("# knowledge", encoding="utf-8")
            idx = tmp / "idx.json"
            idx.write_text("{}", encoding="utf-8")
            plan_path = tmp / "chapter_plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

            calls: List[str] = []

            def fake_complete_text(self, messages, temperature=None, cache_segments=None):  # noqa: ANN001
                user = "\n".join(
                    m.get("content", "") for m in messages if m.get("role") == "user"
                )
                calls.append(user)
                return f"第{len(calls)}段正文内容，足够长以跳过扩写。" * 30

            def fake_load_config(name: str):
                if name == "agents.yaml":
                    return _agent_config(**(agent_overrides or {}))
                raise AssertionError(name)

            with patch("src.writer.DRAFTS_DIR", drafts), patch(
                "src.writer.OUTLINE_PATH", outline
            ), patch("src.writer.KB_PATH", kb), patch(
                "src.writer.INDEX_PATH", idx
            ), patch(
                "src.writer.CHAPTER_PLAN_PATH", plan_path
            ), patch(
                "src.writer.load_config", side_effect=fake_load_config
            ), patch(
                "src.writer.NovelLinter"
            ) as linter_cls, patch(
                "src.llm_client.LLMClient.complete_text", fake_complete_text
            ), patch(
                "src.writer.review_text",
                return_value={"verdict": "Approve", "lint_issues": [], "agent_reviews": []},
            ), patch(
                "src.writer._summarize_chapter",
                return_value={"summary": "s", "key_events": ["e"], "ending_state": "end"},
            ), patch(
                "src.writer._propose_entity_advance", return_value=[]
            ):
                linter_cls.return_value.lint.return_value = []
                write_chapters(chapters=1, force=True, max_attempts=1)

            draft = (drafts / "chapter_01.md").read_text(encoding="utf-8")
            return calls, draft

    def test_one_llm_call_per_segment(self) -> None:
        calls, draft = self._run(plan=_plan_with_segments(3))
        self.assertEqual(len(calls), 3)
        # the assembled chapter concatenates every segment's output
        self.assertIn("第1段正文内容", draft)
        self.assertIn("第2段正文内容", draft)
        self.assertIn("第3段正文内容", draft)

    def test_non_final_segments_suppress_wrapup_final_does_not(self) -> None:
        calls, _ = self._run(plan=_plan_with_segments(3))
        self.assertIn("本段不是最后一段", calls[0])
        self.assertIn("不要收束全章", calls[0])
        self.assertIn("本段不是最后一段", calls[1])
        # final segment is told to close the chapter
        self.assertIn("本段是本章最后一段", calls[2])
        self.assertNotIn("本段不是最后一段", calls[2])
        # per-segment quota replaces the per-chapter length band
        self.assertIn("本段目标长度", calls[0])
        self.assertIn("约 1300 字", calls[0])  # the per-segment quota is rendered
        self.assertNotIn("中文正文 3500-5500 字", calls[0])

    def test_segment_two_carries_prior_text_and_does_not_reopen(self) -> None:
        calls, _ = self._run(plan=_plan_with_segments(3))
        self.assertIn("本段为开篇段", calls[0])
        self.assertIn("本章已写前文", calls[1])
        self.assertIn("不要从 opening_scene 重新开场", calls[1])

    def test_toggle_off_is_single_shot(self) -> None:
        calls, _ = self._run(
            plan=_plan_with_segments(3), agent_overrides={"segmented_write": False}
        )
        self.assertEqual(len(calls), 1)
        self.assertIn("中文正文 3500-5500 字", calls[0])

    def test_empty_segments_is_single_shot_even_when_enabled(self) -> None:
        plan = _plan_with_segments(3)
        plan["chapters"][0]["segments"] = []
        calls, _ = self._run(plan=plan)
        self.assertEqual(len(calls), 1)
        self.assertIn("中文正文 3500-5500 字", calls[0])


if __name__ == "__main__":
    unittest.main()
