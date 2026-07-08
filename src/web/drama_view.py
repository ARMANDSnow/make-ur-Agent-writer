"""Read-only drama workspace progress aggregation."""

from __future__ import annotations

from typing import Any, Dict

from ..drama_schemas import DramaStoryboard, episode_paths, validate_storyboard_hard
from ..utils import read_json_optional


STATIONS = ("setup", "hook", "storyboard", "characters")


def collect_drama_progress(workspace: str) -> Dict[str, Any]:
    """Return the 4-station drama progress shape for the WebUI."""

    ep = episode_paths(workspace)
    wizard_input_path = ep.root / "data" / "wizard_input.json"
    setup_path = ep.setup_path
    storyboard_path = ep.storyboard_path

    wizard_input = read_json_optional(wizard_input_path, None)
    setup_data = read_json_optional(setup_path, None)
    storyboard_data = read_json_optional(storyboard_path, None)
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
    storyboard_done = _storyboard_done(storyboard_data)

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
            {
                "id": "storyboard",
                "label": "分镜",
                "status": "done" if storyboard_done else ("todo" if hook_done else "locked"),
                "data": storyboard_data if storyboard_done else None,
            },
            {"id": "characters", "label": "角色", "status": "locked", "data": None},
        ],
    }


def _storyboard_done(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    try:
        board = DramaStoryboard(**data)
    except Exception:
        return False
    return not validate_storyboard_hard(board)
