"""Loopback-only HTTP server for short-lived drama image capabilities.

This process is intentionally smaller than the local Web workbench.  It serves
one exact read-only route for a Cloudflare Quick Tunnel and returns the same
empty 404 response for everything else.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable


CALLBACK_HOST = "127.0.0.1"
DEFAULT_CALLBACK_PORT = 8766
MAX_CONCURRENT_REQUESTS = 8
REQUEST_TIMEOUT_SECONDS = 5.0
_ASSET_PATH_RE = re.compile(
    r"^/media/drama-assets/(?P<token>[A-Za-z0-9_-]{32,64})$"
)
_SECRET_ENV_KEYS = (
    "OPENAI_API_KEY",
    "PLANNER_API_KEY",
    "AI_DRAW_API_KEY",
    "SD_API_KEY",
)
AssetReader = Callable[[str], tuple[bytes, str]]


def _pin_safe_environment() -> None:
    """Keep this callback process independent from dotenv and providers."""

    os.environ["DRAGON_RAJA_SKIP_DOTENV"] = "1"
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["OPENAI_MODEL"] = "mock"
    os.environ["DRAMA_MODEL"] = "mock"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"
    for key in _SECRET_ENV_KEYS:
        os.environ.pop(key, None)


class CallbackOnlyHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server with a hard upper bound on active handlers."""

    daemon_threads = True
    request_queue_size = MAX_CONCURRENT_REQUESTS

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        max_concurrency: int = MAX_CONCURRENT_REQUESTS,
        request_timeout: float = REQUEST_TIMEOUT_SECONDS,
        asset_reader: AssetReader | None = None,
    ) -> None:
        if (
            isinstance(max_concurrency, bool)
            or not isinstance(max_concurrency, int)
            or max_concurrency <= 0
        ):
            raise ValueError("max_concurrency must be a positive integer")
        if (
            isinstance(request_timeout, bool)
            or not isinstance(request_timeout, (int, float))
            or not math.isfinite(float(request_timeout))
            or request_timeout <= 0
        ):
            raise ValueError("request_timeout must be finite and positive")
        self.max_concurrency = max_concurrency
        self.request_timeout = float(request_timeout)
        self.asset_reader = asset_reader
        self._request_slots = threading.BoundedSemaphore(max_concurrency)
        super().__init__(server_address, handler_class)

    def process_request(
        self,
        request: socket.socket,
        client_address: tuple[str, int],
    ) -> None:
        if not self._request_slots.acquire(blocking=False):
            try:
                request.settimeout(self.request_timeout)
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Length: 0\r\n"
                    b"Cache-Control: no-store\r\n"
                    b"Connection: close\r\n\r\n"
                )
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(
        self,
        request: socket.socket,
        client_address: tuple[str, int],
    ) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()

    def handle_error(
        self,
        request: socket.socket,
        client_address: tuple[str, int],
    ) -> None:
        # Never let BaseServer print request details or a capability-bearing
        # request line after an unexpected handler failure.
        return


class DramaAssetCallbackHandler(BaseHTTPRequestHandler):
    """Serve only an exact GET capability; all other requests are 404."""

    protocol_version = "HTTP/1.1"
    server_version = "DramaAssetCallback"
    sys_version = ""

    def setup(self) -> None:
        super().setup()
        timeout = getattr(self.server, "request_timeout", REQUEST_TIMEOUT_SECONDS)
        self.connection.settimeout(timeout)
        self._deadline_timer = threading.Timer(timeout, self._expire_connection)
        self._deadline_timer.daemon = True
        self._deadline_timer.start()

    def finish(self) -> None:
        timer = getattr(self, "_deadline_timer", None)
        if timer is not None:
            timer.cancel()
        super().finish()

    def _expire_connection(self) -> None:
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def log_message(self, _format: str, *_args: Any) -> None:  # noqa: A003
        return

    def parse_request(self) -> bool:
        try:
            request_line = self.raw_requestline.decode("iso-8859-1").rstrip("\r\n")
        except UnicodeDecodeError:
            request_line = ""
        words = request_line.split()
        self._raw_request_target = words[1] if len(words) == 3 else ""
        if not super().parse_request():
            return False
        if self.request_version not in {"HTTP/1.0", "HTTP/1.1"}:
            # BaseHTTPRequestHandler suppresses all headers for HTTP/0.9.
            # Force a normal status-bearing response before rejecting it.
            self.request_version = "HTTP/1.0"
            self._not_found()
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        match = _ASSET_PATH_RE.fullmatch(
            getattr(self, "_raw_request_target", "")
        )
        if match is None:
            self._not_found()
            return
        try:
            reader = getattr(self.server, "asset_reader", None)
            if reader is None:
                from . import drama_video

                reader = drama_video.read_public_asset
            data, content_type = reader(match.group("token"))
        except Exception:
            self._not_found()
            return
        self._respond(
            200,
            data,
            content_type=content_type,
            extra_headers={"X-Content-Type-Options": "nosniff"},
        )

    def __getattr__(self, name: str) -> Any:
        # BaseHTTPRequestHandler otherwise emits a distinguishable 501 for an
        # unknown method.  Funnel every do_<METHOD> lookup into the same 404.
        if name.startswith("do_"):
            return self._not_found
        raise AttributeError(name)

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        # The stdlib error page reflects malformed request lines.  Never let a
        # capability, query, method or parser detail enter a public response.
        if getattr(self, "request_version", "") not in {"HTTP/1.0", "HTTP/1.1"}:
            self.request_version = "HTTP/1.0"
        self._not_found()

    def _not_found(self) -> None:
        self._respond(404, b"", content_type="application/octet-stream")

    def _respond(
        self,
        status: int,
        body: bytes,
        *,
        content_type: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.close_connection = True
        self.send_response_only(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)


def create_server(
    *,
    host: str = CALLBACK_HOST,
    port: int = DEFAULT_CALLBACK_PORT,
    max_concurrency: int = MAX_CONCURRENT_REQUESTS,
    request_timeout: float = REQUEST_TIMEOUT_SECONDS,
    asset_reader: AssetReader | None = None,
) -> CallbackOnlyHTTPServer:
    """Create but do not start the callback-only loopback server."""

    if host != CALLBACK_HOST:
        raise ValueError("drama asset callback server must bind to 127.0.0.1")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("port must be an integer between 0 and 65535")
    return CallbackOnlyHTTPServer(
        (host, port),
        DramaAssetCallbackHandler,
        max_concurrency=max_concurrency,
        request_timeout=request_timeout,
        asset_reader=asset_reader,
    )


def serve(*, port: int = DEFAULT_CALLBACK_PORT) -> None:
    """Run the callback-only listener until interrupted."""

    server = create_server(port=port)
    ready = {
        "ok": True,
        "service": "drama-asset-callback",
        "host": CALLBACK_HOST,
        "port": server.server_port,
    }
    print(json.dumps(ready, sort_keys=True, separators=(",", ":")), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> int:
    # This mutation belongs to the dedicated callback process boundary.  Keep
    # create_server() embeddable so tests and library callers are not allowed
    # to rewrite their host process environment merely by constructing a
    # loopback listener.
    _pin_safe_environment()
    parser = argparse.ArgumentParser(
        description="Serve only short-lived drama asset callback capabilities."
    )
    parser.add_argument("--port", type=int, default=DEFAULT_CALLBACK_PORT)
    args = parser.parse_args()
    try:
        serve(port=args.port)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"callback server failed: {type(exc).__name__}") from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
