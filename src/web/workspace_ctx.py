"""iter 025/026: per-request workspace context for the WebUI.

iter 017's design has ``WORKSPACE_NAME`` as the single source of truth
for the active workspace. That worked for the CLI (one workspace per
process) but the WebUI serves many workspaces from one process and
iter 026 added a worker thread that holds the workspace context for the
duration of a multi-minute auto-pipeline job. If we kept iter 025's
"swap env var under a process-wide lock" semantics, every other request
thread would block on that lock for the whole job → dashboard frozen.

iter 026 code-review #1 switched the mechanism to a thread-local
override stored in ``src.paths._THREAD_OVERRIDE``. Each thread carries
its own workspace name; ``paths.workspace_name()`` consults the
thread-local first, then falls back to env vars so CLI behavior is
byte-identical. No cross-thread lock is needed — threads don't see each
other's overrides — so dashboard reads can run concurrently with a
running worker.

``use_workspace`` remains a context manager that saves / restores so a
handler can't accidentally leak its workspace into the next handler
served by the same thread (ThreadingHTTPServer reuses thread pools
implicitly when ``threading.Thread.run`` exits, but the override would
already be cleared by the ``finally``).

Thread-safety contract: ``use_workspace(name)`` mutates ``paths`` state
for the current thread only. Nested calls in the same thread stack and
restore correctly. Do not share an open context across threads; each
thread that needs a workspace must call ``use_workspace`` itself.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from .. import paths


@contextmanager
def use_workspace(name: str | None) -> Iterator[None]:
    """Temporarily set this thread's workspace override for the duration
    of the ``with`` block, restoring the previous value on exit (incl.
    on exception).

    Passing ``None`` or empty string puts ``paths.workspace_name()`` into
    legacy (repo-root) mode for THIS THREAD only — env-var defaults like
    ``BOOK=longzu`` set by the operator's shell do NOT leak through,
    because the empty-string override is explicit.
    """

    previous = paths._get_thread_override()
    paths._set_thread_override("" if name is None else name)
    try:
        yield
    finally:
        paths._set_thread_override(previous)
