"""iter 074: 章节版本 diff — pure module + route contract.

Covers the reader/editor-facing chapter version diff: enumerate current draft
+ retry snapshots archived by ``book_runner._archive_chapter_artifacts``, and
compute a unified diff between two versions. Path-traversal is fail-closed —
a version id is either ``current`` or a ``\\d{8}_\\d{6}`` snapshot stamp.

Mock-only; no LLM calls (builds draft/snapshot files directly on disk).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import paths
from src.web import chapter_diff, routes


class ChapterDiffModuleTests(unittest.TestCase):
    """Pure functions — no workspace context, just a temp drafts dir."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.drafts = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_current(self, text: str, meta: dict | None = None) -> None:
        (self.drafts / "chapter_01.md").write_text(text, encoding="utf-8")
        if meta is not None:
            (self.drafts / "chapter_01.meta.json").write_text(
                json.dumps(meta, ensure_ascii=False), encoding="utf-8"
            )

    def _write_snapshot(self, stamp: str, text: str, meta: dict | None = None, reason: str | None = None) -> Path:
        snap = self.drafts / "snapshots" / f"stale_chapter_01_{stamp}"
        snap.mkdir(parents=True, exist_ok=True)
        (snap / "chapter_01.md").write_text(text, encoding="utf-8")
        if meta is not None:
            (snap / "chapter_01.meta.json").write_text(
                json.dumps(meta, ensure_ascii=False), encoding="utf-8"
            )
        if reason is not None:
            (snap / "archive_reason.json").write_text(
                json.dumps({"reason": reason, "chapter": 1}), encoding="utf-8"
            )
        return snap

    def test_list_orders_current_first_then_snapshots_newest_first(self) -> None:
        self._write_current("行A\n行B\n", {"verdict": "Approve", "rewrite_count": 2})
        self._write_snapshot("20260612_170000", "旧一\n", {"verdict": "Reject"}, reason="retry_attempt_1")
        self._write_snapshot("20260612_180000", "旧二\n", {"verdict": "Reject"}, reason="retry_attempt_2")
        versions = chapter_diff.list_chapter_versions(self.drafts, 1)
        self.assertEqual([v["id"] for v in versions], ["current", "20260612_180000", "20260612_170000"])
        self.assertEqual(versions[0]["label"], "当前草稿")
        self.assertEqual(versions[0]["verdict"], "Approve")
        self.assertEqual(versions[0]["rewrite_count"], 2)
        self.assertEqual(versions[1]["reason"], "retry_attempt_2")
        self.assertIn("2026-06-12 18:00:00", versions[1]["label"])

    def test_list_graceful_when_no_snapshots_or_no_draft(self) -> None:
        # No files at all → empty list, no crash (mock-friendly, iron rule ④).
        self.assertEqual(chapter_diff.list_chapter_versions(self.drafts, 1), [])
        # Only current draft → single version, snapshots dir absent.
        self._write_current("只有当前\n", {"verdict": "Approve"})
        versions = chapter_diff.list_chapter_versions(self.drafts, 1)
        self.assertEqual([v["id"] for v in versions], ["current"])

    def test_list_tolerates_corrupt_meta(self) -> None:
        self._write_current("正文\n")
        (self.drafts / "chapter_01.meta.json").write_text("{not json", encoding="utf-8")
        versions = chapter_diff.list_chapter_versions(self.drafts, 1)
        self.assertEqual(len(versions), 1)
        self.assertIsNone(versions[0]["verdict"])  # degraded, not crashed
        self.assertTrue(versions[0]["exists"])

    def test_list_ignores_malformed_snapshot_dirs(self) -> None:
        self._write_current("cur\n", {})
        # Wrong stamp shape → skipped.
        bad = self.drafts / "snapshots" / "stale_chapter_01_not_a_stamp"
        bad.mkdir(parents=True)
        (bad / "chapter_01.md").write_text("x\n", encoding="utf-8")
        # Valid stamp but missing md → skipped.
        empty = self.drafts / "snapshots" / "stale_chapter_01_20260101_000000"
        empty.mkdir(parents=True)
        versions = chapter_diff.list_chapter_versions(self.drafts, 1)
        self.assertEqual([v["id"] for v in versions], ["current"])

    def test_resolve_version_text_fail_closed(self) -> None:
        self._write_current("当前\n")
        self._write_snapshot("20260612_170000", "旧\n")
        self.assertEqual(chapter_diff.resolve_version_text(self.drafts, 1, "current"), "当前\n")
        self.assertEqual(chapter_diff.resolve_version_text(self.drafts, 1, "20260612_170000"), "旧\n")
        # Path traversal / bad shapes → None, never touch disk outside snapshots.
        for bad in ("../../etc/passwd", "..", "20260612_170000/../..", "", "current/../..", "abcd"):
            self.assertIsNone(
                chapter_diff.resolve_version_text(self.drafts, 1, bad), f"leaked on {bad!r}"
            )
        # Well-formed but nonexistent stamp → None.
        self.assertIsNone(chapter_diff.resolve_version_text(self.drafts, 1, "19990101_000000"))

    def test_compute_diff_identical_and_changed(self) -> None:
        same = chapter_diff.compute_diff("一\n二\n", "一\n二\n")
        self.assertTrue(same["identical"])
        self.assertEqual(same["diff_lines"], [])
        self.assertFalse(same["truncated"])
        changed = chapter_diff.compute_diff("一\n二\n三\n", "一\n贰\n三\n", old_label="old", new_label="new")
        self.assertFalse(changed["identical"])
        types = [ln["type"] for ln in changed["diff_lines"]]
        self.assertIn("add", types)
        self.assertIn("del", types)
        dels = [ln["text"] for ln in changed["diff_lines"] if ln["type"] == "del"]
        adds = [ln["text"] for ln in changed["diff_lines"] if ln["type"] == "add"]
        self.assertTrue(any("二" in d for d in dels))
        self.assertTrue(any("贰" in a for a in adds))

    def test_version_entry_reports_size_bytes_without_reading_text(self) -> None:
        # iter076（codex 审查 iter074 #6）：版本列举零正文 IO——``chars``（全文 len）
        # 改为 ``size_bytes``（stat），且不再调用 read_text。
        text = "行A\n行B\n"
        self._write_current(text, {"verdict": "Approve"})
        orig_read_text = Path.read_text
        reads: list = []

        def spy(path_self, *a, **k):
            reads.append(str(path_self))
            return orig_read_text(path_self, *a, **k)

        with mock.patch.object(Path, "read_text", spy):
            versions = chapter_diff.list_chapter_versions(self.drafts, 1)
        # meta.json 读取允许；章节正文 md 全程零读取。
        self.assertFalse([p for p in reads if p.endswith("chapter_01.md")])
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["size_bytes"], len(text.encode("utf-8")))
        self.assertNotIn("chars", versions[0])
        self.assertTrue(versions[0]["exists"])

    def test_snapshot_symlink_escape_excluded_from_versions(self) -> None:
        # iter076（codex 低风险 symlink 项）：快照里指向外部的 symlink 不得进版本列表
        # （否则 /versions 可探测任意文件的存在性与长度）。
        self._write_current("正常当前稿\n", {})
        outside = Path(self._tmp.name).parent / f"outside_{os.getpid()}_secret.txt"
        outside.write_text("外部机密内容\n", encoding="utf-8")
        try:
            snap = self.drafts / "snapshots" / "stale_chapter_01_20260612_170000"
            snap.mkdir(parents=True)
            (snap / "chapter_01.md").symlink_to(outside)
            versions = chapter_diff.list_chapter_versions(self.drafts, 1)
            self.assertEqual([v["id"] for v in versions], ["current"])  # symlink 版本被排除
        finally:
            outside.unlink(missing_ok=True)

    def test_compute_diff_input_cap_skips_difflib(self) -> None:
        # 超过每侧输入上限 → 不跑 difflib，回 meta 说明行 + truncated。
        with mock.patch.object(chapter_diff, "MAX_DIFF_INPUT_CHARS", 10):
            out = chapter_diff.compute_diff("甲" * 11, "乙" * 3)
        self.assertTrue(out["truncated"])
        self.assertFalse(out["identical"])
        self.assertEqual(len(out["diff_lines"]), 1)
        self.assertEqual(out["diff_lines"][0]["type"], "meta")
        self.assertIn("文本过大", out["diff_lines"][0]["text"])

    def test_compute_diff_line_cap_truncates_output(self) -> None:
        # 输出行数超过上限 → 截断 + 追加说明行（最后一行 meta）。
        old = "\n".join(f"旧{i}" for i in range(40)) + "\n"
        new = "\n".join(f"新{i}" for i in range(40)) + "\n"
        with mock.patch.object(chapter_diff, "MAX_DIFF_LINES", 10):
            out = chapter_diff.compute_diff(old, new)
        self.assertTrue(out["truncated"])
        self.assertEqual(len(out["diff_lines"]), 11)   # 10 行 + 1 说明行
        self.assertEqual(out["diff_lines"][-1]["type"], "meta")
        self.assertIn("仅显示前 10 行", out["diff_lines"][-1]["text"])


class ChapterDiffRouteTests(unittest.TestCase):
    """End-to-end via routes.dispatch against a hand-built workspace."""

    WS = "difftest"

    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        self.drafts = paths.WORKSPACE_DIR / self.WS / "outputs" / "drafts"
        self.drafts.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _seed(self) -> str:
        (self.drafts / "chapter_01.md").write_text("行A\n行B\n行C\n", encoding="utf-8")
        (self.drafts / "chapter_01.meta.json").write_text(
            json.dumps({"verdict": "Approve", "rewrite_count": 1}), encoding="utf-8"
        )
        stamp = "20260612_172600"
        snap = self.drafts / "snapshots" / f"stale_chapter_01_{stamp}"
        snap.mkdir(parents=True, exist_ok=True)
        (snap / "chapter_01.md").write_text("行A\n行B旧\n行C\n", encoding="utf-8")
        (snap / "chapter_01.meta.json").write_text(
            json.dumps({"verdict": "Reject", "rewrite_count": 0}), encoding="utf-8"
        )
        (snap / "archive_reason.json").write_text(
            json.dumps({"reason": "retry_attempt_1", "chapter": 1}), encoding="utf-8"
        )
        return stamp

    def _get(self, path: str) -> tuple[int, dict]:
        status, _ct, body = routes.dispatch("GET", path)
        return status, json.loads(body)

    def test_versions_endpoint(self) -> None:
        stamp = self._seed()
        status, data = self._get(f"/api/workspace/{self.WS}/chapter/1/versions")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["chapter"], 1)
        self.assertEqual([v["id"] for v in data["versions"]], ["current", stamp])

    def test_versions_unknown_workspace_404(self) -> None:
        status, data = self._get("/api/workspace/nope/chapter/1/versions")
        self.assertEqual(status, 404, data)

    def test_diff_endpoint_returns_classified_lines(self) -> None:
        stamp = self._seed()
        status, data = self._get(
            f"/api/workspace/{self.WS}/chapter/1/diff?v1={stamp}&v2=current"
        )
        self.assertEqual(status, 200, data)
        self.assertFalse(data["identical"])
        types = [ln["type"] for ln in data["diff_lines"]]
        self.assertIn("add", types)
        self.assertIn("del", types)

    def test_diff_defaults_v2_to_current(self) -> None:
        stamp = self._seed()
        status, data = self._get(f"/api/workspace/{self.WS}/chapter/1/diff?v1={stamp}")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["v2"], "current")

    def test_diff_unknown_version_id_400(self) -> None:
        self._seed()
        # Path-traversal / unknown ids are rejected before any file access.
        for bad in ("../../etc/passwd", "19990101_000000", "bogus"):
            status, data = self._get(
                f"/api/workspace/{self.WS}/chapter/1/diff?v1={bad}&v2=current"
            )
            self.assertEqual(status, 400, f"{bad!r} -> {data}")
            self.assertEqual(data["error"], "unknown version id")

    def test_diff_identical_versions(self) -> None:
        self._seed()
        status, data = self._get(
            f"/api/workspace/{self.WS}/chapter/1/diff?v1=current&v2=current"
        )
        self.assertEqual(status, 200, data)
        self.assertTrue(data["identical"])
        self.assertEqual(data["diff_lines"], [])

    def test_versions_bad_chapter_number(self) -> None:
        self._seed()
        status, data = self._get(f"/api/workspace/{self.WS}/chapter/0/versions")
        self.assertEqual(status, 400, data)


if __name__ == "__main__":
    unittest.main()
