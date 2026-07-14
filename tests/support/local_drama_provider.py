"""Loopback-only fake media provider for the iter103 local E2E harness.

The server deliberately exposes only deterministic OpenAI-image-compatible
and short-drama-video-compatible contracts.  It never stores credentials,
prompts, callback capabilities, or signed result URLs in its public counters.
"""

from __future__ import annotations

import base64
import http.client
import json
import threading
from contextlib import AbstractContextManager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def strict_mp4_fixture() -> bytes:
    """Return a bounded MP4 accepted by the production structural probe.

    The checked-in mock already has a real ISO-BMFF box graph and sample
    table.  This local-provider fixture changes only the probed duration and
    display dimensions to the authorized 5 second, 720x1280 contract.
    """

    from src import drama_video

    payload = bytearray(drama_video._MOCK_MP4)
    moov_start, moov_end = drama_video._first_mp4_box(payload, 0, len(payload), b"moov")
    mvhd_start, _mvhd_end = drama_video._first_mp4_box(
        payload, moov_start, moov_end, b"mvhd"
    )
    if payload[mvhd_start] != 0:
        raise AssertionError("local fixture expects mvhd version 0")
    payload[mvhd_start + 12:mvhd_start + 16] = (1000).to_bytes(4, "big")
    payload[mvhd_start + 16:mvhd_start + 20] = (5000).to_bytes(4, "big")
    for kind, trak_start, trak_end in drama_video._mp4_boxes(payload, moov_start, moov_end):
        if kind != b"trak":
            continue
        tkhd_start, _tkhd_end = drama_video._first_mp4_box(
            payload, trak_start, trak_end, b"tkhd"
        )
        offset = 76 if payload[tkhd_start] == 0 else 88
        payload[tkhd_start + offset:tkhd_start + offset + 4] = (720 << 16).to_bytes(4, "big")
        payload[tkhd_start + offset + 4:tkhd_start + offset + 8] = (1280 << 16).to_bytes(4, "big")
        mdia_start, mdia_end = drama_video._first_mp4_box(payload, trak_start, trak_end, b"mdia")
        minf_start, minf_end = drama_video._first_mp4_box(payload, mdia_start, mdia_end, b"minf")
        stbl_start, stbl_end = drama_video._first_mp4_box(payload, minf_start, minf_end, b"stbl")
        stsd_start, stsd_end = drama_video._first_mp4_box(payload, stbl_start, stbl_end, b"stsd")
        entries = drama_video._mp4_boxes(payload, stsd_start + 8, stsd_end)
        if not entries or bytes(entries[0][0]) not in {b"avc1", b"hvc1", b"hev1"}:
            raise AssertionError("local fixture expects a visual sample entry")
        _kind, sample_start, sample_end = entries[0]
        if sample_end < sample_start + 28:
            raise AssertionError("local visual sample entry is truncated")
        payload[sample_start + 24:sample_start + 26] = (720).to_bytes(2, "big")
        payload[sample_start + 26:sample_start + 28] = (1280).to_bytes(2, "big")
        break
    result = bytes(payload)
    spec = drama_video._probe_mp4(result)
    if (spec.duration_seconds, spec.width, spec.height) != (5.0, 720, 1280):
        raise AssertionError("local MP4 fixture does not satisfy the production probe")
    if mp4_sample_dimensions(result) != (720, 1280):
        raise AssertionError("local MP4 track and sample-entry dimensions differ")
    return result


def mp4_sample_dimensions(data: bytes) -> tuple[int, int]:
    """Read the first visual sample-entry width/height from the local fixture."""

    from src import drama_video

    moov_start, moov_end = drama_video._first_mp4_box(data, 0, len(data), b"moov")
    for kind, trak_start, trak_end in drama_video._mp4_boxes(data, moov_start, moov_end):
        if kind != b"trak":
            continue
        mdia_start, mdia_end = drama_video._first_mp4_box(data, trak_start, trak_end, b"mdia")
        hdlr_start, hdlr_end = drama_video._first_mp4_box(data, mdia_start, mdia_end, b"hdlr")
        if data[hdlr_start:hdlr_end][8:12] != b"vide":
            continue
        minf_start, minf_end = drama_video._first_mp4_box(data, mdia_start, mdia_end, b"minf")
        stbl_start, stbl_end = drama_video._first_mp4_box(data, minf_start, minf_end, b"stbl")
        stsd_start, stsd_end = drama_video._first_mp4_box(data, stbl_start, stbl_end, b"stsd")
        entries = drama_video._mp4_boxes(data, stsd_start + 8, stsd_end)
        if entries:
            _entry, sample_start, sample_end = entries[0]
            if sample_end >= sample_start + 28:
                return (
                    int.from_bytes(data[sample_start + 24:sample_start + 26], "big"),
                    int.from_bytes(data[sample_start + 26:sample_start + 28], "big"),
                )
    raise ValueError("MP4 has no readable visual sample-entry dimensions")


class _ProviderState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.counts = {
            "image_generate": 0,
            "asset_upload": 0,
            "asset_poll": 0,
            "video_create": 0,
            "video_poll": 0,
            "video_download": 0,
            "callback_fetch": 0,
        }
        self.assets: dict[str, str] = {}
        self.callback_port: int | None = None

    def increment(self, key: str) -> int:
        with self.lock:
            self.counts[key] += 1
            return self.counts[key]

    def snapshot(self) -> dict[str, int]:
        with self.lock:
            return dict(self.counts)

    def allow_callback(self, port: int) -> None:
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("callback port is invalid")
        with self.lock:
            self.callback_port = port

    def callback_allowed(self, port: int | None, path: str) -> bool:
        with self.lock:
            return (
                port == self.callback_port
                and path.startswith("/media/drama-assets/")
                and len(path) <= 512
            )


class LocalDramaProvider(AbstractContextManager["LocalDramaProvider"]):
    """Threaded deterministic provider bound to 127.0.0.1 and an OS port."""

    IMAGE_TOKEN = "local-image-test-token"
    VIDEO_TOKEN = "local-video-test-token"

    def __init__(self) -> None:
        self.state = _ProviderState()
        state = self.state
        fixture_root = Path(__file__).resolve().parents[1] / "fixtures" / "provider_contracts"
        image_contract = json.loads(
            (fixture_root / "openai_image_request.json").read_text(encoding="utf-8")
        )["request"]
        video_contract = json.loads(
            (fixture_root / "compatible_video_request.json").read_text(encoding="utf-8")
        )["request"]

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_args: Any) -> None:
                return

            def _send(self, status: int, content_type: str, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, value: dict[str, Any]) -> None:
                self._send(
                    status,
                    "application/json",
                    json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                )

            def _read_json(self) -> dict[str, Any]:
                raw_length = self.headers.get("Content-Length", "")
                try:
                    length = int(raw_length)
                except ValueError as exc:
                    raise ValueError("invalid content length") from exc
                if length <= 0 or length > 32_768:
                    raise ValueError("request body exceeds local contract limit")
                try:
                    value = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("request body is not JSON") from exc
                if not isinstance(value, dict):
                    raise ValueError("request body must be a JSON object")
                return value

            def _authorized(self, token: str) -> bool:
                return self.headers.get("Authorization") == f"Bearer {token}"

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
                try:
                    body = self._read_json()
                    if self.path == "/v1/images/generations":
                        if not self._authorized(LocalDramaProvider.IMAGE_TOKEN):
                            self._json(401, {"error": "unauthorized"})
                            return
                        if (
                            set(body) != set(image_contract["required_fields"])
                            or not isinstance(body.get("model"), str)
                            or not isinstance(body.get("prompt"), str)
                            or not 0 < len(body["prompt"]) <= image_contract["maximum_prompt_characters"]
                            or any(
                                body.get(key) != value
                                for key, value in image_contract["fixed_values"].items()
                            )
                        ):
                            self._json(400, {"error": "openai image contract mismatch"})
                            return
                        state.increment("image_generate")
                        self._json(200, {
                            "model": body["model"],
                            "size": "1x1",
                            "data": [{"b64_json": base64.b64encode(PNG_1X1).decode("ascii")}],
                        })
                        return
                    if self.path == "/v1/sd/assets":
                        if not self._authorized(LocalDramaProvider.VIDEO_TOKEN):
                            self._json(401, {"error": "unauthorized"})
                            return
                        if set(body) != {"URL", "Name", "AssetType"} or body.get("AssetType") != "Image":
                            self._json(400, {"error": "asset contract mismatch"})
                            return
                        callback = urlparse(str(body.get("URL") or ""))
                        if (
                            callback.scheme != "https"
                            or callback.hostname != "127.0.0.1"
                            or not state.callback_allowed(callback.port or 443, callback.path)
                        ):
                            self._json(400, {"error": "callback must be loopback https contract"})
                            return
                        connection = http.client.HTTPConnection(
                            callback.hostname, callback.port or 443, timeout=5
                        )
                        try:
                            target = callback.path + (("?" + callback.query) if callback.query else "")
                            connection.request("GET", target)
                            response = connection.getresponse()
                            callback_bytes = response.read(2 * 1024 * 1024)
                        finally:
                            connection.close()
                        if response.status != 200 or response.getheader("content-type") != "image/png" or callback_bytes != PNG_1X1:
                            self._json(400, {"error": "callback asset mismatch"})
                            return
                        state.increment("callback_fetch")
                        number = state.increment("asset_upload")
                        asset_id = f"asset-{number}"
                        state.assets[asset_id] = "ready"
                        self._json(200, {"asset": {"id": asset_id}})
                        return
                    if self.path == "/v1/video/generate":
                        if not self._authorized(LocalDramaProvider.VIDEO_TOKEN):
                            self._json(401, {"error": "unauthorized"})
                            return
                        content = body.get("content")
                        expected_keys = set(video_contract["required_fields"])
                        image_rows = content[1:] if isinstance(content, list) else []
                        if (
                            set(body) != expected_keys
                            or not isinstance(content, list)
                            or not content
                            or not isinstance(content[0], dict)
                            or content[0].get("type") != "text"
                            or not isinstance(content[0].get("text"), str)
                            or not image_rows
                            or any(
                                not isinstance(row, dict)
                                or row.get("type") != "image_url"
                                or row.get("role") != "reference_image"
                                or not isinstance(row.get("image_url"), dict)
                                or not str((row.get("image_url") or {}).get("url") or "").startswith("asset://asset-")
                                for row in image_rows
                            )
                            or any(
                                body.get(key) != value
                                for key, value in video_contract["fixed_values"].items()
                            )
                        ):
                            self._json(400, {"error": "compatible video contract mismatch"})
                            return
                        state.increment("video_create")
                        self._json(200, {"task": {"id": "video-task-1", "status": "pending"}})
                        return
                    self._json(404, {"error": "not found"})
                except (OSError, ValueError):
                    self._json(400, {"error": "local provider rejected request"})

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
                if self.path.startswith("/v1/sd/assets/"):
                    if not self._authorized(LocalDramaProvider.VIDEO_TOKEN):
                        self._json(401, {"error": "unauthorized"})
                        return
                    asset_id = self.path.rsplit("/", 1)[-1]
                    state.increment("asset_poll")
                    if asset_id not in state.assets:
                        self._json(404, {"error": "asset not found"})
                        return
                    self._json(200, {"asset": {"id": asset_id, "status": "ready"}})
                    return
                if self.path.startswith("/v1/video/tasks/"):
                    if not self._authorized(LocalDramaProvider.VIDEO_TOKEN):
                        self._json(401, {"error": "unauthorized"})
                        return
                    poll = state.increment("video_poll")
                    if poll == 1:
                        self._json(200, {"task": {"id": "video-task-1", "status": "processing"}})
                    else:
                        result_url = (
                            f"https://127.0.0.1:{self.server.server_port}"
                            "/result/video.mp4?signature=local-only"
                        )
                        self._json(200, {"task": {
                            "id": "video-task-1",
                            "status": "completed",
                            "video_url": result_url,
                            "cost_cny": 0.25,
                        }})
                    return
                if self.path.startswith("/result/video.mp4?"):
                    state.increment("video_download")
                    self._send(200, "video/mp4", strict_mp4_fixture())
                    return
                self._json(404, {"error": "not found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def counters(self) -> dict[str, int]:
        return self.state.snapshot()

    def authorize_callback(self, port: int) -> None:
        self.state.allow_callback(port)

    def __enter__(self) -> "LocalDramaProvider":
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
