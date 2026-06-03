"""iter 037: read-only drama workspace progress aggregation."""

from __future__ import annotations

from typing import Any, Dict

from .. import paths
from ..utils import read_json_optional


STATIONS = ("setup", "hook", "storyboard", "characters")


def collect_drama_progress(workspace: str) -> Dict[str, Any]:
    """Return the 4-station drama progress shape for the WebUI."""

    root = paths.WORKSPACE_DIR / workspace
    wizard_input_path = root / "data" / "wizard_input.json"
    setup_path = root / "outputs" / "episodes" / "episode_01.setup.json"

    wizard_input = read_json_optional(wizard_input_path, None)
    setup_data = read_json_optional(setup_path, None)
    setup_done = bool(
        isinstance(setup_data, dict)
        and isinstance(setup_data.get("core_setup"), dict)
        and setup_data["core_setup"].get("protagonist")
    )
    hook_done = bool(
        isinstance(setup_data, dict)
        and isinstance(setup_data.get("hook"), dict)
        and setup_data["hook"].get("type")
    )

    return {
        "workspace": workspace,
        "wizard_input": wizard_input if isinstance(wizard_input, dict) else None,
        "stations": [
            {
                "id": "setup",
                "label": "核心设定",
                "status": "done" if setup_done else "todo",
                "data": setup_data if setup_done else None,
            },
            {
                "id": "hook",
                "label": "钩子",
                "status": "done" if hook_done else ("todo" if setup_done else "locked"),
                "data": setup_data.get("hook") if isinstance(setup_data, dict) and hook_done else None,
            },
            {"id": "storyboard", "label": "分镜", "status": "locked", "data": None},
            {"id": "characters", "label": "角色", "status": "locked", "data": None},
        ],
    }
