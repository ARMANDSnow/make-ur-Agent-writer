"""iter 026 P5: 4 hardening fixes from code-review #3 / #6 / #7 / #10."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from src import paths
from src.cli_workspace import list_workspaces
from src.web import routes
from src.web.server import serve


class TailJsonlPerformanceTests(unittest.TestCase):
    """#3 — _tail_jsonl must read constant-ish memory regardless of
    file size (no fh.readlines on a multi-MB file)."""

    def test_tail_of_large_file_returns_last_n(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as fh:
            for i in range(100_000):
                fh.write(f'{{"i": {i}}}\n'.encode("utf-8"))
            path = Path(fh.name)
        try:
            t0 = time.time()
            out = routes._tail_jsonl(path, 5)
            elapsed = time.time() - t0
            self.assertEqual(len(out), 5)
            self.assertEqual(out[-1]["i"], 99_999)
            self.assertEqual(out[0]["i"], 99_995)
            # Should be much faster than reading the whole 3 MB file
            # — set a generous ceiling to avoid flakes on slow CI.
            self.assertLess(elapsed, 0.5, f"tail took {elapsed:.3f}s")
        finally:
            path.unlink()

    def test_tail_empty_file_returns_empty_list(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as fh:
            path = Path(fh.name)
        try:
            self.assertEqual(routes._tail_jsonl(path, 10), [])
        finally:
            path.unlink()

    def test_tail_n_zero_returns_empty(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as fh:
            fh.write(b'{"x":1}\n{"x":2}\n')
            path = Path(fh.name)
        try:
            self.assertEqual(routes._tail_jsonl(path, 0), [])
        finally:
            path.unlink()


class ListWorkspacesFilterTests(unittest.TestCase):
    """#6 — list_workspaces must skip dev/tool cache dirs that share
    the parent (``__pycache__`` etc.)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = paths.WORKSPACE_DIR
        paths.WORKSPACE_DIR = Path(self._tmp.name)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved
        self._tmp.cleanup()

    def test_filters_dev_dirs(self) -> None:
        (paths.WORKSPACE_DIR / "real_book" / "data").mkdir(parents=True)
        (paths.WORKSPACE_DIR / "another_real" / "outputs").mkdir(parents=True)
        (paths.WORKSPACE_DIR / "__pycache__").mkdir()
        (paths.WORKSPACE_DIR / "no_subdirs_yet").mkdir()
        self.assertEqual(list_workspaces(), ["another_real", "real_book"])

    def test_empty_workspace_dir(self) -> None:
        self.assertEqual(list_workspaces(), [])


class DispatchExceptionMaskingTests(unittest.TestCase):
    """#7 — dispatch catch-all must NOT leak str(exc) to the client.
    Only ``trace_id`` + generic message."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = paths.WORKSPACE_DIR
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        ws = paths.WORKSPACE_DIR / "alpha"
        for sub in ("data", "outputs", "logs"):
            (ws / sub).mkdir(parents=True)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved
        self._tmp.cleanup()

    def test_unexpected_exception_returns_trace_id(self) -> None:
        # Force collect_status to blow up by stubbing it. We patch
        # the symbol routes imports.
        original = routes.collect_status

        def boom(*_a, **_kw):
            raise RuntimeError("secret path /Users/private/.env and trailing\nnewline")

        routes.collect_status = boom
        try:
            status, _ct, body = routes.dispatch("GET", "/api/workspace/alpha/status")
            data = json.loads(body)
            self.assertEqual(status, 500)
            self.assertEqual(data["error"], "internal server error")
            self.assertIn("trace_id", data)
            # No leaked traceback content
            self.assertNotIn("secret", body.decode())
            self.assertNotIn("Users", body.decode())
        finally:
            routes.collect_status = original


class ServeHostWarningTests(unittest.TestCase):
    """#10 — non-loopback bind must print a multi-line stderr WARNING."""

    def _serve_capture_stderr(self, host: str) -> str:
        # Patch serve_forever to no-op so the test doesn't actually
        # block on a listening socket forever.
        saved = ThreadingHTTPServer.serve_forever

        def _stop(self):
            raise KeyboardInterrupt

        ThreadingHTTPServer.serve_forever = _stop
        buf = io.StringIO()
        try:
            with contextlib.redirect_stderr(buf):
                serve(host=host, port=0)
        finally:
            ThreadingHTTPServer.serve_forever = saved
        return buf.getvalue()

    def test_zero_zero_host_warns(self) -> None:
        out = self._serve_capture_stderr("0.0.0.0")
        self.assertIn("WARNING", out)
        self.assertIn("NO authentication", out)

    def test_loopback_does_not_warn(self) -> None:
        out = self._serve_capture_stderr("127.0.0.1")
        self.assertNotIn("WARNING", out)


if __name__ == "__main__":
    unittest.main()
