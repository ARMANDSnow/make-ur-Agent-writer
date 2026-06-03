"""iter 038: socket-bind skip helper sanity."""

from __future__ import annotations

import unittest

from tests._socket_skip import SOCKET_BIND_BLOCKED, SOCKET_WILDCARD_BIND_BLOCKED


class SocketSkipTests(unittest.TestCase):
    def test_socket_bind_blocked_is_bool(self) -> None:
        self.assertIsInstance(SOCKET_BIND_BLOCKED, bool)
        self.assertIsInstance(SOCKET_WILDCARD_BIND_BLOCKED, bool)


if __name__ == "__main__":
    unittest.main()
