"""Contract tests for integrations.novel_client.NovelClient (iter 049).

A stub ``ThreadingHTTPServer`` emulates the WebUI job API (src/web/routes.py)
so the client's request shaping, job-poll loop, and error mapping are pinned
without a live continuer or any LLM call.
"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from integrations.novel_client import NovelApiError, NovelClient, TERMINAL_STATUSES


class _StubState:
    def __init__(self) -> None:
        self.jobs = {}            # job_id -> {ws, step, scenario, polls}
        self.counter = 0
        self.saved_outline = None
        self.workspaces = ["alpha", "龙族"]


def _make_handler(state: _StubState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence test noise
            pass

        def _send(self, code, obj):
            raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

        # ---- routing helpers ----
        def _parts(self):
            p = urlparse(self.path)
            return unquote(p.path), parse_qs(p.query)

        def do_GET(self):
            path, query = self._parts()
            seg = path.strip("/").split("/")
            if path == "/api/workspaces/":
                return self._send(200, {"workspaces": state.workspaces})
            # /api/workspace/<ws>/...
            if len(seg) >= 3 and seg[0] == "api" and seg[1] == "workspace":
                ws = seg[2]
                tail = seg[3:]
                if tail == ["status"]:
                    return self._send(200, {"cost_cny": 0.0, "tokens": 0})
                if tail == ["workbench"]:
                    return self._send(
                        200,
                        {
                            "stage": "outline",
                            "has_kb": True,
                            "has_outline": False,
                            "has_plan": False,
                            "draft_count": 0,
                        },
                    )
                if tail == ["plan"]:
                    return self._send(
                        200,
                        {
                            "plan": {"chapters": [{"title": "第一章"}, {"title": "第二章"}]},
                            "outline_md": "# 大纲\n第一章 ...",
                            "decisions": {},
                            "draft_chapters": [],
                        },
                    )
                if tail == ["readiness"]:
                    if ws == "blocked_book":
                        return self._send(
                            200,
                            {
                                "status": "blocked",
                                "blockers": ["outline_missing"],
                                "warnings": [],
                                "recommended_commands": ["run plan-chapters"],
                            },
                        )
                    return self._send(
                        200, {"status": "ready", "blockers": [], "warnings": []}
                    )
                if len(tail) == 2 and tail[0] == "job":
                    return self._job_poll(ws, tail[1])
            return self._send(404, {"error": "no such route"})

        def do_POST(self):
            path, _query = self._parts()
            seg = path.strip("/").split("/")
            if path == "/api/wizard/premise-start":
                body = self._body()
                return self._send(202, {"name": body.get("workspace")})
            if len(seg) >= 4 and seg[0] == "api" and seg[1] == "workspace":
                ws = seg[2]
                if seg[3] == "run":
                    return self._run(ws)
                if seg[3] == "job" and len(seg) == 6 and seg[5] == "cancel":
                    return self._send(
                        202,
                        {
                            "job_id": seg[4],
                            "status": "running",
                            "cancel_requested": True,
                            "requested_at": 0.0,
                        },
                    )
            return self._send(404, {"error": "no such route"})

        def do_PUT(self):
            path, _query = self._parts()
            seg = path.strip("/").split("/")
            if len(seg) == 4 and seg[0] == "api" and seg[1] == "workspace" and seg[3] == "outline":
                body = self._body()
                outline = body.get("outline") or ""
                state.saved_outline = outline
                return self._send(200, {"saved": True, "chars": len(outline)})
            return self._send(404, {"error": "no such route"})

        # ---- job state machine ----
        def _run(self, ws):
            if ws == "busy_book":
                return self._send(
                    202 if False else 409,
                    {"error": "workspace already has a running job", "running_job_id": "old-1"},
                )
            body = self._body()
            step = body.get("step")
            state.counter += 1
            job_id = f"job{state.counter}"
            scenario = {
                "blocked_book": "blocked",
                "fail_book": "failed",
            }.get(ws, "succeeded")
            state.jobs[job_id] = {"ws": ws, "step": step, "scenario": scenario, "polls": 0}
            return self._send(202, {"job_id": job_id, "status": "pending", "step": step})

        def _job_poll(self, ws, job_id):
            job = state.jobs.get(job_id)
            if job is None or job["ws"] != ws:
                return self._send(404, {"error": "job not found"})
            job["polls"] += 1
            step = job["step"]
            base = {"job_id": job_id, "workspace": ws, "step": step, "error": None}
            if job["polls"] < 2:  # one running tick, then terminal
                base.update({"status": "running", "current_step": step, "progress": 0.5})
                return self._send(200, base)
            scenario = job["scenario"]
            base.update({"status": scenario, "current_step": scenario, "progress": 1.0})
            if scenario == "succeeded" and step == "write-book":
                base["result_summary"] = {
                    "status": "succeeded",
                    "chapters": 1,
                    "blocked": 0,
                    "cost_cny": 1.04,
                    "budget_cny": 5.0,
                }
            elif scenario == "blocked":
                base["result_summary"] = {
                    "status": "blocked",
                    "blocked": 1,
                    "first_blocked": {"reason": "start_point_missing", "error": "no start"},
                }
            elif scenario == "failed":
                base["error"] = "RuntimeError: boom"
            return self._send(200, base)

    return Handler


class NovelClientTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = _StubState()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self.state))
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = NovelClient(
            f"http://127.0.0.1:{self.port}", poll_interval_s=0.01, job_timeout_s=5.0
        )

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    async def test_create_premise(self):
        out = await self.client.create_premise("newbook", "一个赛博朋克侦探故事")
        self.assertEqual(out["name"], "newbook")

    async def test_list_workspaces(self):
        names = await self.client.list_workspaces()
        self.assertIn("alpha", names)
        self.assertIn("龙族", names)

    async def test_run_and_wait_success_streams_progress(self):
        seen = []

        async def on_progress(step, frac):
            seen.append((step, frac))

        job = await self.client.run_and_wait(
            "mybook", "write-book", {"chapters": 1}, on_progress=on_progress
        )
        self.assertEqual(job["status"], "succeeded")
        self.assertIn(job["status"], TERMINAL_STATUSES)
        self.assertEqual(job["result_summary"]["cost_cny"], 1.04)
        # progress fired for the running tick (0.5) and the terminal tick (1.0)
        self.assertEqual([f for _s, f in seen], [0.5, 1.0])

    async def test_run_and_wait_sync_progress_callback(self):
        seen = []
        job = await self.client.run_and_wait(
            "mybook", "plan-chapters", {"target_chapters": 3},
            on_progress=lambda s, f: seen.append(f),
        )
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(seen, [0.5, 1.0])

    async def test_run_and_wait_blocked(self):
        job = await self.client.run_and_wait("blocked_book", "write-book", {"chapters": 1})
        self.assertEqual(job["status"], "blocked")
        self.assertEqual(job["result_summary"]["first_blocked"]["reason"], "start_point_missing")

    async def test_run_and_wait_failed(self):
        job = await self.client.run_and_wait("fail_book", "write-book", {"chapters": 1})
        self.assertEqual(job["status"], "failed")
        self.assertIn("RuntimeError", job["error"])

    async def test_run_step_conflict_409(self):
        with self.assertRaises(NovelApiError) as ctx:
            await self.client.run_step("busy_book", "write-book", {})
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.running_job_id, "old-1")

    async def test_save_outline(self):
        out = await self.client.save_outline("mybook", "# 新大纲")
        self.assertTrue(out["saved"])
        self.assertEqual(self.state.saved_outline, "# 新大纲")

    async def test_readiness_blocked(self):
        r = await self.client.readiness("blocked_book", chapters=2)
        self.assertEqual(r["status"], "blocked")
        self.assertIn("outline_missing", r["blockers"])

    async def test_plan_returns_chapters(self):
        p = await self.client.plan("mybook")
        self.assertEqual(len(p["plan"]["chapters"]), 2)

    def test_workbench_url_encodes_cjk(self):
        client = NovelClient("http://127.0.0.1:8765/")
        self.assertEqual(
            client.workbench_url("龙族"),
            "http://127.0.0.1:8765/w/%E9%BE%99%E6%97%8F/workbench",
        )

    async def test_connection_error_raises(self):
        dead = NovelClient("http://127.0.0.1:1", request_timeout_s=1.0)
        with self.assertRaises(NovelApiError) as ctx:
            await dead.list_workspaces()
        self.assertEqual(ctx.exception.status_code, 0)


if __name__ == "__main__":
    unittest.main()
