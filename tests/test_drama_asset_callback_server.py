"""Callback-only public drama asset service regressions for iter141."""

from __future__ import annotations

import base64
import http.client
import io
import math
import os
import socket
import sys
import threading
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from src import drama_asset_callback_server as callback
from src import drama_video


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class DramaAssetCallbackServerTests(TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name) / "workspaces"
        root.mkdir()
        self.workspace_root = root
        self.server = callback.create_server(
            port=0,
            asset_reader=self._read_asset,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()
        self.addCleanup(self._stop_server)

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _register(self, *, lifetime: float = 30) -> tuple[str, Path]:
        source = Path(self.temporary.name) / "source.png"
        source.write_bytes(_PNG_1X1)
        token = drama_video.register_public_asset(
            source,
            expires_at=time.monotonic() + lifetime,
            store_root=self.workspace_root,
        )
        self.addCleanup(self._revoke_assets, [token])
        return token, source

    def _read_asset(self, token: str) -> tuple[bytes, str]:
        return drama_video.read_public_asset(
            token,
            store_root=self.workspace_root,
        )

    def _revoke_assets(self, tokens: list[str]) -> None:
        drama_video.revoke_public_assets(
            tokens,
            store_root=self.workspace_root,
        )

    def _request(self, method: str, target: str) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection(
            callback.CALLBACK_HOST,
            self.server.server_port,
            timeout=2,
        )
        try:
            connection.request(method, target)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def _raw_request(self, request: bytes) -> bytes:
        sock = socket.create_connection(
            (callback.CALLBACK_HOST, self.server.server_port),
            timeout=2,
        )
        try:
            sock.sendall(request)
            sock.shutdown(socket.SHUT_WR)
            response = bytearray()
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response.extend(chunk)
            return bytes(response)
        finally:
            sock.close()

    def test_exact_get_returns_frozen_png_with_safe_headers(self) -> None:
        token, source = self._register()
        source.write_bytes(b"changed-after-registration")
        status, headers, body = self._request(
            "GET",
            f"/media/drama-assets/{token}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, _PNG_1X1)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(headers["Content-Length"], str(len(_PNG_1X1)))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Connection"], "close")

    def test_revoked_and_expired_tokens_are_uniform_404(self) -> None:
        revoked, _source = self._register()
        self._revoke_assets([revoked])
        self.assertEqual(
            self._request("GET", f"/media/drama-assets/{revoked}"),
            (404, {
                "Content-Type": "application/octet-stream",
                "Content-Length": "0",
                "Cache-Control": "no-store",
                "Connection": "close",
            }, b""),
        )

        expired, _source = self._register(lifetime=0.01)
        time.sleep(0.02)
        status, _headers, body = self._request(
            "GET",
            f"/media/drama-assets/{expired}",
        )
        self.assertEqual((status, body), (404, b""))

    def test_paths_queries_encodings_and_methods_are_uniform_404(self) -> None:
        token, _source = self._register()
        targets = (
            "/",
            "/api",
            "/w/example/",
            "/static/app.js",
            f"/media/drama-assets/{token}/",
            f"/media/drama-assets/{token}?probe=1",
            f"/media/drama-assets/%2F{token}",
            f"//media/drama-assets/{token}",
            "/media/drama-assets/" + "a" * 31,
            "/media/drama-assets/" + "a" * 65,
        )
        for target in targets:
            with self.subTest(target=target):
                status, _headers, body = self._request("GET", target)
                self.assertEqual((status, body), (404, b""))
        for method in ("HEAD", "POST", "OPTIONS", "DELETE", "BREW"):
            with self.subTest(method=method):
                status, _headers, body = self._request(
                    method,
                    f"/media/drama-assets/{token}",
                )
                self.assertEqual((status, body), (404, b""))

    def test_malformed_and_http09_requests_cannot_reflect_or_bypass_headers(self) -> None:
        token, _source = self._register()
        malformed = self._raw_request(
            (
                f"GET /media/drama-assets/{token}?secret=1 EXTRA HTTP/1.1\r\n"
                "Host: callback\r\n\r\n"
            ).encode("ascii")
        )
        self.assertTrue(malformed.startswith(b"HTTP/1.1 404"))
        self.assertNotIn(token.encode("ascii"), malformed)
        self.assertNotIn(b"secret=1", malformed)
        self.assertTrue(malformed.endswith(b"\r\n\r\n"))

        http09 = self._raw_request(
            f"GET /media/drama-assets/{token}\r\n".encode("ascii")
        )
        self.assertTrue(http09.startswith(b"HTTP/1.1 404"))
        self.assertIn(b"Content-Length: 0\r\n", http09)
        self.assertNotIn(_PNG_1X1, http09)

        rejected_early = (
            f"POST /media/drama-assets/{token}\r\n",
            f"GET /media/drama-assets/{token} HTTP/2.0\r\n\r\n",
            f"GET /media/drama-assets/{token}?q=1 HTTP/x\r\n\r\n",
            f"GET /media/drama-assets/{token} EXTRA NOPE\r\n\r\n",
        )
        for request in rejected_early:
            with self.subTest(request=request.split()[0:2]):
                response = self._raw_request(request.encode("ascii"))
                self.assertTrue(response.startswith(b"HTTP/1.1 404"))
                self.assertIn(b"Content-Length: 0\r\n", response)
                self.assertIn(b"Cache-Control: no-store\r\n", response)
                self.assertNotIn(token.encode("ascii"), response)
                self.assertTrue(response.endswith(b"\r\n\r\n"))

    def test_server_never_logs_capability_or_request_details(self) -> None:
        token, _source = self._register()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self._request("GET", f"/media/drama-assets/{token}")
            self._request("BREW", f"/media/drama-assets/{token}?secret=1")
        rendered = stdout.getvalue() + stderr.getvalue()
        self.assertEqual(rendered, "")
        self.assertNotIn(token, rendered)

    def test_server_rejects_non_loopback_and_bounds_resources(self) -> None:
        with self.assertRaisesRegex(ValueError, "127.0.0.1"):
            callback.create_server(host="0.0.0.0", port=0)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            callback.create_server(port=0, max_concurrency=0)
        with self.assertRaisesRegex(ValueError, "request_timeout"):
            callback.create_server(port=0, request_timeout=0)
        for invalid in (math.nan, math.inf, -math.inf):
            with self.subTest(request_timeout=invalid):
                with self.assertRaisesRegex(ValueError, "finite"):
                    callback.create_server(port=0, request_timeout=invalid)
        self.assertEqual(self.server.max_concurrency, 8)
        self.assertEqual(self.server.request_timeout, 5.0)

    def test_total_request_deadline_closes_a_trickled_header(self) -> None:
        short = callback.create_server(port=0, request_timeout=0.2)
        thread = threading.Thread(
            target=short.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        thread.start()
        try:
            sock = socket.create_connection(
                (callback.CALLBACK_HOST, short.server_port),
                timeout=1,
            )
            started = time.monotonic()
            try:
                closed = False
                for byte in b"GET /slow HTTP/1.1\r\n":
                    try:
                        sock.sendall(bytes([byte]))
                    except OSError:
                        closed = True
                        break
                    time.sleep(0.05)
                if not closed:
                    try:
                        closed = sock.recv(1) == b""
                    except OSError:
                        closed = True
                self.assertTrue(closed)
                self.assertLess(time.monotonic() - started, 0.8)
            finally:
                sock.close()
        finally:
            short.shutdown()
            short.server_close()
            thread.join(timeout=2)

    def test_create_server_does_not_mutate_host_environment(self) -> None:
        sentinel = {
            "OPENAI_MODEL": "provider/model",
            "DRAMA_MODEL": "provider/model",
            "OPENAI_API_KEY": "secret-openai",
            "PLANNER_API_KEY": "secret-planner",
            "AI_DRAW_API_KEY": "secret-image",
            "SD_API_KEY": "secret-video",
        }
        with patch.dict(
            os.environ,
            sentinel,
            clear=False,
        ):
            extra = callback.create_server(port=0)
            try:
                for key, value in sentinel.items():
                    self.assertEqual(os.environ[key], value)
            finally:
                extra.server_close()

    def test_cli_process_pins_mock_and_removes_inherited_provider_keys(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_MODEL": "provider/model",
                "DRAMA_MODEL": "provider/model",
                "OPENAI_API_KEY": "secret-openai",
                "PLANNER_API_KEY": "secret-planner",
                "AI_DRAW_API_KEY": "secret-image",
                "SD_API_KEY": "secret-video",
            },
            clear=False,
        ):
            with (
                patch.object(sys, "argv", ["drama-asset-callback"]),
                patch.object(callback, "serve") as serve_mock,
            ):
                self.assertEqual(callback.main(), 0)
            serve_mock.assert_called_once_with(
                port=callback.DEFAULT_CALLBACK_PORT,
            )
            self.assertEqual(os.environ["OPENAI_MODEL"], "mock")
            self.assertEqual(os.environ["DRAMA_MODEL"], "mock")
            self.assertEqual(os.environ["DRAGON_RAJA_SKIP_DOTENV"], "1")
            self.assertEqual(os.environ["PYTHON_DOTENV_DISABLED"], "1")
            for key in callback._SECRET_ENV_KEYS:
                self.assertNotIn(key, os.environ)


if __name__ == "__main__":
    import unittest

    unittest.main()
