"""iter 050: structured per-chapter plan edit (apply_chapter_plan_item_edit)
+ B-M-2 fingerprint whitelist refactor.

The edit path must keep the write-book fingerprint gate self-consistent by
construction: it merges whitelisted fields, validates via Pydantic, then
re-derives every fingerprint through the SAME ``_attach_plan_fingerprints``
entry that plan generation uses (the 048c rule — no write path hand-crafts
fingerprints). The whitelist refactor must be hash-compatible with the old
blacklist for canonical (model-produced) plan items, or every written
chapter in existing workspaces would strict-expire on upgrade.

Mock-only.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.plot_planner import (
    EDITABLE_PLAN_ITEM_FIELDS,
    _ITEM_FINGERPRINT_FIELDS,
    apply_chapter_plan_item_edit,
    chapter_plan_item_fingerprint,
    generate_chapter_plan,
    plan_fingerprint,
)
from src.utils import sha256_data


class FingerprintWhitelistTests(unittest.TestCase):
    """B-M-2: blacklist → whitelist must be byte-identical for canonical
    items, and immune to unknown future fields (the defensive payoff)."""

    CANONICAL_ITEM = {
        "chapter_no": 3,
        "title": "迷雾中的来信",
        "opening_scene": "雨夜，主角收到一封没有署名的信。",
        "key_events": ["收到匿名信", "发现信纸上的暗记"],
        "relationships_in_play": ["主角 ↔ 神秘寄信人"],
        "ending_hook": "信尾的落款是一个早已死去的人的名字。",
        "target_chinese_chars": 4000,
        "plot_purpose": "引入中段最大悬念。",
        "segments": [],
        "chapter_plan_item_fingerprint": "",
    }

    def _legacy_blacklist_fingerprint(self, item: dict) -> str:
        # Inline replica of the pre-050 blacklist filter, kept here so the
        # compatibility contract is pinned by a test, not by memory.
        stable = {
            key: value
            for key, value in dict(item).items()
            if key
            not in {
                "chapter_plan_item_fingerprint",
                "plan_fingerprint",
                "start_point_fingerprint",
                "segments",
            }
        }
        return sha256_data(stable)

    def test_whitelist_hash_equals_legacy_blacklist_for_canonical_item(self) -> None:
        item = dict(self.CANONICAL_ITEM)
        self.assertEqual(
            chapter_plan_item_fingerprint(item),
            self._legacy_blacklist_fingerprint(item),
        )

    def test_unknown_field_does_not_change_fingerprint(self) -> None:
        item = dict(self.CANONICAL_ITEM)
        baseline = chapter_plan_item_fingerprint(item)
        item["injected_future_field"] = "x"
        self.assertEqual(chapter_plan_item_fingerprint(item), baseline)
        # The legacy blacklist would have let this field poison the hash —
        # exactly the failure mode B-M-2 closes.
        self.assertNotEqual(self._legacy_blacklist_fingerprint(item), baseline)

    def test_editable_fields_is_whitelist_minus_chapter_no(self) -> None:
        self.assertEqual(
            EDITABLE_PLAN_ITEM_FIELDS,
            frozenset(_ITEM_FINGERPRINT_FIELDS) - {"chapter_no"},
        )


class ApplyChapterPlanItemEditTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmp.name)
        self.outline_path = tmp_path / "outline.md"
        self.plan_path = tmp_path / "chapter_plan.json"
        self.outline_path.write_text("# mock outline", encoding="utf-8")
        self._patches = [
            patch("src.plot_planner.OUTLINE_PATH", self.outline_path),
            patch("src.plot_planner.CHAPTER_PLAN_PATH", self.plan_path),
            # iter 053a 密闭性：不 patch DECISIONS_PATH 的话，repo 根 outputs/
            # debate/decisions.json（verify.sh 实跑残留，带起点指纹+outline
            # 哈希）会跟本测试的 tmp outline 撞 outline_content_mismatch 硬拦
            # ——setUp 中途抛异常还会让已 start 的 patch 永久泄漏，污染后续
            # 测试（workspace_isolation 连环挂的实录根因）。
            patch("src.plot_planner.DECISIONS_PATH", tmp_path / "decisions.json"),
        ]
        for p in self._patches:
            p.start()
        try:
            generate_chapter_plan(target_chapters=5, force=False)
        except BaseException:
            # setUp 失败时 unittest 不会调 tearDown——必须就地止血，防 patch 泄漏。
            for p in self._patches:
                p.stop()
            raise

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def _plan(self) -> dict:
        return json.loads(self.plan_path.read_text(encoding="utf-8"))

    def test_edit_keeps_fingerprints_self_consistent(self) -> None:
        before = self._plan()
        data = apply_chapter_plan_item_edit(2, {"title": "改后的标题"})
        self.assertEqual(data["chapters"][1]["title"], "改后的标题")
        # Gate self-consistency: every stored fingerprint matches a fresh
        # recomputation — _plan_metadata_failures would report nothing.
        on_disk = self._plan()
        self.assertEqual(on_disk["plan_fingerprint"], plan_fingerprint(on_disk))
        for item in on_disk["chapters"]:
            self.assertEqual(
                item["chapter_plan_item_fingerprint"],
                chapter_plan_item_fingerprint(item),
            )
        # The plan-level fingerprint changed (written chapters strict-expire:
        # accepted semantics) but NON-edited items stay byte-identical so
        # their item-level fingerprints survive.
        self.assertNotEqual(on_disk["plan_fingerprint"], before["plan_fingerprint"])
        self.assertEqual(on_disk["chapters"][0], before["chapters"][0])
        self.assertEqual(
            on_disk["chapters"][0]["chapter_plan_item_fingerprint"],
            before["chapters"][0]["chapter_plan_item_fingerprint"],
        )

    def test_edit_preserves_stored_start_point_fingerprint(self) -> None:
        # The stored start_point_fingerprint is what lets
        # book_runner._plan_metadata_failures detect "plan generated under a
        # different start point". The edit path must NOT refresh it from
        # live state — that would forge freshness.
        data = self._plan()
        data["start_point_fingerprint"] = "sentinel-from-plan-generation"
        self.plan_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        result = apply_chapter_plan_item_edit(1, {"title": "新标题"})
        self.assertEqual(
            result["start_point_fingerprint"], "sentinel-from-plan-generation"
        )
        # And plan_fingerprint is computed over the preserved value.
        self.assertEqual(result["plan_fingerprint"], plan_fingerprint(result))

    def test_edit_does_not_backfill_empty_start_point_fingerprint(self) -> None:
        # iter 050d (L-1): a plan generated WITHOUT a start point carries an
        # empty fingerprint. If a start point is configured later, editing a
        # chapter must NOT back-fill the live fingerprint — that would bless
        # a plan that was never generated under the current start point. The
        # gate fail-safes with start_point_fingerprint_missing instead.
        data = self._plan()
        data["start_point_fingerprint"] = ""
        self.plan_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        result = apply_chapter_plan_item_edit(1, {"title": "改标题"})
        self.assertEqual(result["start_point_fingerprint"], "")
        self.assertEqual(result["plan_fingerprint"], plan_fingerprint(result))

    def test_rejects_non_editable_field(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            apply_chapter_plan_item_edit(1, {"chapter_no": 9})
        self.assertIn("non-editable", str(ctx.exception))
        with self.assertRaises(ValueError):
            apply_chapter_plan_item_edit(1, {"segments": []})
        with self.assertRaises(ValueError):
            apply_chapter_plan_item_edit(1, {"chapter_plan_item_fingerprint": "x"})

    def test_rejects_out_of_range_values(self) -> None:
        for bad_fields in (
            {"target_chinese_chars": 2400},
            {"target_chinese_chars": 6100},
            {"key_events": ["只有一条"]},
            {"key_events": [f"事件{i}" for i in range(8)]},
        ):
            with self.assertRaises(ValueError, msg=f"accepted {bad_fields}"):
                apply_chapter_plan_item_edit(1, bad_fields)
        # And nothing was written: plan on disk still self-consistent and
        # chapter 1 unchanged.
        on_disk = self._plan()
        self.assertEqual(on_disk["plan_fingerprint"], plan_fingerprint(on_disk))

    def test_empty_fields_rejected(self) -> None:
        with self.assertRaises(ValueError):
            apply_chapter_plan_item_edit(1, {})

    def test_unknown_chapter_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            apply_chapter_plan_item_edit(99, {"title": "x"})

    def test_missing_plan_raises_filenotfounderror(self) -> None:
        self.plan_path.unlink()
        with self.assertRaises(FileNotFoundError):
            apply_chapter_plan_item_edit(1, {"title": "x"})


if __name__ == "__main__":
    unittest.main()
