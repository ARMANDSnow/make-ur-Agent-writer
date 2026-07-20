"""Read-only aggregate data for the drama Insights page.

The collector deliberately exposes only counters and derived metrics.  Raw
LLM log fields (prompts, errors, request hashes, API keys, and so on) never
leave this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .. import paths
from ..cost_estimator import cost_cny
from ..drama_media_metrics import collect_workspace_media_metrics
from ..drama_media_pricing import collect_workspace_media_pricing


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
_MAX_INSIGHTS_NAMESPACE_ENTRIES = 512
_MAX_LLM_LOG_BYTES = 4 * 1024 * 1024
_MAX_LLM_LOG_LINES = 10_000
_MAX_LLM_LOG_LINE_BYTES = 64 * 1024
_MAX_EPISODE_JSON_BYTES = 2 * 1024 * 1024
_MAX_EPISODE_NAMESPACE_BYTES = 16 * 1024 * 1024
_MAX_JSON_DEPTH = 40
_MOCK_COST_NOTE = (
    "LLM mock 模式费用恒为 0，启用真模型后才产生文本费用；"
    "媒体金额来自独立 pricing facts，"
    "unknown 不计作 0。"
)


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
    media_pricing = collect_workspace_media_pricing(workspace)
    media_metrics = collect_workspace_media_metrics(workspace)
    return {
        "llm_cost": llm_cost,
        "episode_meta_cost": episode_meta_cost,
        "media_pricing": media_pricing,
        "media_metrics": media_metrics,
        "duration": duration,
        "hook_types": hook_types,
        "cost_note": _MOCK_COST_NOTE,
    }


def _collect_llm_cost(path: Path) -> Dict[str, Any]:
    totals = {
        "status": "ok",
        "calls": 0,
        "prompt_tokens": 0,
        "response_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_cny": 0.0,
        "dirty_lines": 0,
    }
    state, raw = _read_workspace_file(path, maximum=_MAX_LLM_LOG_BYTES)
    if state == "missing":
        return totals
    if state != "ok" or raw is None:
        return {**totals, "status": "degraded", "dirty_lines": 1}

    total_cost = 0.0
    try:
        lines = raw.splitlines()
        if len(lines) > _MAX_LLM_LOG_LINES:
            raise ValueError("LLM log line limit exceeded")
        for raw_line in lines:
                if len(raw_line) > _MAX_LLM_LOG_LINE_BYTES:
                    raise ValueError("LLM log line size exceeded")
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    raise ValueError("invalid LLM log row") from None
                if not isinstance(record, dict):
                    raise ValueError("invalid LLM log row")
                _require_bounded_json(record)

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
                    raise ValueError("invalid LLM log row")

                record_cost = cost_cny(
                    parsed_tokens["prompt_tokens"],
                    parsed_tokens["cache_read_tokens"],
                    parsed_tokens["response_tokens"],
                    model=model,
                )
                if not math.isfinite(record_cost) or record_cost < 0 or not math.isfinite(total_cost + record_cost):
                    raise ValueError("invalid LLM log cost")
                totals["calls"] += 1
                for field in _TOKEN_FIELDS:
                    totals[field] += parsed_tokens[field]
                total_cost += record_cost
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return {
            **{key: 0 for key in totals if key not in {"status", "cost_cny"}},
            "status": "degraded",
            "cost_cny": 0.0,
            "dirty_lines": 1,
        }

    totals["cost_cny"] = round(total_cost, 4)
    return totals


def _collect_episode_meta_cost(episodes_dir: Path) -> Dict[str, Any]:
    result = {"status": "ok", "cost_cny": 0.0, "episodes": 0, "invalid": 0}
    total = 0.0
    files, namespace_invalid = _matching_files(episodes_dir, _EPISODE_META_RE)
    if namespace_invalid:
        return {**result, "status": "degraded", "invalid": namespace_invalid}
    for path, token in files:
        episode_no = _canonical_episode_no(path, _EPISODE_META_RE, suffix=".meta.json")
        if episode_no is None:
            result["invalid"] += 1
            continue
        state, data = _read_json_object(path, expected_token=token)
        if state == "invalid":
            return {**result, "status": "degraded", "cost_cny": 0.0, "episodes": 0, "invalid": 1}
        if state != "ok" or data is None:
            return {**result, "status": "degraded", "cost_cny": 0.0, "episodes": 0, "invalid": 1}
        artifact_episode_no = data.get("episode_no")
        if (
            not isinstance(artifact_episode_no, int)
            or isinstance(artifact_episode_no, bool)
            or artifact_episode_no != episode_no
        ):
            return {**result, "status": "degraded", "cost_cny": 0.0, "episodes": 0, "invalid": 1}
        # Legacy meta without cost_cny is a valid zero-cost record.
        raw_cost = data.get("cost_cny", 0)
        value = _nonnegative_number(raw_cost, maximum=_MAX_EPISODE_COST_CNY)
        if value is None:
            return {**result, "status": "degraded", "cost_cny": 0.0, "episodes": 0, "invalid": 1}
        if not math.isfinite(total + value):
            return {**result, "status": "degraded", "cost_cny": 0.0, "episodes": 0, "invalid": 1}
        result["episodes"] += 1
        total += value
    final_files, final_invalid = _matching_files(episodes_dir, _EPISODE_META_RE)
    if final_invalid or final_files != files:
        return {
            "status": "degraded",
            "cost_cny": 0.0,
            "episodes": 0,
            "invalid": max(1, final_invalid),
        }
    result["cost_cny"] = round(total, 4)
    return result


def _collect_episode_metrics(episodes_dir: Path) -> Tuple[Dict[str, Any], list[Dict[str, Any]]]:
    total = 0
    within_tolerance = 0
    invalid = 0
    hooks: Counter[str] = Counter()

    files, namespace_invalid = _matching_files(episodes_dir, _EPISODE_RE)
    if namespace_invalid:
        return {
            "status": "degraded",
            "total": 0,
            "within_tolerance": 0,
            "rate": 0.0,
            "tolerance_seconds": _DURATION_TOLERANCE_SECONDS,
            "invalid": namespace_invalid,
        }, []
    for path, token in files:
        episode_no = _canonical_episode_no(path, _EPISODE_RE, suffix=".json")
        if episode_no is None:
            invalid += 1
            continue
        state, episode = _read_json_object(path, expected_token=token)
        if state != "ok" or episode is None:
            return {
                "status": "degraded",
                "total": 0,
                "within_tolerance": 0,
                "rate": 0.0,
                "tolerance_seconds": _DURATION_TOLERANCE_SECONDS,
                "invalid": 1,
            }, []
        artifact_episode_no = episode.get("episode_no")
        if (
            not isinstance(artifact_episode_no, int)
            or isinstance(artifact_episode_no, bool)
            or artifact_episode_no != episode_no
        ):
            return {
                "status": "degraded",
                "total": 0,
                "within_tolerance": 0,
                "rate": 0.0,
                "tolerance_seconds": _DURATION_TOLERANCE_SECONDS,
                "invalid": 1,
            }, []

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
    final_files, final_invalid = _matching_files(episodes_dir, _EPISODE_RE)
    if final_invalid or final_files != files:
        return {
            "status": "degraded",
            "total": 0,
            "within_tolerance": 0,
            "rate": 0.0,
            "tolerance_seconds": _DURATION_TOLERANCE_SECONDS,
            "invalid": max(1, final_invalid),
        }, []

    duration = {
        "status": "ok",
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


def _matching_files(
    directory: Path, pattern: "re.Pattern[str]"
) -> tuple[list[tuple[Path, tuple[int, int, int, int, str]]], int]:
    directory_fd = _open_workspace_directory(directory)
    if directory_fd is None:
        try:
            info = directory.lstat()
        except FileNotFoundError:
            return [], 0
        except OSError:
            return [], 1
        return [], 1
    try:
        matched: list[tuple[Path, tuple[int, int, int, int, str]]] = []
        invalid = 0
        total_bytes = 0
        with os.scandir(directory_fd) as entries:
            for count, entry in enumerate(entries, start=1):
                if count > _MAX_INSIGHTS_NAMESPACE_ENTRIES:
                    return [], 1
                if pattern.fullmatch(entry.name):
                    suffix = (
                        ".meta.json"
                        if pattern is _EPISODE_META_RE
                        else ".json"
                    )
                    if _canonical_episode_no(
                        directory / entry.name,
                        pattern,
                        suffix=suffix,
                    ) is None:
                        invalid += 1
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        invalid += 1
                    else:
                        info = os.stat(
                            entry.name,
                            dir_fd=directory_fd,
                            follow_symlinks=False,
                        )
                        if not stat.S_ISREG(info.st_mode):
                            invalid += 1
                        elif (
                            info.st_size < 0
                            or total_bytes + info.st_size
                            > _MAX_EPISODE_NAMESPACE_BYTES
                        ):
                            return [], 1
                        else:
                            total_bytes += info.st_size
                            path = directory / entry.name
                            stat_token = (
                                info.st_dev,
                                info.st_ino,
                                info.st_size,
                                info.st_mtime_ns,
                            )
                            state, raw = _read_workspace_file(
                                path,
                                maximum=_MAX_EPISODE_JSON_BYTES,
                                expected_token=stat_token,
                            )
                            if state != "ok" or raw is None:
                                invalid += 1
                            else:
                                matched.append(
                                    (path, (*stat_token, hashlib.sha256(raw).hexdigest()))
                                )
        return sorted(matched, key=lambda item: item[0].name), invalid
    except OSError:
        return [], 1
    finally:
        os.close(directory_fd)


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


def _read_json_object(
    path: Path,
    *,
    expected_token: Optional[tuple[Any, ...]] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    state, raw = _read_workspace_file(
        path,
        maximum=_MAX_EPISODE_JSON_BYTES,
        expected_token=expected_token,
    )
    if state != "ok" or raw is None:
        return state, None
    try:
        data = json.loads(raw)
        _require_bounded_json(data)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return "invalid", None
    if not isinstance(data, dict):
        return "invalid", None
    return "ok", data


def _workspace_relative_parts(path: Path) -> tuple[str, ...]:
    relative = path.relative_to(paths.WORKSPACE_DIR)
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("unsafe workspace path")
    return tuple(relative.parts)


def _open_workspace_directory(path: Path) -> Optional[int]:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        return None
    try:
        parts = _workspace_relative_parts(path)
        current = os.open(
            str(paths.WORKSPACE_DIR),
            os.O_RDONLY | directory | nofollow,
        )
        try:
            for part in parts:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=current,
                )
                os.close(current)
                current = next_fd
            return current
        except Exception:
            os.close(current)
            raise
    except (FileNotFoundError, NotADirectoryError):
        return None
    except (OSError, ValueError):
        return None


def _read_workspace_file(
    path: Path,
    *,
    maximum: int,
    expected_token: Optional[tuple[Any, ...]] = None,
) -> tuple[str, Optional[bytes]]:
    parent_fd = _open_workspace_directory(path.parent)
    if parent_fd is None:
        try:
            info = path.parent.lstat()
        except FileNotFoundError:
            return "missing", None
        except OSError:
            return "invalid", None
        return "invalid", None
    file_fd: Optional[int] = None
    try:
        file_fd = os.open(
            path.name,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_fd,
        )
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            return "invalid", None
        before_token = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        if expected_token is not None and before_token != expected_token[:4]:
            return "invalid", None
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(64 * 1024, maximum + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                return "invalid", None
            chunks.append(chunk)
        after = os.fstat(file_fd)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
        if identity(before) != identity(after):
            return "invalid", None
        raw = b"".join(chunks)
        if (
            expected_token is not None
            and len(expected_token) == 5
            and hashlib.sha256(raw).hexdigest() != expected_token[4]
        ):
            return "invalid", None
        return "ok", raw
    except FileNotFoundError:
        return "missing", None
    except OSError:
        return "invalid", None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(parent_fd)


def _require_bounded_json(value: Any, *, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise ValueError("JSON nesting limit exceeded")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise ValueError("JSON key is invalid")
            _require_bounded_json(item, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            _require_bounded_json(item, depth=depth + 1)


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
