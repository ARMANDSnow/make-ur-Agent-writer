"""iter 050 (B1/B2): PUT /api/workspace/<name>/draft/<chapter> + the
review-chapter job.

The load-bearing invariant: ``reviewer.review_target`` trusts
``meta.draft_sha256`` and never re-hashes the file, so the draft PUT must
sync md + meta inside one ``workspace_reserved`` hold. After an edit the
strict status correctly shows ``external_review_stale`` (review.json still
hashes the old text); after the review-chapter job that failure — and only
that family — disappears (mock reviewer always Rejects, so
``external_review_reject`` remains as the precise residual, the 048c
"mock limitation as sharper evidence" trick).

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
from src.utils import sha256_text
from src.web import jobs, routes


class DraftEditTests(unittest.TestCase):
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

    def _drive_to_written_chapter(self, ws: str) -> Path:
        self._premise(ws)
        self._run_step(ws, "prepare-greenfield", {"force": True})
        self._run_step(ws, "debate")
        rec = self._run_step(
            ws, "plan-chapters", {"target_chapters": 5, "require_start_point": False}
        )
        self.assertEqual(rec["status"], "succeeded")
        self._run_step(
            ws, "write-book", {"require_start_point": False, "require_plan": True}
        )
        drafts = paths.WORKSPACE_DIR / ws / "outputs" / "drafts"
        self.assertTrue((drafts / "chapter_01.md").exists())
        return drafts

    def _put_draft(self, ws: str, chapter: int, content: str) -> tuple[int, dict]:
        status, _ct, body = routes.dispatch(
            "PUT",
            f"/api/workspace/{ws}/draft/{chapter}",
            json.dumps({"content": content}, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json"},
        )
        return status, json.loads(body)

    # ---- contract ----------------------------------------------------------

    def test_edit_writes_md_and_syncs_meta(self) -> None:
        drafts = self._drive_to_written_chapter("editdraft")
        new_text = "# 第 1 章 改写版\n\n主角推门而入，烛火摇曳。"
        status, data = self._put_draft("editdraft", 1, new_text + "\n\n\n")
        self.assertEqual(status, 200, data)
        self.assertTrue(data["saved"])
        self.assertTrue(data["review_stale"])
        # md normalized to writer's on-disk shape (single trailing newline).
        on_disk = (drafts / "chapter_01.md").read_text(encoding="utf-8")
        self.assertEqual(on_disk, new_text + "\n")
        # meta sha matches BOTH the response and a fresh hash of the file —
        # the draft_hash_mismatch failure mode is structurally closed.
        meta = json.loads((drafts / "chapter_01.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["draft_sha256"], sha256_text(on_disk))
        self.assertEqual(meta["draft_sha256"], data["draft_sha256"])
        self.assertTrue(meta["edited"])
        self.assertTrue(meta["needs_human_review"])
        # review.json still hashes the OLD text → stale by construction.
        review = json.loads(
            (drafts.parent / "reviews" / "chapter_01.review.json").read_text(encoding="utf-8")
        )
        self.assertNotEqual(review.get("draft_sha256"), meta["draft_sha256"])

    def test_edit_then_rereview_clears_stale_failures(self) -> None:
        self._drive_to_written_chapter("reloop")
        status, _data = self._put_draft("reloop", 1, "# 第 1 章\n\n编辑后的正文，足够成段。")
        self.assertEqual(status, 200)
        rec = self._run_step("reloop", "review-chapter", {"chapter": 1})
        self.assertEqual(rec["status"], "succeeded", f"review-chapter: {rec.get('error')}")
        summary = rec.get("result_summary") or {}
        failures = summary.get("strict_failures") or []
        # The edit-induced failures are gone; what remains is the mock
        # reviewer's unconditional Reject family — proving the re-review
        # consumed the NEW text and re-anchored sha + run_context.
        self.assertNotIn("external_review_stale", failures)
        self.assertNotIn("draft_hash_mismatch", failures)
        self.assertNotIn("external_review_missing_draft_hash", failures)
        self.assertIn("external_review_reject", failures)

    def test_review_chapter_blocked_paths(self) -> None:
        ws = "blockedrev"
        self._premise(ws)
        self._run_step(ws, "prepare-greenfield", {"force": True})
        # No drafts at all → draft_missing.
        rec = self._run_step(ws, "review-chapter", {"chapter": 1})
        self.assertEqual(rec["status"], "blocked")
        summary = rec.get("result_summary") or {}
        first = summary.get("first_blocked") or {}
        self.assertEqual(first.get("reason"), "draft_missing")
        # Draft exists but no chapter_plan → chapter_plan_missing.
        drafts = paths.WORKSPACE_DIR / ws / "outputs" / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        (drafts / "chapter_01.md").write_text("# 手写稿\n", encoding="utf-8")
        rec = self._run_step(ws, "review-chapter", {"chapter": 1})
        self.assertEqual(rec["status"], "blocked")
        first = (rec.get("result_summary") or {}).get("first_blocked") or {}
        self.assertEqual(first.get("reason"), "chapter_plan_missing")

    def test_validation_errors(self) -> None:
        drafts = self._drive_to_written_chapter("valdraft")
        before = (drafts / "chapter_01.md").read_text(encoding="utf-8")
        status, data = self._put_draft("valdraft", 1, "   ")
        self.assertEqual(status, 400)
        status, data = self._put_draft("valdraft", 1, "坏\x00字符")
        self.assertEqual(status, 400)
        self.assertIn("control", data["error"])
        status, data = self._put_draft("valdraft", 99, "# 不存在的章\n")
        self.assertEqual(status, 404)
        # Failed edits never touch the file.
        self.assertEqual((drafts / "chapter_01.md").read_text(encoding="utf-8"), before)

    def test_busy_workspace_returns_409(self) -> None:
        self._drive_to_written_chapter("busydraft")
        with jobs.workspace_reserved("busydraft"):
            status, data = self._put_draft("busydraft", 1, "# 并发写\n\n内容。")
        self.assertEqual(status, 409)
        self.assertIn("running_job_id", data)

    def test_review_chapter_step_registered(self) -> None:
        self.assertTrue(jobs.is_known_step("review-chapter"))


if __name__ == "__main__":
    unittest.main()
