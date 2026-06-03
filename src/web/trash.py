"""iter 033: soft-delete a workspace by moving it to workspaces/_trash/.

Hard rm is intentionally out of scope. The user (or a future iter 034
cleanup CLI) is responsible for purging _trash/ on their own schedule.
"""

from __future__ import annotations

import time
from typing import Tuple

from .. import paths


TRASH_DIR_NAME = "_trash"


def soft_delete_workspace(name: str) -> Tuple[bool, str]:
    """Move workspaces/<name>/ to workspaces/_trash/<name>__<ts>/.

    Returns (ok, message). On success ``message`` is the new path
    relative to ``paths.WORKSPACE_DIR``. On failure ``ok=False`` and
    ``message`` is a human-readable reason.

    Idempotency note: a second delete returns ok=False with
    ``workspace_not_found`` because the source directory is already
    gone — caller should map this to HTTP 404.
    """

    src = paths.WORKSPACE_DIR / name
    if not src.is_dir():
        return False, "workspace_not_found"
    trash_root = paths.WORKSPACE_DIR / TRASH_DIR_NAME
    trash_root.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    target = trash_root / f"{name}__{ts}"
    # If a same-second delete collides, append a counter; keeps the
    # rename atomic and avoids overwriting an existing trash entry.
    counter = 1
    while target.exists():
        counter += 1
        target = trash_root / f"{name}__{ts}_{counter}"
    src.rename(target)
    return True, str(target.relative_to(paths.WORKSPACE_DIR))
