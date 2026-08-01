"""Guarded client for the short-drama asset and video task API.

Read/query operations are available once configured. Creating a real video
task has an additional per-call gate so ordinary Web or test paths cannot
spend video credits by merely inheriting a configured environment.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Sequence
from urllib.parse import quote, urlparse

from .ai_draw_client import _validate_public_endpoint, validate_api_base_url
from .config import load_dotenv_if_available
from .secure_http import request_bytes


DEFAULT_SD_BASE_URL = "https://model.service-inference.ai"
DEFAULT_VIDEO_MODEL = "dreamina-seedance-2-0-hc"
MAX_JSON_RESPONSE_BYTES = 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_RATIO_RE = re.compile(r"^\d{1,2}:\d{1,2}$")
_RESOLUTION_RE = re.compile(r"^\d{3,4}p$")


class VideoGenerationNotAuthorized(PermissionError):
    """Raised before network when a real video submission is not authorized."""


class VideoCreateRejected(RuntimeError):
    """The provider returned a bounded, explicit rejection to video create.

    Only redacted scalar classification is retained.  The provider response
    body is intentionally never attached to the exception or persisted by the
    caller.
    """

    def __init__(
        self,
        *,
        http_status: int,
        provider_outcome: str | None = None,
        provider_error_class: str | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__("video provider explicitly rejected the create request")
        self.http_status = http_status
        self.provider_outcome = provider_outcome
        self.provider_error_class = provider_error_class
        self.provider_request_id = provider_request_id


class _DuplicateJSONField(ValueError):
    """Internal sentinel; its message never includes the conflicting field."""


def _strict_json_object(pairs: list[tuple[str, Any]]) -> Dict[str, Any]:
    value: Dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJSONField("video API returned duplicate JSON field")
        value[key] = item
    return value


class DramaVideoClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        request_timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        load_dotenv_if_available()
        self.base_url = (base_url or os.getenv("SD_API_BASE_URL") or DEFAULT_SD_BASE_URL).strip().rstrip("/")
        self.api_key = (api_key or os.getenv("SD_API_KEY") or "").strip()
        if (
            isinstance(request_timeout_seconds, bool)
            or not isinstance(request_timeout_seconds, (int, float))
            or not 1 <= float(request_timeout_seconds) <= 300
        ):
            raise ValueError("video API request timeout must be between 1 and 300 seconds")
        self.request_timeout_seconds = float(request_timeout_seconds)
        validate_api_base_url(self.base_url, label="SD_API_BASE_URL")

    def upload_asset(self, *, url: str, name: str, asset_type: str) -> Dict[str, Any]:
        _validate_public_url(url, field="asset URL")
        clean_name = _bounded_text(name, field="asset name", maximum=120)
        if asset_type not in {"Image", "Video", "Audio"}:
            raise ValueError("asset_type must be Image, Video, or Audio")
        return self._request_json(
            "POST",
            "/v1/sd/assets",
            {"URL": url, "Name": clean_name, "AssetType": asset_type},
        )

    def get_asset(self, asset_id: str) -> Dict[str, Any]:
        return self._request_json("GET", f"/v1/sd/assets/{quote(_resource_id(asset_id), safe='')}")

    def list_tasks(self) -> Dict[str, Any]:
        return self._request_json("GET", "/v1/video/tasks")

    def get_task(self, task_id: str) -> Dict[str, Any]:
        return self._request_json("GET", f"/v1/video/tasks/{quote(_resource_id(task_id), safe='')}")

    def create_video_task(
        self,
        *,
        prompt: str,
        reference_asset_id: str | None = None,
        reference_asset_ids: Sequence[str] | None = None,
        duration: int = 5,
        resolution: str = "480p",
        ratio: str = "1:1",
        generate_audio: bool = False,
        watermark: bool = False,
        model: str | None = None,
        allow_real_video: bool = False,
    ) -> Dict[str, Any]:
        if not allow_real_video:
            raise VideoGenerationNotAuthorized(
                "real video generation requires explicit allow_real_video=True authorization"
            )
        payload = build_video_payload(
            prompt=prompt,
            reference_asset_id=reference_asset_id,
            reference_asset_ids=reference_asset_ids,
            duration=duration,
            resolution=resolution,
            ratio=ratio,
            generate_audio=generate_audio,
            watermark=watermark,
            model=model,
        )
        return self._request_json(
            "POST",
            "/v1/video/generate",
            payload,
            classify_create_rejection=True,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Dict[str, Any] | None = None,
        *,
        classify_create_rejection: bool = False,
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("SD_API_KEY is required")
        if any(char in self.api_key for char in "\r\n\x00"):
            raise ValueError("SD_API_KEY contains control characters")
        _validate_public_endpoint(urlparse(self.base_url).hostname)
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        response = request_bytes(
            self.base_url + path,
            method=method,
            body=body,
            headers=headers,
            timeout_seconds=self.request_timeout_seconds,
            max_response_bytes=MAX_JSON_RESPONSE_BYTES,
            peer_validator=_validate_public_endpoint,
        )
        if (
            response.status != 200
            and classify_create_rejection
            and 400 <= response.status < 500
        ):
            details = _redacted_create_rejection_details(
                response.body,
                content_type=response.content_type,
            )
            raise VideoCreateRejected(http_status=response.status, **details)
        if response.status != 200:
            raise ValueError(f"video API request failed with HTTP {response.status}")
        content_type = response.content_type
        raw = response.body
        if content_type != "application/json":
            raise ValueError("video API response content-type must be application/json")
        try:
            value = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_strict_json_object,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJSONField) as exc:
            raise ValueError("video API returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("video API response must be a JSON object")
        return value


def _redacted_create_rejection_details(
    body: bytes,
    *,
    content_type: str,
) -> Dict[str, str | None]:
    """Extract only bounded identifiers/classes; never retain response text."""

    empty: Dict[str, str | None] = {
        "provider_outcome": None,
        "provider_error_class": None,
        "provider_request_id": None,
    }
    if content_type != "application/json":
        return empty
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_strict_json_object,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        _DuplicateJSONField,
        RecursionError,
    ):
        return empty
    if type(value) is not dict:
        return empty
    error = value.get("error")
    error_object = error if type(error) is dict else {}
    return {
        "provider_outcome": _safe_provider_token(
            value.get("outcome") or value.get("status")
        ),
        "provider_error_class": _safe_provider_token(
            error_object.get("code")
            or error_object.get("type")
            or value.get("error_code")
        ),
        "provider_request_id": _safe_provider_identifier(
            value.get("request_id")
            or value.get("requestId")
            or error_object.get("request_id")
            or error_object.get("requestId")
        ),
    }


def _safe_provider_token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", token):
        return None
    return token


def _safe_provider_identifier(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", token):
        return None
    return token


def build_video_payload(
    *,
    prompt: str,
    reference_asset_id: str | None = None,
    reference_asset_ids: Sequence[str] | None = None,
    duration: int = 5,
    resolution: str = "480p",
    ratio: str = "1:1",
    generate_audio: bool = False,
    watermark: bool = False,
    model: str | None = None,
) -> Dict[str, Any]:
    text = _bounded_text(prompt, field="video prompt", maximum=4000)
    if isinstance(duration, bool) or not isinstance(duration, int) or not 1 <= duration <= 30:
        raise ValueError("duration must be an integer between 1 and 30")
    if not isinstance(resolution, str) or not _RESOLUTION_RE.fullmatch(resolution):
        raise ValueError("resolution must look like 480p or 1080p")
    if not isinstance(ratio, str) or not _RATIO_RE.fullmatch(ratio):
        raise ValueError("ratio must look like 1:1 or 16:9")
    if not isinstance(generate_audio, bool) or not isinstance(watermark, bool):
        raise ValueError("generate_audio and watermark must be bool")
    content: List[Dict[str, Any]] = [{"type": "text", "text": text}]
    if reference_asset_id is not None and reference_asset_ids is not None:
        raise ValueError("use reference_asset_id or reference_asset_ids, not both")
    raw_asset_ids: Sequence[str] = (
        reference_asset_ids if reference_asset_ids is not None else ([reference_asset_id] if reference_asset_id else [])
    )
    if isinstance(raw_asset_ids, (str, bytes)) or len(raw_asset_ids) > 8:
        raise ValueError("reference_asset_ids must contain at most 8 resource ids")
    seen: set[str] = set()
    for raw_asset_id in raw_asset_ids:
        asset_id = _resource_id(raw_asset_id)
        if asset_id in seen:
            continue
        seen.add(asset_id)
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"asset://{asset_id}"},
                "role": "reference_image",
            }
        )
    return {
        "model": _bounded_text(model or DEFAULT_VIDEO_MODEL, field="video model", maximum=120),
        "content": content,
        "duration": duration,
        "resolution": resolution,
        "ratio": ratio,
        "generate_audio": generate_audio,
        "watermark": watermark,
    }


def _resource_id(value: str) -> str:
    if not isinstance(value, str) or not _RESOURCE_ID_RE.fullmatch(value):
        raise ValueError("resource id contains unsupported characters")
    return value


def _bounded_text(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = value.strip()
    if not text or len(text) > maximum or any(char in text for char in "\r\n\x00"):
        raise ValueError(f"{field} must be 1-{maximum} single-line characters")
    return text


def _validate_public_url(value: str, *, field: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{field} must be a public https URL")
    _validate_public_endpoint(parsed.hostname)
