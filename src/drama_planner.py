"""iter 037: drama station 1, core setup planning.

This module is mock-first. Real-model wiring arrives in iter 040+, so the
non-mock path deliberately raises before any LLM client can be involved.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

from . import paths
from .drama_schemas import DramaSetup, episode_paths, normalize_episode_no
from .llm_client import LLMClient
from .schemas import model_to_dict


TRACK_PINYIN = {
    "霸总": "bazhong",
    "重生": "chongsheng",
    "推理": "tuili",
    "系统": "xitong",
    "觉醒": "juexing",
}

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "drama"


def run(workspace: str, *, mock: bool | None = None, episode_no: int = 1) -> Dict[str, Any]:
    """Run station 1 for ``workspace`` and return the setup JSON."""

    episode_no = normalize_episode_no(episode_no)
    if episode_no > 1:
        return _inherit_previous_setup(workspace, episode_no=episode_no)

    wizard_input = _load_wizard_input(workspace)
    track = wizard_input["track"]
    if track not in TRACK_PINYIN:
        raise ValueError(f"unknown track: {track!r}")

    system_prompt = build_system_prompt(workspace, "drama_planner", wizard_input)
    _log_prompt(workspace, "drama_planner", system_prompt)
    client = None if mock is True else LLMClient("drama_plan")
    use_mock = client.is_mock if mock is None and client is not None else bool(mock)
    if use_mock:
        result = _load_fixture(track, "setup")
    else:
        if client is None:
            client = LLMClient("drama_plan")
        generated = client.complete_json(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "请输出站①核心设定 JSON。不要输出 Markdown，不要解释。"},
            ],
            DramaSetup,
        )
        result = model_to_dict(generated)
    # Server-owned identity fields cannot be overridden by model output.
    result["track"] = track
    result["episode_no"] = episode_no
    result["season_no"] = 1
    result["target_duration_seconds"] = wizard_input.get(
        "episode_duration_seconds", result.get("target_duration_seconds")
    )
    return model_to_dict(DramaSetup(**result))


def _inherit_previous_setup(workspace: str, *, episode_no: int) -> Dict[str, Any]:
    """Create a later-episode setup from the preceding local setup only.

    The selected hook is deliberately removed so station 2 must choose a fresh
    one.  No prompt is built or logged on this path, which keeps episode
    continuation independent from model configuration.
    """

    previous_path = episode_paths(workspace, episode_no=episode_no - 1).setup_path
    if not previous_path.is_file():
        raise FileNotFoundError(f"previous episode setup is required; missing {previous_path}")
    try:
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"previous episode setup must be valid JSON: {previous_path}") from exc
    if not isinstance(previous, dict):
        raise ValueError(f"previous episode setup must be a JSON object: {previous_path}")
    core_setup = previous.get("core_setup")
    if not isinstance(core_setup, dict) or not core_setup.get("protagonist"):
        raise ValueError("previous episode setup missing core_setup.protagonist")

    wizard_input = _load_wizard_input(workspace)
    track = str(previous.get("track") or wizard_input.get("track") or "")
    if track not in TRACK_PINYIN:
        raise ValueError(f"unknown track: {track!r}")

    # Only series-level fields cross the episode boundary. Episode-local
    # creative choices must start empty so ep3+ cannot accidentally continue
    # an earlier episode's title, logline, mainline, hook, or cast decision.
    return {
        "episode_no": episode_no,
        "season_no": 1,
        "title": "",
        "logline": "",
        "track": track,
        "target_duration_seconds": previous.get(
            "target_duration_seconds",
            wizard_input.get("episode_duration_seconds", 60),
        ),
        "core_setup": dict(core_setup),
        "episode_mainline": "",
        "introduces_new_characters": False,
    }


def build_system_prompt(workspace: str, template_name: str, wizard_input: Dict[str, Any] | None = None) -> str:
    """Compose a drama agent system prompt from the workspace snapshot."""

    data = wizard_input if wizard_input is not None else _load_wizard_input(workspace)
    snapshot = _load_snapshot(workspace)
    prompt_template = _load_prompt_template(template_name)
    return _compose_prompt(snapshot, prompt_template, data)


def _load_wizard_input(workspace: str) -> Dict[str, Any]:
    path = paths.WORKSPACE_DIR / workspace / "data" / "wizard_input.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing wizard_input.json for workspace {workspace!r}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"wizard_input.json must be an object for workspace {workspace!r}")
    return data


def _load_snapshot(workspace: str) -> str:
    path = paths.WORKSPACE_DIR / workspace / "data" / "creation_standard.snapshot.md"
    if not path.is_file():
        raise FileNotFoundError(
            f"missing creation_standard.snapshot.md for workspace {workspace!r}; "
            "this workspace cannot run drama agents"
        )
    return path.read_text(encoding="utf-8")


def _load_prompt_template(name: str) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / "prompts" / "drama" / f"{name}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"missing prompt template: {path}")
    return path.read_text(encoding="utf-8")


def _compose_prompt(snapshot: str, template: str, wizard_input: Dict[str, Any]) -> str:
    return template.format(
        snapshot=snapshot,
        topic=wizard_input.get("topic", ""),
        track=wizard_input.get("track", ""),
        episode_count=wizard_input.get("episode_count", 0),
        episode_duration_seconds=wizard_input.get("episode_duration_seconds", 0),
        episode_no=wizard_input.get("episode_no", 1),
    )


def _log_prompt(workspace: str, agent: str, prompt: str) -> None:
    log_path = paths.WORKSPACE_DIR / workspace / "logs" / "drama_prompts.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "agent": agent,
        "prompt_chars": len(prompt),
    }
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_fixture(track: str, station: str) -> Dict[str, Any]:
    pinyin = TRACK_PINYIN.get(track)
    if not pinyin:
        raise ValueError(f"unknown track: {track!r}")
    path = FIXTURE_DIR / f"track_{pinyin}_{station}.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing fixture: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"fixture must be a JSON object: {path}")
    return data
