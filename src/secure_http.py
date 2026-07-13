"""Peer-verified bounded transport for credentialed provider requests."""

from __future__ import annotations

import http.client
from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.parse import urlparse


@dataclass(frozen=True)
class BoundedResponse:
    status: int
    content_type: str
    body: bytes


class RequestNotSentError(ConnectionError):
    """Connect/peer validation failed before HTTP headers or body were sent."""


def request_bytes(
    url: str,
    *,
    method: str,
    body: bytes | None,
    headers: Mapping[str, str],
    timeout_seconds: float,
    max_response_bytes: int,
    peer_validator: Callable[[str], None],
) -> BoundedResponse:
    """Connect/TLS, validate the actual peer, then send sensitive bytes."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("provider URL must be http(s)")
    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection = connection_cls(
        parsed.hostname,
        port=parsed.port or (443 if parsed.scheme == "https" else 80),
        timeout=timeout_seconds,
    )
    try:
        try:
            connection.connect()
            peer_ip = connection.sock.getpeername()[0] if connection.sock is not None else ""
            peer_validator(peer_ip)
        except Exception as exc:
            raise RequestNotSentError("provider request was rejected before send") from exc
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        connection.request(method, target, body=body, headers=dict(headers))
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise ValueError("provider redirects are not allowed")
        declared = response.getheader("content-length")
        if declared:
            try:
                length = int(declared)
            except ValueError as exc:
                raise ValueError("provider content-length is invalid") from exc
            if length < 0 or length > max_response_bytes:
                raise ValueError("provider response exceeds size limit")
        data = response.read(max_response_bytes + 1)
        if len(data) > max_response_bytes:
            raise ValueError("provider response exceeds size limit")
        content_type = (response.getheader("content-type") or "").split(";", 1)[0].strip().lower()
        return BoundedResponse(response.status, content_type, data)
    finally:
        connection.close()
