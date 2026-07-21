"""Disposable H3 context memory bound to the current H2 authority closure.

The cache stores event/source identities only.  It never stores source prose,
rolling-summary text, plaintext keywords, prompts, embeddings, or provider data.
Deleting it cannot change the event graph, RenderPlan, or canonical episode.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from . import paths
from .drama_event_graph import (
    DramaEventGraphError,
    event_graph_scope_fingerprint,
    select_event_projection,
)
from .drama_render_plan import inspect_render_plan_source_events
from .drama_render_store import inspect_render_plan
from .drama_schemas import (
    DRAMA_CONTEXT_MEMORY_MAX_KEYWORDS,
    DRAMA_CONTEXT_MEMORY_MAX_RECORDS,
    DramaContextMemoryCache,
    DramaContextMemoryRecord,
    DramaEventGraph,
    DramaEventProjection,
    RenderPlan,
    _canonical_sha256,
    normalize_episode_no,
)
from .drama_source_adapter import (
    DramaSourceAdapterError,
    load_production_source_event_graph,
)
from .drama_store import (
    _read_strict_workspace_bytes,
    _validate_render_workspace_root,
)
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_CONTEXT_MEMORY_BYTES = 2 * 1024 * 1024
MAX_CONTEXT_POLICY_FILE_BYTES = 2 * 1024 * 1024
_CONTEXT_DIRECTORY = ("outputs", "drama", "context_memory")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_POLICY_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,159}$")
_DEFAULT_POLICY_FILES = (
    "config/agents.yaml",
    "docs/product/short_drama_creation_standard.md",
    "src/drama_context_memory.py",
    "src/drama_render_plan.py",
)


class DramaContextMemoryError(ValueError):
    """Bounded public H3 error without private text or local paths."""


ContextMemoryState = Literal[
    "missing",
    "fresh",
    "stale",
    "invalid",
    "blocked_source",
]


@dataclass(frozen=True)
class DramaContextMemoryQuery:
    cache_id: str
    keyword_event_ids: tuple[str, ...]
    recent_event_ids: tuple[str, ...]
    summary_event_ids: tuple[str, ...]
    combined_event_ids: tuple[str, ...]


@dataclass(frozen=True)
class DramaContextMemoryInspection:
    state: ContextMemoryState
    reasons: tuple[str, ...]
    cache: DramaContextMemoryCache | None = None
    query: DramaContextMemoryQuery | None = None


@dataclass(frozen=True)
class _CurrentContext:
    graph: DramaEventGraph
    projection: DramaEventProjection
    plan: RenderPlan
    graph_family_id: str
    source_snapshot_fingerprint: str
    policy_fingerprint: str

    @property
    def binding_token(self) -> tuple[str, ...]:
        return (
            self.graph.graph_fingerprint,
            self.projection.projection_fingerprint,
            self.plan.plan_fingerprint,
            self.source_snapshot_fingerprint,
            self.policy_fingerprint,
        )


def _strict_sha256(value: Any, *, name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise DramaContextMemoryError(f"{name} must be a sha256 fingerprint")
    return value


def _strict_positive_int(value: Any, *, name: str, maximum: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > maximum
    ):
        raise DramaContextMemoryError(f"{name} must be a strict bounded integer")
    return value


def _normalize_keyword(value: Any) -> str:
    if type(value) is not str:
        raise DramaContextMemoryError("context keyword must be text")
    if len(value) > 320:
        raise DramaContextMemoryError("context keyword is invalid")
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if (
        not normalized
        or len(normalized) > 80
        or any(unicodedata.category(char).startswith("C") for char in normalized)
    ):
        raise DramaContextMemoryError("context keyword is invalid")
    return normalized


def context_keyword_hash(value: str) -> str:
    """Hash one in-memory query; plaintext is never persisted by this module."""

    return _canonical_sha256(
        {
            "artifact_type": "drama_context_keyword",
            "schema_version": 1,
            "keyword": _normalize_keyword(value),
        }
    )


def context_memory_policy_fingerprint(sources: Mapping[str, bytes]) -> str:
    """Bind exact strategy/prompt bytes without retaining their contents."""

    if type(sources) is not dict or not sources:
        raise DramaContextMemoryError("context policy sources are required")
    if len(sources) > 32:
        raise DramaContextMemoryError("context policy source count exceeds its limit")
    records: list[dict[str, Any]] = []
    for label, payload in sources.items():
        if (
            type(label) is not str
            or _POLICY_LABEL_RE.fullmatch(label) is None
            or label.startswith("/")
            or any(part in {"", ".", ".."} for part in label.split("/"))
            or type(payload) is not bytes
            or not payload
            or len(payload) > MAX_CONTEXT_POLICY_FILE_BYTES
        ):
            raise DramaContextMemoryError("context policy source is invalid")
        records.append(
            {
                "label": label,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    records.sort(key=lambda item: item["label"])
    if len({item["label"] for item in records}) != len(records):
        raise DramaContextMemoryError("context policy labels must be unique")
    return _canonical_sha256(
        {
            "artifact_type": "drama_context_policy",
            "schema_version": 1,
            "sources": records,
        }
    )


def _read_repo_policy_file(relative: str) -> bytes:
    if _POLICY_LABEL_RE.fullmatch(relative) is None or any(
        part in {"", ".", ".."} for part in relative.split("/")
    ):
        raise DramaContextMemoryError("default context policy label is invalid")
    parts = relative.split("/")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise DramaContextMemoryError("strict policy reads are unavailable")
    try:
        def read_once() -> bytes:
            directory_fd: int | None = os.open(
                str(paths.ROOT),
                os.O_RDONLY | directory | nofollow,
            )
            fd: int | None = None
            try:
                for part in parts[:-1]:
                    next_fd = os.open(
                        part,
                        os.O_RDONLY | directory | nofollow,
                        dir_fd=directory_fd,
                    )
                    os.close(directory_fd)
                    directory_fd = next_fd
                fd = os.open(
                    parts[-1],
                    os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0),
                    dir_fd=directory_fd,
                )
                opened = os.fstat(fd)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_size <= 0
                    or opened.st_size > MAX_CONTEXT_POLICY_FILE_BYTES
                ):
                    raise DramaContextMemoryError(
                        "default context policy is invalid"
                    )
                chunks: list[bytes] = []
                remaining = opened.st_size
                while remaining:
                    chunk = os.read(fd, min(65536, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                payload = b"".join(chunks)
                if len(payload) != opened.st_size:
                    raise DramaContextMemoryError(
                        "default context policy changed during read"
                    )
                return payload
            finally:
                if fd is not None:
                    os.close(fd)
                if directory_fd is not None:
                    os.close(directory_fd)

        first = read_once()
        second = read_once()
    except DramaContextMemoryError:
        raise
    except OSError as exc:
        raise DramaContextMemoryError("default context policy cannot be read") from exc
    if (
        first != second
        or not first
        or len(first) > MAX_CONTEXT_POLICY_FILE_BYTES
    ):
        raise DramaContextMemoryError("default context policy changed during read")
    return first


def load_default_context_policy_fingerprint() -> str:
    """Return the zero-network fingerprint of the tracked drama strategy files."""

    return context_memory_policy_fingerprint(
        {label: _read_repo_policy_file(label) for label in _DEFAULT_POLICY_FILES}
    )


def _revalidate_graph(value: DramaEventGraph) -> DramaEventGraph:
    try:
        if type(value) is not DramaEventGraph:
            raise TypeError("context graph must be an exact validated model")
        return DramaEventGraph(**model_to_dict(value))
    except (TypeError, ValueError) as exc:
        raise DramaContextMemoryError("context graph is invalid") from exc


def _revalidate_projection(
    value: DramaEventProjection,
) -> DramaEventProjection:
    try:
        if type(value) is not DramaEventProjection:
            raise TypeError("context projection must be an exact validated model")
        return DramaEventProjection(**model_to_dict(value))
    except (TypeError, ValueError) as exc:
        raise DramaContextMemoryError("context projection is invalid") from exc


def _revalidate_plan(value: RenderPlan) -> RenderPlan:
    try:
        if type(value) is not RenderPlan:
            raise TypeError("context RenderPlan must be an exact validated model")
        return RenderPlan(**model_to_dict(value))
    except (TypeError, ValueError) as exc:
        raise DramaContextMemoryError("context RenderPlan is invalid") from exc


def build_context_memory_cache(
    *,
    graph: DramaEventGraph,
    projection: DramaEventProjection,
    render_plan: RenderPlan,
    graph_family_id: str,
    source_snapshot_fingerprint: str,
    policy_fingerprint: str,
    recent_limit: int = 8,
    summary_event_ids: Sequence[str] | None = None,
    keyword_event_ids: Mapping[str, Sequence[str]] | None = None,
) -> DramaContextMemoryCache:
    """Build a text-free recent/summary/keyword cache from exact H2 facts."""

    current_graph = _revalidate_graph(graph)
    current_projection = _revalidate_projection(projection)
    plan = _revalidate_plan(render_plan)
    snapshot = _strict_sha256(
        source_snapshot_fingerprint,
        name="context source snapshot",
    )
    policy = _strict_sha256(policy_fingerprint, name="context policy")
    recent_count = _strict_positive_int(
        recent_limit,
        name="context recent limit",
        maximum=64,
    )
    if (
        type(graph_family_id) is not str
        or not graph_family_id
        or plan.source_event_graph_family_id != graph_family_id
        or plan.source_event_snapshot_fingerprint != snapshot
        or plan.source_event_graph_id != current_graph.graph_id
        or plan.source_event_graph_fingerprint != current_graph.graph_fingerprint
        or plan.source_event_projection_fingerprint is None
        or plan.source_event_ids != list(current_projection.selected_event_ids)
        or plan.source_event_graph_id != current_projection.graph_id
        or plan.source_event_graph_fingerprint != current_projection.graph_fingerprint
        or plan.source_event_workspace_scope_fingerprint
        != current_projection.workspace_scope_fingerprint
        or plan.source_event_scope_fingerprint != current_projection.scope_fingerprint
        or inspect_render_plan_source_events(plan, current_projection, snapshot) != "fresh"
    ):
        raise DramaContextMemoryError("context H2 binding is inconsistent")

    selected_ids = tuple(current_projection.selected_event_ids)
    selected_set = set(selected_ids)
    by_id = {item.event_id: item for item in current_graph.events}
    if not selected_set.issubset(by_id):
        raise DramaContextMemoryError("context selection crosses graph membership")
    ordered_selected = sorted(
        (by_id[event_id] for event_id in selected_ids),
        key=lambda item: (item.chronology_order, item.event_id),
    )
    recent_ids = {
        item.event_id for item in ordered_selected[-min(recent_count, len(ordered_selected)) :]
    }

    if summary_event_ids is None:
        summary_ids = set(selected_ids)
    else:
        if (
            isinstance(summary_event_ids, (str, bytes))
            or type(summary_event_ids) not in (list, tuple)
            or len(summary_event_ids) > DRAMA_CONTEXT_MEMORY_MAX_RECORDS
            or any(type(item) is not str for item in summary_event_ids)
            or len(summary_event_ids) != len(set(summary_event_ids))
            or not set(summary_event_ids).issubset(selected_set)
        ):
            raise DramaContextMemoryError("context summary selection is invalid")
        summary_ids = set(summary_event_ids)

    keywords_by_event: dict[str, set[str]] = {event_id: set() for event_id in selected_ids}
    keyword_map = {} if keyword_event_ids is None else keyword_event_ids
    if type(keyword_map) is not dict or len(keyword_map) > DRAMA_CONTEXT_MEMORY_MAX_KEYWORDS:
        raise DramaContextMemoryError("context keyword mapping is invalid")
    seen_keyword_hashes: set[str] = set()
    for keyword, event_ids in keyword_map.items():
        keyword_hash = context_keyword_hash(keyword)
        if keyword_hash in seen_keyword_hashes:
            raise DramaContextMemoryError("context keywords normalize to a duplicate")
        seen_keyword_hashes.add(keyword_hash)
        if (
            isinstance(event_ids, (str, bytes))
            or type(event_ids) not in (list, tuple)
            or len(event_ids) > DRAMA_CONTEXT_MEMORY_MAX_RECORDS
            or any(type(item) is not str for item in event_ids)
            or len(event_ids) != len(set(event_ids))
            or not set(event_ids).issubset(selected_set)
        ):
            raise DramaContextMemoryError("context keyword event selection is invalid")
        for event_id in event_ids:
            keywords_by_event[event_id].add(keyword_hash)

    records: list[DramaContextMemoryRecord] = []
    for event in ordered_selected:
        roles: list[str] = []
        keyword_hashes = sorted(keywords_by_event[event.event_id])
        if keyword_hashes:
            roles.append("keyword")
        if event.event_id in recent_ids:
            roles.append("recent")
        if event.event_id in summary_ids:
            roles.append("summary")
        if not roles:
            continue
        record_payload = {
            "event_id": event.event_id,
            "event_fingerprint": event.event_fingerprint,
            "source_fingerprint": event.source_fingerprint,
            "chronology_order": event.chronology_order,
            "roles": roles,
            "keyword_hashes": keyword_hashes,
        }
        records.append(
            DramaContextMemoryRecord(
                **record_payload,
                record_fingerprint=_canonical_sha256(record_payload),
            )
        )
    if not records or len(records) > DRAMA_CONTEXT_MEMORY_MAX_RECORDS:
        raise DramaContextMemoryError("context memory record count is invalid")

    graph_records = [model_to_dict(item) for item in current_projection.graph_event_records]
    payload = {
        "schema_version": 1,
        "workspace_scope_fingerprint": current_projection.workspace_scope_fingerprint,
        "season_no": plan.season_no,
        "episode_no": plan.episode_no,
        "graph_family_id": graph_family_id,
        "graph_scope_fingerprint": current_projection.scope_fingerprint,
        "source_snapshot_fingerprint": snapshot,
        "graph_id": current_graph.graph_id,
        "graph_fingerprint": current_graph.graph_fingerprint,
        "graph_event_records": graph_records,
        "selected_event_ids": sorted(selected_ids),
        "source_projection_fingerprint": plan.source_event_projection_fingerprint,
        "render_plan_fingerprint": plan.plan_fingerprint,
        "policy_fingerprint": policy,
        "records": [model_to_dict(item) for item in records],
    }
    fingerprint = _canonical_sha256(payload)
    try:
        return DramaContextMemoryCache(
            **payload,
            cache_id=f"dcm_{fingerprint[:24]}",
            cache_fingerprint=fingerprint,
        )
    except (TypeError, ValueError) as exc:
        raise DramaContextMemoryError("context memory cache is invalid") from exc


def query_context_memory(
    cache: DramaContextMemoryCache,
    *,
    keywords: Sequence[str] = (),
    limit: int = 64,
) -> DramaContextMemoryQuery:
    """Return deterministic event IDs; no embedding or network path exists."""

    try:
        if type(cache) is not DramaContextMemoryCache:
            raise TypeError("context cache must be an exact validated model")
        current = DramaContextMemoryCache(**model_to_dict(cache))
    except (TypeError, ValueError) as exc:
        raise DramaContextMemoryError("context memory cache is invalid") from exc
    cap = _strict_positive_int(limit, name="context query limit", maximum=256)
    if (
        isinstance(keywords, (str, bytes))
        or type(keywords) not in (list, tuple)
        or len(keywords) > DRAMA_CONTEXT_MEMORY_MAX_KEYWORDS
    ):
        raise DramaContextMemoryError("context query keywords are invalid")
    query_hashes = [context_keyword_hash(value) for value in keywords]
    if len(query_hashes) != len(set(query_hashes)):
        raise DramaContextMemoryError("context query keywords normalize to a duplicate")
    query_set = set(query_hashes)
    keyword_ids = tuple(
        item.event_id for item in current.records if query_set.intersection(item.keyword_hashes)
    )
    recent_ids = tuple(item.event_id for item in current.records if "recent" in item.roles)
    summary_ids = tuple(item.event_id for item in current.records if "summary" in item.roles)
    combined_list: list[str] = []
    seen: set[str] = set()
    for event_id in (*keyword_ids, *recent_ids, *summary_ids):
        if event_id not in seen:
            seen.add(event_id)
            combined_list.append(event_id)
            if len(combined_list) == cap:
                break
    combined = tuple(combined_list)
    return DramaContextMemoryQuery(
        cache_id=current.cache_id,
        keyword_event_ids=keyword_ids[:cap],
        recent_event_ids=recent_ids[:cap],
        summary_event_ids=summary_ids[:cap],
        combined_event_ids=combined,
    )


def inspect_context_memory_binding(
    cache: DramaContextMemoryCache,
    *,
    graph: DramaEventGraph,
    projection: DramaEventProjection,
    render_plan: RenderPlan,
    graph_family_id: str,
    source_snapshot_fingerprint: str,
    policy_fingerprint: str,
) -> tuple[str, ...]:
    """Return bounded stale reasons; an empty tuple means fresh."""

    try:
        if type(cache) is not DramaContextMemoryCache:
            raise TypeError("context cache must be an exact validated model")
        current_cache = DramaContextMemoryCache(**model_to_dict(cache))
        current_graph = _revalidate_graph(graph)
        current_projection = _revalidate_projection(projection)
        plan = _revalidate_plan(render_plan)
    except (TypeError, ValueError, DramaContextMemoryError) as exc:
        raise DramaContextMemoryError("context memory binding is invalid") from exc
    reasons: list[str] = []
    comparisons = (
        (
            (current_cache.season_no, current_cache.episode_no),
            (plan.season_no, plan.episode_no),
            "episode_scope_mismatch",
        ),
        (current_cache.graph_family_id, graph_family_id, "graph_family_mismatch"),
        (
            current_cache.source_snapshot_fingerprint,
            source_snapshot_fingerprint,
            "source_snapshot_mismatch",
        ),
        (current_cache.graph_id, current_graph.graph_id, "graph_mismatch"),
        (
            current_cache.graph_fingerprint,
            current_graph.graph_fingerprint,
            "graph_mismatch",
        ),
        (
            current_cache.source_projection_fingerprint,
            plan.source_event_projection_fingerprint,
            "source_projection_mismatch",
        ),
        (
            current_cache.render_plan_fingerprint,
            plan.plan_fingerprint,
            "render_plan_mismatch",
        ),
        (current_cache.policy_fingerprint, policy_fingerprint, "policy_mismatch"),
    )
    for actual, expected, reason in comparisons:
        if actual != expected:
            reasons.append(reason)
    if (
        current_cache.workspace_scope_fingerprint
        != current_projection.workspace_scope_fingerprint
        or current_cache.graph_scope_fingerprint != current_projection.scope_fingerprint
        or current_cache.graph_event_records != current_projection.graph_event_records
        or current_cache.selected_event_ids != current_projection.selected_event_ids
        or inspect_render_plan_source_events(
            plan,
            current_projection,
            source_snapshot_fingerprint,
        )
        != "fresh"
    ):
        reasons.append("source_projection_mismatch")
    current_events = {item.event_id: item for item in current_graph.events}
    if any(
        (event := current_events.get(record.event_id)) is None
        or event.event_fingerprint != record.event_fingerprint
        or event.source_fingerprint != record.source_fingerprint
        or event.chronology_order != record.chronology_order
        for record in current_cache.records
    ):
        reasons.append("record_source_mismatch")
    return tuple(dict.fromkeys(reasons))


def context_memory_path(
    workspace: str,
    *,
    season_no: int,
    episode_no: int,
) -> Path:
    season = _strict_positive_int(season_no, name="context season", maximum=999)
    episode = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    if root == paths.ROOT:
        raise DramaContextMemoryError("context memory requires a named workspace")
    return (
        root
        / _CONTEXT_DIRECTORY[0]
        / _CONTEXT_DIRECTORY[1]
        / _CONTEXT_DIRECTORY[2]
        / f"season_{season:02d}"
        / f"episode_{episode:02d}.json"
    )


def _canonical_cache_bytes(cache: DramaContextMemoryCache) -> bytes:
    envelope = {
        "schema_version": 1,
        "artifact_type": "drama_context_memory",
        "cache_id": cache.cache_id,
        "cache_fingerprint": cache.cache_fingerprint,
        "cache": model_to_dict(cache),
    }
    return (
        json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise DramaContextMemoryError("context memory JSON is invalid")
        output[key] = value
    return output


def _reject_json_constant(_value: str) -> None:
    raise DramaContextMemoryError("context memory JSON is invalid")


def _parse_json_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise DramaContextMemoryError("context memory JSON is invalid")
    return number


def _parse_cache_bytes(payload: bytes) -> DramaContextMemoryCache:
    try:
        raw = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_members,
            parse_constant=_reject_json_constant,
            parse_float=_parse_json_float,
        )
    except DramaContextMemoryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise DramaContextMemoryError("context memory JSON is invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "artifact_type",
        "cache_id",
        "cache_fingerprint",
        "cache",
    }:
        raise DramaContextMemoryError("context memory envelope is invalid")
    if (
        type(raw["schema_version"]) is not int
        or raw["schema_version"] != 1
        or raw["artifact_type"] != "drama_context_memory"
        or not isinstance(raw["cache"], dict)
    ):
        raise DramaContextMemoryError("context memory envelope is invalid")
    try:
        cache = DramaContextMemoryCache(**raw["cache"])
    except (TypeError, ValueError) as exc:
        raise DramaContextMemoryError("context memory payload is invalid") from exc
    if (
        raw["cache_id"] != cache.cache_id
        or raw["cache_fingerprint"] != cache.cache_fingerprint
        or payload != _canonical_cache_bytes(cache)
    ):
        raise DramaContextMemoryError("context memory file is noncanonical")
    return cache


def load_context_memory_cache(
    workspace: str,
    *,
    season_no: int,
    episode_no: int,
) -> DramaContextMemoryCache:
    root = paths.workspace_root(workspace)
    path = context_memory_path(
        workspace,
        season_no=season_no,
        episode_no=episode_no,
    )
    try:
        payload = _read_strict_workspace_bytes(
            root,
            path,
            maximum=MAX_CONTEXT_MEMORY_BYTES,
        )
    except FileNotFoundError:
        raise
    except (OSError, ValueError) as exc:
        raise DramaContextMemoryError("context memory cannot be read safely") from exc
    cache = _parse_cache_bytes(payload)
    if cache.workspace_scope_fingerprint != event_graph_scope_fingerprint(workspace):
        raise DramaContextMemoryError("context memory belongs to another workspace")
    if cache.season_no != season_no or cache.episode_no != normalize_episode_no(episode_no):
        raise DramaContextMemoryError("context memory scope is invalid")
    return cache


def _target_token(workspace: str, path: Path) -> tuple[Any, ...]:
    root = paths.workspace_root(workspace)
    try:
        payload = _read_strict_workspace_bytes(
            root,
            path,
            maximum=MAX_CONTEXT_MEMORY_BYTES,
        )
    except FileNotFoundError:
        return ("missing",)
    except (OSError, ValueError):
        return ("invalid",)
    return ("file", len(payload), hashlib.sha256(payload).hexdigest())


def _target_token_at(directory_fd: int, name: str) -> tuple[Any, ...]:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    file_fd: int | None = None
    try:
        file_fd = os.open(name, os.O_RDONLY | nofollow | nonblock, dir_fd=directory_fd)
    except FileNotFoundError:
        return ("missing",)
    except OSError:
        return ("invalid",)
    try:
        info = os.fstat(file_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size <= 0
            or info.st_size > MAX_CONTEXT_MEMORY_BYTES
        ):
            return ("invalid",)
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(file_fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != info.st_size:
            return ("invalid",)
        return ("file", len(payload), hashlib.sha256(payload).hexdigest())
    except OSError:
        return ("invalid",)
    finally:
        if file_fd is not None:
            os.close(file_fd)


def _write_cache(
    workspace: str,
    cache: DramaContextMemoryCache,
    *,
    expected_target_token: tuple[Any, ...],
    precommit_check: Any = None,
) -> Path:
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    if cache.workspace_scope_fingerprint != event_graph_scope_fingerprint(workspace):
        raise DramaContextMemoryError("context memory belongs to another workspace")
    target = context_memory_path(
        workspace,
        season_no=cache.season_no,
        episode_no=cache.episode_no,
    )
    payload = _canonical_cache_bytes(cache)
    if not payload or len(payload) > MAX_CONTEXT_MEMORY_BYTES:
        raise DramaContextMemoryError("context memory exceeds its size limit")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise DramaContextMemoryError("strict no-follow context writes are unavailable")
    directory_fd: int | None = None
    temp_fd: int | None = None
    temp_name = f".{target.name}.tmp.{os.getpid()}.{threading.get_ident()}"
    try:
        directory_fd = os.open(str(root), os.O_RDONLY | directory | nofollow)
        for part in (*_CONTEXT_DIRECTORY, f"season_{cache.season_no:02d}"):
            try:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=directory_fd,
                )
            except FileNotFoundError:
                os.mkdir(part, 0o700, dir_fd=directory_fd)
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=directory_fd,
                )
            os.close(directory_fd)
            directory_fd = next_fd
        if _target_token_at(directory_fd, target.name) != expected_target_token:
            raise DramaContextMemoryError("context memory changed concurrently")
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=directory_fd,
        )
        view = memoryview(payload)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError("short context memory write")
            view = view[written:]
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = None
        if precommit_check is not None:
            precommit_check()
        if _target_token_at(directory_fd, target.name) != expected_target_token:
            raise DramaContextMemoryError("context memory changed concurrently")
        if expected_target_token == ("missing",):
            try:
                os.link(
                    temp_name,
                    target.name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise DramaContextMemoryError(
                    "context memory changed concurrently"
                ) from exc
        else:
            # Replacement is intentionally limited to an explicit caller opt-in
            # while the cooperative workspace flock is held.  The token guard is
            # not claimed to be an OS compare-and-swap against hostile writers.
            os.replace(
                temp_name,
                target.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
        return target
    except DramaContextMemoryError:
        raise
    except OSError as exc:
        raise DramaContextMemoryError("context memory could not be written safely") from exc
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if directory_fd is not None:
            try:
                os.unlink(temp_name, dir_fd=directory_fd)
            except OSError:
                pass
            try:
                os.close(directory_fd)
            except OSError:
                pass


def _load_current_context(workspace: str, *, episode_no: int) -> _CurrentContext:
    inspection = inspect_render_plan(workspace, episode_no=episode_no)
    if inspection.state != "fresh" or inspection.plan is None:
        raise DramaContextMemoryError("current RenderPlan is unavailable")
    plan = inspection.plan
    if (
        plan.source_event_graph_family_id is None
        or plan.source_event_spoiler_boundary is None
        or plan.source_event_allowed_chapter_ids is None
        or plan.source_event_snapshot_fingerprint is None
    ):
        raise DramaContextMemoryError("current RenderPlan has no H2 binding")
    try:
        result = load_production_source_event_graph(
            workspace=workspace,
            graph_family_id=plan.source_event_graph_family_id,
            max_spoiler_boundary=plan.source_event_spoiler_boundary,
        )
        if (
            result.status != "ready"
            or result.graph is None
            or result.source_snapshot_fingerprint is None
        ):
            raise DramaContextMemoryError("current source graph is unavailable")
        projection = select_event_projection(
            result.graph,
            selected_event_ids=plan.source_event_ids,
            allowed_source_chapter_ids=plan.source_event_allowed_chapter_ids,
            max_spoiler_boundary=plan.source_event_spoiler_boundary,
        )
    except (DramaEventGraphError, DramaSourceAdapterError, OSError, TypeError, ValueError) as exc:
        if isinstance(exc, DramaContextMemoryError):
            raise
        raise DramaContextMemoryError("current source graph is invalid") from exc
    if inspect_render_plan_source_events(
        plan,
        projection,
        result.source_snapshot_fingerprint,
    ) != "fresh":
        raise DramaContextMemoryError("current H2 binding is stale")
    return _CurrentContext(
        graph=result.graph,
        projection=projection,
        plan=plan,
        graph_family_id=plan.source_event_graph_family_id,
        source_snapshot_fingerprint=result.source_snapshot_fingerprint,
        policy_fingerprint=load_default_context_policy_fingerprint(),
    )


def create_context_memory_cache(
    workspace: str,
    *,
    episode_no: int = 1,
    recent_limit: int = 8,
    summary_event_ids: Sequence[str] | None = None,
    keyword_event_ids: Mapping[str, Sequence[str]] | None = None,
    replace_stale: bool = False,
) -> DramaContextMemoryCache:
    """Create/refresh the current episode cache under one workspace lock."""

    number = normalize_episode_no(episode_no)
    if type(replace_stale) is not bool:
        raise DramaContextMemoryError("replace_stale must be bool")
    try:
        with use_workspace(workspace), acquire_write_lock(source="drama-context-memory"):
            current = _load_current_context(workspace, episode_no=number)
            cache = build_context_memory_cache(
                graph=current.graph,
                projection=current.projection,
                render_plan=current.plan,
                graph_family_id=current.graph_family_id,
                source_snapshot_fingerprint=current.source_snapshot_fingerprint,
                policy_fingerprint=current.policy_fingerprint,
                recent_limit=recent_limit,
                summary_event_ids=summary_event_ids,
                keyword_event_ids=keyword_event_ids,
            )
            target = context_memory_path(
                workspace,
                season_no=cache.season_no,
                episode_no=number,
            )
            token = _target_token(workspace, target)
            if token[0] == "file":
                existing = load_context_memory_cache(
                    workspace,
                    season_no=cache.season_no,
                    episode_no=number,
                )
                if existing == cache:
                    latest = _load_current_context(workspace, episode_no=number)
                    if latest.binding_token != current.binding_token:
                        raise DramaContextMemoryError(
                            "context memory source changed before replay"
                        )
                    return existing
                if not replace_stale:
                    raise DramaContextMemoryError(
                        "context memory differs; explicit replacement is required"
                    )
            elif token[0] == "invalid":
                raise DramaContextMemoryError("context memory target is invalid")
            expected_binding = current.binding_token

            def precommit() -> None:
                latest = _load_current_context(workspace, episode_no=number)
                if latest.binding_token != expected_binding:
                    raise DramaContextMemoryError(
                        "context memory source changed before commit"
                    )

            _write_cache(
                workspace,
                cache,
                expected_target_token=token,
                precommit_check=precommit,
            )
            return cache
    except WorkspaceLocked as exc:
        raise DramaContextMemoryError("context memory workspace is busy") from exc
    except DramaContextMemoryError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise DramaContextMemoryError("context memory creation was rejected") from exc


def inspect_context_memory_cache(
    workspace: str,
    *,
    episode_no: int = 1,
    keywords: Sequence[str] = (),
    limit: int = 64,
) -> DramaContextMemoryInspection:
    """Inspect current cache without mutating any canonical or cache artifact."""

    number = normalize_episode_no(episode_no)
    try:
        plan_inspection = inspect_render_plan(workspace, episode_no=number)
        season_no = (
            plan_inspection.plan.season_no
            if plan_inspection.plan is not None
            else 1
        )
        cache = load_context_memory_cache(
            workspace,
            season_no=season_no,
            episode_no=number,
        )
    except FileNotFoundError:
        return DramaContextMemoryInspection("missing", ("missing",))
    except (DramaContextMemoryError, OSError, TypeError, ValueError):
        return DramaContextMemoryInspection("invalid", ("cache_invalid",))
    try:
        current = _load_current_context(workspace, episode_no=number)
    except (DramaContextMemoryError, OSError, TypeError, ValueError):
        return DramaContextMemoryInspection(
            "blocked_source",
            ("current_source_unavailable",),
            cache,
        )
    reasons = inspect_context_memory_binding(
        cache,
        graph=current.graph,
        projection=current.projection,
        render_plan=current.plan,
        graph_family_id=current.graph_family_id,
        source_snapshot_fingerprint=current.source_snapshot_fingerprint,
        policy_fingerprint=current.policy_fingerprint,
    )
    if reasons:
        return DramaContextMemoryInspection("stale", reasons, cache)
    try:
        query = query_context_memory(cache, keywords=keywords, limit=limit)
    except DramaContextMemoryError:
        return DramaContextMemoryInspection("invalid", ("query_invalid",), cache)
    return DramaContextMemoryInspection("fresh", (), cache, query)
