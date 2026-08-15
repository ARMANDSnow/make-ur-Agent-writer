"""Wizard end-to-end for imported-continuation preparation."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from src import paths
from src.web import jobs, routes
from src.web import workspace_meta


def _build_multipart(
    workspace: str,
    filename: str,
    content: bytes,
    mime: str,
    extra_fields: Optional[dict[str, str]] = None,
) -> tuple[bytes, str]:
    boundary = "----WIZARDTESTBOUND"
    chunks = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"workspace\"\r\n\r\n{workspace}\r\n".encode("utf-8")
    ]
    for key, value in (extra_fields or {}).items():
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode("utf-8")
        )
    chunks.append(
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"upload\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    )
    body = b"".join(chunks)
    return body, f"multipart/form-data; boundary={boundary}"


class WizardE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        jobs.reset_for_tests()
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _wait_for_done(self, ws: str, job_id: str, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, _, body = routes.dispatch("GET", f"/api/workspace/{ws}/job/{job_id}")
            rec = json.loads(body)
            if rec.get("status") in ("succeeded", "blocked", "failed", "aborted", "lost"):
                return rec
            time.sleep(0.05)
        self.fail("job did not finish")

    def test_upload_txt_prepares_manifest_without_writing_continuation(self) -> None:
        body, ct = _build_multipart(
            "newbook",
            "novel.txt",
            ("第一章 起点\n清晨六点，雨敲在玻璃上。\n" * 60).encode("utf-8"),
            "text/plain",
        )
        status, _ct, resp = routes.dispatch(
            "POST", "/api/wizard/start", body, {"content-type": ct}
        )
        self.assertEqual(status, 202, resp.decode("utf-8"))
        data = json.loads(resp)
        self.assertEqual(data["name"], "newbook")
        rec = self._wait_for_done("newbook", data["job_id"])
        self.assertEqual(rec["status"], "succeeded", f"job error: {rec.get('error')}")
        manifest = paths.WORKSPACE_DIR / "newbook" / "data" / "chapter_manifest.json"
        self.assertTrue(manifest.exists(), f"missing {manifest}")
        ch1 = paths.WORKSPACE_DIR / "newbook" / "outputs" / "drafts" / "chapter_01.md"
        self.assertFalse(ch1.exists(), "import must not write before a start point is selected")
        meta = workspace_meta.read("newbook")
        self.assertEqual(meta["creation_mode"], "continuation")

    def test_invalid_workspace_name_400(self) -> None:
        body, ct = _build_multipart("-bad-", "x.txt", b"hi", "text/plain")
        status, _ct, resp = routes.dispatch(
            "POST", "/api/wizard/start", body, {"content-type": ct}
        )
        self.assertEqual(status, 400)
        # iter063 A3: now a Chinese, actionable error card instead of the raw
        # English "invalid workspace name" the wizard used to show verbatim.
        data = json.loads(resp)
        self.assertEqual(data["card"]["code"], "invalid_workspace_name")
        self.assertIn("作品名", data["error"])

    def test_upload_only_forwards_local_prepare_timeout(self) -> None:
        body, ct = _build_multipart(
            "optionsbook",
            "novel.txt",
            ("第一章\n测试。\n" * 30).encode("utf-8"),
            "text/plain",
            extra_fields={"extract_limit": "7", "budget_cny": "3.5", "timeout_minutes": "12"},
        )
        with patch("src.web.wizard.jobs.start_job", return_value={"job_id": "a" * 32}) as start:
            status, _ct, resp = routes.dispatch(
                "POST", "/api/wizard/start", body, {"content-type": ct}
            )
        self.assertEqual(status, 202, resp.decode("utf-8"))
        self.assertEqual(start.call_args.args[1], "prepare-import")
        params = start.call_args.args[2]
        self.assertEqual(params["timeout_minutes"], 12.0)
        self.assertNotIn("extract_limit", params)
        self.assertNotIn("budget_cny", params)

    def test_unsupported_mime_415(self) -> None:
        body, ct = _build_multipart("okname", "x.pdf", b"%PDF-1.4", "application/pdf")
        status, _ct, resp = routes.dispatch(
            "POST", "/api/wizard/start", body, {"content-type": ct}
        )
        self.assertEqual(status, 415)

    def test_missing_upload_field_400(self) -> None:
        # Only workspace, no file
        boundary = "----X"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"workspace\"\r\n\r\nokname\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        status, _ct, resp = routes.dispatch(
            "POST", "/api/wizard/start", body,
            {"content-type": f"multipart/form-data; boundary={boundary}"},
        )
        self.assertEqual(status, 400)
        self.assertIn("upload", json.loads(resp)["error"])

    def test_corrupt_epub_rolls_back_workspace(self) -> None:
        """Iter 026 code-review #2 fix: a malformed .epub (or anything
        that ``extract_epub`` rejects) must roll back the half-created
        workspace so the user can retry with the same name. Before the
        fix the exception bubbled to dispatch catch-all, returned a 500
        trace_id, and left the workspace dir on disk → next same-name
        upload hit 409 forever."""
        body, ct = _build_multipart(
            "retryable",
            "broken.epub",
            b"NOT-A-VALID-ZIP-FILE-AT-ALL",
            "application/epub+zip",
        )
        status, _ct, resp = routes.dispatch(
            "POST", "/api/wizard/start", body, {"content-type": ct}
        )
        self.assertEqual(status, 400, resp.decode("utf-8"))
        self.assertIn("upload", json.loads(resp)["error"])
        # The workspace dir must NOT remain on disk.
        self.assertFalse((paths.WORKSPACE_DIR / "retryable").exists())
        # And the user can immediately retry with the same name.
        body2, ct2 = _build_multipart(
            "retryable", "ok.txt", ("第一章\n测试。\n" * 30).encode(), "text/plain"
        )
        status2, _ct2, resp2 = routes.dispatch(
            "POST", "/api/wizard/start", body2, {"content-type": ct2}
        )
        self.assertEqual(status2, 202, resp2.decode("utf-8"))
        # Drain the spawned job to keep tearDown clean.
        self._wait_for_done("retryable", json.loads(resp2)["job_id"])

    def test_non_utf8_txt_rolls_back_workspace(self) -> None:
        """iter059 NEW-B: a binary / non-UTF-8 .txt was accepted by the raw
        write_bytes, then failed deep in the background job, leaving the
        workspace lingering (409 on same-name retry). Now it's a synchronous
        400 + rollback, mirroring the corrupt-EPUB UX."""
        body, ct = _build_multipart(
            "binbook", "novel.txt", b"\xff\xfe\x00\x01binary-not-utf8\x80\x81", "text/plain"
        )
        status, _ct, resp = routes.dispatch(
            "POST", "/api/wizard/start", body, {"content-type": ct}
        )
        self.assertEqual(status, 400, resp.decode("utf-8"))
        # iter063 A3: Chinese error card; title still mentions UTF-8.
        data = json.loads(resp)
        self.assertEqual(data["card"]["code"], "upload_not_utf8")
        self.assertIn("UTF-8", data["error"])
        self.assertFalse((paths.WORKSPACE_DIR / "binbook").exists())
        # Same-name retry with a valid file works.
        body2, ct2 = _build_multipart(
            "binbook", "ok.txt", ("第一章\n测试。\n" * 30).encode(), "text/plain"
        )
        status2, _ct2, resp2 = routes.dispatch(
            "POST", "/api/wizard/start", body2, {"content-type": ct2}
        )
        self.assertEqual(status2, 202, resp2.decode("utf-8"))
        self._wait_for_done("binbook", json.loads(resp2)["job_id"])

    def test_no_chapter_txt_rolls_back_workspace(self) -> None:
        """iter059 #3: a UTF-8 .txt with no recognizable chapter headings would
        split into 0 chapters and the job failed with the cryptic "chapter
        manifest not found" while the workspace lingered. Now: synchronous 400 +
        rollback so the user can re-upload."""
        body, ct = _build_multipart(
            "noheadings",
            "novel.txt",
            ("就是一段没有任何章节标题的散文，反复堆叠。\n" * 80).encode("utf-8"),
            "text/plain",
        )
        status, _ct, resp = routes.dispatch(
            "POST", "/api/wizard/start", body, {"content-type": ct}
        )
        self.assertEqual(status, 400, resp.decode("utf-8"))
        # iter063 A3: Chinese, actionable card ("没找到章节标题") instead of the
        # raw English "no chapter headings…" string.
        data = json.loads(resp)
        self.assertEqual(data["card"]["code"], "upload_no_chapters")
        self.assertIn("章节", data["error"])
        self.assertFalse((paths.WORKSPACE_DIR / "noheadings").exists())
        # And a same-name retry with a properly-headed file works.
        body2, ct2 = _build_multipart(
            "noheadings", "ok.txt", ("第一章\n测试。\n" * 30).encode(), "text/plain"
        )
        status2, _ct2, resp2 = routes.dispatch(
            "POST", "/api/wizard/start", body2, {"content-type": ct2}
        )
        self.assertEqual(status2, 202, resp2.decode("utf-8"))
        self._wait_for_done("noheadings", json.loads(resp2)["job_id"])

    def test_existing_workspace_409(self) -> None:
        (paths.WORKSPACE_DIR / "occupied" / "data").mkdir(parents=True)
        body, ct = _build_multipart("occupied", "x.txt", b"hi", "text/plain")
        status, _ct, resp = routes.dispatch(
            "POST", "/api/wizard/start", body, {"content-type": ct}
        )
        self.assertEqual(status, 409)





if __name__ == "__main__":
    unittest.main()
