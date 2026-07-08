"""iter 056 轨 D: 风格卡 web 端点——预置库列举、激活(快照)、编辑(050 edit-loop
校验)、上传样本提取(multipart + pollJob + 样本不持久化)、workbench has_start_point
gate、busy 409。Mock-only。
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
from src.web.workspace_ctx import use_workspace
from src.workspace_lock import acquire_write_lock


class _WebHarness(unittest.TestCase):
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

    def _premise(self, ws: str) -> str:
        status, _ct, resp = routes.dispatch(
            "POST",
            "/api/wizard/premise-start",
            json.dumps({"workspace": ws, "premise": "少年觉醒上古血脉，在宗门倾轧中改命。"}, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 202, resp)
        return ws

    def _get_style(self, ws: str):
        status, _ct, body = routes.dispatch("GET", f"/api/workspace/{ws}/writer-style")
        return status, json.loads(body)

    def _activate(self, ws: str, preset_id: str):
        status, _ct, body = routes.dispatch(
            "POST",
            f"/api/workspace/{ws}/writer-style/activate",
            json.dumps({"preset_id": preset_id}).encode("utf-8"),
            {"content-type": "application/json"},
        )
        return status, json.loads(body)

    def _put(self, ws: str, fields, raw=None):
        body = raw if raw is not None else json.dumps({"fields": fields}, ensure_ascii=False).encode("utf-8")
        status, _ct, resp = routes.dispatch("PUT", f"/api/workspace/{ws}/writer-style", body, {"content-type": "application/json"})
        return status, json.loads(resp)

    def _workbench(self, ws: str) -> dict:
        _status, _ct, body = routes.dispatch("GET", f"/api/workspace/{ws}/workbench")
        return json.loads(body)

    def _multipart(self, **fields):
        boundary = "----STYLETESTBOUND"
        body = b""
        for key, value in fields.items():
            if isinstance(value, tuple):  # (filename, content_bytes, mime)
                fn, content, mime = value
                body += (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{fn}"\r\n'
                    f"Content-Type: {mime}\r\n\r\n"
                ).encode("utf-8") + content + b"\r\n"
            else:
                body += (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
                ).encode("utf-8")
        body += f"--{boundary}--\r\n".encode("utf-8")
        return body, f"multipart/form-data; boundary={boundary}"

    def _wait_for_done(self, ws: str, job_id: str, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, _, body = routes.dispatch("GET", f"/api/workspace/{ws}/job/{job_id}")
            rec = json.loads(body)
            if rec.get("status") in ("succeeded", "blocked", "failed", "aborted", "lost"):
                return rec
            time.sleep(0.05)
        self.fail("job did not finish")


class PresetAndActivateTests(_WebHarness):
    def test_style_presets_returns_six(self) -> None:
        ws = self._premise("pres")
        status, _ct, body = routes.dispatch("GET", f"/api/workspace/{ws}/style-presets")
        self.assertEqual(status, 200)
        presets = json.loads(body)["presets"]
        self.assertEqual(len(presets), 6)
        self.assertTrue(all(p["card"]["name"] for p in presets))

    def test_writer_style_404_when_none(self) -> None:
        ws = self._premise("none")
        status, _data = self._get_style(ws)
        self.assertEqual(status, 404)

    def test_activate_then_get(self) -> None:
        ws = self._premise("act")
        status, data = self._activate(ws, "cold_scifi")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["preset_id"], "cold_scifi")
        status, got = self._get_style(ws)
        self.assertEqual(status, 200)
        self.assertEqual(got["source"], "preset")
        self.assertEqual(got["fields"]["name"], "冷峻科幻")

    def test_activate_bad_id_400(self) -> None:
        ws = self._premise("badid")
        status, data = self._activate(ws, "no_such_preset")
        self.assertEqual(status, 400, data)


class EditTests(_WebHarness):
    def test_put_save_then_get(self) -> None:
        ws = self._premise("put")
        status, data = self._put(ws, {"name": "我的风格", "rhythm": "快节奏"})
        self.assertEqual(status, 200, data)
        status, got = self._get_style(ws)
        self.assertEqual(status, 200)
        self.assertEqual(got["fields"]["name"], "我的风格")
        self.assertEqual(got["source"], "manual")

    def test_put_unknown_field_400(self) -> None:
        ws = self._premise("unk")
        status, data = self._put(ws, {"bogus": "x"})
        self.assertEqual(status, 400, data)

    def test_put_control_chars_400(self) -> None:
        ws = self._premise("ctrl")
        # raw JSON 携带  转义 → 解析后含真控制字符（源码本身不含 null）
        raw = b'{"fields": {"name": "a\\u0000b"}}'
        status, data = self._put(ws, None, raw=raw)
        self.assertEqual(status, 400, data)

    def test_put_bad_json_400(self) -> None:
        ws = self._premise("badjson")
        status, data = self._put(ws, None, raw=b"{not json")
        self.assertEqual(status, 400, data)

    def test_put_over_length_400(self) -> None:
        ws = self._premise("toolong")
        status, data = self._put(ws, {"name": "字" * 100})  # >40 → schema 拒
        self.assertEqual(status, 400, data)


class WorkbenchGateTests(_WebHarness):
    def test_has_start_point_false_for_premise(self) -> None:
        ws = self._premise("wb")
        wb = self._workbench(ws)
        self.assertIn("has_start_point", wb)
        self.assertFalse(wb["has_start_point"])


class ExtractTests(_WebHarness):
    def test_extract_text_creates_card_and_deletes_sample(self) -> None:
        ws = self._premise("ext")
        sample = "这是一段用于风格提炼的写作样本内容。" * 30  # >200 字符
        body, ct = self._multipart(text=sample)
        status, _ct, resp = routes.dispatch("POST", f"/api/workspace/{ws}/writer-style/extract", body, {"content-type": ct})
        self.assertEqual(status, 202, resp)
        rec = self._wait_for_done(ws, json.loads(resp)["job_id"])
        self.assertEqual(rec["status"], "succeeded", rec)
        status, data = self._get_style(ws)
        self.assertEqual(status, 200)
        self.assertEqual(data["source"], "extract")
        self.assertEqual(data["fields"]["name"], "mock 风格卡")
        # 样本不持久化：临时文件提取后即删
        self.assertFalse((paths.WORKSPACE_DIR / ws / "data" / ".writer_style_sample.tmp").exists())

    def test_extract_too_short_400(self) -> None:
        ws = self._premise("short")
        body, ct = self._multipart(text="太短了")
        status, _ct, resp = routes.dispatch("POST", f"/api/workspace/{ws}/writer-style/extract", body, {"content-type": ct})
        self.assertEqual(status, 400, resp)

    def test_extract_non_multipart_415(self) -> None:
        ws = self._premise("nm")
        status, _ct, resp = routes.dispatch(
            "POST",
            f"/api/workspace/{ws}/writer-style/extract",
            json.dumps({"text": "x"}).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 415, resp)


class ExtractUniqueSampleTests(_WebHarness):
    """iter060 (#11): each upload stages its sample to a per-request UNIQUE path
    threaded through the job params — was a fixed .writer_style_sample.tmp
    written before the job read it, so two concurrent extracts overwrote each
    other (loser clobbered the winner's sample)."""

    def _mkws(self, ws: str) -> None:
        (paths.WORKSPACE_DIR / ws / "data").mkdir(parents=True, exist_ok=True)

    def _upload(self, ws: str, sample: str):
        body, ct = self._multipart(text=sample)
        return routes.dispatch(
            "POST", f"/api/workspace/{ws}/writer-style/extract", body, {"content-type": ct}
        )

    def test_route_threads_unique_sample_token(self) -> None:
        self._mkws("u1")
        captured: dict = {}
        real = jobs.start_job

        def fake(name, step, params=None):  # capture params, don't spawn a worker
            captured["params"] = params
            return {"job_id": "a" * 32, "status": "running"}

        jobs.start_job = fake
        try:
            status, _ct, resp = self._upload("u1", "样本内容。" * 60)
        finally:
            jobs.start_job = real
        self.assertEqual(status, 202, resp)
        params = captured["params"]
        # iter061 P0: the route passes only a random token, never a path — the
        # exploitable sample_path key must be gone.
        self.assertNotIn("sample_path", params)
        token = params["sample_token"]
        self.assertRegex(token, r"^[0-9a-f]{32}$")
        staged = paths.WORKSPACE_DIR / "u1" / "data" / f".writer_style_sample.{token}.tmp"
        self.assertTrue(staged.exists())  # staged (job faked, so not consumed)
        self.assertFalse((paths.WORKSPACE_DIR / "u1" / "data" / ".writer_style_sample.tmp").exists())

    def test_concurrent_uploads_distinct_tokens_no_clobber(self) -> None:
        self._mkws("u2")
        seen: list = []
        real = jobs.start_job

        def fake(name, step, params=None):
            seen.append(params["sample_token"])
            return {"job_id": "b" * 32, "status": "running"}

        jobs.start_job = fake
        try:
            self._upload("u2", "AAAA 第一份样本。" * 60)
            self._upload("u2", "BBBB 第二份样本。" * 60)
        finally:
            jobs.start_job = real
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0], seen[1])  # distinct tokens
        data_dir = paths.WORKSPACE_DIR / "u2" / "data"
        f0 = data_dir / f".writer_style_sample.{seen[0]}.tmp"
        f1 = data_dir / f".writer_style_sample.{seen[1]}.tmp"
        # both samples survive — neither overwrote the other (the TOCTOU fix)
        self.assertIn("AAAA", f0.read_text(encoding="utf-8"))
        self.assertIn("BBBB", f1.read_text(encoding="utf-8"))

    def test_upload_returns_409_without_staging_sample_when_cli_lock_held(self) -> None:
        self._mkws("u_lock")
        real = jobs.start_job

        def fail_start(*_args, **_kwargs):
            raise AssertionError("start_job must not run when workspace flock is held")

        jobs.start_job = fail_start
        try:
            with use_workspace("u_lock"):
                with acquire_write_lock(source="cli-long-run"):
                    status, _ct, resp = self._upload("u_lock", "锁内样本内容。" * 60)
        finally:
            jobs.start_job = real

        self.assertEqual(status, 409, resp)
        data = json.loads(resp)
        self.assertTrue(data.get("workspace_locked"), data)
        self.assertEqual(data.get("holder", {}).get("source"), "cli-long-run")
        samples = list((paths.WORKSPACE_DIR / "u_lock" / "data").glob(".writer_style_sample.*.tmp"))
        self.assertEqual(samples, [])

    def test_handler_consumes_token_sample(self) -> None:
        # The handler rebuilds the path inside data_dir from the token, reads the
        # sample and deletes it (sample-not-persisted guard).
        self._mkws("u3")
        os.environ["WORKSPACE_NAME"] = "u3"
        try:
            token = "feedface" * 4  # 32 hex chars
            staged = paths.writer_style_sample_path().with_name(f".writer_style_sample.{token}.tmp")
            staged.write_text("用于风格提炼的写作样本内容。" * 30, encoding="utf-8")
            result = jobs._step_extract_style({"sample_token": token, "force": True}, lambda *a: None)
            self.assertEqual(result.get("status"), "succeeded", result)
            self.assertFalse(staged.exists())  # consumed + deleted
        finally:
            os.environ.pop("WORKSPACE_NAME", None)

    def test_handler_sweeps_orphan_samples_from_cancelled_jobs(self) -> None:
        # iter063 ①: a sample left by an EARLIER extract job that was cancelled
        # before its finally ran would otherwise persist forever (the unique-token
        # path can't be overwritten by a later upload). The next extract job
        # sweeps all sibling .writer_style_sample.*.tmp — P0-A copyright guardrail.
        self._mkws("u6")
        os.environ["WORKSPACE_NAME"] = "u6"
        try:
            orphan = paths.writer_style_sample_path().with_name(
                ".writer_style_sample." + ("deadbeef" * 4) + ".tmp"
            )
            orphan.write_text("孤儿样本残留", encoding="utf-8")
            token = "feedface" * 4
            staged = paths.writer_style_sample_path().with_name(f".writer_style_sample.{token}.tmp")
            staged.write_text("用于风格提炼的写作样本内容。" * 30, encoding="utf-8")
            result = jobs._step_extract_style({"sample_token": token, "force": True}, lambda *a: None)
            self.assertEqual(result.get("status"), "succeeded", result)
            self.assertFalse(orphan.exists(), "orphaned sample must be swept")
            self.assertFalse(staged.exists(), "current sample consumed + deleted")
        finally:
            os.environ.pop("WORKSPACE_NAME", None)

    def test_handler_deletes_sample_on_cancel(self) -> None:
        # iter063 ①: a JobCancelled raised by progress_cb (cancel/timeout) must
        # still delete the sample — it used to leak because progress_cb ran
        # before the try/finally that owns the unlink.
        self._mkws("u7")
        os.environ["WORKSPACE_NAME"] = "u7"
        try:
            token = "abadcafe" * 4
            staged = paths.writer_style_sample_path().with_name(f".writer_style_sample.{token}.tmp")
            staged.write_text("写作样本内容。" * 40, encoding="utf-8")

            def _cancel(*_a):
                raise jobs.JobCancelled("cancelled mid-extract")

            with self.assertRaises(jobs.JobCancelled):
                jobs._step_extract_style({"sample_token": token, "force": True}, _cancel)
            self.assertFalse(staged.exists(), "sample deleted even when cancelled")
        finally:
            os.environ.pop("WORKSPACE_NAME", None)

    def test_cleanup_extract_sample_handles_queued_cancel(self) -> None:
        # iter063 ① (审查补漏): a job cancelled while QUEUED never runs the
        # handler's try/finally, so the worker finally must still delete the
        # staged sample (P0-A guardrail). Per-token, traversal-safe.
        self._mkws("u8")
        os.environ["WORKSPACE_NAME"] = "u8"
        try:
            token = "facefeed" * 4
            staged = paths.writer_style_sample_path().with_name(f".writer_style_sample.{token}.tmp")
            staged.write_text("queued-then-cancelled 样本", encoding="utf-8")
            jobs._cleanup_extract_sample("u8", {"sample_token": token})
            self.assertFalse(staged.exists(), "queued-cancel sample must be cleaned by worker finally")
            # invalid/traversal token → no-op, no crash, no external delete
            jobs._cleanup_extract_sample("u8", {"sample_token": "../../../etc/passwd"})
            jobs._cleanup_extract_sample("u8", {})
        finally:
            os.environ.pop("WORKSPACE_NAME", None)

    def test_handler_ignores_caller_sample_path_no_external_delete(self) -> None:
        # iter061 P0: a caller-supplied params.sample_path pointing OUTSIDE the
        # workspace must be ignored — the handler rebuilds from a token only, so
        # the external file is neither read nor deleted.
        self._mkws("u4")
        os.environ["WORKSPACE_NAME"] = "u4"
        external = Path(self._tmp.name) / "victim_outside_workspace.txt"
        external.write_text("do not delete me", encoding="utf-8")
        try:
            result = jobs._step_extract_style({"sample_path": str(external), "force": True}, lambda *a: None)
        finally:
            os.environ.pop("WORKSPACE_NAME", None)
        self.assertTrue(external.exists(), "external file must NOT be deleted")
        self.assertEqual(result.get("status"), "blocked", result)  # fixed-path fallback absent

    def test_handler_rejects_traversal_token_no_external_delete(self) -> None:
        # A non-hex / traversal token must not resolve outside data_dir.
        self._mkws("u5")
        os.environ["WORKSPACE_NAME"] = "u5"
        external = Path(self._tmp.name) / "victim2.txt"
        external.write_text("safe", encoding="utf-8")
        try:
            result = jobs._step_extract_style(
                {"sample_token": f"../../../../{external}", "force": True}, lambda *a: None
            )
        finally:
            os.environ.pop("WORKSPACE_NAME", None)
        self.assertTrue(external.exists())
        self.assertEqual(result.get("status"), "blocked", result)

    def test_run_endpoint_rejects_arbitrary_sample_path(self) -> None:
        # End-to-end: POST /run with a malicious params.sample_path must not let
        # extract-style read+delete a file outside the workspace.
        self._mkws("u6")
        external = Path(self._tmp.name) / "secret_outside.txt"
        external.write_text("top secret", encoding="utf-8")
        body = json.dumps(
            {"step": "extract-style", "params": {"sample_path": str(external)}}
        ).encode()
        status, _ct, resp = routes.dispatch("POST", "/api/workspace/u6/run", body)
        self.assertEqual(status, 202, resp)
        self._wait_for_done("u6", json.loads(resp)["job_id"])
        self.assertTrue(external.exists(), "external file must survive the job")


class BusyTests(_WebHarness):
    def test_activate_busy_409(self) -> None:
        ws = self._premise("busy")
        with jobs.workspace_reserved(ws):
            status, data = self._activate(ws, "cold_scifi")
        self.assertEqual(status, 409, data)


if __name__ == "__main__":
    unittest.main()
