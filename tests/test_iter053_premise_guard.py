"""iter 053（搭车项，052 实测缺口）：premise 扩写稿 6 字段非空校验。

052 真模型段二实录：shudian052 的扩写稿 genre_tone / world_notes /
central_conflict 空着落盘（schema 只有长度上限），靠 personas 兜底未出事。
本组钉死：空字段自动重试一次（带"必须补全"提示）→ 仍空照常落盘但记
record 层 ``_incomplete_fields`` 标记 → 标记不进 fields 层（load_expansion
的 Pydantic 反序列化）也不进 ``expansion_prompt_block`` 渲染面 → 手工补全
保存后摘牌。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import paths, premise_expansion
from src.llm_client import LLMClient
from src.schemas import PremiseExpansion


def _expansion(**overrides) -> PremiseExpansion:
    base = dict(
        genre_tone="",
        protagonist="店主周明",
        world_notes=[],
        central_conflict="",
        ending_anchor="第七天的真相",
        arc_hints=[],
    )
    base.update(overrides)
    return PremiseExpansion(**base)


def _full_expansion() -> PremiseExpansion:
    return _expansion(
        genre_tone="悬疑",
        world_notes=["旧书店", "亡友的信"],
        central_conflict="七天倒计时谋杀预言",
        arc_hints=["第一封信"],
    )


class _WorkspaceHarness(unittest.TestCase):
    WS = "expws053"

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


class EmptyFieldGuardTests(_WorkspaceHarness):
    def test_still_empty_after_retry_marks_record_level(self) -> None:
        with patch.object(
            LLMClient, "complete_json", side_effect=[_expansion(), _expansion()]
        ) as mock_json:
            record = premise_expansion.expand_premise("旧书店店主收到亡友的信。")
        # 重试发生过一次，且重试 prompt 带"必须补全"与缺失字段中文名。
        self.assertEqual(mock_json.call_count, 2)
        retry_prompt = mock_json.call_args_list[1].args[0][1]["content"]
        self.assertIn("必须全部补全", retry_prompt)
        self.assertIn("题材基调", retry_prompt)
        # 标记在 record 层，不在 fields 层（load_expansion 反序列化会炸）。
        self.assertEqual(
            record["_incomplete_fields"],
            ["genre_tone", "world_notes", "central_conflict", "arc_hints"],
        )
        self.assertNotIn("_incomplete_fields", record["fields"])
        on_disk = json.loads(
            paths.premise_expansion_path().read_text(encoding="utf-8")
        )
        self.assertEqual(on_disk["_incomplete_fields"], record["_incomplete_fields"])
        # load_expansion 照常可读（Pydantic 不被标记炸掉）。
        self.assertIsNotNone(premise_expansion.load_expansion())
        # 标记绝不进 prompt 渲染面（debate prompt 消费它，debater.py）。
        block = premise_expansion.expansion_prompt_block()
        self.assertNotIn("_incomplete", block)
        self.assertNotIn("题材基调", block)  # 空字段不渲染
        self.assertIn("店主周明", block)  # 非空字段照常渲染

    def test_retry_filling_fields_clears_marker(self) -> None:
        with patch.object(
            LLMClient, "complete_json", side_effect=[_expansion(), _full_expansion()]
        ) as mock_json:
            record = premise_expansion.expand_premise("立意 B")
        self.assertEqual(mock_json.call_count, 2)
        self.assertNotIn("_incomplete_fields", record)
        self.assertEqual(record["fields"]["genre_tone"], "悬疑")

    def test_full_first_draft_skips_retry(self) -> None:
        with patch.object(
            LLMClient, "complete_json", side_effect=[_full_expansion()]
        ) as mock_json:
            record = premise_expansion.expand_premise("立意 C")
        self.assertEqual(mock_json.call_count, 1)
        self.assertNotIn("_incomplete_fields", record)

    def test_retry_failure_falls_back_to_first_draft(self) -> None:
        # 重试炸了不影响主路径：带第一稿照常落盘 + 标记（fail-open）。
        with patch.object(
            LLMClient,
            "complete_json",
            side_effect=[_expansion(), RuntimeError("retry boom")],
        ):
            record = premise_expansion.expand_premise("立意 D")
        self.assertIn("_incomplete_fields", record)
        self.assertEqual(record["fields"]["protagonist"], "店主周明")

    def test_manual_save_recalculates_marker(self) -> None:
        with patch.object(
            LLMClient, "complete_json", side_effect=[_expansion(), _expansion()]
        ):
            premise_expansion.expand_premise("立意 E")
        # 手工只补一部分 → 标记重算后仍在（剩余空字段）。
        partial = premise_expansion.save_expansion_fields(
            {
                "genre_tone": "悬疑",
                "protagonist": "店主周明",
                "world_notes": ["旧书店"],
                "central_conflict": "",
                "ending_anchor": "第七天的真相",
                "arc_hints": [],
            }
        )
        self.assertEqual(
            partial["_incomplete_fields"], ["central_conflict", "arc_hints"]
        )
        # 全部补全 → 摘牌。
        full = premise_expansion.save_expansion_fields(
            {
                "genre_tone": "悬疑",
                "protagonist": "店主周明",
                "world_notes": ["旧书店"],
                "central_conflict": "七天倒计时",
                "ending_anchor": "第七天的真相",
                "arc_hints": ["第一封信"],
            }
        )
        self.assertNotIn("_incomplete_fields", full)


if __name__ == "__main__":
    unittest.main()
