import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

from src.writer import _write_prompt, write_chapters


def _write_fixture(tmp: Path) -> tuple[Path, Path, Path, Path]:
    drafts = tmp / "drafts"
    drafts.mkdir(parents=True)
    outline = tmp / "outline.md"
    outline.write_text("# test outline", encoding="utf-8")
    kb = tmp / "global_knowledge.md"
    kb.write_text("# test knowledge", encoding="utf-8")
    idx = tmp / "knowledge_index.json"
    idx.write_text("{}", encoding="utf-8")
    return drafts, outline, kb, idx


def _agent_config(**overrides: Any) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "max_review_attempts": 3,
        "polish_pass": True,
        "review_during_lint_block": True,
        "continuation_anchor": "",
    }
    cfg.update(overrides)
    return cfg


class WriterLintFailureTests(unittest.TestCase):
    def test_lint_error_writes_human_review_draft_and_failure_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            drafts = tmp / "drafts"
            drafts.mkdir(parents=True)
            outline = tmp / "outline.md"
            outline.write_text("# test outline", encoding="utf-8")
            kb = tmp / "global_knowledge.md"
            kb.write_text("# test knowledge", encoding="utf-8")
            idx = tmp / "knowledge_index.json"
            idx.write_text("{}", encoding="utf-8")

            with patch("src.writer.DRAFTS_DIR", drafts), patch("src.writer.OUTLINE_PATH", outline), patch(
                "src.writer.KB_PATH", kb
            ), patch("src.writer.INDEX_PATH", idx):
                # Mock linter to always return lint errors
                with patch("src.writer.NovelLinter") as mock_linter_cls:
                    mock_linter = mock_linter_cls.return_value
                    mock_linter.lint.return_value = [
                        {"rule": "meta_chapter_markers", "severity": "error", "message": "bad", "line": 1, "excerpt": "x"}
                    ]

                    reports = write_chapters(chapters=1, force=True, max_attempts=1)

            md_path = drafts / "chapter_01.md"
            meta_path = drafts / "chapter_01.meta.json"
            failure_path = drafts / "chapter_01.failure.json"
            self.assertTrue(md_path.exists())
            self.assertTrue(meta_path.exists())
            self.assertTrue(failure_path.exists())
            failure = json.loads(failure_path.read_text(encoding="utf-8"))
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertIn("lint_issues", failure)
            self.assertTrue(meta["needs_human_review"])
            self.assertEqual(meta["rewrite_count"], 0)
            self.assertEqual(meta["last_blocking_reasons"][0]["reviewer"], "deterministic_linter")
            self.assertEqual(reports[0]["written"], True)


class WriterRejectLintCleanTests(unittest.TestCase):
    def test_reject_lint_clean_writes_draft_with_human_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            drafts = tmp / "drafts"
            drafts.mkdir(parents=True)
            outline = tmp / "outline.md"
            outline.write_text("# test outline", encoding="utf-8")
            kb = tmp / "global_knowledge.md"
            kb.write_text("# test knowledge", encoding="utf-8")
            idx = tmp / "knowledge_index.json"
            idx.write_text("{}", encoding="utf-8")

            with patch("src.writer.DRAFTS_DIR", drafts), patch("src.writer.OUTLINE_PATH", outline), patch(
                "src.writer.KB_PATH", kb
            ), patch("src.writer.INDEX_PATH", idx):
                with patch("src.writer.NovelLinter") as mock_linter_cls:
                    mock_linter = mock_linter_cls.return_value
                    mock_linter.lint.return_value = []  # lint clean
                    with patch("src.writer.review_text") as mock_review:
                        mock_review.return_value = {
                            "verdict": "Reject",
                            "lint_issues": [],
                            "agent_reviews": [{"verdict": "Reject", "issues": ["bad pacing"]}],
                        }
                        reports = write_chapters(chapters=1, force=True, max_attempts=1)

            md_path = drafts / "chapter_01.md"
            meta_path = drafts / "chapter_01.meta.json"
            self.assertTrue(md_path.exists())
            self.assertTrue(meta_path.exists())
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertTrue(meta.get("needs_human_review"))
            self.assertEqual(reports[0]["written"], True)

    def test_writer_prompt_includes_style_examples_when_present(self) -> None:
        messages, cache_segments = _write_prompt(
            chapter_no=1,
            knowledge="knowledge",
            facts="facts",
            style_examples="### opening_rhythm\n\n风格样例",
            continuation_anchor="",
            index={},
            outline="outline",
            feedback="",
        )
        prompt = "\n".join(item["content"] for item in messages)
        cached_text = "\n".join(item["content"] for item in cache_segments if item.get("cache"))
        self.assertIn("opening_rhythm", prompt)
        self.assertIn("不要复制具体情节", prompt)
        self.assertIn("opening_rhythm", cached_text)

    def test_writer_prompt_includes_continuation_anchor(self) -> None:
        messages, _cache_segments = _write_prompt(
            chapter_no=1,
            knowledge="knowledge",
            facts="facts",
            style_examples="",
            continuation_anchor="第三部结局后三个月",
            index={},
            outline="outline",
            feedback="",
        )
        prompt = "\n".join(item["content"] for item in messages)
        self.assertIn("续写起点", prompt)
        self.assertIn("第三部结局后三个月", prompt)
        self.assertIn("中文正文 3500-5500 字", prompt)

    def test_writer_prompt_includes_rolling_context_and_ending_state(self) -> None:
        messages, _cache_segments = _write_prompt(
            chapter_no=2,
            knowledge="knowledge",
            facts="facts",
            style_examples="",
            continuation_anchor="",
            index={},
            outline="outline",
            rolling_context="## 已写章节回顾\n第 1 章摘要",
            previous_chapter_ending="上一章停在雨夜门口",
            feedback="",
        )
        prompt = "\n".join(item["content"] for item in messages)
        self.assertIn("已写章节回顾", prompt)
        self.assertIn("上一章结尾状态", prompt)
        self.assertIn("本章开场衔接提示", prompt)
        self.assertIn("上一章停在雨夜门口", prompt)

    def test_writer_prompt_includes_chapter_plan_when_present(self) -> None:
        messages, _cache_segments = _write_prompt(
            chapter_no=3,
            knowledge="knowledge",
            facts="facts",
            style_examples="",
            continuation_anchor="",
            index={},
            outline="outline",
            chapter_plan_item={
                "chapter_no": 3,
                "title": "计划中的第三章",
                "opening_scene": "路明非在芝加哥车站醒来，手里攥着旧硬币。",
                "key_events": ["发现列车票背面的暗号", "与旧同伴重新建立联系"],
                "relationships_in_play": ["路明非/旧同伴"],
                "ending_hook": "站台广播念出一个不该出现的名字。",
                "target_chinese_chars": 4200,
                "plot_purpose": "把第二章的线索转入主动调查。",
            },
            rolling_context="## 已写章节回顾\n上一章已经抵达芝加哥。",
            feedback="",
        )
        prompt = "\n".join(item["content"] for item in messages)
        self.assertIn("本章计划（必须严格遵守）", prompt)
        self.assertIn("路明非在芝加哥车站醒来", prompt)
        self.assertIn("发现列车票背面的暗号", prompt)
        self.assertIn("已写章节回顾/上一章结尾状态 > 本章计划 > 辩论大纲", prompt)

    def test_writer_prompt_includes_entity_state_when_present(self) -> None:
        graph = {
            "entities": [
                {"id": "a", "name": "甲", "type": "character", "tags": ["#同盟"], "key_facts": ["事实甲"]},
                {"id": "b", "name": "乙", "type": "character", "tags": ["#同盟"], "key_facts": ["事实乙"]},
            ],
            "relationships": [
                {
                    "src_id": "a",
                    "dst_id": "b",
                    "relation_type": "同盟",
                    "timeline": [{"anchor_chapter": "now", "state": "当前必须互相信任", "active": True}],
                }
            ],
        }
        with patch("src.writer.load_entity_graph", return_value=graph):
            messages, cache_segments = _write_prompt(
                chapter_no=1,
                knowledge="knowledge",
                facts="facts",
                style_examples="",
                continuation_anchor="",
                index={},
                outline="outline",
                feedback="",
            )
        prompt = "\n".join(item["content"] for item in messages)
        cached_text = "\n".join(item["content"] for item in cache_segments if item.get("cache"))
        self.assertIn("tags:", prompt)
        self.assertIn("tag 反向索引", prompt)
        self.assertIn("当前活跃关系", prompt)
        self.assertIn("当前必须互相信任", prompt)
        self.assertIn("严格遵守'当前活跃关系'", prompt)
        self.assertIn("tags:", cached_text)
        self.assertIn("tag 反向索引", cached_text)
        self.assertIn("当前必须互相信任", cached_text)

    def test_polish_pass_runs_after_final_reject_and_respects_disable(self) -> None:
        for enabled in (True, False):
            with self.subTest(polish_pass=enabled), tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                drafts, outline, kb, idx = _write_fixture(tmp)
                calls = []

                def fake_complete_text(self, messages, temperature=None, cache_segments=None):
                    calls.append("\n".join(message.get("content", "") for message in messages))
                    return "polished draft" if len(calls) > 1 else "first draft"

                def fake_load_config(name: str):
                    if name == "agents.yaml":
                        return _agent_config(polish_pass=enabled)
                    raise AssertionError(name)

                with patch("src.writer.DRAFTS_DIR", drafts), patch("src.writer.OUTLINE_PATH", outline), patch(
                    "src.writer.KB_PATH", kb
                ), patch("src.writer.INDEX_PATH", idx), patch("src.writer.load_config", side_effect=fake_load_config), patch(
                    "src.writer.NovelLinter"
                ) as linter_cls, patch(
                    "src.llm_client.LLMClient.complete_text", fake_complete_text
                ), patch(
                    "src.writer.review_text",
                    return_value={"verdict": "Reject", "lint_issues": [], "agent_reviews": []},
                ):
                    linter_cls.return_value.lint.return_value = []
                    write_chapters(chapters=1, force=True, max_attempts=1)

                meta = json.loads((drafts / "chapter_01.meta.json").read_text(encoding="utf-8"))
                draft = (drafts / "chapter_01.md").read_text(encoding="utf-8")
                self.assertEqual(meta["polish_applied"], enabled)
                self.assertEqual(("polished draft" in draft), enabled)
                if enabled:
                    self.assertEqual(meta["polish_diff_stats"]["pre_chars"], len("first draft"))

    def test_polish_triggers_when_chinese_chars_below_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            drafts, outline, kb, idx = _write_fixture(tmp)
            calls = []

            def fake_complete_text(self, messages, temperature=None, cache_segments=None):
                calls.append("\n".join(message.get("content", "") for message in messages))
                return "扩写后正文" if len(calls) > 1 else "短正文"

            def fake_load_config(name: str):
                if name == "agents.yaml":
                    return _agent_config(polish_pass=True)
                raise AssertionError(name)

            with patch("src.writer.DRAFTS_DIR", drafts), patch("src.writer.OUTLINE_PATH", outline), patch(
                "src.writer.KB_PATH", kb
            ), patch("src.writer.INDEX_PATH", idx), patch("src.writer.load_config", side_effect=fake_load_config), patch(
                "src.writer.NovelLinter"
            ) as linter_cls, patch(
                "src.llm_client.LLMClient.complete_text", fake_complete_text
            ), patch(
                "src.writer.review_text",
                return_value={"verdict": "Approve", "lint_issues": [], "agent_reviews": []},
            ):
                linter_cls.return_value.lint.return_value = []
                write_chapters(chapters=1, force=True, max_attempts=1)

            meta = json.loads((drafts / "chapter_01.meta.json").read_text(encoding="utf-8"))
            draft = (drafts / "chapter_01.md").read_text(encoding="utf-8")
            self.assertTrue(meta["polish_applied"])
            self.assertIn("扩写后正文", draft)
            self.assertIn("目标 3500-5500 中文字", calls[-1])

    def test_reviewer_runs_even_when_lint_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            drafts, outline, kb, idx = _write_fixture(tmp)

            def fake_load_config(name: str):
                if name == "agents.yaml":
                    return _agent_config(polish_pass=False, review_during_lint_block=True)
                raise AssertionError(name)

            shadow_report = {
                "verdict": "Reject",
                "lint_issues": [{"rule": "not_x_but_y", "severity": "error", "message": "bad", "line": 1, "anchor": "bad"}],
                "agent_reviews": [{"agent_name": "江南人格模拟", "verdict": "Reject", "issues": []}],
            }
            with patch("src.writer.DRAFTS_DIR", drafts), patch("src.writer.OUTLINE_PATH", outline), patch(
                "src.writer.KB_PATH", kb
            ), patch("src.writer.INDEX_PATH", idx), patch("src.writer.load_config", side_effect=fake_load_config), patch(
                "src.writer.NovelLinter"
            ) as linter_cls, patch(
                "src.writer.review_text", return_value=shadow_report
            ) as mock_review:
                linter_cls.return_value.lint.return_value = [
                    {"rule": "not_x_but_y", "severity": "error", "message": "bad", "line": 1, "anchor": "bad", "count": 5}
                ]
                write_chapters(chapters=1, force=True, max_attempts=1)

            meta = json.loads((drafts / "chapter_01.meta.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["lint_blocked_reviews"])
            self.assertEqual(meta["lint_blocked_reviews"][0]["attempt"], 1)
            self.assertEqual(meta["lint_blocked_reviews"][0]["review"]["agent_reviews"][0]["agent_name"], "江南人格模拟")
            self.assertTrue(mock_review.call_args.kwargs["run_agents_on_lint_error"])

    def test_write_chapter_persists_summary_and_entity_proposals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            drafts, outline, kb, idx = _write_fixture(tmp)

            def fake_load_config(name: str):
                if name == "agents.yaml":
                    return _agent_config(polish_pass=False)
                raise AssertionError(name)

            with patch("src.writer.DRAFTS_DIR", drafts), patch("src.writer.OUTLINE_PATH", outline), patch(
                "src.writer.KB_PATH", kb
            ), patch("src.writer.INDEX_PATH", idx), patch("src.writer.load_config", side_effect=fake_load_config), patch(
                "src.writer.NovelLinter"
            ) as linter_cls, patch(
                "src.writer.review_text",
                return_value={"verdict": "Approve", "lint_issues": [], "agent_reviews": []},
            ), patch(
                "src.writer._complete_write_text", return_value="足够干净的正文"
            ), patch(
                "src.writer._summarize_chapter",
                return_value={"summary": "本章摘要", "key_events": ["事件"], "ending_state": "结尾状态"},
            ) as summarize, patch(
                "src.writer._propose_entity_advance",
                return_value=[
                    {
                        "src_id": "a",
                        "dst_id": "b",
                        "old_active_state": "旧",
                        "new_state": "新",
                        "trigger_event": "事件",
                        "confidence": 0.9,
                    }
                ],
            ) as propose:
                linter_cls.return_value.lint.return_value = []
                write_chapters(chapters=1, force=True, max_attempts=1)

            rolling = json.loads((drafts / "rolling_chapter_summary.json").read_text(encoding="utf-8"))
            proposals = json.loads((drafts / "chapter_01.entity_advance_proposals.json").read_text(encoding="utf-8"))
        summarize.assert_called_once()
        propose.assert_called_once()
        self.assertEqual(rolling["chapters"][0]["ending_state"], "结尾状态")
        self.assertEqual(proposals["proposed_advances"][0]["new_state"], "新")

    def test_write_chapters_falls_back_when_chapter_plan_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            drafts, outline, kb, idx = _write_fixture(tmp)
            missing_plan = tmp / "missing_chapter_plan.json"

            def fake_load_config(name: str):
                if name == "agents.yaml":
                    return _agent_config(polish_pass=False)
                raise AssertionError(name)

            with patch("src.writer.DRAFTS_DIR", drafts), patch("src.writer.OUTLINE_PATH", outline), patch(
                "src.writer.KB_PATH", kb
            ), patch("src.writer.INDEX_PATH", idx), patch(
                "src.writer.CHAPTER_PLAN_PATH", missing_plan
            ), patch(
                "src.writer.load_config", side_effect=fake_load_config
            ), patch(
                "src.writer.NovelLinter"
            ) as linter_cls, patch(
                "src.writer.review_text",
                return_value={"verdict": "Approve", "lint_issues": [], "agent_reviews": []},
            ), patch(
                "src.writer._complete_write_text", return_value="没有计划也可以写的正文"
            ), patch(
                "src.writer._summarize_chapter",
                return_value={"summary": "摘要", "key_events": ["事件"], "ending_state": "结尾"},
            ), patch(
                "src.writer._propose_entity_advance", return_value=[]
            ):
                linter_cls.return_value.lint.return_value = []
                reports = write_chapters(chapters=1, force=True, max_attempts=1)

            self.assertEqual(reports[0]["chapter"], 1)
            self.assertTrue((drafts / "chapter_01.md").exists())

    def test_shadow_review_handles_review_text_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            drafts, outline, kb, idx = _write_fixture(tmp)

            def fake_load_config(name: str):
                if name == "agents.yaml":
                    return _agent_config(polish_pass=False, review_during_lint_block=True)
                raise AssertionError(name)

            fallback_report = {
                "target": "chapter_01.md",
                "rewrite_round": 0,
                "verdict": "Approve",
                "lint_issues": [{"rule": "not_x_but_y", "severity": "error", "message": "bad", "line": 1, "anchor": "bad"}],
                "agent_reviews": [],
                "_fallback_reason": "(parse_failed)",
            }
            with patch("src.writer.DRAFTS_DIR", drafts), patch("src.writer.OUTLINE_PATH", outline), patch(
                "src.writer.KB_PATH", kb
            ), patch("src.writer.INDEX_PATH", idx), patch("src.writer.load_config", side_effect=fake_load_config), patch(
                "src.writer.NovelLinter"
            ) as linter_cls, patch(
                "src.writer.review_text", return_value=fallback_report
            ):
                linter_cls.return_value.lint.return_value = [
                    {"rule": "not_x_but_y", "severity": "error", "message": "bad", "line": 1, "anchor": "bad", "count": 5}
                ]
                write_chapters(chapters=1, force=True, max_attempts=1)

            meta = json.loads((drafts / "chapter_01.meta.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["lint_blocked_reviews"])
            self.assertEqual(meta["lint_blocked_reviews"][0]["review"]["_fallback_reason"], "(parse_failed)")
            self.assertEqual(meta["lint_blocked_reviews"][0]["review"]["verdict"], "Approve")


if __name__ == "__main__":
    unittest.main()
