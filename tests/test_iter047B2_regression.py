"""iter047B2: regression tests for the H/M defects found in the iter046-047
adversarial acceptance pass. Each test reproduces a confirmed pre-fix failure
and locks in the fix. Mock-only; workspace fixtures mirror test_kb_view /
test_foreshadowing.

Coverage:
* H1  corrupt knowledge_index.json -> fail-open to raw KB (not JSONDecodeError)
* H1b corrupt manifest / start_chapter.json -> fail-open (no crash)
* H2  start set but manifest missing -> fail-closed to raw KB (no fake
      "起点安全" header, no post-start spoiler leak)
* M5  character state picks the manifest-nearest pre-start entry, not array tail
* H3  malformed ttl in registry keeps the must-resolve gate CLOSED (not silently
      open via book_runner's swallowed exception)
* M1  a reworded clue does not resurrect a human-resolved item
* M2  'irresolvable' status stays tracked (still-open), not skipped as resolved
* M3  unknown / wrong-case status still blocks once past TTL
* M4  negative min_chars does not spin the assembler to its 100k guard
* M6  preflight surfaces open (not just expired) must-resolve foreshadowing
* M7  readiness KB warning uses the injection paths (_kb_path/_index_path)
* M8  segment position is authoritative for is_final (mis-flagged plan ignored)
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
RAW_KB = "RAW PROSE KB 全书压缩，含 LATE_RULE_SPOILER 起点之后内容。\n"


def _write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


class _WorkspaceCase(unittest.TestCase):
    """Shared fixture: manifest s_ch001..s_ch003 + raw KB + a structured index."""

    ws_name = "iter047b2ws"

    def setUp(self) -> None:
        self._old = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = self.ws_name
        self.ws = REPO / "workspaces" / self.ws_name
        (self.ws / "data" / "manual_overrides").mkdir(parents=True, exist_ok=True)
        (self.ws / "data" / "knowledge_base").mkdir(parents=True, exist_ok=True)
        _write_json(
            self.ws / "data" / "chapter_manifest.json",
            [
                {"chapter_id": "s_ch001", "volume_id": "s", "title": "1"},
                {"chapter_id": "s_ch002", "volume_id": "s", "title": "2"},
                {"chapter_id": "s_ch003", "volume_id": "s", "title": "3"},
            ],
        )
        self.kb = self.ws / "data" / "knowledge_base" / "global_knowledge.md"
        self.kb.write_text(RAW_KB, encoding="utf-8")
        self.index = self.ws / "data" / "knowledge_base" / "knowledge_index.json"
        _write_json(
            self.index,
            {
                "characters": {
                    "甲": [
                        {"chapter_id": "s_ch001", "after": "EARLY_CHAR_STATE"},
                        {"chapter_id": "s_ch003", "after": "LATE_CHAR_SPOILER"},
                    ]
                },
                "relationships": [
                    {"chapter_id": "s_ch001", "characters": ["甲", "乙"], "after": "EARLY_BOND"},
                    {"chapter_id": "s_ch003", "characters": ["甲", "丙"], "after": "LATE_RIVALRY_SPOILER"},
                ],
                "foreshadowing": [
                    {"chapter_id": "s_ch001", "kind": "clue", "status": "open", "description": "EARLY_CLUE"},
                    {"chapter_id": "s_ch003", "kind": "clue", "status": "open", "description": "LATE_CLUE_SPOILER"},
                ],
                "worldbuilding": [
                    {"chapter_id": "s_ch001", "topic": "规则一", "detail": "EARLY_RULE"},
                    {"chapter_id": "s_ch003", "topic": "规则二", "detail": "LATE_RULE_SPOILER"},
                ],
                "style_samples": [],
            },
        )

    def tearDown(self) -> None:
        if self.ws.exists():
            shutil.rmtree(self.ws)
        if self._old is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old


class KbViewHardeningTests(_WorkspaceCase):
    ws_name = "iter047b2kb"

    def test_h1_corrupt_index_fails_open_to_raw_kb(self) -> None:
        from src import start_point
        from src.kb_view import start_safe_knowledge

        start_point.set_start_point("s_ch002")
        self.index.write_text("{corrupt not json", encoding="utf-8")
        # pre-fix: JSONDecodeError propagated; post-fix: fail-open to raw KB
        self.assertEqual(start_safe_knowledge(), RAW_KB)

    def test_h1b_corrupt_manifest_fails_open(self) -> None:
        from src import start_point
        from src.kb_view import start_safe_knowledge

        start_point.set_start_point("s_ch002")
        (self.ws / "data" / "chapter_manifest.json").write_text("[bad json", encoding="utf-8")
        # corrupt manifest -> order empty -> start not locatable -> raw KB, no crash
        self.assertEqual(start_safe_knowledge(), RAW_KB)

    def test_h1b_corrupt_start_point_fails_open(self) -> None:
        from src import start_point
        from src.kb_view import start_safe_knowledge

        (self.ws / "data" / "manual_overrides" / "start_chapter.json").write_text("{bad", encoding="utf-8")
        self.assertIsNone(start_point.get_start_chapter_id())  # no crash, treated as unset
        self.assertEqual(start_safe_knowledge(), RAW_KB)

    def test_h2_missing_manifest_fails_closed_no_fake_safe_header(self) -> None:
        from src import start_point
        from src.kb_view import start_safe_knowledge

        start_point.set_start_point("s_ch002")
        (self.ws / "data" / "chapter_manifest.json").unlink()
        out = start_safe_knowledge()
        # pre-fix: a block headed "起点安全" that leaked all LATE_* canon;
        # post-fix: raw KB (no fake safe header, no structured leak)
        self.assertEqual(out, RAW_KB)
        self.assertNotIn("起点安全", out)
        for spoiler in ("LATE_CHAR_SPOILER", "LATE_RIVALRY_SPOILER", "LATE_CLUE_SPOILER"):
            self.assertNotIn(spoiler, out)

    def test_m5_kept_state_uses_manifest_order_not_array_tail(self) -> None:
        from src import start_point
        from src.kb_view import start_safe_knowledge

        # 甲's states are in REVERSE manifest order in the array; both pre-start.
        _write_json(
            self.index,
            {
                "characters": {
                    "甲": [
                        {"chapter_id": "s_ch002", "after": "NEAR_START_STATE"},
                        {"chapter_id": "s_ch001", "after": "FAR_OLD_STATE"},
                    ]
                }
            },
        )
        start_point.set_start_point("s_ch003")
        out = start_safe_knowledge()
        # post-fix: nearest-in-manifest (s_ch002) wins, not the array tail (s_ch001)
        self.assertIn("NEAR_START_STATE", out)
        self.assertNotIn("FAR_OLD_STATE", out)


class ForeshadowingGateHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter047b2fo"
        self.ws = REPO / "workspaces" / "iter047b2fo"
        (self.ws / "data" / "knowledge_base").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.ws.exists():
            shutil.rmtree(self.ws)
        if self._old is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old

    def _seed_index(self, foreshadowing) -> None:
        _write_json(
            self.ws / "data" / "knowledge_base" / "knowledge_index.json",
            {"foreshadowing": foreshadowing},
        )

    def test_h3_malformed_ttl_keeps_gate_closed(self) -> None:
        from src import book_runner, foreshadowing, paths

        _write_json(
            paths.foreshadowing_registry_path(),
            {
                "version": 1,
                "items": [
                    {
                        "id": "fo_x",
                        "description": "bad ttl clue",
                        "kind": "clue",
                        "planted_chapter": 0,
                        "ttl": "soon",  # non-int
                        "must_resolve": True,
                        "status": "open",
                    }
                ],
            },
        )
        # pre-fix: int("soon") raised -> book_runner swallowed -> ready (leak).
        od = foreshadowing.overdue_must_resolve(50)
        self.assertEqual([it["id"] for it in od], ["fo_x"])
        r = book_runner.check_write_readiness(
            chapters=1,
            resume_from=50,
            require_start_point=False,
            require_plan=False,
            require_external_review=False,
        )
        self.assertTrue(any(b.startswith("foreshadowing_must_resolve_overdue") for b in r["blockers"]))

    def test_m1_reword_does_not_resurrect_resolved(self) -> None:
        from src import foreshadowing

        self._seed_index([{"chapter_id": "s_ch001", "kind": "clue", "status": "open", "description": "the locket holds a photo"}])
        foreshadowing.build_registry(ttl=3)
        item = foreshadowing.load_registry()["items"][0]
        foreshadowing.resolve(item["id"])
        # re-extract reworded the description (trailing period + extra space)
        self._seed_index([{"chapter_id": "s_ch001", "kind": "clue", "status": "open", "description": "the locket holds a photo. "}])
        foreshadowing.build_registry(ttl=3)
        items = foreshadowing.load_registry()["items"]
        # post-fix: id stable under normalization -> single item, stays resolved
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "resolved")

    def test_m2_irresolvable_status_still_tracked(self) -> None:
        from src import foreshadowing

        self._seed_index([{"chapter_id": "s_ch001", "kind": "clue", "status": "irresolvable", "description": "IRRES clue"}])
        foreshadowing.build_registry(ttl=3)
        descs = {it["description"] for it in foreshadowing.load_registry()["items"]}
        self.assertIn("IRRES clue", descs)  # pre-fix: skipped as 'resolved'

    def test_m3_unknown_and_wrongcase_status_still_blocks(self) -> None:
        from src import foreshadowing, paths

        _write_json(
            paths.foreshadowing_registry_path(),
            {
                "version": 1,
                "items": [
                    {"id": "fo_def", "description": "deferred clue", "kind": "clue", "planted_chapter": 0, "ttl": 1, "must_resolve": True, "status": "deferred"},
                    {"id": "fo_cap", "description": "capital open", "kind": "clue", "planted_chapter": 0, "ttl": 1, "must_resolve": True, "status": "Open"},
                ],
            },
        )
        ids = {it["id"] for it in foreshadowing.overdue_must_resolve(50)}
        self.assertEqual(ids, {"fo_def", "fo_cap"})  # pre-fix: both slipped past


class ContextBudgetHardeningTests(unittest.TestCase):
    def test_m4_negative_min_chars_does_not_spin(self) -> None:
        from src.context_budget import Layer, assemble

        calls = {"n": 0}

        def counter(s: str) -> int:
            calls["n"] += 1
            return len(s)

        # empty soft layer with negative min_chars + a hard layer over budget:
        # pre-fix spun to the 100k guard (~200k counter calls); post-fix converges.
        out = assemble(
            [Layer("kb", "", priority=1, min_chars=-1), Layer("ctx", "x" * 1000, priority=9, hard=True)],
            budget_tokens=10,
            token_counter=counter,
        )
        self.assertLess(calls["n"], 50)
        self.assertIn("x" * 1000, out)  # hard layer preserved


class PreflightForeshadowingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter047b2pf"
        self.ws = REPO / "workspaces" / "iter047b2pf"
        (self.ws / "data").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.ws.exists():
            shutil.rmtree(self.ws)
        if self._old is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old

    def test_m6_open_must_resolve_is_warned(self) -> None:
        from src import paths
        from src.preflight import _check_foreshadowing_registry

        _write_json(
            paths.foreshadowing_registry_path(),
            {
                "version": 1,
                "items": [
                    {"id": "fo_o", "description": "open must", "kind": "clue", "planted_chapter": 0, "ttl": 5, "must_resolve": True, "status": "open"}
                ],
            },
        )
        warn, info = [], []
        _check_foreshadowing_registry(warn, info, self.ws)
        # pre-fix: only 'expired' counted -> 0 warning while the gate could block.
        self.assertTrue(warn, msg="open must-resolve should warn")
        self.assertTrue(any("open=1" in i for i in info))


class BookRunnerPathTests(unittest.TestCase):
    # No manifest here (a manifest would drive preflight's _check_longest_chapter,
    # which needs richer entries) — this test isolates the KB-warning path.
    def setUp(self) -> None:
        self._old = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter047b2br"
        self.ws = REPO / "workspaces" / "iter047b2br"
        (self.ws / "data").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.ws.exists():
            shutil.rmtree(self.ws)
        if self._old is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old

    def test_m7_readiness_kb_warning_uses_injection_paths(self) -> None:
        from src import book_runner

        tmp = Path(tempfile.mkdtemp())
        try:
            kb = tmp / "global_knowledge.md"
            kb.write_text("kb", encoding="utf-8")
            idx = tmp / "knowledge_index.json"  # intentionally absent
            # pre-fix the warning checked a CWD-relative Path("."); post-fix it
            # follows _kb_path/_index_path, so patching them must change the result.
            with patch.object(book_runner, "_kb_path", lambda: kb), patch.object(
                book_runner, "_index_path", lambda: idx
            ), patch.object(book_runner.start_point, "get_start_chapter_id", lambda: "s_ch002"):
                r = book_runner.check_write_readiness(
                    chapters=1,
                    resume_from=1,
                    require_start_point=False,
                    require_plan=False,
                    require_external_review=False,
                )
            self.assertTrue(
                any("knowledge_index.json" in w for w in r["warnings"]),
                msg=f"warnings={r['warnings']}",
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class WriterSegmentTests(unittest.TestCase):
    def test_m8_position_is_authoritative_for_is_final(self) -> None:
        from src.writer import _segment_directive_block

        # non-final position, but the plan mis-flags is_final=True
        mid = _segment_directive_block(
            segment={"beat": "b", "is_final": True}, segment_index=1, segment_total=3, prior_segments_text=""
        )
        self.assertIn("本段不是最后一段", mid)
        self.assertNotIn("本段是本章最后一段", mid)
        # final position wins even if the plan says is_final=False
        last = _segment_directive_block(
            segment={"beat": "b", "is_final": False}, segment_index=3, segment_total=3, prior_segments_text=""
        )
        self.assertIn("本段是本章最后一段", last)


if __name__ == "__main__":
    unittest.main()
