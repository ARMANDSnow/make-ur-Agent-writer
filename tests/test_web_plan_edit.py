"""iter 050: PUT /api/workspace/<name>/chapter-plan/<chapter> — the web
surface of the structured plan edit. Validation/fingerprints are covered in
test_plot_planner_edit.py; this file pins the HTTP contract: status codes,
busy guard, written_chapters_invalidated, control-char rejection (C3c).

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
from src.plot_planner import plan_fingerprint
from src.web import jobs, routes


class PlanEditEndpointTests(unittest.TestCase):
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

    # ---- helpers (same harness as test_workbench_replan) ------------------

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

    def _drive_to_plan(self, ws: str) -> None:
        self._premise(ws)
        self._run_step(ws, "prepare-greenfield", {"force": True})
        self._run_step(ws, "debate")
        rec = self._run_step(
            ws, "plan-chapters", {"target_chapters": 5, "require_start_point": False}
        )
        self.assertEqual(rec["status"], "succeeded", f"plan-chapters: {rec.get('error')}")

    def _put_edit(self, ws: str, chapter: int, fields: dict) -> tuple[int, dict]:
        status, _ct, body = routes.dispatch(
            "PUT",
            f"/api/workspace/{ws}/chapter-plan/{chapter}",
            json.dumps({"fields": fields}, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json"},
        )
        return status, json.loads(body)

    def _plan_path(self, ws: str) -> Path:
        return paths.WORKSPACE_DIR / ws / "outputs" / "debate" / "chapter_plan.json"

    # ---- contract ----------------------------------------------------------

    def test_edit_saves_and_returns_new_fingerprint(self) -> None:
        self._drive_to_plan("editws")
        before = json.loads(self._plan_path("editws").read_text(encoding="utf-8"))
        status, data = self._put_edit("editws", 2, {"title": "网页改的标题"})
        self.assertEqual(status, 200, data)
        self.assertTrue(data["saved"])
        self.assertEqual(data["written_chapters_invalidated"], [])
        on_disk = json.loads(self._plan_path("editws").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["chapters"][1]["title"], "网页改的标题")
        self.assertEqual(data["plan_fingerprint"], on_disk["plan_fingerprint"])
        self.assertEqual(on_disk["plan_fingerprint"], plan_fingerprint(on_disk))
        self.assertNotEqual(on_disk["plan_fingerprint"], before["plan_fingerprint"])

    def test_edit_reports_written_chapters_invalidated(self) -> None:
        self._drive_to_plan("draftws")
        drafts = paths.WORKSPACE_DIR / "draftws" / "outputs" / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        (drafts / "chapter_01.md").write_text("# 已写正文\n", encoding="utf-8")
        # A partial must NOT count as a written chapter.
        (drafts / "chapter_02.partial.md").write_text("…", encoding="utf-8")
        status, data = self._put_edit("draftws", 3, {"title": "牵连已写章"})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["written_chapters_invalidated"], [1])

    def test_validation_error_returns_400_with_field_detail(self) -> None:
        self._drive_to_plan("badws")
        before = self._plan_path("badws").read_text(encoding="utf-8")
        status, data = self._put_edit("badws", 1, {"target_chinese_chars": 99})
        self.assertEqual(status, 400)
        self.assertIn("target_chinese_chars", data["error"])
        status, data = self._put_edit("badws", 1, {"chapter_no": 7})
        self.assertEqual(status, 400)
        self.assertIn("non-editable", data["error"])
        # Failed edits never touch the file.
        self.assertEqual(self._plan_path("badws").read_text(encoding="utf-8"), before)

    def test_control_characters_rejected(self) -> None:
        self._drive_to_plan("ctrlws")
        status, data = self._put_edit("ctrlws", 1, {"title": "坏\x00标题"})
        self.assertEqual(status, 400)
        self.assertIn("control", data["error"])
        # Nested list values are scanned too.
        status, data = self._put_edit("ctrlws", 1, {"key_events": ["甲", "乙\x1b[31m"]})
        self.assertEqual(status, 400)
        # \n \r \t stay legal (multi-line scene descriptions).
        status, _data = self._put_edit("ctrlws", 1, {"opening_scene": "第一行\n第二行"})
        self.assertEqual(status, 200)

    def test_missing_plan_and_missing_chapter_return_404(self) -> None:
        self._premise("nopws")
        status, data = self._put_edit("nopws", 1, {"title": "x"})
        self.assertEqual(status, 404, data)
        self._drive_to_plan("noc99ws")
        status, data = self._put_edit("noc99ws", 99, {"title": "x"})
        self.assertEqual(status, 404, data)
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/ghostws/chapter-plan/1",
            b'{"fields": {"title": "x"}}',
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 404)

    def test_busy_workspace_returns_409(self) -> None:
        self._drive_to_plan("busyws")
        with jobs.workspace_reserved("busyws"):
            status, data = self._put_edit("busyws", 1, {"title": "并发改"})
        self.assertEqual(status, 409)
        self.assertIn("running_job_id", data)

    def test_bad_body_returns_400(self) -> None:
        self._drive_to_plan("bodyws")
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/bodyws/chapter-plan/1",
            b"not json",
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 400)
        status, data = self._put_edit("bodyws", 1, {})
        self.assertEqual(status, 400)


class PlanEditFrontendStringTests(unittest.TestCase):
    """Pin the iter 050 stage-③ frontend invariants (same string-assert
    convention as test_static_subscore_compat): D4 placeholders, B3-hint CTA
    mapping, and a11y label/for pairing in the edit form."""

    def test_d4_loading_and_stale_placeholders_present(self) -> None:
        from src.web import static

        self.assertIn("细纲加载中…", static.JS_DASHBOARD)
        self.assertIn("细纲已过期（上游设定/大纲已更新）", static.JS_DASHBOARD)

    def test_d1_friendly_409_helper(self) -> None:
        from src.web import static

        # _httpError attaches status+payload and rewrites the bare
        # "workspace busy" 409 into an actionable message; all three fetch
        # helpers must route through it.
        self.assertIn("function _httpError(res, data)", static.JS_DASHBOARD)
        self.assertIn("工作区正被另一任务占用", static.JS_DASHBOARD)
        self.assertEqual(static.JS_DASHBOARD.count("throw _httpError(res, data)"), 3)

    def test_b3_hint_fingerprint_cta_mapping(self) -> None:
        from src.web import static

        self.assertIn("plan_fingerprint_stale", static.JS_DASHBOARD)
        self.assertIn('/fingerprint/.test(reason)', static.JS_DASHBOARD)
        self.assertIn("细纲已变更/过期", static.JS_DASHBOARD)

    def test_edit_form_inputs_have_label_for(self) -> None:
        from src.web import static

        # The textField helper pairs every label[for] with the field id at
        # render time (ids are concatenated in JS, so assert the helper
        # pattern + each id literal; live pairing was verified in-browser).
        self.assertIn("'<label for=\"' + id + '\">'", static.JS_DASHBOARD)
        for field_id in (
            "plan-edit-title",
            "plan-edit-opening",
            "plan-edit-hook",
            "plan-edit-target",
            "plan-edit-purpose",
        ):
            self.assertIn(field_id, static.JS_DASHBOARD)
        # The two dynamic-list labels carry explicit for= in the source.
        self.assertIn('for="plan-edit-events-0"', static.JS_DASHBOARD)
        self.assertIn('for="plan-edit-rels-0"', static.JS_DASHBOARD)


if __name__ == "__main__":
    unittest.main()
