"""Independent loopback callback process for the iter103 local E2E."""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", closefd=True) as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--ready-file", required=True)
    args = parser.parse_args()
    root = Path(args.workspace_root)
    marker = root / ".dragon-raja-local-e2e"
    if root.is_symlink() or not root.is_dir() or marker.is_symlink() or not marker.is_file():
        raise SystemExit("invalid local E2E workspace root")

    os.environ["DRAGON_RAJA_SKIP_DOTENV"] = "1"
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["OPENAI_MODEL"] = "mock"
    os.environ["DRAMA_MODEL"] = "mock"
    for key in ("OPENAI_API_KEY", "PLANNER_API_KEY", "AI_DRAW_API_KEY", "SD_API_KEY"):
        os.environ.pop(key, None)

    from src import paths
    from src.web import routes

    paths.WORKSPACE_DIR = root.resolve(strict=True)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            response = routes.dispatch("GET", self.path)
            status, content_type, body = response[:3]
            headers = response[3] if len(response) > 3 else {}
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    _atomic_json(Path(args.ready_file), {"port": server.server_port})
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

