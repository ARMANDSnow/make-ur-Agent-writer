"""Detect whether tests can bind a local listening socket.

Some sandboxes reject ``socket.bind(("127.0.0.1", 0))`` with
``PermissionError``. Server integration tests should skip in that
environment, while still running normally on a local machine.
"""

from __future__ import annotations

import socket


def _probe(host: str) -> bool:
    """Return True if binding ``host`` is blocked by the environment."""

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
        return False
    except PermissionError:
        return True
    except OSError:
        return False


SOCKET_BIND_BLOCKED = _probe("127.0.0.1")
SOCKET_WILDCARD_BIND_BLOCKED = _probe("0.0.0.0")
