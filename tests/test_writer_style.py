"""iter 056 轨 A: 作家风格卡数据层——schema 长度门、预置库完整性 +
graceful degrade、快照独立性、artifact lifecycle、注入 block 的仅-premise
边界与字节自带分隔。Mock-only（不联网、不真模型）。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from src import paths, writer_style
from src.schemas import WriterStyleCard


class WriterStyleCardSchemaTests(unittest.TestCase):
    """纯 schema + 纯函数渲染，无需 workspace。"""

    def test_name_length_gate(self) -> None:
        with self.assertRaises(ValidationError):
            WriterStyleCard(name="字" * 41)

    def test_imagery_length_gate(self) -> None:
        with self.assertRaises(ValidationError):
            WriterStyleCard(imagery="字" * 301)

    def test_taboo_item_length_gate(self) -> None:
        with self.assertRaises(ValidationError):
            WriterStyleCard(taboo=["字" * 301])

    def test_taboo_count_gate(self) -> None:
        with self.assertRaises(ValidationError):
            WriterStyleCard(taboo=["一句"] * 13)

    def test_valid_card_ok(self) -> None:
        card = WriterStyleCard(name="冷峻", rhythm="快节奏", signatures=["手法一", "手法二"])
        self.assertEqual(card.name, "冷峻")
        self.assertEqual(len(card.signatures), 2)

    def test_render_folds_newlines_and_lists(self) -> None:
        md = writer_style.render_card_markdown(
            {"rhythm": "第一行\n第二行", "signatures": ["手法一", "手法二"]}
        )
        self.assertIn("- 叙事节奏：第一行 第二行", md)
        self.assertIn("  - 手法一", md)
        self.assertIn("  - 手法二", md)
        # 内嵌换行被折叠，不会破坏可缓存段结构
        self.assertNotIn("第一行\n第二行", md)

    def test_render_empty_fields_empty(self) -> None:
        self.assertEqual(writer_style.render_card_markdown({}), "")


class StylePresetsTests(unittest.TestCase):
    def test_builtin_library_complete(self) -> None:
        presets = writer_style.load_presets()
        self.assertEqual(len(presets), 6)
        ids = [p["id"] for p in presets]
        self.assertEqual(len(ids), len(set(ids)), "preset id 必须唯一")
        for p in presets:
            self.assertTrue(p["card"]["name"], f"{p['id']} name 非空")
            self.assertTrue(p["card"]["category"], f"{p['id']} category 非空")
            # 每张 card 都能过 schema（load_presets 已校验并规整）
            WriterStyleCard(**p["card"])

    def test_missing_library_returns_empty(self) -> None:
        with patch("src.writer_style.load_config", return_value={}):
            self.assertEqual(writer_style.load_presets(), [])

    def test_bad_card_and_dup_id_skipped(self) -> None:
        lib = {
            "schema_version": 1,
            "presets": [
                {"id": "good", "card": {"name": "好卡"}},
                {"id": "bad", "card": {"name": "字" * 41}},  # 超长 → 跳过
                {"id": "good", "card": {"name": "重复 id"}},  # 重复 → 跳过
                "not a dict",  # 非 dict → 跳过
                {"id": "", "card": {"name": "空 id"}},  # 空 id → 跳过
            ],
        }
        with patch("src.writer_style.load_config", return_value=lib):
            presets = writer_style.load_presets()
            self.assertEqual([p["id"] for p in presets], ["good"])


class _WorkspaceHarness(unittest.TestCase):
    """Tmp workspace via WORKSPACE_NAME so paths.* resolve into it."""

    WS = "stylews"

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


class ActivateAndLoadTests(_WorkspaceHarness):
    def test_activate_snapshots_fields_not_reference(self) -> None:
        rec = writer_style.activate_preset("classical_wuxia")
        self.assertEqual(rec["source"], "preset")
        self.assertEqual(rec["preset_id"], "classical_wuxia")
        self.assertFalse(rec["edited"])
        self.assertEqual(rec["fields"]["name"], "古典武侠")
        # 快照独立性：即便预置库此后“清空/升级”，已激活卡仍读自己的快照
        with patch("src.writer_style.load_config", return_value={"schema_version": 9, "presets": []}):
            self.assertEqual(writer_style.load_presets(), [])
            card = writer_style.load_card()
            self.assertEqual(card["fields"]["name"], "古典武侠")

    def test_activate_unknown_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            writer_style.activate_preset("no_such_preset")

    def test_load_card_missing_returns_none(self) -> None:
        self.assertIsNone(writer_style.load_card())

    def test_load_card_corrupt_json_returns_none(self) -> None:
        path = paths.writer_style_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(writer_style.load_card())

    def test_load_card_bad_schema_returns_none(self) -> None:
        path = paths.writer_style_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fields": {"taboo": ["字" * 301]}}), encoding="utf-8")
        self.assertIsNone(writer_style.load_card())


class SaveCardTests(_WorkspaceHarness):
    def test_save_from_scratch_manual(self) -> None:
        rec = writer_style.save_card_fields({"name": "我的风格", "rhythm": "快"})
        self.assertEqual(rec["source"], "manual")
        self.assertTrue(rec["edited"])
        self.assertEqual(rec["scope"], "book")
        reloaded = writer_style.load_card()
        self.assertEqual(reloaded["fields"]["name"], "我的风格")

    def test_save_invalid_raises_valueerror(self) -> None:
        with self.assertRaises(ValueError):
            writer_style.save_card_fields({"name": "字" * 41})

    def test_edit_preserves_preset_source(self) -> None:
        writer_style.activate_preset("humor_satire")
        rec = writer_style.save_card_fields({"name": "改名", "rhythm": "改节奏"})
        self.assertEqual(rec["source"], "preset")  # 来源保留
        self.assertEqual(rec["preset_id"], "humor_satire")
        self.assertTrue(rec["edited"])


class PromptBlockTests(_WorkspaceHarness):
    def test_block_empty_for_continuation_book(self) -> None:
        writer_style.activate_preset("cold_scifi")  # 即便有卡
        with patch("src.writer_style.start_point.get_start_chapter_id", return_value="ch_0005"):
            self.assertEqual(writer_style.writer_style_prompt_block(), "")

    def test_block_empty_when_no_card(self) -> None:
        # premise 书（无起点）但无卡
        with patch("src.writer_style.start_point.get_start_chapter_id", return_value=None):
            self.assertEqual(writer_style.writer_style_prompt_block(), "")

    def test_block_injects_for_premise_with_card(self) -> None:
        writer_style.activate_preset("cold_scifi")
        with patch("src.writer_style.start_point.get_start_chapter_id", return_value=None):
            block = writer_style.writer_style_prompt_block()
        self.assertIn("作家风格卡", block)
        self.assertIn("冷峻科幻", block)
        self.assertIn("以系统戒律为准", block)
        self.assertTrue(block.endswith("\n\n"), "block 自带尾部分隔")

    def test_block_empty_on_bad_card(self) -> None:
        path = paths.writer_style_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{corrupt", encoding="utf-8")
        with patch("src.writer_style.start_point.get_start_chapter_id", return_value=None):
            self.assertEqual(writer_style.writer_style_prompt_block(), "")


if __name__ == "__main__":
    unittest.main()
