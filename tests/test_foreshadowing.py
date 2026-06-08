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
        self.assertEqual(foreshadowing.overdue_must_resolve(3), [])  # 3-0 not > 3
        od = {it["description"] for it in foreshadowing.overdue_must_resolve(4)}
        self.assertEqual(od, {"MUST clue", "CLUE clue"})  # ambiguity excluded (not must_resolve)

    def test_gc_marks_expired_and_must_resolve_still_blocks(self) -> None:
        from src import foreshadowing

        foreshadowing.build_registry(ttl=3)
        report = foreshadowing.gc(10)
        self.assertEqual(len(report["expired"]), 3)  # all three open items past ttl
        od = {it["description"] for it in foreshadowing.overdue_must_resolve(10)}
        self.assertEqual(od, {"MUST clue", "CLUE clue"})  # expired must_resolve keep blocking

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
        od = foreshadowing.overdue_must_resolve(5)
        self.assertEqual({it["description"] for it in od}, {"MUST clue", "CLUE clue"})
        must = next(it for it in od if it["description"] == "MUST clue")
        self.assertTrue(foreshadowing.resolve(must["id"]))
        self.assertEqual({it["description"] for it in foreshadowing.overdue_must_resolve(5)}, {"CLUE clue"})

    def test_rebuild_merge_preserves_resolved(self) -> None:
        from src import foreshadowing

        foreshadowing.build_registry(ttl=3)
        must = self._by_desc()["MUST clue"]
        foreshadowing.resolve(must["id"])
        foreshadowing.build_registry(ttl=3)  # re-extract / re-seed
        self.assertEqual(self._by_desc()["MUST clue"]["status"], "resolved")  # decision survived

    def test_readiness_real_registry_blocks(self) -> None:
        # End-to-end (no patch): a built registry with overdue must-resolve clues
        # makes check_write_readiness emit the blocker. resume_from=5 -> current=4.
        from src import book_runner, foreshadowing

        foreshadowing.build_registry(ttl=1)
        r = book_runner.check_write_readiness(
            chapters=1,
            resume_from=5,
            require_start_point=False,
            require_plan=False,
            require_external_review=False,
        )
        self.assertTrue(any(b.startswith("foreshadowing_must_resolve_overdue") for b in r["blockers"]))

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


if __name__ == "__main__":
    unittest.main()
