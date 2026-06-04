"""iter 027 P2 (code-review #7 fix): single source of truth for the
WebUI's workspace-name validation.

iter 025 / iter 026 had this regex + reserved-name set duplicated in
both ``src/web/routes.py`` (for dashboard handlers) and
``src/web/wizard.py`` (for upload handler). A future change to one
without the other would silently let a workspace get created via the
wizard that the dashboard then rejects with 400 — invisible workspace.

Pull both into one module that both call sites import. The CLI-level
``src/cli_workspace.py:_validate_name`` is intentionally kept separate
because the project-level CLI may want a stricter / different policy
than the WebUI (e.g. CLI may want to forbid CJK if a downstream tool
can't handle the encoding).
"""

from __future__ import annotations

import re


# Identifier-style names: letters / digits / underscore / CJK Unified
# Ideographs, optionally with internal hyphens. Forbids leading or
# trailing ``-`` so the name doesn't collide with argparse flag
# parsing in iter 026 wizard / settings paths (code-review #9).
WORKSPACE_NAME_RE = re.compile(
    r"^[a-zA-Z0-9_一-鿿]"
    r"(?:[a-zA-Z0-9_一-鿿-]{0,30}[a-zA-Z0-9_一-鿿])?$"
)

# ``legacy`` is a paths.py sentinel — setting WORKSPACE_NAME to it
# resolves to repo-root mode (returns None). ``_trash`` is the reserved
# soft-delete holding area. User-creatable workspaces with either name
# would collide with internal control paths.
RESERVED_NAMES = frozenset({"legacy", "_trash"})


def validate_workspace_name(name: str) -> bool:
    """Return True if ``name`` is allowed as a WebUI workspace name."""
    if name in RESERVED_NAMES:
        return False
    return bool(WORKSPACE_NAME_RE.match(name))
