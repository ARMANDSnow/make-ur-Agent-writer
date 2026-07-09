"""Minimal AI drawing client for drama character references.

The default path is intentionally local-only: when ``AI_DRAW_ENDPOINT`` is not
configured we write a deterministic SVG placeholder that gives the WebUI a real
preview artifact without network access or image dependencies.
"""

from __future__ import annotations

import html
import ipaddress
import json
import os
import socket
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .drama_schemas import DramaCharacter, ReferenceImage, character_paths


MAX_RESPONSE_BYTES = 5 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
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
    if mock is True or not endpoint:
        return _write_placeholder_svg(workspace, char, season_no=season_no)
    return _call_draw_endpoint(workspace, char, endpoint, season_no=season_no)


def _write_placeholder_svg(workspace: str, character: DramaCharacter, *, season_no: int) -> Dict[str, Any]:
    cp = character_paths(workspace, season_no=season_no)
    out_dir = cp.refs_dir / character.id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "portrait_neutral.svg"
    prompt = character.prompt_template_sd or character.visual_signature or character.name
    out_path.write_text(_placeholder_svg(character, prompt), encoding="utf-8")
    rel = _workspace_relative(cp.root, out_path)
    image = ReferenceImage(
        path=rel,
        generated_by="placeholder_svg",
        prompt=prompt[:1000],
        seed=0,
    )
    return image.model_dump()


def _call_draw_endpoint(
    workspace: str,
    character: DramaCharacter,
    endpoint: str,
    *,
    season_no: int,
) -> Dict[str, Any]:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("AI_DRAW_ENDPOINT must be an http(s) URL")
    _validate_public_endpoint(parsed.hostname)

    payload = {
        "character_id": character.id,
        "name": character.name,
        "prompt": character.prompt_template_sd,
        "lora_token": character.lora_token,
    }
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("AI_DRAW_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers)
    opener = build_opener(_NoRedirect)
    with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("AI draw response exceeds size limit")

    suffix = _suffix_for_content_type(content_type)
    cp = character_paths(workspace, season_no=season_no)
    out_dir = cp.refs_dir / character.id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"portrait_neutral{suffix}"
    out_path.write_bytes(data)
    image = ReferenceImage(
        path=_workspace_relative(cp.root, out_path),
        generated_by=content_type or "ai_draw_endpoint",
        prompt=character.prompt_template_sd[:1000],
        seed=None,
    )
    return image.model_dump()


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
