"""iter 025: HTTP server integration (bind, serve, shutdown)."""

from __future__ import annotations

import socket
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from src.web.server import WebHandler


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.port = _free_port()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), WebHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        # give the bind a moment so the first request doesn't race
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2.0)

    def _get(self, path: str):
        return urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=2.0)

    def test_workspaces_endpoint(self) -> None:
        resp = self._get("/api/workspaces")
        self.assertEqual(resp.status, 200)
        self.assertIn("json", resp.headers.get("Content-Type", ""))
        body = resp.read().decode("utf-8")
        self.assertIn("workspaces", body)

    def test_index_html(self) -> None:
        resp = self._get("/")
        self.assertEqual(resp.status, 200)
        self.assertIn("html", resp.headers.get("Content-Type", ""))

    def test_unknown_path_404(self) -> None:
        try:
            self._get("/api/no-such-route")
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 404)
            self.assertIn("json", exc.headers.get("Content-Type", ""))

    def test_legacy_workspace_url_emits_location_header(self) -> None:
        """Iter 032: ``/workspace/<name>/`` returns 301 with a Location
        header pointing at the new ``/w/<name>/`` IA. urllib follows
        redirects automatically, so we use a no-redirect opener and
        check the status + header directly."""

        import tempfile
        from pathlib import Path
        from src import paths
        from src.web import routes as _routes

        # Stand up a workspace dir so the dispatcher doesn't 404 the
        # legacy URL before getting to the redirect path.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = paths.WORKSPACE_DIR
            paths.WORKSPACE_DIR = root
            (root / "alpha" / "data").mkdir(parents=True)
            try:
                _routes._clear_overview_cache()
                opener = urllib.request.build_opener(_NoRedirect())
                try:
                    resp = opener.open(
                        f"http://127.0.0.1:{self.port}/workspace/alpha/", timeout=2.0
                    )
                    self.fail(f"expected 301, got {resp.status}")
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 301)
                    self.assertEqual(exc.headers.get("Location"), "/w/alpha/")
            finally:
                paths.WORKSPACE_DIR = saved


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def http_error_301(self, req, fp, code, msg, headers):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)

    def http_error_302(self, req, fp, code, msg, headers):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


if __name__ == "__main__":
    unittest.main()
