"""Read-only aggregate data for the drama Insights page.

The collector deliberately exposes only counters and derived metrics.  Raw
LLM log fields (prompts, errors, request hashes, API keys, and so on) never
leave this module.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .. import paths
from ..cost_estimator import cost_cny


_EPISODE_RE = re.compile(r"^episode_(\d+)\.json$")
_EPISODE_META_RE = re.compile(r"^episode_(\d+)\.meta\.json$")
_TOKEN_FIELDS = (
    "prompt_tokens",
    "response_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)
_DURATION_TOLERANCE_SECONDS = 3
_MAX_TOKEN_COUNT = 1_000_000_000
_MAX_EPISODE_COST_CNY = 1_000_000.0
_MAX_TARGET_DURATION_SECONDS = 300.0
_MAX_ESTIMATED_DURATION_SECONDS = 600.0
_MOCK_COST_NOTE = "mock 模式费用恒为 0；启用真模型后才会产生真实费用。"


def collect_drama_insights(workspace: str) -> Dict[str, Any]:
    """Aggregate local drama costs, duration compliance, and hook types.

    ``routes.api_workspace_insights`` validates the workspace name and type
    before calling this function.  Missing directories and legacy artifacts
    degrade to zero-filled aggregates.
    """

    root = paths.WORKSPACE_DIR / workspace
    llm_cost = _collect_llm_cost(root / "logs" / "llm_calls.jsonl")
    episode_meta_cost = _collect_episode_meta_cost(root / "outputs" / "episodes")
    duration, hook_types = _collect_episode_metrics(root / "outputs" / "episodes")
    return {
        "llm_cost": llm_cost,
        "episode_meta_cost": episode_meta_cost,
        "duration": duration,
        "hook_types": hook_types,
        "cost_note": _MOCK_COST_NOTE,
    }


def _collect_llm_cost(path: Path) -> Dict[str, Any]:
    totals = {
        "calls": 0,
        "prompt_tokens": 0,
        "response_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_cny": 0.0,
        "dirty_lines": 0,
    }
    if not path.is_file():
        return totals

    total_cost = 0.0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    totals["dirty_lines"] += 1
                    continue
                if not isinstance(record, dict):
                    totals["dirty_lines"] += 1
                    continue

                task = record.get("task")
                if not isinstance(task, str) or not task.startswith("drama_"):
                    continue

                parsed_tokens: Dict[str, int] = {}
                invalid = False
                for field in _TOKEN_FIELDS:
                    value = _nonnegative_int(record.get(field, 0))
                    if value is None:
                        invalid = True
                        break
                    parsed_tokens[field] = value
                # Some historical logs carry a precomputed cost.  It is not
                # used for the ledger (cost_cny() is the single pricing source)
                # but an invalid value still marks the record as dirty.
                if not invalid and "cost_cny" in record:
                    invalid = _nonnegative_number(record.get("cost_cny")) is None
                model = record.get("model", "")
                if not isinstance(model, str):
                    invalid = True
                if invalid:
                    totals["dirty_lines"] += 1
                    continue

                record_cost = cost_cny(
                    parsed_tokens["prompt_tokens"],
                    parsed_tokens["cache_read_tokens"],
                    parsed_tokens["response_tokens"],
                    model=model,
                )
                if not math.isfinite(record_cost) or record_cost < 0 or not math.isfinite(total_cost + record_cost):
                    totals["dirty_lines"] += 1
                    continue
                totals["calls"] += 1
                for field in _TOKEN_FIELDS:
                    totals[field] += parsed_tokens[field]
                total_cost += record_cost
    except OSError:
        # A concurrent delete/permission change must not take down Insights.
        return totals

    totals["cost_cny"] = round(total_cost, 4)
    return totals


def _collect_episode_meta_cost(episodes_dir: Path) -> Dict[str, Any]:
    result = {"cost_cny": 0.0, "episodes": 0, "invalid": 0}
    total = 0.0
    for path in _matching_files(episodes_dir, _EPISODE_META_RE):
        episode_no = _canonical_episode_no(path, _EPISODE_META_RE, suffix=".meta.json")
        if episode_no is None:
            result["invalid"] += 1
            continue
        state, data = _read_json_object(path)
        if state == "invalid":
            result["invalid"] += 1
            continue
        if state != "ok" or data is None:
            continue
        artifact_episode_no = data.get("episode_no")
        if (
            not isinstance(artifact_episode_no, int)
            or isinstance(artifact_episode_no, bool)
            or artifact_episode_no != episode_no
        ):
            result["invalid"] += 1
            continue
        # Legacy meta without cost_cny is a valid zero-cost record.
        raw_cost = data.get("cost_cny", 0)
        value = _nonnegative_number(raw_cost, maximum=_MAX_EPISODE_COST_CNY)
        if value is None:
            result["invalid"] += 1
            continue
        if not math.isfinite(total + value):
            result["invalid"] += 1
            continue
        result["episodes"] += 1
        total += value
    result["cost_cny"] = round(total, 4)
    return result


def _collect_episode_metrics(episodes_dir: Path) -> Tuple[Dict[str, Any], list[Dict[str, Any]]]:
    total = 0
    within_tolerance = 0
    invalid = 0
    hooks: Counter[str] = Counter()

    for path in _matching_files(episodes_dir, _EPISODE_RE):
        episode_no = _canonical_episode_no(path, _EPISODE_RE, suffix=".json")
        if episode_no is None:
            invalid += 1
            continue
        state, episode = _read_json_object(path)
        if state != "ok" or episode is None:
            invalid += 1
            continue
        artifact_episode_no = episode.get("episode_no")
        if (
            not isinstance(artifact_episode_no, int)
            or isinstance(artifact_episode_no, bool)
            or artifact_episode_no != episode_no
        ):
            invalid += 1
            continue

        target = _nonnegative_number(
            episode.get("target_duration_seconds"), maximum=_MAX_TARGET_DURATION_SECONDS
        )
        estimate = _nonnegative_number(
            episode.get("estimated_duration_seconds"), maximum=_MAX_ESTIMATED_DURATION_SECONDS
        )
        if target is None or target <= 0 or estimate is None:
            invalid += 1
        else:
            total += 1
            if abs(estimate - target) <= _DURATION_TOLERANCE_SECONDS:
                within_tolerance += 1

        ending_hook = episode.get("ending_hook")
        raw_type = ending_hook.get("type") if isinstance(ending_hook, dict) else None
        hook_type = raw_type.strip()[:80] if isinstance(raw_type, str) else ""
        hooks[hook_type or "(未标注)"] += 1

    duration = {
        "total": total,
        "within_tolerance": within_tolerance,
        "rate": round(within_tolerance / total, 4) if total else 0.0,
        "tolerance_seconds": _DURATION_TOLERANCE_SECONDS,
        "invalid": invalid,
    }
    hook_types = [
        {"type": hook_type, "count": count}
        for hook_type, count in sorted(hooks.items(), key=lambda item: (-item[1], item[0]))
    ]
    return duration, hook_types


def _matching_files(directory: Path, pattern: "re.Pattern[str]") -> list[Path]:
    if not directory.is_dir():
        return []
    try:
        return sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and pattern.fullmatch(path.name)
        )
    except OSError:
        return []


def _canonical_episode_no(
    path: Path,
    pattern: "re.Pattern[str]",
    *,
    suffix: str,
) -> Optional[int]:
    match = pattern.fullmatch(path.name)
    if match is None:
        return None
    raw = match.group(1)
    if not raw.isascii() or not raw.isdigit():
        return None
    digits = raw.lstrip("0") or "0"
    if len(digits) > 3:
        return None
    number = int(digits)
    if number < 1 or number > 100:
        return None
    expected = f"episode_{number:02d}{suffix}"
    return number if path.name == expected else None


def _read_json_object(path: Path) -> Tuple[str, Optional[Dict[str, Any]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return "invalid", None
    if not isinstance(data, dict):
        return "invalid", None
    return "ok", data


def _nonnegative_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= _MAX_TOKEN_COUNT else None
    if isinstance(value, str) and value.isascii() and value.isdigit():
        stripped = value.lstrip("0") or "0"
        if len(stripped) > len(str(_MAX_TOKEN_COUNT)):
            return None
        number = int(stripped)
        return number if number <= _MAX_TOKEN_COUNT else None
    return None


def _nonnegative_number(value: Any, *, maximum: Optional[float] = None) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    if maximum is not None and number > maximum:
        return None
    return number
