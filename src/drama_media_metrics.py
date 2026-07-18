"""Bounded, read-only lifecycle metrics for generic drama media tasks."""

from __future__ import annotations

import os
import re
import stat
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import drama_edit_export, drama_media_tasks, paths
from .drama_store import _validate_render_workspace_root
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_MEDIA_METRICS_EPISODES = 100
MAX_MEDIA_METRICS_TASKS = 4000
MAX_MEDIA_METRICS_ROWS = 1000
MAX_MEDIA_METRICS_NAMESPACE_ENTRIES = 1000
_TASK_LEDGER_RE = re.compile(r"^episode_([0-9]{3})\.tasks\.json$")
_RELATIVE_DIRECTORY = "outputs/drama/media_tasks"
_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


class DramaMediaMetricsError(ValueError):
    """Bounded error that never includes task-private identity."""


def _empty_metrics() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "ok",
        "ledger_count": 0,
        "invalid_ledgers": 0,
        "task_count": 0,
        "terminal_count": 0,
        "succeeded_count": 0,
        "failed_count": 0,
        "cancelled_count": 0,
        "unknown_submission_count": 0,
        "pending_count": 0,
        "success_rate": None,
        "queue_wait_known_samples": 0,
        "queue_wait_unknown_samples": 0,
        "queue_wait_sum_ms": 0,
        "queue_wait_average_ms": None,
        "run_known_samples": 0,
        "run_unknown_samples": 0,
        "run_sum_ms": 0,
        "run_average_ms": None,
        "rows": [],
    }


def _ratio_string(numerator: int, denominator: int) -> str | None:
    if denominator <= 0:
        return None
    scaled, remainder = divmod(numerator * 1_000_000, denominator)
    if remainder * 2 >= denominator:
        scaled += 1
    whole, fraction = divmod(scaled, 1_000_000)
    return f"{whole}.{fraction:06d}"


def _scan_episode_numbers(root: Path) -> tuple[list[int], int]:
    directory_fd: int | None = None
    try:
        directory_fd = drama_edit_export._open_output_directory(
            root, _RELATIVE_DIRECTORY, create=False
        )
    except drama_edit_export.DramaEditExportError:
        current = root
        for part in ("outputs", "drama", "media_tasks"):
            candidate = current / part
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                return [], 0
            except OSError:
                return [], 1
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                return [], 1
            current = candidate
        return [], 1
    numbers: list[int] = []
    invalid = 0
    try:
        with os.scandir(directory_fd) as entries:
            for index, entry in enumerate(entries, start=1):
                if index > MAX_MEDIA_METRICS_NAMESPACE_ENTRIES:
                    raise DramaMediaMetricsError(
                        "media metrics namespace exceeds its limit"
                    )
                match = _TASK_LEDGER_RE.fullmatch(entry.name)
                if match is None or not entry.is_file(follow_symlinks=False):
                    invalid += 1
                    continue
                number = int(match.group(1))
                if (
                    number < 1
                    or number > MAX_MEDIA_METRICS_EPISODES
                    or entry.name != f"episode_{number:03d}.tasks.json"
                ):
                    invalid += 1
                    continue
                numbers.append(number)
    except OSError:
        return [], invalid + 1
    finally:
        os.close(directory_fd)
    if len(numbers) != len(set(numbers)):
        raise DramaMediaMetricsError(
            "media metrics namespace identity is ambiguous"
        )
    return sorted(numbers), invalid


def _task_sample(
    task: Any,
    lifecycle: Any,
) -> dict[str, Any]:
    terminal = task.state in _TERMINAL
    queue_known = (
        lifecycle is not None
        and lifecycle.ready_at_ms is not None
        and lifecycle.first_claimed_at_ms is not None
    )
    run_known = (
        lifecycle is not None
        and lifecycle.first_claimed_at_ms is not None
        and lifecycle.terminal_at_ms is not None
    )
    return {
        "terminal": terminal,
        "succeeded": task.state == "succeeded",
        "failed": task.state == "failed",
        "cancelled": task.state == "cancelled",
        "unknown_submission": task.state == "submission_unknown",
        "pending": task.state not in _TERMINAL
        and task.state != "submission_unknown",
        "queue_known": queue_known,
        "queue_wait_ms": (
            lifecycle.first_claimed_at_ms - lifecycle.ready_at_ms
            if queue_known
            else None
        ),
        "run_known": run_known,
        "run_ms": (
            lifecycle.terminal_at_ms - lifecycle.first_claimed_at_ms
            if run_known
            else None
        ),
    }


def _aggregate_samples(
    entries: list[tuple[Any, Any, str | None, str | None]],
) -> dict[str, Any]:
    groups: dict[
        tuple[int, str, str, str, str | None, str | None],
        list[dict[str, Any]],
    ] = defaultdict(list)
    all_samples: list[dict[str, Any]] = []
    for task, lifecycle, provider_id, model_id in entries:
        sample = _task_sample(task, lifecycle)
        all_samples.append(sample)
        groups[
            (
                task.episode_no,
                task.subject_id,
                task.media_kind,
                task.stage,
                provider_id,
                model_id,
            )
        ].append(sample)
    if len(groups) > MAX_MEDIA_METRICS_ROWS:
        raise DramaMediaMetricsError("media metrics rows exceed their limit")

    def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
        terminal = sum(item["terminal"] for item in samples)
        succeeded = sum(item["succeeded"] for item in samples)
        queue_values = [
            item["queue_wait_ms"]
            for item in samples
            if item["queue_known"]
        ]
        run_values = [
            item["run_ms"] for item in samples if item["run_known"]
        ]
        return {
            "task_count": len(samples),
            "terminal_count": terminal,
            "succeeded_count": succeeded,
            "failed_count": sum(item["failed"] for item in samples),
            "cancelled_count": sum(item["cancelled"] for item in samples),
            "unknown_submission_count": sum(
                item["unknown_submission"] for item in samples
            ),
            "pending_count": sum(item["pending"] for item in samples),
            "success_rate": _ratio_string(succeeded, terminal),
            "queue_wait_known_samples": len(queue_values),
            "queue_wait_unknown_samples": len(samples) - len(queue_values),
            "queue_wait_sum_ms": sum(queue_values),
            "queue_wait_average_ms": _ratio_string(
                sum(queue_values), len(queue_values)
            ),
            "run_known_samples": len(run_values),
            "run_unknown_samples": len(samples) - len(run_values),
            "run_sum_ms": sum(run_values),
            "run_average_ms": _ratio_string(
                sum(run_values), len(run_values)
            ),
        }

    rows = []
    for identity in sorted(
        groups,
        key=lambda item: (
            item[0],
            item[1],
            item[2],
            item[3],
            item[4] or "",
            item[5] or "",
        ),
    ):
        (
            episode_no,
            subject_id,
            media_kind,
            stage,
            provider_id,
            model_id,
        ) = identity
        rows.append(
            {
                "episode_no": episode_no,
                "subject_id": subject_id,
                "media_kind": media_kind,
                "stage": stage,
                "provider_id": provider_id,
                "model_id": model_id,
                **summarize(groups[identity]),
            }
        )
    return {**summarize(all_samples), "rows": rows}


def collect_workspace_media_metrics(workspace: str) -> dict[str, Any]:
    """Return a safe fail-closed lifecycle projection for drama Insights."""

    empty = _empty_metrics()
    try:
        root = paths.workspace_root(workspace)
        if not root.exists():
            return empty
        _validate_render_workspace_root(root)
        with use_workspace(workspace), acquire_write_lock(
            source="drama-media-metrics"
        ):
            numbers, invalid = _scan_episode_numbers(root)
            if invalid:
                return {
                    **empty,
                    "status": "degraded",
                    "invalid_ledgers": invalid,
                }
            tokens = {
                number: drama_media_tasks._target_token(
                    root,
                    drama_media_tasks.media_task_ledger_path(
                        workspace, episode_no=number
                    ),
                )
                for number in numbers
            }
            entries: list[tuple[Any, Any, str | None, str | None]] = []
            for number in numbers:
                try:
                    ledger, source_token = drama_media_tasks._read_ledger(
                        workspace,
                        episode_no=number,
                        include_source_token=True,
                    )
                except (
                    FileNotFoundError,
                    drama_media_tasks.DramaMediaTaskError,
                ):
                    return {
                        **empty,
                        "status": "degraded",
                        "invalid_ledgers": 1,
                    }
                if source_token != tokens[number]:
                    return {
                        **empty,
                        "status": "degraded",
                        "invalid_ledgers": 1,
                    }
                if len(entries) + len(ledger.tasks) > MAX_MEDIA_METRICS_TASKS:
                    return {
                        **empty,
                        "status": "degraded",
                        "invalid_ledgers": 1,
                    }
                lifecycle = {item.task_id: item for item in ledger.lifecycle}
                bindings = {
                    item.task_id: item for item in ledger.backend_bindings
                }
                for task in ledger.tasks:
                    binding = bindings.get(task.task_id)
                    entries.append(
                        (
                            task,
                            lifecycle.get(task.task_id),
                            None if binding is None else binding.provider_id,
                            None if binding is None else binding.model_id,
                        )
                    )
            final_numbers, final_invalid = _scan_episode_numbers(root)
            final_tokens = {
                number: drama_media_tasks._target_token(
                    root,
                    drama_media_tasks.media_task_ledger_path(
                        workspace, episode_no=number
                    ),
                )
                for number in final_numbers
            }
            if (
                final_invalid
                or final_numbers != numbers
                or final_tokens != tokens
            ):
                return {
                    **empty,
                    "status": "degraded",
                    "invalid_ledgers": 1,
                }
            aggregate = _aggregate_samples(entries)
        return {
            "schema_version": 1,
            "status": "ok",
            "ledger_count": len(numbers),
            "invalid_ledgers": 0,
            **aggregate,
        }
    except (
        OSError,
        RecursionError,
        TypeError,
        ValueError,
        DramaMediaMetricsError,
        WorkspaceLocked,
    ):
        return {
            **empty,
            "status": "degraded",
            "invalid_ledgers": 1,
        }
