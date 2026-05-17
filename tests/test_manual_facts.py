import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

from src.compressor import build_knowledge_index
from src.debater import build_outline
from src.llm_client import LLMClient
from src.manual_facts import global_facts_summary, load_global_facts
from src.writer import write_chapters


class ManualFactsTests(unittest.TestCase):
    def test_load_global_facts_accepts_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "global_facts.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "fact_id": "erii_dead",
                            "statement": "上杉绘梨衣已死亡。",
                            "confidence": 1.0,
                            "scope": "global",
                            "applies_to": ["compress", "debate", "write", "review"],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            facts = load_global_facts(path)
            summary = global_facts_summary(path)
        self.assertEqual(facts[0]["fact_id"], "erii_dead")
        self.assertIn("上杉绘梨衣已死亡", summary)

    def test_knowledge_index_includes_manual_global_facts(self) -> None:
        with patch("src.compressor.load_global_facts", return_value=[{"fact_id": "f1", "statement": "S"}]):
            index = build_knowledge_index([])
        self.assertEqual(index["manual_global_facts"][0]["fact_id"], "f1")

    def test_debate_outline_prompt_includes_global_facts(self) -> None:
        client = LLMClient("debate")
        captured = {}

        def fake_complete_text(self, messages, temperature=None):
            captured["prompt"] = "\n".join(m.get("content", "") for m in messages)
            return "# outline"

        with patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as mock_prop:
            mock_prop.return_value = False
            with patch.object(LLMClient, "complete_text", fake_complete_text):
                build_outline(
                    "topic",
                    {"votes": []},
                    [{"round": 1, "agent": "a", "response": "r"}],
                    client,
                    global_facts="FACT: 绘梨衣已死亡",
                )
        self.assertIn("FACT: 绘梨衣已死亡", captured["prompt"])

    def test_writer_prompt_includes_global_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            drafts = tmp / "drafts"
            drafts.mkdir(parents=True)
            outline = tmp / "outline.md"
            outline.write_text("# outline", encoding="utf-8")
            kb = tmp / "global_knowledge.md"
            kb.write_text("# knowledge", encoding="utf-8")
            idx = tmp / "knowledge_index.json"
            idx.write_text("{}", encoding="utf-8")
            captured = {}

            def fake_complete_text(self, messages, temperature=None):
                captured["prompt"] = "\n".join(m.get("content", "") for m in messages)
                return "干净正文。"

            def fake_load_config(name: str):
                if name == "agents.yaml":
                    return {
                        "max_review_attempts": 3,
                        "polish_pass": False,
                        "review_during_lint_block": True,
                        "continuation_anchor": "",
                    }
                raise AssertionError(name)

            with patch("src.writer.DRAFTS_DIR", drafts), patch("src.writer.OUTLINE_PATH", outline), patch(
                "src.writer.KB_PATH", kb
            ), patch("src.writer.INDEX_PATH", idx), patch(
                "src.writer.global_facts_summary", return_value="FACT: 绘梨衣已死亡"
            ), patch(
                "src.writer.load_config", side_effect=fake_load_config
            ), patch(
                "src.llm_client.LLMClient.complete_text", fake_complete_text
            ), patch(
                "src.writer.NovelLinter"
            ) as linter_cls, patch(
                "src.writer.load_style_examples", return_value=""
            ), patch(
                "src.writer.review_text",
                return_value={"verdict": "Approve", "lint_issues": [], "agent_reviews": []},
            ):
                linter_cls.return_value.lint.return_value = []
                write_chapters(chapters=1, force=True, max_attempts=1)
        self.assertIn("FACT: 绘梨衣已死亡", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
