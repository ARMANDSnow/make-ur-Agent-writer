"""iter 047c: tests for the foreshadowing TTL registry + GC + must-resolve gate.

knowledge_index fixtures cover the axes that matter:
* kind ∈ {unresolved, clue} -> must_resolve; kind=ambiguity -> not.
* messy resolved statuses (resolved_in_chunk) -> skipped at build.
TTL is in chapters; overdue = current - planted > ttl. must_resolve items keep
blocking write-readiness (even after gc marks them expired) until resolved.
build_registry is merge-additive (resolve decisions survive a re-extract).
Absent / corrupt registry -> no-op.
"""

import json
import os
import shutil
import unittest
from pathlib import Path


class ForeshadowingRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter047cfo"
        root = Path(__file__).resolve().parent.parent
        self.ws = root / "workspaces" / "iter047cfo"
        (self.ws / "data" / "knowledge_base").mkdir(parents=True, exist_ok=True)
        index = {
            "foreshadowing": [
                {"chapter_id": "s_ch001", "kind": "unresolved", "status": "unresolved", "description": "MUST clue"},
                {"chapter_id": "s_ch001", "kind": "clue", "status": "unresolved", "description": "CLUE clue"},
                {"chapter_id": "s_ch001", "kind": "ambiguity", "status": "unresolved", "description": "soft amb"},
                {"chapter_id": "s_ch002", "kind": "payoff", "status": "resolved", "description": "closed payoff"},
                {"chapter_id": "s_ch002", "kind": "clue", "status": "resolved_in_chunk", "description": "chunk done"},
            ]
        }
        (self.ws / "data" / "knowledge_base" / "knowledge_index.json").write_text(
            json.dumps(index, ensure_ascii=False), encoding="utf-8"
        )

    def tearDown(self) -> None:
        if self.ws.exists():
            shutil.rmtree(self.ws)
        if self._old is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old

    def _by_desc(self):
        from src import foreshadowing

        return {it["description"]: it for it in foreshadowing.load_registry()["items"]}

    def test_build_registry_kinds_and_skip_resolved(self) -> None:
        from src import foreshadowing

        foreshadowing.build_registry(ttl=3)
        d = self._by_desc()
        # clue + unresolved -> must_resolve; ambiguity -> not
        self.assertTrue(d["MUST clue"]["must_resolve"])
        self.assertTrue(d["CLUE clue"]["must_resolve"])
        self.assertFalse(d["soft amb"]["must_resolve"])
        # resolved (incl. messy 'resolved_in_chunk') skipped
        self.assertNotIn("closed payoff", d)
        self.assertNotIn("chunk done", d)

    def test_no_registry_is_noop(self) -> None:
        from src import foreshadowing

        self.assertFalse(foreshadowing.registry_exists())
        self.assertEqual(foreshadowing.overdue_must_resolve(99), [])

    def test_corrupt_registry_is_noop(self) -> None:
        from src import foreshadowing, paths

        paths.foreshadowing_registry_path().write_text("{bad json", encoding="utf-8")
        self.assertEqual(foreshadowing.overdue_must_resolve(99), [])  # fail-open, no crash

    def test_overdue_only_after_ttl(self) -> None:
        from src import foreshadowing

        foreshadowing.build_registry(ttl=3)
        # iter077: seeded items are source-boundary (planted 0) -> excluded from
        # the gating list by default; visible via include_boundary / advisory.
        self.assertEqual(foreshadowing.overdue_must_resolve(4), [])
        self.assertEqual(foreshadowing.overdue_must_resolve(3, include_boundary=True), [])  # 3-0 not > 3
        od = {it["description"] for it in foreshadowing.overdue_must_resolve(4, include_boundary=True)}
        self.assertEqual(od, {"MUST clue", "CLUE clue"})  # ambiguity excluded (not must_resolve)
        adv = {it["description"] for it in foreshadowing.boundary_overdue_must_resolve(4)}
        self.assertEqual(adv, {"MUST clue", "CLUE clue"})

    def test_gc_marks_expired_and_must_resolve_still_blocks(self) -> None:
        from src import foreshadowing

        foreshadowing.build_registry(ttl=3)
        report = foreshadowing.gc(10)
        self.assertEqual(len(report["expired"]), 3)  # all three open items past ttl
        # expired must_resolve stay in the (boundary-advisory) overdue list
        od = {it["description"] for it in foreshadowing.boundary_overdue_must_resolve(10)}
        self.assertEqual(od, {"MUST clue", "CLUE clue"})

    def test_gc_no_change_does_not_overwrite(self) -> None:
        from src import foreshadowing, paths

        foreshadowing.build_registry(ttl=99)
        path = paths.foreshadowing_registry_path()
        before = path.read_text(encoding="utf-8")
        foreshadowing.gc(1)  # nothing overdue
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_resolve_clears_overdue(self) -> None:
        from src import foreshadowing

        foreshadowing.build_registry(ttl=1)
        od = foreshadowing.boundary_overdue_must_resolve(5)
        self.assertEqual({it["description"] for it in od}, {"MUST clue", "CLUE clue"})
        must = next(it for it in od if it["description"] == "MUST clue")
        self.assertTrue(foreshadowing.resolve(must["id"]))
        self.assertEqual(
            {it["description"] for it in foreshadowing.boundary_overdue_must_resolve(5)},
            {"CLUE clue"},
        )

    def test_rebuild_merge_preserves_resolved(self) -> None:
        from src import foreshadowing

        foreshadowing.build_registry(ttl=3)
        must = self._by_desc()["MUST clue"]
        foreshadowing.resolve(must["id"])
        foreshadowing.build_registry(ttl=3)  # re-extract / re-seed
        self.assertEqual(self._by_desc()["MUST clue"]["status"], "resolved")  # decision survived

    def test_readiness_boundary_registry_warns_not_blocks(self) -> None:
        # iter077 P0-1 end-to-end (no patch): a built registry seeds only
        # source-boundary items (planted 0) — overdue ones must surface as a
        # WARNING, never a blocker (pre-fix this deterministically killed every
        # 14+-chapter continuation at a segment boundary). resume_from=5 -> current=4.
        from src import book_runner, foreshadowing

        foreshadowing.build_registry(ttl=1)
        r = book_runner.check_write_readiness(
            chapters=1,
            resume_from=5,
            require_start_point=False,
            require_plan=False,
            require_external_review=False,
        )
        self.assertFalse(any(b.startswith("foreshadowing_must_resolve_overdue") for b in r["blockers"]))
        self.assertTrue(any(w.startswith("foreshadowing_boundary_overdue") for w in r["warnings"]))
        self.assertNotEqual(r["status"], "blocked")

    def test_readiness_deep_resume_not_blocked_by_boundary_seeds(self) -> None:
        # The capstone shape itself: default ttl=12, resume deep past it
        # (segment start ch16 -> current=15 > 12). Must NOT block.
        from src import book_runner, foreshadowing

        foreshadowing.build_registry()  # default ttl
        r = book_runner.check_write_readiness(
            chapters=5,
            resume_from=16,
            require_start_point=False,
            require_plan=False,
            require_external_review=False,
        )
        self.assertFalse(any(b.startswith("foreshadowing_must_resolve_overdue") for b in r["blockers"]))

    def test_readiness_continuation_planted_still_blocks(self) -> None:
        # fail-closed preserved: a clue planted DURING the continuation
        # (planted_chapter >= 1, e.g. hand-armed) still gates once past TTL.
        from src import book_runner, foreshadowing, paths
        from src.utils import write_json

        foreshadowing.build_registry(ttl=1)
        data = foreshadowing.load_registry()
        armed = next(it for it in data["items"] if it["description"] == "MUST clue")
        armed["planted_chapter"] = 2  # re-armed by hand (escape hatch)
        write_json(paths.foreshadowing_registry_path(), data)
        r = book_runner.check_write_readiness(
            chapters=1,
            resume_from=5,  # current=4; 4-2=2 > ttl=1 -> overdue
            require_start_point=False,
            require_plan=False,
            require_external_review=False,
        )
        self.assertTrue(any(b.startswith("foreshadowing_must_resolve_overdue:1") for b in r["blockers"]))

    def test_expired_continuation_item_stays_gating(self) -> None:
        # 铁律⑨审查补覆盖（迁移丢失面）：gc 过（status=expired）的续写新种
        # must_resolve 项必须仍在闸门列表——047B2 M3 的 fail-closed 承诺对
        # planted>=1 路径持续有测试守护。
        from src import foreshadowing, paths
        from src.utils import write_json

        write_json(
            paths.foreshadowing_registry_path(),
            {
                "version": 1,
                "items": [
                    {"id": "fo_exp", "description": "expired cont", "kind": "clue",
                     "planted_chapter": 1, "ttl": 1, "must_resolve": True, "status": "expired"}
                ],
            },
        )
        self.assertEqual([it["id"] for it in foreshadowing.overdue_must_resolve(50)], ["fo_exp"])

    def test_unparseable_planted_stays_gating(self) -> None:
        # fail-closed: planted_chapter that can't be parsed must NOT be silently
        # exempted as boundary — it stays in the gating list.
        from src import foreshadowing, paths
        from src.utils import write_json

        write_json(
            paths.foreshadowing_registry_path(),
            {
                "version": 1,
                "items": [
                    {"id": "fo_bad", "description": "bad planted", "kind": "clue",
                     "planted_chapter": "unknown", "ttl": 1, "must_resolve": True, "status": "open"}
                ],
            },
        )
        self.assertEqual([it["id"] for it in foreshadowing.overdue_must_resolve(50)], ["fo_bad"])
        self.assertEqual(foreshadowing.boundary_overdue_must_resolve(50), [])

    def test_readiness_first_chapter_does_not_block(self) -> None:
        # off-by-one: at resume_from=1 (current=0) nothing is overdue regardless.
        from src import book_runner, foreshadowing

        foreshadowing.build_registry(ttl=1)
        r = book_runner.check_write_readiness(
            chapters=1,
            resume_from=1,
            require_start_point=False,
            require_plan=False,
            require_external_review=False,
        )
        self.assertFalse(any(b.startswith("foreshadowing_must_resolve_overdue") for b in r["blockers"]))

    def test_blocker_kind_and_primary_label(self) -> None:
        from src.book_runner import _blocker_kind, _primary_blocker

        self.assertEqual(_blocker_kind("foreshadowing_must_resolve_overdue:3"), "foreshadowing_overdue")
        pb = _primary_blocker(["foreshadowing_must_resolve_overdue:3"])
        self.assertEqual(pb["kind"], "foreshadowing_overdue")
        self.assertIn("伏笔", pb["label"])
        self.assertEqual(pb["cta_action"], "show_diagnostics")  # no dead CTA


class Iter078OriginFieldTests(unittest.TestCase):
    """iter078 技债-2：boundary 判定改显式 origin 字段优先。

    动机（iter077 审查提名）：planted_chapter<=0 猜测下，未来「续写回灌
    compress」的新种伏笔会生而 advisory、闸门静默失效。origin 优先 +
    无 origin 回落旧启发式（存量 registry 零迁移）。"""

    def test_origin_source_book_respects_rearm_escape_hatch(self) -> None:
        from src import foreshadowing

        # source_book 出身走 planted 启发式：planted=0 豁免、改正数 = iter077
        # 逃生门重新武装（origin 不无条件压过它）。
        self.assertTrue(
            foreshadowing.is_boundary_item({"origin": "source_book", "planted_chapter": 0})
        )
        self.assertFalse(
            foreshadowing.is_boundary_item({"origin": "source_book", "planted_chapter": 5})
        )

    def test_origin_continuation_gates_even_at_planted_zero(self) -> None:
        from src import foreshadowing

        # 未来续写回灌路径的新种项：即使 planted_chapter=0 形态也必须进闸门
        item = {"origin": "continuation", "planted_chapter": 0}
        self.assertFalse(foreshadowing.is_boundary_item(item))

    def test_missing_or_garbage_origin_falls_back_to_planted_heuristic(self) -> None:
        from src import foreshadowing

        # 存量 registry（iter078 前）三形态回落旧启发式
        self.assertTrue(foreshadowing.is_boundary_item({"planted_chapter": 0}))
        self.assertFalse(foreshadowing.is_boundary_item({"planted_chapter": 1}))
        # unparseable planted 仍不豁免（fail-closed，iter047B2 H3）
        self.assertFalse(foreshadowing.is_boundary_item({"planted_chapter": "abc"}))
        # 非法 origin 同样回落
        self.assertTrue(
            foreshadowing.is_boundary_item({"origin": "weird", "planted_chapter": 0})
        )
        self.assertFalse(
            foreshadowing.is_boundary_item({"origin": "weird", "planted_chapter": 2})
        )


class Iter078OriginSeedingTests(unittest.TestCase):
    """build_registry 播种必须带 origin=source_book（独立 fixture，不复跑父类）。"""

    def setUp(self) -> None:
        self._old = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter078fo"
        root = Path(__file__).resolve().parent.parent
        self.ws = root / "workspaces" / "iter078fo"
        (self.ws / "data" / "knowledge_base").mkdir(parents=True, exist_ok=True)
        index = {
            "foreshadowing": [
                {"chapter_id": "s_ch001", "kind": "clue", "status": "unresolved", "description": "种子A"},
            ]
        }
        (self.ws / "data" / "knowledge_base" / "knowledge_index.json").write_text(
            json.dumps(index, ensure_ascii=False), encoding="utf-8"
        )

    def tearDown(self) -> None:
        if self.ws.exists():
            shutil.rmtree(self.ws)
        if self._old is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old

    def test_seeded_items_carry_source_book_origin(self) -> None:
        from src import foreshadowing

        foreshadowing.build_registry(ttl=3)
        items = foreshadowing.load_registry()["items"]
        self.assertTrue(items)
        for item in items:
            self.assertEqual(item.get("origin"), "source_book")


if __name__ == "__main__":
    unittest.main()
