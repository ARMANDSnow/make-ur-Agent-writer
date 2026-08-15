"""iter 025: HTTP server integration (bind, serve, shutdown)."""

from __future__ import annotations

import socket
import threading
import time
import unittest
import urllib.request
from http.client import HTTPMessage
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

from tests._socket_skip import SOCKET_BIND_BLOCKED

from src.web.server import WebHandler


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerFramingUnitTests(unittest.TestCase):
    """Transport framing checks that do not depend on loopback availability."""

    _PROTECTED_PATH = (
        "/api/workspace/ghost/job/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/cancel"
    )

    def _handler(self, fields: tuple[tuple[str, str], ...]) -> WebHandler:
        handler = object.__new__(WebHandler)
        headers = HTTPMessage()
        for name, value in fields:
            headers.add_header(name, value)
        handler.headers = headers
        handler.rfile = Mock()
        handler.wfile = Mock()
        handler.send_error = Mock()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        return handler

    def test_protected_mutation_rejects_ambiguous_framing_before_body_read(self) -> None:
        cases = (
            (),
            (("Content-Length", ""),),
            (("Content-Length", "+2"),),
            (("Content-Length", "02"),),
            (("Content-Length", "-1"),),
            (("Content-Length", "invalid"),),
            (("Content-Length", "2"), ("Content-Length", "2")),
            (("Content-Length", "2"), ("Content-Length", "65537")),
            (("Transfer-Encoding", ""), ("Content-Length", "2")),
            (("Transfer-Encoding", "chunked"), ("Content-Length", "2")),
            (
                ("Transfer-Encoding", ""),
                ("Transfer-Encoding", "chunked"),
                ("Content-Length", "2"),
            ),
        )
        for fields in cases:
            with self.subTest(fields=fields):
                handler = self._handler(fields)
                with patch("src.web.server.routes.dispatch") as dispatch:
                    handler._respond_inner("POST", self._PROTECTED_PATH)
                handler.send_error.assert_called_once()
                self.assertEqual(handler.send_error.call_args.args[0], 400)
                handler.rfile.read.assert_not_called()
                dispatch.assert_not_called()

    def test_protected_mutation_keeps_unique_oversize_length_at_413(self) -> None:
        for raw_length in ("65537", "9" * 5000):
            with self.subTest(raw_length_size=len(raw_length)):
                handler = self._handler((("Content-Length", raw_length),))
                with patch("src.web.server.routes.dispatch") as dispatch:
                    handler._respond_inner("POST", self._PROTECTED_PATH)
                handler.send_error.assert_called_once()
                self.assertEqual(handler.send_error.call_args.args[0], 413)
                handler.rfile.read.assert_not_called()
                dispatch.assert_not_called()

    def test_protected_mutation_accepts_one_canonical_length(self) -> None:
        handler = self._handler((
            ("Content-Length", "2"),
            ("Content-Type", "application/json"),
            ("X-Workspace-Mutation-Intent", "mutate-v1"),
            ("Host", "127.0.0.1:8765"),
        ))
        handler.rfile.read.return_value = b"{}"
        with patch(
            "src.web.server.routes.dispatch",
            return_value=(202, "application/json", b"{}"),
        ) as dispatch:
            handler._respond_inner("POST", self._PROTECTED_PATH)
        handler.send_error.assert_not_called()
        handler.rfile.read.assert_called_once_with(2)
        self.assertEqual(dispatch.call_args.args[2], b"{}")

    def test_protected_mutation_rejects_short_body_before_dispatch(self) -> None:
        handler = self._handler((
            ("Content-Length", "2"),
            ("Content-Type", "application/json"),
            ("X-Workspace-Mutation-Intent", "mutate-v1"),
            ("Host", "127.0.0.1:8765"),
        ))
        handler.rfile.read.return_value = b"{"
        with patch("src.web.server.routes.dispatch") as dispatch:
            handler._respond_inner("POST", self._PROTECTED_PATH)
        handler.send_error.assert_called_once_with(400, "Incomplete request body")
        dispatch.assert_not_called()

    def test_optional_bearer_gate_rejects_before_body_read(self) -> None:
        handler = self._handler((
            ("Content-Length", "2"),
            ("Content-Type", "application/json"),
            ("X-Workspace-Mutation-Intent", "mutate-v1"),
            ("Host", "127.0.0.1:8765"),
        ))
        with patch("src.web.auth.required_token", return_value="synthetic-token"), patch(
            "src.web.server.routes.dispatch"
        ) as dispatch:
            handler._respond_inner("POST", self._PROTECTED_PATH)
        handler.rfile.read.assert_not_called()
        dispatch.assert_not_called()
        handler.send_response.assert_called_once_with(401)

    def test_protected_mutation_rejects_header_contract_before_body_read(self) -> None:
        cases = (
            (
                ("Content-Length", "2"),
                ("Content-Type", "application/json"),
                ("Host", "127.0.0.1:8765"),
            ),
            (
                ("Content-Length", "2"),
                ("Content-Type", "text/plain"),
                ("X-Workspace-Mutation-Intent", "mutate-v1"),
                ("Host", "127.0.0.1:8765"),
            ),
            (
                ("Content-Length", "2"),
                ("Content-Type", "application/json"),
                ("X-Workspace-Mutation-Intent", "mutate-v1"),
                ("Host", "127.0.0.1:8765"),
                ("Origin", "https://evil.example"),
                ("Sec-Fetch-Site", "cross-site"),
            ),
        )
        for fields in cases:
            with self.subTest(fields=fields):
                handler = self._handler(fields)
                with patch("src.web.server.routes.dispatch") as dispatch:
                    handler._respond_inner("POST", self._PROTECTED_PATH)
                handler.rfile.read.assert_not_called()
                dispatch.assert_not_called()
                handler.send_response.assert_called_once()

    def test_non_protected_post_keeps_missing_length_compatibility(self) -> None:
        handler = self._handler(())
        with patch(
            "src.web.server.routes.dispatch",
            return_value=(200, "application/json", b"{}"),
        ) as dispatch:
            handler._respond_inner("POST", "/api/non-protected")
        handler.send_error.assert_not_called()
        handler.rfile.read.assert_not_called()
        self.assertEqual(dispatch.call_args.args[2], b"")


@unittest.skipIf(SOCKET_BIND_BLOCKED, "sandbox: socket.bind blocked")
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
