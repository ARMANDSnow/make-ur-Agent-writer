"""iter 050 (B3): KB + entity_graph edit surfaces.

KB PUT deliberately keeps the workbench mtime-chain semantics: saving the
KB makes downstream outline/plan stale (048b red-team fix ③) — pinned here
so a future "convenience" mtime hack can't silently revive the
"old artifact masquerades as new" trap. Entity edits enforce the field
whitelist: id/type/src_id/dst_id/relation_type and timeline
chapter_id/order/active stay immutable (spoiler filter + advance chain
key off them, entities.py).

Mock-only.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from src import paths
from src.web import jobs, routes


class KbEntityEditTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        jobs.reset_for_tests()
        self._tmp.cleanup()

    # ---- helpers -----------------------------------------------------------

    def _premise(self, ws: str) -> None:
        status, _ct, resp = routes.dispatch(
            "POST",
            "/api/wizard/premise-start",
            json.dumps(
                {"workspace": ws, "premise": "少年觉醒上古血脉，逆天改命。"},
                ensure_ascii=False,
            ).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 202, resp.decode("utf-8"))

    def _wait_for_done(self, ws: str, job_id: str, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, _, body = routes.dispatch("GET", f"/api/workspace/{ws}/job/{job_id}")
            rec = json.loads(body)
            if rec.get("status") in ("succeeded", "blocked", "failed", "aborted", "lost"):
                return rec
            time.sleep(0.05)
        self.fail("job did not finish")

    def _run_step(self, ws: str, step: str, params: dict | None = None) -> dict:
        status, _ct, resp = routes.dispatch(
            "POST",
            f"/api/workspace/{ws}/run",
            json.dumps({"step": step, "params": params or {}}).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 202, resp.decode("utf-8"))
        return self._wait_for_done(ws, json.loads(resp)["job_id"])

    def _drive_to_prepared(self, ws: str) -> None:
        self._premise(ws)
        self._run_step(ws, "prepare-greenfield", {"force": True})

    def _put(self, ws: str, suffix: str, payload: dict) -> tuple[int, dict]:
        status, _ct, body = routes.dispatch(
            "PUT",
            f"/api/workspace/{ws}{suffix}",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json"},
        )
        return status, json.loads(body)

    def _get(self, ws: str, suffix: str) -> tuple[int, dict]:
        status, _ct, body = routes.dispatch("GET", f"/api/workspace/{ws}{suffix}")
        return status, json.loads(body)

    # ---- KB ----------------------------------------------------------------

    def test_kb_roundtrip_and_stage_rollback(self) -> None:
        self._drive_to_prepared("kbws")
        self._run_step("kbws", "debate")
        status, st = self._get("kbws", "/workbench")
        self.assertEqual(status, 200)
        self.assertTrue(st["has_outline"])

        status, kb = self._get("kbws", "/kb")
        self.assertEqual(status, 200)
        self.assertTrue(kb["content"])

        time.sleep(0.02)  # mtime resolution guard
        status, data = self._put("kbws", "/kb", {"content": kb["content"] + "\n\n## 手工补充设定\n主角惧高。\n"})
        self.assertEqual(status, 200, data)
        on_disk = (paths.WORKSPACE_DIR / "kbws" / "data" / "knowledge_base" / "global_knowledge.md").read_text(encoding="utf-8")
        self.assertIn("主角惧高", on_disk)

        # 048b semantics preserved: KB newer than outline → workbench falls
        # back, prompting regeneration of downstream artifacts.
        status, st = self._get("kbws", "/workbench")
        self.assertEqual(status, 200)
        self.assertFalse(st["has_outline"])
        self.assertEqual(st["stage"], "outline")

    def test_kb_validation(self) -> None:
        self._drive_to_prepared("kbval")
        status, data = self._put("kbval", "/kb", {"content": "   "})
        self.assertEqual(status, 400)
        status, data = self._put("kbval", "/kb", {"content": "坏\x07设定"})
        self.assertEqual(status, 400)
        self.assertIn("control", data["error"])
        with jobs.workspace_reserved("kbval"):
            status, data = self._put("kbval", "/kb", {"content": "## 并发\n"})
        self.assertEqual(status, 409)

    # ---- entity ------------------------------------------------------------

    def test_entity_edit_whitelist(self) -> None:
        self._drive_to_prepared("entws")
        status, graph = self._get("entws", "/entity-graph")
        self.assertEqual(status, 200)
        entities = graph.get("entities") or []
        self.assertTrue(entities, "prepare-greenfield should produce entities")
        ent = entities[0]
        eid = str(ent["id"])

        status, data = self._put(
            "entws",
            f"/entity/{eid}",
            {"fields": {"name": "改名后的主角", "key_facts": ["惧高", "左撇子"], "description": "新描写。"}},
        )
        self.assertEqual(status, 200, data)
        status, graph2 = self._get("entws", "/entity-graph")
        ent2 = next(e for e in graph2["entities"] if str(e["id"]) == eid)
        self.assertEqual(ent2["name"], "改名后的主角")
        self.assertEqual(ent2["key_facts"], ["惧高", "左撇子"])
        # Immutable fields untouched.
        self.assertEqual(ent2["id"], ent["id"])
        self.assertEqual(ent2.get("type"), ent.get("type"))

        # id is not editable — explicit 400, not silent ignore.
        status, data = self._put("entws", f"/entity/{eid}", {"fields": {"id": "hacked"}})
        self.assertEqual(status, 400)
        self.assertIn("non-editable", data["error"])
        status, data = self._put("entws", f"/entity/{eid}", {"fields": {"key_facts": "不是列表"}})
        self.assertEqual(status, 400)
        status, data = self._put("entws", "/entity/ghost-entity", {"fields": {"name": "x"}})
        self.assertEqual(status, 404)

    def test_relationship_active_state_edit(self) -> None:
        self._drive_to_prepared("relws")
        status, graph = self._get("relws", "/entity-graph")
        rels = graph.get("relationships") or []
        active_idx = next(
            (
                i
                for i, r in enumerate(rels)
                if any(t.get("active") for t in (r.get("timeline") or []) if isinstance(t, dict))
            ),
            None,
        )
        self.assertIsNotNone(active_idx, "greenfield graph should have an active relationship")

        status, data = self._put("relws", f"/relationship/{active_idx}", {"state": "已彻底决裂"})
        self.assertEqual(status, 200, data)
        status, graph2 = self._get("relws", "/entity-graph")
        rel2 = graph2["relationships"][active_idx]
        active = next(t for t in rel2["timeline"] if t.get("active"))
        self.assertEqual(active["state"], "已彻底决裂")
        # Immutable timeline keys untouched.
        orig_active = next(t for t in rels[active_idx]["timeline"] if t.get("active"))
        for key in ("chapter_id", "order"):
            if key in orig_active:
                self.assertEqual(active.get(key), orig_active.get(key))

        status, data = self._put("relws", "/relationship/999", {"state": "越界"})
        self.assertEqual(status, 404)
        status, data = self._put("relws", f"/relationship/{active_idx}", {"state": ""})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
