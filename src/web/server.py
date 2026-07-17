"""iter 025: ThreadingHTTPServer entry point.

``serve(host, port)`` is the only function ``main.py`` needs to call.
The handler class converts wire-format requests into ``routes.dispatch``
arguments and writes the tuple it returns back to the socket.

Ctrl+C triggers a clean ``server.shutdown()`` via ``KeyboardInterrupt``
so the port is released immediately on the next start.
"""

from __future__ import annotations

import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlsplit

from . import routes


_DRAMA_ASSET_MUTATION_PATH_RE = re.compile(
    r"^/api/workspace/[^/]+/drama/assets/"
    r"(?:select|status|art-direction-scope)/?$"
)
_DRAMA_ASSET_MUTATION_BODY_LIMIT = 32 * 1024


class WebHandler(BaseHTTPRequestHandler):
    server_version = "AgentContinuationWebUI/0.25"

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        self._respond("GET", self.path)

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        self._respond("POST", self.path)

    def do_PUT(self) -> None:  # noqa: N802 - stdlib naming
        self._respond("PUT", self.path)

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - stdlib hook
        # Default impl writes to stderr in a noisy CLF-ish format. For
        # this local dev tool a compact single line is enough; keep it
        # on stderr so it doesn't pollute --capture in test runs.
        import sys
        rendered = fmt % args
        # The video provider callback uses a bearer capability in the path.
        # BaseHTTPRequestHandler's request line would otherwise persist that
        # live token verbatim in stderr/access logs.
        rendered = re.sub(
            r"/media/drama-assets/[A-Za-z0-9_-]{32,64}",
            "/media/drama-assets/<redacted>",
            rendered,
        )
        sys.stderr.write(f"[web] {self.address_string()} {rendered}\n")

    def _respond(self, method: str, path: str) -> None:
        # iter 026: POST / PUT carry bodies. Hard cap at 64 MB so a
        # rogue Content-Length doesn't make us allocate the universe;
        # the wizard's multipart upload enforces its own tighter 50 MB
        # cap inside wizard.start_upload.
        body_bytes: bytes = b""
        if method in ("POST", "PUT"):
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                length = 0
            decoded_path = unquote(urlsplit(path).path)
            if (
                method == "POST"
                and _DRAMA_ASSET_MUTATION_PATH_RE.fullmatch(decoded_path)
                and length > _DRAMA_ASSET_MUTATION_BODY_LIMIT
            ):
                # iter129: this cap must run before rfile.read.  The route
                # repeats it for direct-dispatch tests and defense in depth.
                self.send_error(413, "Asset mutation payload too large")
                return
            if length > 64 * 1024 * 1024:
                self.send_error(413, "Payload too large")
                return
            if length > 0:
                body_bytes = self.rfile.read(length)
        # Pass lowercase-keyed headers dict — the wizard multipart
        # parser needs Content-Type; future handlers may want others.
        request_headers = {k.lower(): v for k, v in self.headers.items()}
        response_headers = {}
        try:
            response = routes.dispatch(method, path, body_bytes, request_headers)
            if len(response) == 4:
                status, content_type, body, response_headers = response
            else:
                status, content_type, body = response
        except Exception:  # pragma: no cover - last-resort guard
            # iter 025 had a bug: building the 500 JSON body from
            # ``str(exc)`` produces invalid JSON if the message contains
            # newlines or backslashes (code-review #7 / server.py:41).
            # Use a fixed body here; the real exception is already on
            # the dispatch path which now uses trace_id + server log.
            import sys
            import traceback as _tb

            sys.stderr.write("[web] handler dispatch crashed:\n")
            _tb.print_exc(file=sys.stderr)
            status = 500
            content_type = "application/json; charset=utf-8"
            body = b'{"error": "internal server error"}'
            response_headers = {}
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # No cache: dashboard data is read fresh on every load.
        self.send_header("Cache-Control", "no-store")
        # Only download handlers use the optional fourth response item. Keep
        # the allowlist deliberately narrow and reject CR/LF so future route
        # code cannot turn a filename into response-header injection.
        for key in ("Content-Disposition", "X-Content-Type-Options"):
            value = response_headers.get(key)
            if isinstance(value, str) and "\r" not in value and "\n" not in value:
                self.send_header(key, value)
        # ``routes.render_workspace_redirect`` emits a 301 body
        # whose ``<p data-redirect-to="...">`` carries the target URL.
        # The dispatcher contract is (status, content_type, body) — no
        # header dict — so we sniff the body here to add a Location.
        # Cheaper than restructuring every handler to return a header
        # bag for the one redirect endpoint.
        if 300 <= status < 400 and b"data-redirect-to=" in body:
            try:
                start = body.index(b'data-redirect-to="') + len(b'data-redirect-to="')
                end = body.index(b'"', start)
                self.send_header("Location", body[start:end].decode("utf-8", errors="replace"))
            except ValueError:
                pass
        self.end_headers()
        self.wfile.write(body)


# Iter 026 code-review #10: any host other than loopback opens the
# unauthenticated dashboard to the LAN. Tools can iterate this set to
# decide whether to warn; we keep it explicit so adding e.g. ``::1``
# (IPv6 loopback) later is a one-line change.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Start the dashboard. Blocks until Ctrl+C.

    Prints a multi-line stderr WARNING if ``host`` is not a loopback
    address — by default the dashboard exposes everything in ``workspaces/``
    (status, cost, manifest, reviews, llm_calls.jsonl tail), so binding to
    ``0.0.0.0`` on a public network is an information leak unless the opt-in
    ``NOVEL_API_TOKEN`` gate (iter 049) is set.
    """

    # iter 049: ensure ``.env`` is loaded into os.environ before the first
    # request, so a ``NOVEL_API_TOKEN`` written there actually gates ``/api/*``
    # (otherwise the gate stays silently disabled until some other code path
    # triggers ``get_model_config`` → ``load_dotenv_if_available``).
    from ..config import load_dotenv_if_available

    load_dotenv_if_available()

    address = (host, port)
    httpd = ThreadingHTTPServer(address, WebHandler)
    print(f"[web] serving on http://{host}:{port}")
    print("[web] press Ctrl+C to stop")
    if host not in _LOOPBACK_HOSTS:
        import sys

        sys.stderr.write(
            "\n"
            "================================================================\n"
            f"  ⚠️  WARNING: web dashboard bound to {host!r} (NOT loopback)\n"
            "  · NO authentication; anyone on the network can read all\n"
            "    workspace data (status / cost / manifest / reviews / logs).\n"
            "  · POST /api/workspace/<name>/run can trigger pipeline jobs.\n"
            "  · PUT /api/settings can overwrite .env (incl. API key field).\n"
            "  Press Ctrl+C now and restart with --host 127.0.0.1 unless\n"
            "  this network is trusted.\n"
            "================================================================\n\n"
        )
        sys.stderr.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[web] shutting down…")
    finally:
        httpd.server_close()
