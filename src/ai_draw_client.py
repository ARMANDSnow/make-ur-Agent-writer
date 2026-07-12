"""AI drawing client for drama character references.

The default remains local-only. A real OpenAI-compatible call requires an
explicit ``AI_DRAW_MODEL`` (or ``mock=False`` in the gated smoke), while the
legacy direct-image endpoint remains an explicit opt-in of its own.
"""

from __future__ import annotations

import base64
import binascii
import html
import ipaddress
import json
import os
import socket
import tempfile
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .drama_schemas import DramaCharacter, ReferenceImage, character_paths


MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_JSON_RESPONSE_BYTES = 7 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
# iter091: the successful image2 probe and the later 120s timeout indicate
# provider latency can exceed two minutes. Keep one bounded attempt, but allow
# the requested 3-5 minute window; callers still never auto-retry paid POSTs.
IMAGE_GENERATION_TIMEOUT_SECONDS = 300
USER_AGENT = "DragonRajaAIContinuer/iter089"
DEFAULT_IMAGE_MODEL = "gpt-image-2"
DEFAULT_IMAGE_SIZE = "1024x1024"
SUPPORTED_ENDPOINT_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def redraw_character_reference(
    workspace: str,
    character: Dict[str, Any] | DramaCharacter,
    *,
    season_no: int = 1,
    mock: bool | None = None,
) -> Dict[str, Any]:
    char = character if isinstance(character, DramaCharacter) else DramaCharacter(**character)
    endpoint = os.getenv("AI_DRAW_ENDPOINT", "").strip()
    if mock is True:
        return _write_placeholder_svg(workspace, char, season_no=season_no)
    if endpoint:
        return _call_draw_endpoint(workspace, char, endpoint, season_no=season_no)

    configured_model = os.getenv("AI_DRAW_MODEL")
    if mock is None and not str(configured_model or "").strip():
        return _write_placeholder_svg(workspace, char, season_no=season_no)
    base_url, api_key = _resolve_openai_draw_credentials()
    if not base_url or not api_key:
        if mock is False:
            raise ValueError("AI draw requires a base URL and API key")
        raise ValueError("AI draw is enabled but its base URL or API key is missing")
    model = (configured_model or DEFAULT_IMAGE_MODEL).strip()
    if not model or len(model) > 80 or any(char in model for char in "\r\n\x00"):
        raise ValueError("AI_DRAW_MODEL must be 1-80 characters without controls")
    if any(char in api_key for char in "\r\n\x00"):
        raise ValueError("AI draw API key contains control characters")
    return _call_openai_image_api(
        workspace,
        char,
        base_url=base_url,
        api_key=api_key,
        model=model,
        season_no=season_no,
    )


def _write_placeholder_svg(workspace: str, character: DramaCharacter, *, season_no: int) -> Dict[str, Any]:
    cp = character_paths(workspace, season_no=season_no)
    out_dir = cp.refs_dir / character.id
    out_path = out_dir / "portrait_neutral.svg"
    prompt = character.prompt_template_sd or character.visual_signature or character.name
    rel = _workspace_relative(cp.root, out_path)
    image = ReferenceImage(
        path=rel,
        generated_by="placeholder_svg",
        prompt=prompt[:1000],
        seed=0,
    )
    _atomic_write_bytes(out_path, _placeholder_svg(character, prompt).encode("utf-8"))
    return image.model_dump()


def _resolve_openai_draw_credentials() -> tuple[str, str]:
    dedicated_base = str(os.getenv("AI_DRAW_BASE_URL") or "").strip()
    dedicated_key = str(os.getenv("AI_DRAW_API_KEY") or "").strip()
    if bool(dedicated_base) != bool(dedicated_key):
        raise ValueError("AI_DRAW_BASE_URL and AI_DRAW_API_KEY must be configured together")
    if dedicated_base and dedicated_key:
        return dedicated_base, dedicated_key
    return (
        str(os.getenv("OPENAI_BASE_URL") or "").strip(),
        str(os.getenv("OPENAI_API_KEY") or "").strip(),
    )


def _call_draw_endpoint(
    workspace: str,
    character: DramaCharacter,
    endpoint: str,
    *,
    season_no: int,
) -> Dict[str, Any]:
    api_key = os.getenv("AI_DRAW_API_KEY", "").strip()
    parsed = validate_api_base_url(
        endpoint,
        label="AI_DRAW_ENDPOINT",
        allow_http=not bool(api_key),
    )
    _validate_public_endpoint(parsed.hostname)
    payload = {
        "character_id": character.id,
        "name": character.name,
        "prompt": character.prompt_template_sd,
        "lora_token": character.lora_token,
    }
    headers = {"Content-Type": "application/json"}
    if any(char in api_key for char in "\r\n\x00"):
        raise ValueError("AI_DRAW_API_KEY contains control characters")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers)
    opener = build_opener(_NoRedirect)
    with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("AI draw response exceeds size limit")

    _suffix_for_content_type(content_type)
    detected_type, suffix = _detect_image_type(data)
    if content_type != detected_type:
        raise ValueError("AI draw response content-type does not match image bytes")
    return _persist_image(
        workspace,
        character,
        data,
        content_type=detected_type,
        suffix=suffix,
        generated_by="ai_draw_endpoint",
        prompt=character.prompt_template_sd,
        season_no=season_no,
    )


def _call_openai_image_api(
    workspace: str,
    character: DramaCharacter,
    *,
    base_url: str,
    api_key: str,
    model: str,
    season_no: int,
) -> Dict[str, Any]:
    endpoint = _images_generation_url(base_url)
    parsed = validate_api_base_url(endpoint, label="AI draw base URL")
    _validate_public_endpoint(parsed.hostname)

    prompt = character.prompt_template_sd or character.visual_signature or character.name
    payload = {
        "model": model,
        "prompt": prompt,
        "size": DEFAULT_IMAGE_SIZE,
        "n": 1,
        "response_format": "b64_json",
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": USER_AGENT,
        },
    )
    opener = build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=IMAGE_GENERATION_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            raw = response.read(MAX_JSON_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise ValueError(f"AI draw API request failed with HTTP {exc.code}") from None
    except URLError:
        raise ValueError("AI draw API request failed due to a network error") from None
    if len(raw) > MAX_JSON_RESPONSE_BYTES:
        raise ValueError("AI draw JSON response exceeds size limit")
    if content_type not in {"", "application/json"}:
        raise ValueError("AI draw API response content-type must be application/json")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("AI draw API returned invalid JSON") from exc
    data = body.get("data") if isinstance(body, dict) else None
    item = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
    if item is None:
        raise ValueError("AI draw API response is missing image data")
    if isinstance(item.get("b64_json"), str):
        image_bytes = _decode_base64_image(item["b64_json"])
        content_type, suffix = _detect_image_type(image_bytes)
    elif isinstance(item.get("url"), str):
        image_bytes, content_type, suffix = _download_generated_image(
            item["url"], api_hostname=parsed.hostname or ""
        )
    else:
        raise ValueError("AI draw API response is missing b64_json or url")
    provider_model = body.get("model") if isinstance(body, dict) else None
    if not isinstance(provider_model, str) or not provider_model.strip() or len(provider_model.strip()) > 80:
        provider_model = model
    provider_size = body.get("size") if isinstance(body, dict) else None
    if not isinstance(provider_size, str) or len(provider_size) > 40:
        provider_size = ""
    width, height = _image_dimensions(image_bytes, content_type)
    return _persist_image(
        workspace,
        character,
        image_bytes,
        content_type=content_type,
        suffix=suffix,
        generated_by=str(provider_model).strip(),
        prompt=prompt,
        season_no=season_no,
        requested_model=model,
        requested_size=DEFAULT_IMAGE_SIZE,
        provider_size=provider_size,
        width=width,
        height=height,
    )


def _images_generation_url(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        raise ValueError("AI draw base URL is required")
    if base.endswith("/images/generations"):
        return base
    if base.endswith("/v1"):
        return base + "/images/generations"
    return base + "/v1/images/generations"


def _decode_base64_image(value: str) -> bytes:
    if len(value) > ((MAX_RESPONSE_BYTES + 2) // 3) * 4 + 8:
        raise ValueError("AI draw image exceeds size limit")
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("AI draw API returned invalid base64 image data") from exc
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("AI draw image exceeds size limit")
    return data


def _download_generated_image(url: str, *, api_hostname: str = "") -> tuple[bytes, str, str]:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise ValueError("AI draw image URL must be an https URL")
    allowed_hosts = {api_hostname.rstrip(".").lower()} if api_hostname else set()
    allowed_hosts.update(
        item.strip().rstrip(".").lower()
        for item in str(os.getenv("AI_DRAW_RESULT_HOSTS") or "").split(",")
        if item.strip()
    )
    result_host = str(parsed.hostname or "").rstrip(".").lower()
    if result_host not in allowed_hosts:
        raise ValueError("AI draw image URL host is not in the trusted result-host allowlist")
    _validate_public_endpoint(parsed.hostname)
    opener = build_opener(_NoRedirect)
    try:
        with opener.open(Request(url, headers={"User-Agent": USER_AGENT}), timeout=REQUEST_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            data = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise ValueError(f"AI draw image download failed with HTTP {exc.code}") from None
    except URLError:
        raise ValueError("AI draw image download failed due to a network error") from None
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("AI draw image exceeds size limit")
    detected_type, suffix = _detect_image_type(data)
    if content_type and content_type != detected_type:
        raise ValueError("AI draw image content-type does not match image bytes")
    return data, detected_type, suffix


def _detect_image_type(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    raise ValueError("AI draw response bytes must be png, jpeg, or webp")


def _persist_image(
    workspace: str,
    character: DramaCharacter,
    data: bytes,
    *,
    content_type: str,
    suffix: str,
    generated_by: str,
    prompt: str,
    season_no: int,
    requested_model: str = "",
    requested_size: str = "",
    provider_size: str = "",
    width: int | None = None,
    height: int | None = None,
) -> Dict[str, Any]:
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("AI draw image exceeds size limit")
    cp = character_paths(workspace, season_no=season_no)
    out_dir = cp.refs_dir / character.id
    out_path = out_dir / f"portrait_neutral{suffix}"
    image = ReferenceImage(
        path=_workspace_relative(cp.root, out_path),
        generated_by=generated_by or content_type,
        prompt=prompt[:1000],
        seed=None,
        requested_model=requested_model,
        requested_size=requested_size,
        provider_size=provider_size,
        width=width,
        height=height,
    )
    _atomic_write_bytes(out_path, data)
    return image.model_dump()


def _image_dimensions(data: bytes, content_type: str) -> tuple[int | None, int | None]:
    if content_type == "image/png" and len(data) >= 24 and data[12:16] == b"IHDR":
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        if width > 0 and height > 0:
            return width, height
    return None, None


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def validate_api_base_url(value: str, *, label: str, allow_http: bool = False):
    parsed = urlparse(value)
    allowed_schemes = {"https", "http"} if allow_http else {"https"}
    if (
        parsed.scheme not in allowed_schemes
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        scheme_text = "http(s)" if allow_http else "https"
        raise ValueError(f"{label} must be an {scheme_text} URL without credentials, query, or fragment")
    return parsed


def _suffix_for_content_type(content_type: str) -> str:
    suffix = SUPPORTED_ENDPOINT_IMAGE_TYPES.get(content_type)
    if suffix is None:
        raise ValueError("AI draw response content-type must be png, jpeg, or webp")
    return suffix


def _validate_public_endpoint(host: str | None) -> None:
    if not host:
        raise ValueError("AI_DRAW_ENDPOINT host is required")
    normalized = host.rstrip(".").lower()
    if normalized in {"localhost"} or normalized.endswith(".localhost"):
        raise ValueError("AI_DRAW_ENDPOINT host must resolve to a public address")
    for ip in _resolve_host_ips(normalized):
        if _unsafe_endpoint_ip(ip):
            raise ValueError("AI_DRAW_ENDPOINT host must resolve to a public address")


def _resolve_host_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        results = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("AI_DRAW_ENDPOINT host could not be resolved") from exc
    ips = []
    for result in results:
        address = result[4][0]
        try:
            ips.append(ipaddress.ip_address(address))
        except ValueError:
            continue
    if not ips:
        raise ValueError("AI_DRAW_ENDPOINT host could not be resolved")
    return ips


def _unsafe_endpoint_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        not ip.is_global
        or ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _workspace_relative(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _placeholder_svg(character: DramaCharacter, prompt: str) -> str:
    title = html.escape(character.name)
    role = html.escape(character.role or character.id)
    sig = html.escape(character.visual_signature or character.lora_token)
    prompt_line = html.escape(prompt[:120])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="36" fill="#f7f2e8"/>
  <rect x="40" y="40" width="432" height="432" rx="28" fill="#fffaf0" stroke="#9b6b43" stroke-width="3"/>
  <circle cx="256" cy="185" r="70" fill="#d6b28a"/>
  <path d="M142 382c24-76 68-114 114-114s90 38 114 114" fill="#8aa39b"/>
  <text x="256" y="94" text-anchor="middle" font-size="28" font-family="Arial, sans-serif" fill="#3d3328">{title}</text>
  <text x="256" y="420" text-anchor="middle" font-size="20" font-family="Arial, sans-serif" fill="#5f5243">{role}</text>
  <text x="256" y="448" text-anchor="middle" font-size="16" font-family="Arial, sans-serif" fill="#7a6b5a">{sig}</text>
  <text x="256" y="474" text-anchor="middle" font-size="13" font-family="Arial, sans-serif" fill="#8b7d6f">{prompt_line}</text>
</svg>
"""
