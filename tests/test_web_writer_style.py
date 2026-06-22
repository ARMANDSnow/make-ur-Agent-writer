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

    def test_route_threads_unique_sample_path(self) -> None:
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
        sp = captured["params"]["sample_path"]
        # unique per request, not the legacy fixed shared name
        self.assertNotEqual(Path(sp).name, ".writer_style_sample.tmp")
        self.assertTrue(Path(sp).name.startswith(".writer_style_sample."))
        self.assertTrue(Path(sp).exists())  # staged (job faked, so not consumed)
        self.assertFalse(paths.writer_style_sample_path().exists())  # fixed path unused

    def test_concurrent_uploads_distinct_paths_no_clobber(self) -> None:
        self._mkws("u2")
        seen: list = []
        real = jobs.start_job

        def fake(name, step, params=None):
            seen.append(params["sample_path"])
            return {"job_id": "b" * 32, "status": "running"}

        jobs.start_job = fake
        try:
            self._upload("u2", "AAAA 第一份样本。" * 60)
            self._upload("u2", "BBBB 第二份样本。" * 60)
        finally:
            jobs.start_job = real
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0], seen[1])  # distinct paths
        # both samples survive — neither overwrote the other (the TOCTOU fix)
        self.assertIn("AAAA", Path(seen[0]).read_text(encoding="utf-8"))
        self.assertIn("BBBB", Path(seen[1]).read_text(encoding="utf-8"))

    def test_handler_consumes_params_sample_path(self) -> None:
        # The handler reads its sample from params["sample_path"] and deletes it
        # (sample-not-persisted guard), proving the per-request path is honored.
        self._mkws("u3")
        os.environ["WORKSPACE_NAME"] = "u3"
        try:
            unique = paths.writer_style_sample_path().with_name(".writer_style_sample.feedface.tmp")
            unique.write_text("用于风格提炼的写作样本内容。" * 30, encoding="utf-8")
            result = jobs._step_extract_style({"sample_path": str(unique), "force": True}, lambda *a: None)
            self.assertEqual(result.get("status"), "succeeded", result)
            self.assertFalse(unique.exists())  # consumed + deleted
        finally:
            os.environ.pop("WORKSPACE_NAME", None)


class BusyTests(_WebHarness):
    def test_activate_busy_409(self) -> None:
        ws = self._premise("busy")
        with jobs.workspace_reserved(ws):
            status, data = self._activate(ws, "cold_scifi")
        self.assertEqual(status, 409, data)


if __name__ == "__main__":
    unittest.main()
