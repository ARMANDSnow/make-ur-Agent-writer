"""iter 037: drama station 2, hook design.

The station consumes the station 1 setup file and returns three mock hook
candidates. Real-model wiring arrives in iter 040+.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from . import paths
from .drama_planner import (
    _load_fixture,
    _load_wizard_input,
    build_system_prompt,
    _log_prompt,
)


def run(workspace: str, *, mock: bool = True) -> Dict[str, Any]:
    """Run station 2 for ``workspace`` and return hook candidates."""

    if not mock:
        raise NotImplementedError("iter 040+")

    setup_path = paths.WORKSPACE_DIR / workspace / "outputs" / "episodes" / "episode_01.setup.json"
    if not setup_path.is_file():
        raise FileNotFoundError(f"station 1 must complete before station 2; missing {setup_path}")
    setup = json.loads(setup_path.read_text(encoding="utf-8"))
    if not isinstance(setup, dict):
        raise ValueError(f"setup must be a JSON object: {setup_path}")
    core_setup = setup.get("core_setup")
    if not isinstance(core_setup, dict) or "protagonist" not in core_setup:
        raise ValueError(
            f"station 1 output for {workspace!r} missing core_setup.protagonist; "
            "station 2 cannot proceed"
        )

    wizard_input = _load_wizard_input(workspace)
    track = wizard_input["track"]
    system_prompt = build_system_prompt(workspace, "hook_designer", wizard_input)
    _log_prompt(workspace, "hook_designer", system_prompt)
    return _load_fixture(track, "hooks")
