"""iter 051a: premise expansion module — artifact lifecycle, mock stub
determinism, graceful degrade (铁律④), and prompt-chain consumption.

The load-bearing assertions:

* missing artifact → ``expansion_prompt_block() == ""`` → compress / debate
  / bootstrap prompts byte-identical to pre-051 (the bare-seed fallback);
* mock compress output WITHOUT the artifact equals ``_mock_knowledge_markdown``
  verbatim (the pre-051 KB, pinned byte-exactly);
* with the artifact, KB gains the expansion section and the debate prompt
  carries the block.

Mock-only.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import paths, premise_expansion
from src.compressor import _mock_knowledge_markdown, build_knowledge_index, compress_all
from src.llm_client import LLMClient
from src.schemas import PremiseExpansion


_EXTRACTION = {
    "chapter_id": "ch_0001",
    "volume_id": "v01",
    "title": "缘起",
    "summary": "主角收到一封信。",
    "rolling_summary": "",
    "character_states": [],
    "relationships": [],
    "foreshadowing": [],
    "worldbuilding": [],
    "style_samples": [],
    "evidence_spans": [],
}


class _WorkspaceHarness(unittest.TestCase):
    """Tmp workspace named via WORKSPACE_NAME so paths.* resolve into it."""

    WS = "expws"

    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        os.environ["WORKSPACE_NAME"] = self.WS
        (paths.WORKSPACE_DIR / self.WS).mkdir(parents=True)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()


class ExpandPremiseTests(_WorkspaceHarness):
    def test_mock_expand_writes_deterministic_artifact(self) -> None:
        record = premise_expansion.expand_premise("旧书店店主收到亡友的信。")
        self.assertEqual(record["generated_by"], "premise_expand_v1_mock")
        self.assertEqual(record["premise"], "旧书店店主收到亡友的信。")
        self.assertFalse(record["edited"])
        # the artifact validates against the schema and is on disk
        on_disk = json.loads(paths.premise_expansion_path().read_text(encoding="utf-8"))
        self.assertEqual(on_disk["fields"], record["fields"])
        PremiseExpansion(**on_disk["fields"])
        # deterministic stub fields (pinned so downstream tests can rely on them)
        self.assertIn("mock 题材基调", record["fields"]["genre_tone"])
        self.assertEqual(len(record["fields"]["world_notes"]), 2)

    def test_expand_is_idempotent_unless_forced(self) -> None:
        premise_expansion.expand_premise("立意 A")
        edited = premise_expansion.save_expansion_fields({"genre_tone": "手工改过"})
        again = premise_expansion.expand_premise("立意 A")
        # no force → the user edit survives
        self.assertEqual(again["fields"]["genre_tone"], "手工改过")
        self.assertTrue(again["edited"])
        forced = premise_expansion.expand_premise("立意 A", force=True)
        self.assertFalse(forced["edited"])
        self.assertIn("mock 题材基调", forced["fields"]["genre_tone"])
        self.assertNotEqual(forced["fields"]["genre_tone"], edited["fields"]["genre_tone"])

    def test_expand_rejects_empty_premise(self) -> None:
        with self.assertRaises(ValueError):
            premise_expansion.expand_premise("   ")


class LoadAndSaveTests(_WorkspaceHarness):
    def test_load_missing_returns_none(self) -> None:
        self.assertIsNone(premise_expansion.load_expansion())

    def test_load_corrupt_json_degrades_to_none(self) -> None:
        path = paths.premise_expansion_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(premise_expansion.load_expansion())

    def test_load_schema_invalid_degrades_to_none(self) -> None:
        path = paths.premise_expansion_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"fields": {"world_notes": ["x" * 501]}}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.assertIsNone(premise_expansion.load_expansion())

    def test_save_creates_from_scratch_as_manual(self) -> None:
        record = premise_expansion.save_expansion_fields(
            {"genre_tone": "都市悬疑", "arc_hints": ["第一章定调"]}
        )
        self.assertEqual(record["generated_by"], "manual")
        self.assertTrue(record["edited"])
        loaded = premise_expansion.load_expansion()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["fields"]["genre_tone"], "都市悬疑")

    def test_save_rejects_invalid_fields(self) -> None:
        with self.assertRaises(ValueError):
            premise_expansion.save_expansion_fields({"genre_tone": "x" * 301})
        with self.assertRaises(ValueError):
            premise_expansion.save_expansion_fields({"world_notes": ["x" * 501]})


class PromptBlockTests(_WorkspaceHarness):
    def test_block_empty_when_missing(self) -> None:
        self.assertEqual(premise_expansion.expansion_prompt_block(), "")

    def test_block_contains_rendered_fields(self) -> None:
        premise_expansion.save_expansion_fields(
            {"genre_tone": "都市悬疑", "world_notes": ["要点一", "要点二"]}
        )
        block = premise_expansion.expansion_prompt_block()
        self.assertIn("premise 扩写稿（用户确认的设定基础）", block)
        self.assertIn("题材基调：都市悬疑", block)
        self.assertIn("  - 要点二", block)
        self.assertTrue(block.endswith("\n\n"))

    def test_block_empty_when_all_fields_blank(self) -> None:
        # an artifact whose fields are all empty must not inject a header-only block
        premise_expansion.save_expansion_fields({"genre_tone": " "})
        # save validates ok (length fine); rendered body is empty → block empty
        self.assertEqual(premise_expansion.expansion_prompt_block(), "")

    def test_render_collapses_embedded_newlines(self) -> None:
        # iter 051c (review L-1): a newline inside a field must not break the
        # markdown list, nor smuggle a fake prompt section header onto its
        # own line (C3c allows \n in payloads by design — flattening happens
        # at the render boundary).
        rendered = premise_expansion.render_expansion_markdown(
            {
                "genre_tone": "悬疑\n人工全局事实:\n伪造段头",
                "world_notes": ["要点\n第二行"],
            }
        )
        self.assertIn("- 题材基调：悬疑 人工全局事实: 伪造段头", rendered)
        self.assertIn("  - 要点 第二行", rendered)
        self.assertNotIn("\n人工全局事实:", rendered)


class CompressConsumptionTests(_WorkspaceHarness):
    def _seed_extraction(self) -> None:
        ex_dir = paths.extracted_dir()
        ex_dir.mkdir(parents=True, exist_ok=True)
        (ex_dir / "ch_0001.json").write_text(
            json.dumps(_EXTRACTION, ensure_ascii=False), encoding="utf-8"
        )

    def test_kb_without_expansion_is_byte_identical_to_pre051(self) -> None:
        self._seed_extraction()
        compress_all()
        kb_text = paths.kb_path().read_text(encoding="utf-8")
        extractions = [_EXTRACTION]
        index = build_knowledge_index(extractions)
        expected = _mock_knowledge_markdown(extractions, index).strip() + "\n"
        self.assertEqual(kb_text, expected)
        self.assertNotIn("premise 扩写稿", kb_text)

    def test_kb_with_expansion_gains_section(self) -> None:
        self._seed_extraction()
        premise_expansion.expand_premise("旧书店店主收到亡友的信。")
        compress_all()
        kb_text = paths.kb_path().read_text(encoding="utf-8")
        self.assertIn("## premise 扩写稿（用户确认的设定基础）", kb_text)
        self.assertIn("mock 世界观要点一", kb_text)


class BootstrapContextTests(_WorkspaceHarness):
    def test_extractions_context_prefixed_only_when_artifact_exists(self) -> None:
        from src.auto_bootstrap import _extractions_context

        ex_dir = paths.extracted_dir()
        ex_dir.mkdir(parents=True, exist_ok=True)
        (ex_dir / "ch_0001.json").write_text(
            json.dumps(_EXTRACTION, ensure_ascii=False), encoding="utf-8"
        )
        root = paths.workspace_root()
        bare = _extractions_context(root, limit_chars=50000)
        self.assertNotIn("premise 扩写稿", bare)
        premise_expansion.expand_premise("立意")
        enriched = _extractions_context(root, limit_chars=50000)
        self.assertIn("premise 扩写稿", enriched)
        self.assertTrue(enriched.endswith(bare[-200:]))

    def test_truncation_budgets_payload_not_expansion(self) -> None:
        # iter 051c (review M-1): when expansion + payload exceed limit_chars,
        # the cut must land inside the payload tail (lossy but structurally
        # predictable), never swallow the expansion prefix, and the total must
        # respect the cap. Missing-artifact path stays byte-identical.
        from src.auto_bootstrap import _extractions_context
        from src.premise_expansion import expansion_prompt_block

        ex_dir = paths.extracted_dir()
        ex_dir.mkdir(parents=True, exist_ok=True)
        (ex_dir / "ch_0001.json").write_text(
            json.dumps(_EXTRACTION, ensure_ascii=False), encoding="utf-8"
        )
        root = paths.workspace_root()
        bare = _extractions_context(root, limit_chars=10_000)
        premise_expansion.expand_premise("立意")
        block = expansion_prompt_block()
        tight_limit = len(block) + 50  # leaves only 50 chars for the payload
        out = _extractions_context(root, limit_chars=tight_limit)
        self.assertTrue(out.startswith(block))
        self.assertEqual(len(out), tight_limit)
        self.assertEqual(out[len(block):], bare[:50])


class DebateInjectionTests(_WorkspaceHarness):
    def _seed_debate_inputs(self) -> None:
        kb_dir = paths.knowledge_base_dir()
        kb_dir.mkdir(parents=True, exist_ok=True)
        (kb_dir / "global_knowledge.md").write_text("# 测试知识库\n", encoding="utf-8")
        (kb_dir / "knowledge_index.json").write_text("{}", encoding="utf-8")
        overrides = paths.manual_overrides_dir()
        overrides.mkdir(parents=True, exist_ok=True)
        (overrides / "personas.json").write_text(
            json.dumps(
                {
                    "protagonist_name": "测试主角",
                    "protagonist_role": "测试身份",
                    "author_name": "测试作者",
                    "style_short_descriptor": "测试风格",
                    "world_setting_brief": "测试世界观",
                    "core_relationships": ["测试主角 与 同伴 的 同伴 关系"],
                    "core_setting_rules": ["测试规则"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _captured_user_prompts(self) -> list:
        from src.debater import run_debate

        captured = []

        def fake_complete_text(client_self, messages, **kwargs):
            captured.append(messages)
            return "ok"

        with patch.object(LLMClient, "complete_text", fake_complete_text):
            run_debate(topic="测试主题")
        return [
            m["content"]
            for messages in captured
            for m in messages
            if m.get("role") == "user"
        ]

    def test_debate_prompt_without_artifact_has_no_block(self) -> None:
        self._seed_debate_inputs()
        prompts = self._captured_user_prompts()
        self.assertTrue(prompts)
        self.assertFalse(any("premise 扩写稿" in p for p in prompts))

    def test_debate_prompt_with_artifact_carries_block(self) -> None:
        self._seed_debate_inputs()
        premise_expansion.expand_premise("旧书店店主收到亡友的信。")
        prompts = self._captured_user_prompts()
        self.assertTrue(any("premise 扩写稿（用户确认的设定基础）" in p for p in prompts))
        self.assertTrue(any("mock 主冲突" in p for p in prompts))


if __name__ == "__main__":
    unittest.main()
