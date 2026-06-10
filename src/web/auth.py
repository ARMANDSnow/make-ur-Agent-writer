"""Optional bearer-token gate for the WebUI API (iter 049).

Opt-in and OFF by default: when ``NOVEL_API_TOKEN`` is unset/empty the gate is
a no-op, so local single-user runs and the existing test-suite are unaffected.
When it IS set, every ``/api/*`` request must carry
``Authorization: Bearer <token>``. Non-API paths (the landing page,
``/w/<book>/...`` deep links, static assets) stay open so a browser can follow
a chat deep-link without a header — matching how the Aeloon plugin / MCP server
hand links to the user.

**Caveat (by design):** the dashboard's *own* browser JS calls ``/api/*``
without a bearer header, so setting ``NOVEL_API_TOKEN`` will 401 the WebUI
itself. The token is meant for *programmatic* clients (the Aeloon plugin / MCP
server) — for local single-user use leave it unset; only set it when exposing
the API to external clients and you don't need the in-browser dashboard.

Kept dependency-free (no import of routes/server) so it is unit-testable in
isolation; ``routes.dispatch`` builds the 401 response itself.
"""

from __future__ import annotations

import hmac
import os
from typing import Dict, Optional

TOKEN_ENV = "NOVEL_API_TOKEN"
_BEARER = "bearer "


def required_token() -> Optional[str]:
    """The configured API token, or ``None`` when the gate is disabled."""
    token = os.environ.get(TOKEN_ENV, "").strip()
    return token or None


def is_authorized(decoded_path: str, headers: Dict[str, str], token: str) -> bool:
    """True if the request may proceed. Only ``/api/*`` is gated; ``token`` is
    the already-resolved, non-empty configured token."""
    if not decoded_path.startswith("/api/"):
        return True
    header = (headers or {}).get("authorization", "") or ""
    if header[: len(_BEARER)].lower() != _BEARER:
        return False
    presented = header[len(_BEARER):].strip()
    # constant-time compare to avoid leaking the token via response timing.
    return hmac.compare_digest(presented, token)
