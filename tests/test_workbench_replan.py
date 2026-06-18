"""iter 048c: workbench stage ③ 重生成细纲 + write-book 兼容回归.

This is the lone reason 048c exists: prove that "re-run plan-chapters"
keeps the chapter_plan.json fingerprints self-consistent so write-book's
strict gate (book_runner._plan_metadata_failures: plan_fingerprint +
chapter_NN_plan_item_fingerprint) does NOT raise plan_fingerprint_mismatch
or chapter_NN_plan_item_fingerprint_mismatch after the user clicks
"重新生成细纲".

The red-team adversarial review flagged that any in-place edit of
chapter_plan.json (the原 048 plan's PUT /chapter-plan) would invalidate
those fingerprints and brick stage ④. 048c sidesteps that trap entirely
by routing "change细纲" through generate_chapter_plan, whose
_attach_plan_fingerprints step (plot_planner.py:220-227) re-attaches all
fingerprints — so the gate stays自洽 by construction, not by handwritten
reconciliation.

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
from src.plot_planner import (
    chapter_plan_item_fingerprint,
    plan_fingerprint,
)
from src.web import jobs, routes


class WorkbenchReplanTests(unittest.TestCase):
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

    # ---- helpers ----------------------------------------------------------

    def _premise(self, ws: str, premise: str = "少年觉醒上古血脉，逆天改命。") -> None:
        status, _ct, resp = routes.dispatch(
            "POST",
            "/api/wizard/premise-start",
            json.dumps({"workspace": ws, "premise": premise}, ensure_ascii=False).encode("utf-8"),
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

    def _plan_data(self, ws: str) -> dict:
        path = paths.WORKSPACE_DIR / ws / "outputs" / "debate" / "chapter_plan.json"
        self.assertTrue(path.exists(), f"missing {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _drive_to_plan(self, ws: str, target_chapters: int = 5) -> dict:
        self._premise(ws)
        self._run_step(ws, "prepare-greenfield", {"force": True})
        self._run_step(ws, "debate")
        rec = self._run_step(
            ws,
            "plan-chapters",
            {"target_chapters": target_chapters, "require_start_point": False},
        )
        self.assertEqual(rec["status"], "succeeded", f"plan-chapters error: {rec.get('error')}")
        return rec

    # ---- core: fingerprints self-consistent after re-plan -----------------

    def test_replan_recomputes_fingerprints_after_corruption(self) -> None:
        """The core 048c reason-to-exist test: if a stale plan_fingerprint
        (whether from user编辑 or any other source) would normally trip the
        write-book gate, re-running plan-chapters must scrub and rewrite the
        fingerprints from scratch via _attach_plan_fingerprints. Validates
        the "route around in-place edit" design — the red-team trap is
        消解 by construction."""
        self._drive_to_plan("fpbook", target_chapters=5)
        plan_path = paths.WORKSPACE_DIR / "fpbook" / "outputs" / "debate" / "chapter_plan.json"
        data1 = json.loads(plan_path.read_text(encoding="utf-8"))
        # Sanity: the fresh plan is internally consistent.
        self.assertEqual(data1["plan_fingerprint"], plan_fingerprint(data1))
        for item in data1["chapters"]:
            self.assertEqual(
                item.get("chapter_plan_item_fingerprint"),
                chapter_plan_item_fingerprint(item),
            )

        # Simulate "user edited细纲 in place" — corrupt both the top-level
        # fingerprint AND a per-chapter fingerprint. A naive PUT /chapter-plan
        # (which 048 草案 originally proposed) would leave the system here,
        # and the next write-book would trip plan_fingerprint_mismatch +
        # chapter_NN_plan_item_fingerprint_mismatch (book_runner.py:570-605).
        corrupted = dict(data1)
        corrupted["plan_fingerprint"] = "deadbeef" * 8
        corrupted["chapters"] = list(data1["chapters"])
        corrupted["chapters"][0] = dict(data1["chapters"][0])
        corrupted["chapters"][0]["chapter_plan_item_fingerprint"] = "cafebabe" * 8
        plan_path.write_text(json.dumps(corrupted, ensure_ascii=False), encoding="utf-8")

        # Re-run plan-chapters — this is what the workbench's "重新生成细纲"
        # button triggers. generate_chapter_plan calls _attach_plan_fingerprints
        # at the end (plot_planner.py:171, 220-227), which scrubs every stored
        # fingerprint and recomputes from the fresh data.
        rec = self._run_step(
            "fpbook",
            "plan-chapters",
            {"target_chapters": 5, "require_start_point": False},
        )
        self.assertEqual(rec["status"], "succeeded", f"replan error: {rec.get('error')}")

        # All fingerprints are recomputed and self-consistent again.
        data2 = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertNotEqual(data2["plan_fingerprint"], "deadbeef" * 8)
        self.assertEqual(data2["plan_fingerprint"], plan_fingerprint(data2))
        for item in data2["chapters"]:
            self.assertEqual(
                item.get("chapter_plan_item_fingerprint"),
                chapter_plan_item_fingerprint(item),
            )

    # ---- write-book NOT blocked by fingerprint mismatch after re-plan ----

    def test_write_book_after_replan_passes_fingerprint_gate(self) -> None:
        self._drive_to_plan("wbook", target_chapters=5)
        # Corrupt the stored fingerprint to simulate "stale plan that would
        # block write-book" — then re-plan to fix it (the workbench routes
        # all "change细纲" through this path, not in-place edit).
        plan_path = paths.WORKSPACE_DIR / "wbook" / "outputs" / "debate" / "chapter_plan.json"
        data = json.loads(plan_path.read_text(encoding="utf-8"))
        data["plan_fingerprint"] = "stale" * 16
        plan_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        rec = self._run_step(
            "wbook",
            "plan-chapters",
            {"target_chapters": 5, "require_start_point": False},
        )
        self.assertEqual(rec["status"], "succeeded")

        # Now stage ④: write-book under the greenfield gate (require_start_point=false,
        # require_plan=true). The mock reviewer defaults to Reject so the job
        # may end in `blocked` via retry_exhausted (that's固有行为, see 048b
        # PLAN); what matters is that it must NOT be blocked on
        # plan_fingerprint_mismatch / chapter_NN_plan_item_fingerprint_mismatch
        # / plan_fingerprint_missing — those are the红队-flagged failure modes
        # that "in-place edit" would trigger and that "re-generate" must avoid.
        rec = self._run_step(
            "wbook",
            "write-book",
            {"require_start_point": False, "require_plan": True},
        )
        summary = rec.get("result_summary") or {}
        first_blocked = summary.get("first_blocked")
        if first_blocked:
            reason = str(first_blocked.get("reason", ""))
            self.assertNotIn("plan_fingerprint_mismatch", reason)
            self.assertNotIn("plan_fingerprint_missing", reason)
            self.assertNotIn("plan_item_fingerprint_mismatch", reason)
            self.assertNotIn("plan_item_fingerprint_missing", reason)
        # A draft must land regardless of strict review verdict — that proves
        # the writer was allowed to run, i.e. the fingerprint gate accepted
        # the freshly-replanned chapter_plan.json.
        ch1 = paths.WORKSPACE_DIR / "wbook" / "outputs" / "drafts" / "chapter_01.md"
        self.assertTrue(ch1.exists(), f"missing {ch1}; write-book never produced a draft")

    # ---- workbench status reflects the replan -----------------------------

    def test_workbench_status_after_replan(self) -> None:
        self._drive_to_plan("stbook", target_chapters=5)
        # mtime ordering: plan_m >= outline_m >= kb_m after the first plan,
        # and a successful re-plan must keep that invariant.
        st_before, _ct, body = routes.dispatch("GET", "/api/workspace/stbook/workbench")
        self.assertEqual(st_before, 200)
        s1 = json.loads(body)
        self.assertTrue(s1["has_plan"])

        self._run_step(
            "stbook",
            "plan-chapters",
            {"target_chapters": 5, "require_start_point": False},
        )
        st_after, _ct, body = routes.dispatch("GET", "/api/workspace/stbook/workbench")
        self.assertEqual(st_after, 200)
        s2 = json.loads(body)
        self.assertTrue(s2["has_plan"])
        # The re-planned chapter_plan.json should still satisfy the workbench
        # gate (plan not stale relative to outline/kb).
        self.assertIn(s2["stage"], ("write", "done"))
        # And the plan on disk is internally self-consistent after replan
        # (this is what makes write-book's fingerprint gate accept it).
        data = self._plan_data("stbook")
        self.assertEqual(data["plan_fingerprint"], plan_fingerprint(data))

    # ---- iter 048d B-M-1: *_missing path coverage ------------------------

    def test_replan_recreates_missing_plan_fingerprint(self) -> None:
        """The 048c reason-to-exist test covered ``plan_fingerprint`` being
        WRONG (mismatch). This covers the orthogonal failure mode flagged
        by adversarial review: ``plan_fingerprint`` field entirely MISSING
        (e.g. a third-party tool that wrote chapter_plan.json without
        running it through _attach_plan_fingerprints). Re-running
        plan-chapters must re-attach a fresh fingerprint."""
        self._drive_to_plan("missfpbook", target_chapters=5)
        plan_path = (
            paths.WORKSPACE_DIR / "missfpbook" / "outputs" / "debate" / "chapter_plan.json"
        )
        data = json.loads(plan_path.read_text(encoding="utf-8"))
        del data["plan_fingerprint"]
        plan_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        rec = self._run_step(
            "missfpbook",
            "plan-chapters",
            {"target_chapters": 5, "require_start_point": False},
        )
        self.assertEqual(rec["status"], "succeeded")
        data2 = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertIn("plan_fingerprint", data2)
        self.assertEqual(data2["plan_fingerprint"], plan_fingerprint(data2))

    def test_replan_recreates_missing_item_fingerprint(self) -> None:
        """Mirror of the above but for per-chapter
        ``chapter_plan_item_fingerprint``. ``book_runner._plan_metadata_failures``
        treats these as a separate code path (chapter_NN_plan_item_fingerprint_missing
        vs _mismatch), so coverage must hit both."""
        self._drive_to_plan("missitembook", target_chapters=5)
        plan_path = (
            paths.WORKSPACE_DIR
            / "missitembook"
            / "outputs"
            / "debate"
            / "chapter_plan.json"
        )
        data = json.loads(plan_path.read_text(encoding="utf-8"))
        del data["chapters"][0]["chapter_plan_item_fingerprint"]
        plan_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        rec = self._run_step(
            "missitembook",
            "plan-chapters",
            {"target_chapters": 5, "require_start_point": False},
        )
        self.assertEqual(rec["status"], "succeeded")
        data2 = json.loads(plan_path.read_text(encoding="utf-8"))
        ch1 = data2["chapters"][0]
        self.assertIn("chapter_plan_item_fingerprint", ch1)
        self.assertEqual(
            ch1["chapter_plan_item_fingerprint"],
            chapter_plan_item_fingerprint(ch1),
        )

    # ---- iter 050: structured edit shares the same fingerprint truth ------

    def test_write_book_after_structured_edit_passes_fingerprint_gate(self) -> None:
        """iter 050 mirror of the 048c reason-to-exist test: the structured
        edit endpoint (PUT /chapter-plan/<n>) re-derives fingerprints via the
        same _attach_plan_fingerprints entry as plan generation, so a
        subsequent write-book must NOT trip the fingerprint gate."""
        self._drive_to_plan("editgate", target_chapters=5)
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/editgate/chapter-plan/1",
            json.dumps(
                {"fields": {"title": "编辑后的第一章", "key_events": ["事件甲", "事件乙", "事件丙"]}},
                ensure_ascii=False,
            ).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 200, body.decode("utf-8"))
        data = self._plan_data("editgate")
        self.assertEqual(data["chapters"][0]["title"], "编辑后的第一章")
        self.assertEqual(data["plan_fingerprint"], plan_fingerprint(data))

        rec = self._run_step(
            "editgate",
            "write-book",
            {"require_start_point": False, "require_plan": True},
        )
        summary = rec.get("result_summary") or {}
        first_blocked = summary.get("first_blocked")
        if first_blocked:
            reason = str(first_blocked.get("reason", ""))
            self.assertNotIn("fingerprint", reason)
        ch1 = paths.WORKSPACE_DIR / "editgate" / "outputs" / "drafts" / "chapter_01.md"
        self.assertTrue(ch1.exists(), "write-book never produced a draft after edit")
        # And the writer consumed the EDITED plan: meta.run_context carries
        # the post-edit fingerprints.
        meta = json.loads(
            (paths.WORKSPACE_DIR / "editgate" / "outputs" / "drafts" / "chapter_01.meta.json")
            .read_text(encoding="utf-8")
        )
        run_context = meta.get("run_context") or {}
        self.assertEqual(run_context.get("plan_fingerprint"), data["plan_fingerprint"])

    def test_structured_edit_only_expires_edited_chapter(self) -> None:
        """iter057 P0-A: plan_fingerprint 收窄为只哈希全局上下文后,编辑某章只让
        **该章**(若已写)strict-expire(via chapter_plan_item_fingerprint),不再波及
        其他已写章。这取代旧的「编辑任意章→所有已写章失效」全局语义——那正是 replan
        append 卡死每个已写章的根源(用户拍板接受精确化)。按章一致性由 item 指纹守护,
        plan_fingerprint 只管全局上下文(overall_arc/起点)。"""
        self._drive_to_plan("expirews", target_chapters=5)
        rec = self._run_step(
            "expirews",
            "write-book",
            {"require_start_point": False, "require_plan": True},
        )
        meta_path = (
            paths.WORKSPACE_DIR / "expirews" / "outputs" / "drafts" / "chapter_01.meta.json"
        )
        self.assertTrue(meta_path.exists(), f"write-book left no meta: {rec.get('error')}")
        data_before = self._plan_data("expirews")
        fp_before = data_before["plan_fingerprint"]
        ch1_item_before = data_before["chapters"][0]["chapter_plan_item_fingerprint"]

        # 1) 编辑**未写**的 ch3 → 不波及已写的 ch1
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/expirews/chapter-plan/3",
            json.dumps({"fields": {"title": "中段改写"}}, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 200, body.decode("utf-8"))
        resp = json.loads(body)
        # ch3 未写 → 失效列表为空(不再误报已写的 ch1)
        self.assertEqual(resp["written_chapters_invalidated"], [])
        data_after3 = self._plan_data("expirews")
        # plan_fingerprint 不变(只哈希全局上下文);ch1 item 指纹不变(ch1 自洽,不重审)
        self.assertEqual(data_after3["plan_fingerprint"], fp_before)
        self.assertEqual(
            data_after3["chapters"][0]["chapter_plan_item_fingerprint"], ch1_item_before
        )

        # 2) 编辑**已写**的 ch1 → 仅 ch1 strict-expire(item 指纹变),失效列表只含 ch1
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/expirews/chapter-plan/1",
            json.dumps({"fields": {"title": "首章改写"}}, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 200, body.decode("utf-8"))
        resp = json.loads(body)
        self.assertEqual(resp["written_chapters_invalidated"], [1])
        data_after1 = self._plan_data("expirews")
        # ch1 item 指纹变了(strict-expire 由它承载);plan_fingerprint 仍不变。
        self.assertNotEqual(
            data_after1["chapters"][0]["chapter_plan_item_fingerprint"], ch1_item_before
        )
        self.assertEqual(data_after1["plan_fingerprint"], fp_before)

    def test_replan_invalidates_stale_drafts_in_workbench_status(self) -> None:
        """Adversarial review视角 A flagged that re-planning after the user
        already wrote drafts should让 has_drafts revert to False (drafts
        become stale relative to the new plan via mtime chain). Covers the
        plan-vs-draft link that the original 048b test only checked at the
        plan-vs-outline link."""
        self._drive_to_plan("staledraftsbook", target_chapters=5)
        # Plant a draft so has_drafts goes True under the original plan.
        drafts_dir = paths.WORKSPACE_DIR / "staledraftsbook" / "outputs" / "drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        (drafts_dir / "chapter_01.md").write_text("# mock draft\n", encoding="utf-8")
        _, _ct, body = routes.dispatch(
            "GET", "/api/workspace/staledraftsbook/workbench"
        )
        s_before = json.loads(body)
        self.assertGreaterEqual(s_before["draft_count"], 1)
        # Push plan's mtime past the draft, simulating a re-plan.
        future = time.time() + 100
        plan_path = (
            paths.WORKSPACE_DIR
            / "staledraftsbook"
            / "outputs"
            / "debate"
            / "chapter_plan.json"
        )
        os.utime(plan_path, (future, future))
        _, _ct, body = routes.dispatch(
            "GET", "/api/workspace/staledraftsbook/workbench"
        )
        s_after = json.loads(body)
        # Drafts on disk are unchanged but the mtime chain now marks them
        # stale → workbench falls back to the write stage.
        self.assertEqual(s_after["draft_count"], 1)
        self.assertEqual(s_after["stage"], "write")


if __name__ == "__main__":
    unittest.main()
