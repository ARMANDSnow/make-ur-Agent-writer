"""iter 025/026: ``use_workspace`` context manager.

iter 026 code-review #1 changed the mechanism from "swap env var under
process-wide RLock" to "set per-thread override in paths._THREAD_OVERRIDE".
These tests assert behavior in terms of ``paths.workspace_name()`` (the
public observable), not the env var, because the env var is no longer
the mechanism — it's only one of several fallbacks.
"""

from __future__ import annotations

import os
import threading
import time
import unittest

from src import paths
from src.web.workspace_ctx import use_workspace


class UseWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        self._saved_book = os.environ.get("BOOK")
        os.environ.pop("WORKSPACE_NAME", None)
        os.environ.pop("BOOK", None)
        paths._set_thread_override(None)

    def tearDown(self) -> None:
        paths._set_thread_override(None)
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        if self._saved_book is None:
            os.environ.pop("BOOK", None)
        else:
            os.environ["BOOK"] = self._saved_book

    def test_sets_and_restores(self) -> None:
        self.assertIsNone(paths.workspace_name())
        with use_workspace("longzu"):
            self.assertEqual(paths.workspace_name(), "longzu")
        self.assertIsNone(paths.workspace_name())

    def test_restores_on_exception(self) -> None:
        with use_workspace("outer"):
            try:
                with use_workspace("inner"):
                    self.assertEqual(paths.workspace_name(), "inner")
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            self.assertEqual(paths.workspace_name(), "outer")
        self.assertIsNone(paths.workspace_name())

    def test_none_forces_legacy_even_when_env_set(self) -> None:
        """Iter 026: empty-string override must override env, not fall
        through to it. Otherwise an operator's BOOK shell default leaks
        into requests that explicitly asked for legacy mode."""
        os.environ["BOOK"] = "shell_default"
        with use_workspace(None):
            self.assertIsNone(paths.workspace_name())
        # Outside the with, env-fallback resumes.
        self.assertEqual(paths.workspace_name(), "shell_default")

    def test_nested_use_does_not_deadlock(self) -> None:
        """Iter 026 #1: with per-thread overrides nesting is trivially
        re-entrant — no lock to contend on."""
        with use_workspace("outer"):
            with use_workspace("inner"):
                self.assertEqual(paths.workspace_name(), "inner")
            self.assertEqual(paths.workspace_name(), "outer")
        self.assertIsNone(paths.workspace_name())

    def test_thread_isolation(self) -> None:
        """Iter 026 #1 core invariant: thread A's use_workspace must NOT
        affect what thread B sees. Before the fix, both threads shared
        os.environ['WORKSPACE_NAME'] under a global lock — B would
        block waiting for A; with the fix B is fully independent."""

        observed: dict[str, str | None] = {}

        def worker_b(barrier: threading.Barrier) -> None:
            with use_workspace("beta"):
                barrier.wait()  # rendezvous with A inside its with
                observed["b_inside"] = paths.workspace_name()
                barrier.wait()  # let A check its own state
            observed["b_after"] = paths.workspace_name()

        barrier = threading.Barrier(2)
        t = threading.Thread(target=worker_b, args=(barrier,))
        with use_workspace("alpha"):
            t.start()
            barrier.wait()  # A waits while B sets its override
            observed["a_inside"] = paths.workspace_name()
            barrier.wait()  # release B from its inner with
            t.join(timeout=2.0)
        observed["a_after"] = paths.workspace_name()

        self.assertEqual(observed["a_inside"], "alpha")
        self.assertEqual(observed["b_inside"], "beta")
        self.assertIsNone(observed["b_after"])
        self.assertIsNone(observed["a_after"])

    def test_does_not_block_other_threads(self) -> None:
        """Iter 026 #1: a long-held use_workspace in one thread must
        not block another thread's use_workspace. Before the fix the
        global RLock would serialize them."""

        gate = threading.Event()
        elapsed_outer = {"v": -1.0}

        def long_holder() -> None:
            with use_workspace("long"):
                gate.set()
                time.sleep(0.5)

        t = threading.Thread(target=long_holder)
        t.start()
        gate.wait(timeout=1.0)
        # ``long_holder`` is now inside its with block, will sleep 0.5s.
        # A concurrent use_workspace must return immediately.
        t0 = time.time()
        with use_workspace("short"):
            elapsed_outer["v"] = time.time() - t0
            self.assertEqual(paths.workspace_name(), "short")
        t.join(timeout=2.0)
        # 50 ms is generous; before the fix this would be ~500 ms.
        self.assertLess(elapsed_outer["v"], 0.05, f"took {elapsed_outer['v']:.3f}s")


if __name__ == "__main__":
    unittest.main()
