"""iter 025: HTTP server integration (bind, serve, shutdown)."""

from __future__ import annotations

import socket
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from tests._socket_skip import SOCKET_BIND_BLOCKED

from src.web.server import WebHandler


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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

    def test_asset_mutation_transport_cap_rejects_before_body_read(self) -> None:
        """A header-only oversized request must receive 413 immediately.

        If the handler tried to read the declared body first, ``recv`` would
        time out because this client intentionally sends no body bytes.
        """

        with socket.create_connection(
            ("127.0.0.1", self.port),
            timeout=1.0,
        ) as client:
            client.settimeout(1.0)
            request = (
                "POST /api/workspace/ghost/drama/assets/select HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.port}\r\n"
                "Content-Type: application/json\r\n"
                "X-Drama-Asset-Intent: mutate-v1\r\n"
                "Content-Length: 65537\r\n"
                "Connection: close\r\n\r\n"
            )
            client.sendall(request.encode("ascii"))
            response = client.recv(4096)
        self.assertRegex(
            response.decode("iso-8859-1"),
            r"^HTTP/1\.[01] 413 ",
        )

    def test_storyboard_put_transport_cap_rejects_before_body_read(self) -> None:
        with socket.create_connection(
            ("127.0.0.1", self.port),
            timeout=1.0,
        ) as client:
            client.settimeout(1.0)
            request = (
                "PUT /api/workspace/ghost/drama/storyboard HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.port}\r\n"
                "Content-Type: application/json\r\n"
                "X-Drama-Mutation-Intent: mutate-v1\r\n"
                "Content-Length: 65537\r\n"
                "Connection: close\r\n\r\n"
            )
            client.sendall(request.encode("ascii"))
            response = client.recv(4096)
        self.assertRegex(
            response.decode("iso-8859-1"),
            r"^HTTP/1\.[01] 413 ",
        )

    def test_job_cancel_transport_cap_rejects_before_body_read(self) -> None:
        with socket.create_connection(
            ("127.0.0.1", self.port),
            timeout=1.0,
        ) as client:
            client.settimeout(1.0)
            request = (
                "POST /api/workspace/ghost/job/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/cancel HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.port}\r\n"
                "Content-Type: application/json\r\n"
                "X-Drama-Mutation-Intent: mutate-v1\r\n"
                "Content-Length: 65537\r\n"
                "Connection: close\r\n\r\n"
            )
            client.sendall(request.encode("ascii"))
            response = client.recv(4096)
        self.assertRegex(
            response.decode("iso-8859-1"),
            r"^HTTP/1\.[01] 413 ",
        )

    def test_job_cancel_rejects_ambiguous_transport_framing(self) -> None:
        requests = (
            "Content-Length: invalid\r\n",
            "Content-Length: -1\r\n",
            "Transfer-Encoding: chunked\r\n",
        )
        for framing in requests:
            with self.subTest(framing=framing.strip()):
                with socket.create_connection(
                    ("127.0.0.1", self.port),
                    timeout=1.0,
                ) as client:
                    client.settimeout(1.0)
                    request = (
                        "POST /api/workspace/ghost/job/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/cancel HTTP/1.1\r\n"
                        f"Host: 127.0.0.1:{self.port}\r\n"
                        "Content-Type: application/json\r\n"
                        "X-Drama-Mutation-Intent: mutate-v1\r\n"
                        f"{framing}"
                        "Connection: close\r\n\r\n"
                    )
                    client.sendall(request.encode("ascii"))
                    response = client.recv(4096)
                self.assertRegex(
                    response.decode("iso-8859-1"),
                    r"^HTTP/1\.[01] 400 ",
                )

    def test_shot_image_mutation_transport_cap_rejects_before_body_read(self) -> None:
        with socket.create_connection(
            ("127.0.0.1", self.port),
            timeout=1.0,
        ) as client:
            client.settimeout(1.0)
            request = (
                "POST /api/workspace/ghost/drama/shot-images/select HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.port}\r\n"
                "Content-Type: application/json\r\n"
                "X-Drama-Shot-Image-Intent: mutate-v1\r\n"
                "Content-Length: 65537\r\n"
                "Connection: close\r\n\r\n"
            )
            client.sendall(request.encode("ascii"))
            response = client.recv(4096)
        self.assertRegex(
            response.decode("iso-8859-1"),
            r"^HTTP/1\.[01] 413 ",
        )

    def test_shot_video_mutation_transport_cap_rejects_before_body_read(self) -> None:
        with socket.create_connection(
            ("127.0.0.1", self.port),
            timeout=1.0,
        ) as client:
            client.settimeout(1.0)
            request = (
                "POST /api/workspace/ghost/drama/shot-videos/select HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.port}\r\n"
                "Content-Type: application/json\r\n"
                "X-Drama-Shot-Video-Intent: mutate-v1\r\n"
                "Content-Length: 65537\r\n"
                "Connection: close\r\n\r\n"
            )
            client.sendall(request.encode("ascii"))
            response = client.recv(4096)
        self.assertRegex(
            response.decode("iso-8859-1"),
            r"^HTTP/1\.[01] 413 ",
        )

    def test_compose_transport_cap_rejects_before_body_read(self) -> None:
        with socket.create_connection(
            ("127.0.0.1", self.port),
            timeout=1.0,
        ) as client:
            client.settimeout(1.0)
            request = (
                "POST /api/workspace/ghost/drama/compose HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{self.port}\r\n"
                "Content-Type: application/json\r\n"
                "X-Drama-Compose-Intent: run-local-v1\r\n"
                "Content-Length: 65537\r\n"
                "Connection: close\r\n\r\n"
            )
            client.sendall(request.encode("ascii"))
            response = client.recv(4096)
        self.assertRegex(
            response.decode("iso-8859-1"),
            r"^HTTP/1\.[01] 413 ",
        )

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

    def test_download_response_emits_allowlisted_headers(self) -> None:
        with patch(
            "src.web.server.routes.dispatch",
            return_value=(
                200,
                "text/csv; charset=utf-8",
                b"a,b\r\n1,2\r\n",
                {
                    "Content-Disposition": 'attachment; filename="episode_01.storyboard.csv"',
                    "X-Content-Type-Options": "nosniff",
                    "X-Not-Allowlisted": "secret",
                },
            ),
        ):
            response = self._get("/download")
            self.assertEqual(response.headers.get("Content-Disposition"), 'attachment; filename="episode_01.storyboard.csv"')
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertIsNone(response.headers.get("X-Not-Allowlisted"))
            self.assertEqual(response.read(), b"a,b\r\n1,2\r\n")

    def test_head_and_range_response_headers_are_preserved(self) -> None:
        with patch(
            "src.web.server.routes.dispatch",
            return_value=(
                206,
                "video/mp4",
                b"",
                {
                    "Content-Length": "16",
                    "Accept-Ranges": "bytes",
                    "Content-Range": "bytes 0-15/128",
                    "X-Content-Type-Options": "nosniff",
                },
            ),
        ) as dispatch:
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/candidate.mp4",
                method="HEAD",
                headers={"Range": "bytes=0-15"},
            )
            response = urllib.request.urlopen(request, timeout=2.0)
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers.get("Content-Length"), "16")
            self.assertEqual(response.headers.get("Accept-Ranges"), "bytes")
            self.assertEqual(response.headers.get("Content-Range"), "bytes 0-15/128")
            self.assertEqual(response.read(), b"")
            self.assertEqual(dispatch.call_args.args[0], "HEAD")
            self.assertEqual(dispatch.call_args.args[3]["range"], "bytes=0-15")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def http_error_301(self, req, fp, code, msg, headers):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)

    def http_error_302(self, req, fp, code, msg, headers):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


if __name__ == "__main__":
    unittest.main()
