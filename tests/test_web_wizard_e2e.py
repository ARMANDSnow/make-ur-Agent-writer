"""iter 026: wizard end-to-end (multipart upload + auto-pipeline job)."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from src import paths
from src.web import jobs, routes
from src.web import workspace_meta


def _build_multipart(workspace: str, filename: str, content: bytes, mime: str) -> tuple[bytes, str]:
    boundary = "----WIZARDTESTBOUND"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"workspace\"\r\n\r\n{workspace}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"upload\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
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
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        jobs.reset_for_tests()
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

    def test_upload_txt_runs_pipeline_to_chapter_01(self) -> None:
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
        ch1 = paths.WORKSPACE_DIR / "newbook" / "outputs" / "drafts" / "chapter_01.md"
        self.assertTrue(ch1.exists(), f"missing {ch1}")

    def test_invalid_workspace_name_400(self) -> None:
        body, ct = _build_multipart("-bad-", "x.txt", b"hi", "text/plain")
        status, _ct, resp = routes.dispatch(
            "POST", "/api/wizard/start", body, {"content-type": ct}
        )
        self.assertEqual(status, 400)
        self.assertIn("invalid workspace name", json.loads(resp)["error"])

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

    def test_existing_workspace_409(self) -> None:
        (paths.WORKSPACE_DIR / "occupied" / "data").mkdir(parents=True)
        body, ct = _build_multipart("occupied", "x.txt", b"hi", "text/plain")
        status, _ct, resp = routes.dispatch(
            "POST", "/api/wizard/start", body, {"content-type": ct}
        )
        self.assertEqual(status, 409)

    def test_drama_start_creates_empty_workspace_without_job(self) -> None:
        status, _ct, resp = routes.dispatch(
            "POST",
            "/api/wizard/drama-start",
            json.dumps({"workspace": "drama_a"}).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 200, resp.decode("utf-8"))
        data = json.loads(resp)
        self.assertEqual(data, {"name": "drama_a", "type": "drama"})
        self.assertNotIn("job_id", data)
        self.assertEqual(workspace_meta.read("drama_a")["type"], "drama")
        self.assertTrue((paths.WORKSPACE_DIR / "drama_a" / "data" / "tables").is_dir())
        self.assertTrue((paths.WORKSPACE_DIR / "drama_a" / "outputs" / "episodes").is_dir())

    def test_drama_start_rejects_reserved_workspace_name(self) -> None:
        status, _ct, resp = routes.dispatch(
            "POST",
            "/api/wizard/drama-start",
            json.dumps({"workspace": "_trash"}).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertIn("invalid workspace name", json.loads(resp)["error"])

    def test_drama_start_requires_json_content_type(self) -> None:
        status, _ct, _resp = routes.dispatch(
            "POST",
            "/api/wizard/drama-start",
            json.dumps({"workspace": "drama_a"}).encode("utf-8"),
            {"content-type": "text/plain"},
        )
        self.assertEqual(status, 415)


if __name__ == "__main__":
    unittest.main()
