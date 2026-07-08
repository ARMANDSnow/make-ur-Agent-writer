"""iter079: capstone 前 P2 hardening regressions.

All tests are mock/local only. They cover the cross-process write lock bridge
for manual Web edits, CLI apply-advance locking, entity proposal-gap visibility,
and the opt-in mock cost exercise switch.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import main
from src import paths
from src.entity_advance import save_entity_advance_proposals
from src.utils import write_json
from src.web import jobs, routes
from src.web.workspace_ctx import use_workspace
from src.workspace_lock import acquire_write_lock


class _TempWebWorkspace(unittest.TestCase):
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

    def _ws(self, name: str = "lockws") -> Path:
        root = paths.WORKSPACE_DIR / name
        (root / "outputs" / "drafts").mkdir(parents=True, exist_ok=True)
        (root / "data" / "knowledge_base").mkdir(parents=True, exist_ok=True)
        (root / "data").mkdir(parents=True, exist_ok=True)
        return root

    def _put(self, ws: str, path: str, payload: dict) -> tuple[int, dict]:
        status, _ct, body = routes.dispatch(
            "PUT",
            f"/api/workspace/{ws}{path}",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json"},
        )
        return status, json.loads(body)


class WebManualWriteLockTests(_TempWebWorkspace):
    def test_manual_edit_endpoints_return_409_when_cli_flock_is_held(self) -> None:
        root = self._ws()
        draft = root / "outputs" / "drafts" / "chapter_01.md"
        meta = root / "outputs" / "drafts" / "chapter_01.meta.json"
        kb = root / "data" / "knowledge_base" / "global_knowledge.md"
        graph = root / "data" / "entity_graph.json"
        draft.write_text("旧正文\n", encoding="utf-8")
        write_json(meta, {"draft_sha256": "old"})
        kb.write_text("旧知识\n", encoding="utf-8")
        write_json(
            graph,
            {
                "entities": [{"id": "e1", "name": "旧名", "type": "person"}],
                "relationships": [
                    {
                        "src_id": "e1",
                        "dst_id": "e2",
                        "relation_type": "ally",
                        "timeline": [{"state": "旧关系", "active": True}],
                    }
                ],
            },
        )

        cases = [
            ("/draft/1", {"content": "新正文"}, draft),
            ("/outline", {"outline": "新大纲"}, root / "outputs" / "debate" / "outline.md"),
            ("/kb", {"content": "新知识"}, kb),
            ("/entity/e1", {"fields": {"name": "新名"}}, graph),
            (
                "/relationship/0",
                {"state": "新关系", "src_id": "e1", "dst_id": "e2"},
                graph,
            ),
        ]

        before = {path: path.read_text(encoding="utf-8") if path.exists() else None for _, _, path in cases}
        with use_workspace("lockws"):
            with acquire_write_lock(source="cli-long-run"):
                for suffix, payload, path in cases:
                    status, data = self._put("lockws", suffix, payload)
                    self.assertEqual(status, 409, (suffix, data))
                    self.assertTrue(data.get("workspace_locked"), data)
                    self.assertEqual(data.get("holder", {}).get("source"), "cli-long-run")
                    holder_json = json.dumps(data.get("holder", {}), ensure_ascii=False)
                    self.assertNotIn("argv", holder_json)
                    self.assertNotIn(str(root), holder_json)
                    self.assertNotIn("write.lock", holder_json)
                    after = path.read_text(encoding="utf-8") if path.exists() else None
                    self.assertEqual(after, before[path], suffix)

    def test_existing_web_reservation_conflict_shape_is_preserved(self) -> None:
        self._ws("busyws")
        with jobs.workspace_reserved("busyws"):
            status, data = self._put("busyws", "/outline", {"outline": "新大纲"})
        self.assertEqual(status, 409)
        self.assertEqual(data.get("error"), "workspace busy")
        self.assertIn("running_job_id", data)
        self.assertNotIn("workspace_locked", data)


class ApplyAdvanceCliLockTests(_TempWebWorkspace):
    def test_apply_advance_exits_4_before_mutating_when_lock_held(self) -> None:
        root = self._ws("applylock")
        graph = root / "data" / "entity_graph.json"
        write_json(graph, {"relationships": []})
        before = graph.read_text(encoding="utf-8")
        argv = [
            "main.py",
            "--book",
            "applylock",
            "apply-advance",
            "--chapter",
            "1",
            "--auto-apply",
            "--allow-empty",
            "--confirm",
        ]

        with use_workspace("applylock"):
            with acquire_write_lock(source="other-writer"):
                with patch("sys.argv", argv), patch(
                    "main.apply_advance_cli",
                    side_effect=AssertionError("apply_advance_cli must not run"),
                ):
                    err = io.StringIO()
                    with redirect_stderr(err):
                        with self.assertRaises(SystemExit) as ctx:
                            main.main()
        self.assertEqual(ctx.exception.code, 4)
        self.assertIn("workspace_locked", err.getvalue())
        self.assertEqual(graph.read_text(encoding="utf-8"), before)


class ReadinessEntityProposalGapTests(unittest.TestCase):
    def _readiness(
        self,
        *,
        seed_proposal: bool = False,
        seed_sidecar: bool = False,
        resume_from: int = 1,
        plan_chapters: int = 1,
        status_by_chapter: dict[int, dict] | None = None,
    ) -> dict:
        from src.book_runner import check_write_readiness
        import tests.test_book_runner as tb

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "outputs" / "drafts"
            drafts.mkdir(parents=True, exist_ok=True)
            plan = tb._strict_plan(chapters=plan_chapters)
            parsed = {int(item["chapter_no"]): dict(item) for item in plan["chapters"]}
            (drafts / "chapter_01.md").write_text("正文\n", encoding="utf-8")
            if seed_proposal:
                save_entity_advance_proposals(1, [], drafts_dir=drafts)
            if seed_sidecar:
                write_json(drafts / "chapter_01.advance_applied.json", {"chapter": 1})

            status = {
                "chapter_no": 1,
                "exists": True,
                "approved": True,
                "needs_review": False,
                "failure": False,
                "verdict": "Approve",
                "strict_failures": [],
            }
            statuses = status_by_chapter or {1: status}

            def _status(chapter_no: int, *_args, **_kwargs) -> dict:
                return dict(
                    statuses.get(
                        chapter_no,
                        {
                            "chapter_no": chapter_no,
                            "exists": False,
                            "approved": False,
                            "needs_review": False,
                            "failure": False,
                            "verdict": None,
                            "strict_failures": [],
                        },
                    )
                )

            patches = [
                patch("src.book_runner.start_point.get_start_chapter_id", return_value=""),
                patch("src.book_runner.start_point.start_point_fingerprint", return_value=""),
                patch("src.book_runner._load_raw_chapter_plan", return_value=plan),
                patch("src.book_runner._load_chapter_plan", return_value=parsed),
                patch("src.book_runner.paths.workspace_name", return_value="unit"),
                patch("src.book_runner.paths.workspace_root", return_value=root),
                patch("src.book_runner.paths.drafts_dir", return_value=drafts),
                patch("src.book_runner.run_preflight", return_value={"status": "ok", "fatal": [], "warn": [], "info": []}),
                patch("src.book_runner.chapter_status", side_effect=_status),
                patch("src.chapter_summary.load_rolling_summary", return_value={}),
            ]
            for p in patches:
                p.start()
            try:
                return check_write_readiness(
                    chapters=1,
                    resume_from=resume_from,
                    require_start_point=False,
                    require_external_review=False,
                )
            finally:
                for p in reversed(patches):
                    p.stop()

    def test_missing_proposal_and_sidecar_warns(self) -> None:
        readiness = self._readiness()
        self.assertIn("entity_proposal_gap:01", readiness["warnings"])
        self.assertEqual(readiness["status"], "warn")

    def test_existing_proposal_or_sidecar_suppresses_warning(self) -> None:
        with_proposal = self._readiness(seed_proposal=True)
        with_sidecar = self._readiness(seed_sidecar=True)
        self.assertNotIn("entity_proposal_gap:01", with_proposal["warnings"])
        self.assertNotIn("entity_proposal_gap:01", with_sidecar["warnings"])

    def test_previous_approved_chapter_warns_on_resume_gap(self) -> None:
        readiness = self._readiness(resume_from=2, plan_chapters=2)
        self.assertIn("entity_proposal_gap:01", readiness["warnings"])

        with_proposal = self._readiness(resume_from=2, plan_chapters=2, seed_proposal=True)
        self.assertNotIn("entity_proposal_gap:01", with_proposal["warnings"])


class MockCostExerciseTests(unittest.TestCase):
    def test_mock_cost_default_zero_and_env_override(self) -> None:
        from src.cost_estimator import cost_cny

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cost_cny(1000, 0, 1000, model="mock"), 0.0)
        with patch.dict(os.environ, {"MOCK_COST_CNY_PER_1K_TOKENS": "0.25"}, clear=True):
            self.assertAlmostEqual(cost_cny(1000, 0, 1000, model="mock"), 0.5, places=6)
        with patch.dict(os.environ, {"MOCK_COST_CNY_PER_1K_TOKENS": "nan"}, clear=True):
            self.assertEqual(cost_cny(1000, 0, 1000, model="mock"), 0.0)


if __name__ == "__main__":
    unittest.main()
