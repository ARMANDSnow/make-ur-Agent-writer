"""Stage H1 typed adaptation event graph and immutable local persistence.

The graph stores only caller-supplied structured facts and source identities.
It never reads source prose, infers causality from chapter adjacency, calls an
LLM/embedding provider, or mutates the creative episode/RenderPlan.
"""

from __future__ import annotations

import json
import os
import re
import stat
import threading
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import paths
from .drama_schemas import (
    DRAMA_EVENT_MAX_FACTS,
    DRAMA_EVENT_MAX_SOURCE_CHAPTERS,
    DRAMA_EVENT_GRAPH_MAX_EVENTS,
    DramaEventFact,
    DramaEventGraph,
    DramaEventProjection,
    DramaEventSourceKind,
    DramaEventSourceRef,
    DramaSourceEvent,
    _canonical_sha256,
    _drama_event_graph_identity_payload,
)
from .drama_store import (
    _read_strict_workspace_bytes,
    _validate_render_workspace_root,
)
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_DRAMA_EVENT_GRAPH_BYTES = 8 * 1024 * 1024
MAX_DRAMA_EVENT_SELECTION = 256
_GRAPH_ID_RE = re.compile(r"^deg_[0-9a-f]{24}$")
_GRAPH_DIRECTORY = ("outputs", "drama", "event_graphs")


class DramaEventGraphError(ValueError):
    """Bounded public event-graph error without source text or local paths."""


def event_graph_scope_fingerprint(workspace: str) -> str:
    """Return the opaque workspace-local scope required by the durable store."""

    if not isinstance(workspace, str) or workspace != workspace.strip() or not workspace:
        raise DramaEventGraphError("event graph workspace is invalid")
    root = paths.workspace_root(workspace)
    if root == paths.ROOT:
        raise DramaEventGraphError("event graph requires a named workspace")
    return _canonical_sha256(
        {
            "artifact_type": "drama_event_graph_scope",
            "schema_version": 1,
            "workspace": root.name,
        }
    )


def _strict_sha256(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise DramaEventGraphError(f"{name} must be a sha256 fingerprint")
    return value


def _strict_int(value: Any, *, name: str, minimum: int, maximum: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or value > maximum
    ):
        raise DramaEventGraphError(f"{name} must be a strict bounded integer")
    return value


def _sorted_unique_ids(
    values: Iterable[str],
    *,
    name: str,
    maximum: int,
    pattern: str = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}",
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(
        values, (list, tuple, set, frozenset)
    ):
        raise DramaEventGraphError(f"{name} must be a bounded collection")
    if len(values) > maximum:
        raise DramaEventGraphError(f"{name} exceeds its limit")
    items = list(values)
    if len(items) > maximum or any(
        not isinstance(item, str) or re.fullmatch(pattern, item) is None
        for item in items
    ):
        raise DramaEventGraphError(f"{name} contains an invalid id")
    if len(items) != len(set(items)):
        raise DramaEventGraphError(f"{name} contains duplicate ids")
    return tuple(sorted(items))


def build_event_fact(
    *,
    kind: str,
    subject_id: str,
    predicate: str,
    object_id: str | None = None,
    value: str | None = None,
) -> DramaEventFact:
    """Build one content-addressed typed precondition/effect."""

    if kind not in {"precondition", "effect"}:
        raise DramaEventGraphError("event fact kind is invalid")
    if predicate not in {
        "state",
        "location",
        "ownership",
        "relationship",
        "knowledge",
        "availability",
        "custom",
    }:
        raise DramaEventGraphError("event fact predicate is invalid")
    atom_pattern = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}"
    if (
        not isinstance(subject_id, str)
        or re.fullmatch(atom_pattern, subject_id) is None
        or (
            object_id is not None
            and (
                not isinstance(object_id, str)
                or re.fullmatch(atom_pattern, object_id) is None
            )
        )
        or (
            value is not None
            and (
                not isinstance(value, str)
                or re.fullmatch(atom_pattern, value) is None
            )
        )
        or (object_id is None and value is None)
    ):
        raise DramaEventGraphError("event fact atoms are invalid")
    payload = {
        "kind": kind,
        "subject_id": subject_id,
        "predicate": predicate,
        "object_id": object_id,
        "value": value,
    }
    fingerprint = _canonical_sha256(payload)
    try:
        return DramaEventFact(
            fact_id=f"def_{fingerprint[:24]}",
            fact_fingerprint=fingerprint,
            **payload,
        )
    except (TypeError, ValueError) as exc:
        raise DramaEventGraphError("event fact is invalid") from exc


def _revalidate_fact(value: DramaEventFact | Mapping[str, Any]) -> DramaEventFact:
    if isinstance(value, DramaEventFact):
        value = model_to_dict(value)
    if not isinstance(value, Mapping):
        raise DramaEventGraphError("event fact must be an object")
    try:
        return DramaEventFact(**dict(value))
    except (TypeError, ValueError) as exc:
        raise DramaEventGraphError("event fact is invalid") from exc


def _source_refs(
    values: Sequence[DramaEventSourceRef | Mapping[str, Any]],
) -> tuple[DramaEventSourceRef, ...]:
    if not isinstance(values, (list, tuple)):
        raise DramaEventGraphError("source chapters must be a list or tuple")
    if len(values) > DRAMA_EVENT_MAX_SOURCE_CHAPTERS:
        raise DramaEventGraphError("source chapters exceed their limit")
    refs: list[DramaEventSourceRef] = []
    for value in values:
        if isinstance(value, DramaEventSourceRef):
            value = model_to_dict(value)
        if not isinstance(value, Mapping):
            raise DramaEventGraphError("source chapter ref must be an object")
        try:
            refs.append(DramaEventSourceRef(**dict(value)))
        except (TypeError, ValueError) as exc:
            raise DramaEventGraphError("source chapter ref is invalid") from exc
    refs.sort(key=lambda item: (item.chapter_no, item.chapter_id))
    keys = [(item.chapter_no, item.chapter_id) for item in refs]
    if len(keys) != len(set(keys)):
        raise DramaEventGraphError("source chapter refs must be unique")
    return tuple(refs)


def _event_payload(
    *,
    workspace_scope_fingerprint: str,
    scope_fingerprint: str,
    source_kind: DramaEventSourceKind,
    adaptation_status: str,
    chronology_order: int,
    source_chapters: tuple[DramaEventSourceRef, ...],
    participant_ids: Iterable[str],
    scene_ids: Iterable[str],
    prop_ids: Iterable[str],
    clue_ids: Iterable[str],
    preconditions: Sequence[DramaEventFact | Mapping[str, Any]],
    effects: Sequence[DramaEventFact | Mapping[str, Any]],
    causal_parent_ids: Iterable[str],
    causality_complete: bool,
    lineage_operation: str,
    lineage_parent_event_ids: Iterable[str],
) -> dict[str, Any]:
    workspace_scope = _strict_sha256(
        workspace_scope_fingerprint,
        name="event workspace scope",
    )
    scope = _strict_sha256(scope_fingerprint, name="event scope")
    if workspace_scope == scope:
        raise DramaEventGraphError(
            "workspace and event graph family scopes must differ"
        )
    order = _strict_int(
        chronology_order,
        name="event chronology",
        minimum=1,
        maximum=1_000_000,
    )
    if type(causality_complete) is not bool:
        raise DramaEventGraphError("causality_complete must be bool")
    if not isinstance(preconditions, (list, tuple)) or not isinstance(
        effects, (list, tuple)
    ):
        raise DramaEventGraphError("event facts must be lists or tuples")
    if len(preconditions) + len(effects) > DRAMA_EVENT_MAX_FACTS:
        raise DramaEventGraphError("event facts exceed their total limit")
    before = sorted(
        (_revalidate_fact(item) for item in preconditions),
        key=lambda item: item.fact_id,
    )
    after = sorted(
        (_revalidate_fact(item) for item in effects),
        key=lambda item: item.fact_id,
    )
    source_payload = [model_to_dict(item) for item in source_chapters]
    return {
        "schema_version": 1,
        "workspace_scope_fingerprint": workspace_scope,
        "scope_fingerprint": scope,
        "source_kind": source_kind,
        "adaptation_status": adaptation_status,
        "chronology_order": order,
        "source_chapters": source_payload,
        "source_fingerprint": _canonical_sha256(source_payload),
        "spoiler_boundary": (
            max(item.chapter_no for item in source_chapters)
            if source_chapters
            else None
        ),
        "participant_ids": _sorted_unique_ids(
            participant_ids, name="participant ids", maximum=64
        ),
        "scene_ids": _sorted_unique_ids(
            scene_ids, name="scene ids", maximum=32
        ),
        "prop_ids": _sorted_unique_ids(prop_ids, name="prop ids", maximum=64),
        "clue_ids": _sorted_unique_ids(clue_ids, name="clue ids", maximum=64),
        "preconditions": [model_to_dict(item) for item in before],
        "effects": [model_to_dict(item) for item in after],
        "causal_parent_ids": _sorted_unique_ids(
            causal_parent_ids,
            name="causal parent ids",
            maximum=64,
            pattern=r"dse_[0-9a-f]{24}",
        ),
        "causality_complete": causality_complete,
        "lineage_operation": lineage_operation,
        "lineage_parent_event_ids": _sorted_unique_ids(
            lineage_parent_event_ids,
            name="lineage parent event ids",
            maximum=64,
            pattern=r"dse_[0-9a-f]{24}",
        ),
    }


def build_source_event(
    *,
    workspace_scope_fingerprint: str,
    scope_fingerprint: str,
    source_kind: DramaEventSourceKind,
    adaptation_status: str,
    chronology_order: int,
    source_chapters: Sequence[DramaEventSourceRef | Mapping[str, Any]] = (),
    participant_ids: Iterable[str] = (),
    scene_ids: Iterable[str] = (),
    prop_ids: Iterable[str] = (),
    clue_ids: Iterable[str] = (),
    preconditions: Sequence[DramaEventFact | Mapping[str, Any]] = (),
    effects: Sequence[DramaEventFact | Mapping[str, Any]] = (),
    causal_parent_ids: Iterable[str] = (),
    causality_complete: bool = False,
    lineage_operation: str = "original",
    lineage_parent_event_ids: Iterable[str] = (),
) -> DramaSourceEvent:
    """Build an immutable event from explicit structured facts only."""

    refs = _source_refs(source_chapters)
    payload = _event_payload(
        workspace_scope_fingerprint=workspace_scope_fingerprint,
        scope_fingerprint=scope_fingerprint,
        source_kind=source_kind,
        adaptation_status=adaptation_status,
        chronology_order=chronology_order,
        source_chapters=refs,
        participant_ids=participant_ids,
        scene_ids=scene_ids,
        prop_ids=prop_ids,
        clue_ids=clue_ids,
        preconditions=preconditions,
        effects=effects,
        causal_parent_ids=causal_parent_ids,
        causality_complete=causality_complete,
        lineage_operation=lineage_operation,
        lineage_parent_event_ids=lineage_parent_event_ids,
    )
    fingerprint = _canonical_sha256(payload)
    try:
        return DramaSourceEvent(
            event_id=f"dse_{fingerprint[:24]}",
            event_fingerprint=fingerprint,
            **payload,
        )
    except (TypeError, ValueError) as exc:
        raise DramaEventGraphError("source event is invalid") from exc


def _revalidate_event(value: DramaSourceEvent | Mapping[str, Any]) -> DramaSourceEvent:
    if isinstance(value, DramaSourceEvent):
        value = model_to_dict(value)
    if not isinstance(value, Mapping):
        raise DramaEventGraphError("source event must be an object")
    try:
        return DramaSourceEvent(**dict(value))
    except (TypeError, ValueError) as exc:
        raise DramaEventGraphError("source event is invalid") from exc


def build_event_graph(
    *,
    workspace_scope_fingerprint: str,
    scope_fingerprint: str,
    events: Sequence[DramaSourceEvent | Mapping[str, Any]],
) -> DramaEventGraph:
    """Build and fully validate one immutable causal/lineage graph."""

    workspace_scope = _strict_sha256(
        workspace_scope_fingerprint,
        name="workspace scope",
    )
    scope = _strict_sha256(scope_fingerprint, name="graph family scope")
    if workspace_scope == scope:
        raise DramaEventGraphError("workspace and graph family scopes must differ")
    if not isinstance(events, (list, tuple)) or not events:
        raise DramaEventGraphError("event graph must contain events")
    if len(events) > DRAMA_EVENT_GRAPH_MAX_EVENTS:
        raise DramaEventGraphError("event graph exceeds its event limit")
    validated = sorted(
        (_revalidate_event(item) for item in events),
        key=lambda item: (item.chronology_order, item.event_id),
    )
    if any(
        item.workspace_scope_fingerprint != workspace_scope
        for item in validated
    ):
        raise DramaEventGraphError("event belongs to another workspace scope")
    records = [
        {
            "chronology_order": item.chronology_order,
            "event_id": item.event_id,
            "event_fingerprint": item.event_fingerprint,
        }
        for item in validated
    ]
    identity_payload = _drama_event_graph_identity_payload(
        workspace_scope_fingerprint=workspace_scope,
        scope_fingerprint=scope,
        records=records,
    )
    fingerprint = _canonical_sha256(identity_payload)
    try:
        return DramaEventGraph(
            graph_id=f"deg_{fingerprint[:24]}",
            graph_fingerprint=fingerprint,
            schema_version=1,
            workspace_scope_fingerprint=workspace_scope,
            scope_fingerprint=scope,
            events=[model_to_dict(item) for item in validated],
        )
    except (TypeError, ValueError) as exc:
        raise DramaEventGraphError("event graph is invalid") from exc


def _revalidate_graph(value: DramaEventGraph | Mapping[str, Any]) -> DramaEventGraph:
    if isinstance(value, DramaEventGraph):
        value = model_to_dict(value)
    if not isinstance(value, Mapping):
        raise DramaEventGraphError("event graph must be an object")
    try:
        return DramaEventGraph(**dict(value))
    except (TypeError, ValueError) as exc:
        raise DramaEventGraphError("event graph is invalid") from exc


def _fact_union(events: Sequence[DramaSourceEvent], field: str) -> list[DramaEventFact]:
    by_id: dict[str, DramaEventFact] = {}
    for event in events:
        for fact in getattr(event, field):
            previous = by_id.setdefault(fact.fact_id, fact)
            if previous != fact:
                raise DramaEventGraphError("event fact identity is ambiguous")
    return [by_id[key] for key in sorted(by_id)]


def _source_union(events: Sequence[DramaSourceEvent]) -> tuple[DramaEventSourceRef, ...]:
    by_id: dict[str, DramaEventSourceRef] = {}
    for event in events:
        for source in event.source_chapters:
            previous = by_id.setdefault(source.chapter_id, source)
            if previous != source:
                raise DramaEventGraphError("event source identity is ambiguous")
    return tuple(
        sorted(by_id.values(), key=lambda item: (item.chapter_no, item.chapter_id))
    )


def merge_source_events(
    graph: DramaEventGraph,
    *,
    event_ids: Sequence[str],
    chronology_order: int | None = None,
) -> tuple[DramaEventGraph, DramaSourceEvent]:
    """Append one merged event while preserving all typed facts/provenance."""

    current = _revalidate_graph(graph)
    ids = _sorted_unique_ids(
        event_ids,
        name="merge event ids",
        maximum=64,
        pattern=r"dse_[0-9a-f]{24}",
    )
    if len(ids) < 2:
        raise DramaEventGraphError("merge requires at least two events")
    by_id = {item.event_id: item for item in current.events}
    try:
        selected = [by_id[item] for item in ids]
    except KeyError as exc:
        raise DramaEventGraphError("merge references an unknown event") from exc
    if any(item.adaptation_status == "omitted" for item in selected):
        raise DramaEventGraphError("omitted event cannot be merged")
    source_kinds = {item.source_kind for item in selected}
    if source_kinds == {"invented"}:
        source_kind: DramaEventSourceKind = "invented"
    elif source_kinds == {"source_derived"}:
        source_kind = "source_derived"
    else:
        source_kind = "mixed"
    source_chapters = _source_union(selected)
    causal_parents = set().union(
        *(set(item.causal_parent_ids) for item in selected)
    ) - set(ids)
    order = (
        max(item.chronology_order for item in selected)
        if chronology_order is None
        else chronology_order
    )
    merged = build_source_event(
        workspace_scope_fingerprint=current.workspace_scope_fingerprint,
        scope_fingerprint=current.scope_fingerprint,
        source_kind=source_kind,
        adaptation_status="merged",
        chronology_order=order,
        source_chapters=source_chapters,
        participant_ids=set().union(
            *(set(item.participant_ids) for item in selected)
        ),
        scene_ids=set().union(*(set(item.scene_ids) for item in selected)),
        prop_ids=set().union(*(set(item.prop_ids) for item in selected)),
        clue_ids=set().union(*(set(item.clue_ids) for item in selected)),
        preconditions=_fact_union(selected, "preconditions"),
        effects=_fact_union(selected, "effects"),
        causal_parent_ids=causal_parents,
        causality_complete=all(item.causality_complete for item in selected),
        lineage_operation="merged",
        lineage_parent_event_ids=ids,
    )
    if merged.event_id in by_id:
        previous = by_id[merged.event_id]
        if previous != merged:
            raise DramaEventGraphError("merged event identity collided")
        return current, previous
    updated = build_event_graph(
        workspace_scope_fingerprint=current.workspace_scope_fingerprint,
        scope_fingerprint=current.scope_fingerprint,
        events=[*current.events, merged],
    )
    return updated, merged


def split_source_event(
    graph: DramaEventGraph,
    *,
    event_id: str,
    partitions: Sequence[Mapping[str, Any]],
) -> tuple[DramaEventGraph, tuple[DramaSourceEvent, ...]]:
    """Split one event by an exact partition of its existing typed facts."""

    current = _revalidate_graph(graph)
    if not isinstance(event_id, str) or re.fullmatch(r"dse_[0-9a-f]{24}", event_id) is None:
        raise DramaEventGraphError("split event id is invalid")
    parent = next((item for item in current.events if item.event_id == event_id), None)
    if parent is None:
        raise DramaEventGraphError("split references an unknown event")
    if parent.adaptation_status == "omitted":
        raise DramaEventGraphError("omitted event cannot be split")
    if not isinstance(partitions, (list, tuple)) or not 2 <= len(partitions) <= 16:
        raise DramaEventGraphError("split requires two to sixteen partitions")
    pre_by_id = {item.fact_id: item for item in parent.preconditions}
    effect_by_id = {item.fact_id: item for item in parent.effects}
    expected_pre = set(pre_by_id)
    expected_effect = set(effect_by_id)
    allocated_pre: list[str] = []
    allocated_effect: list[str] = []
    children: list[DramaSourceEvent] = []
    for raw in partitions:
        if not isinstance(raw, Mapping) or set(raw) - {
            "precondition_fact_ids",
            "effect_fact_ids",
            "chronology_order",
        }:
            raise DramaEventGraphError("split partition is invalid")
        pre_ids = _sorted_unique_ids(
            raw.get("precondition_fact_ids", ()),
            name="split precondition fact ids",
            maximum=64,
            pattern=r"def_[0-9a-f]{24}",
        )
        effect_ids = _sorted_unique_ids(
            raw.get("effect_fact_ids", ()),
            name="split effect fact ids",
            maximum=64,
            pattern=r"def_[0-9a-f]{24}",
        )
        if not pre_ids and not effect_ids:
            raise DramaEventGraphError("split partition must contain a fact")
        if not set(pre_ids).issubset(expected_pre) or not set(effect_ids).issubset(
            expected_effect
        ):
            raise DramaEventGraphError("split partition references an unknown fact")
        order = raw.get("chronology_order", parent.chronology_order)
        child = build_source_event(
            workspace_scope_fingerprint=current.workspace_scope_fingerprint,
            scope_fingerprint=current.scope_fingerprint,
            source_kind=parent.source_kind,
            adaptation_status="split",
            chronology_order=order,
            source_chapters=parent.source_chapters,
            participant_ids=parent.participant_ids,
            scene_ids=parent.scene_ids,
            prop_ids=parent.prop_ids,
            clue_ids=parent.clue_ids,
            preconditions=[pre_by_id[item] for item in pre_ids],
            effects=[effect_by_id[item] for item in effect_ids],
            causal_parent_ids=parent.causal_parent_ids,
            causality_complete=parent.causality_complete,
            lineage_operation="split",
            lineage_parent_event_ids=(parent.event_id,),
        )
        allocated_pre.extend(pre_ids)
        allocated_effect.extend(effect_ids)
        children.append(child)
    if (
        set(allocated_pre) != expected_pre
        or len(allocated_pre) != len(set(allocated_pre))
        or set(allocated_effect) != expected_effect
        or len(allocated_effect) != len(set(allocated_effect))
    ):
        raise DramaEventGraphError("split partitions must exactly cover parent facts")
    child_ids = [item.event_id for item in children]
    if len(child_ids) != len(set(child_ids)):
        raise DramaEventGraphError("split produced duplicate child events")
    existing = {item.event_id: item for item in current.events}
    additions: list[DramaSourceEvent] = []
    for child in children:
        previous = existing.get(child.event_id)
        if previous is not None and previous != child:
            raise DramaEventGraphError("split event identity collided")
        if previous is None:
            additions.append(child)
    if not additions:
        return current, tuple(children)
    updated = build_event_graph(
        workspace_scope_fingerprint=current.workspace_scope_fingerprint,
        scope_fingerprint=current.scope_fingerprint,
        events=[*current.events, *additions],
    )
    return updated, tuple(children)


def select_event_projection(
    graph: DramaEventGraph,
    *,
    selected_event_ids: Sequence[str],
    allowed_source_chapter_ids: Sequence[str],
    max_spoiler_boundary: int,
) -> DramaEventProjection:
    """Return a full causal+lineage closure or reject the selection entirely."""

    current = _revalidate_graph(graph)
    selected = _sorted_unique_ids(
        selected_event_ids,
        name="selected event ids",
        maximum=MAX_DRAMA_EVENT_SELECTION,
        pattern=r"dse_[0-9a-f]{24}",
    )
    if not selected:
        raise DramaEventGraphError("event selection must not be empty")
    allowed = _sorted_unique_ids(
        allowed_source_chapter_ids,
        name="allowed source chapter ids",
        maximum=1000,
    )
    boundary = _strict_int(
        max_spoiler_boundary,
        name="maximum spoiler boundary",
        minimum=1,
        maximum=100_000,
    )
    by_id = {item.event_id: item for item in current.events}
    if not set(selected).issubset(by_id):
        raise DramaEventGraphError("event selection references an unknown event")
    if any(by_id[event_id].adaptation_status == "omitted" for event_id in selected):
        raise DramaEventGraphError("omitted event cannot be selected")
    included: set[str] = set()
    pending = list(selected)
    while pending:
        event_id = pending.pop()
        if event_id in included:
            continue
        event = by_id[event_id]
        included.add(event_id)
        if len(included) > DRAMA_EVENT_GRAPH_MAX_EVENTS:
            raise DramaEventGraphError("event selection closure exceeds its limit")
        pending.extend(event.causal_parent_ids)
        pending.extend(event.lineage_parent_event_ids)
    allowed_set = set(allowed)
    events = [
        item
        for item in current.events
        if item.event_id in included
    ]
    if any(item.adaptation_status == "omitted" for item in events):
        raise DramaEventGraphError("event selection closure contains an omitted event")
    for event in events:
        if (
            event.spoiler_boundary is not None
            and event.spoiler_boundary > boundary
        ):
            raise DramaEventGraphError("event selection crosses the spoiler boundary")
        if any(
            source.chapter_id not in allowed_set
            or source.chapter_no > boundary
            for source in event.source_chapters
        ):
            raise DramaEventGraphError("event selection contains a disallowed source")
    payload = {
        "schema_version": 1,
        "graph_id": current.graph_id,
        "graph_fingerprint": current.graph_fingerprint,
        "workspace_scope_fingerprint": current.workspace_scope_fingerprint,
        "scope_fingerprint": current.scope_fingerprint,
        "graph_event_records": [
            {
                "chronology_order": item.chronology_order,
                "event_id": item.event_id,
                "event_fingerprint": item.event_fingerprint,
            }
            for item in current.events
        ],
        "selected_event_ids": list(selected),
        "included_event_ids": [item.event_id for item in events],
        "allowed_source_chapter_ids": list(allowed),
        "max_spoiler_boundary": boundary,
        "events": [model_to_dict(item) for item in events],
    }
    payload["projection_fingerprint"] = _canonical_sha256(payload)
    try:
        return DramaEventProjection(**payload)
    except (TypeError, ValueError) as exc:
        raise DramaEventGraphError("event projection is invalid") from exc


def event_graph_path(workspace: str, graph_id: str) -> Path:
    if not isinstance(graph_id, str) or _GRAPH_ID_RE.fullmatch(graph_id) is None:
        raise DramaEventGraphError("event graph id is invalid")
    return (
        paths.workspace_root(workspace)
        / _GRAPH_DIRECTORY[0]
        / _GRAPH_DIRECTORY[1]
        / _GRAPH_DIRECTORY[2]
        / f"{graph_id}.json"
    )


def _graph_envelope(graph: DramaEventGraph) -> dict[str, Any]:
    return {
        "artifact_type": "drama_event_graph",
        "graph": model_to_dict(graph),
        "graph_fingerprint": graph.graph_fingerprint,
        "graph_id": graph.graph_id,
        "schema_version": 1,
    }


def _canonical_graph_bytes(graph: DramaEventGraph) -> bytes:
    payload = (
        json.dumps(
            _graph_envelope(graph),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if len(payload) > MAX_DRAMA_EVENT_GRAPH_BYTES:
        raise DramaEventGraphError("event graph exceeds its byte limit")
    return payload


def _parse_graph_bytes(payload: bytes, *, expected_graph_id: str) -> DramaEventGraph:
    try:
        text = payload.decode("utf-8")
        raw = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_members,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise DramaEventGraphError("event graph file is invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "artifact_type",
        "graph",
        "graph_fingerprint",
        "graph_id",
        "schema_version",
    }:
        raise DramaEventGraphError("event graph envelope is invalid")
    if (
        raw["schema_version"] != 1
        or type(raw["schema_version"]) is not int
        or raw["artifact_type"] != "drama_event_graph"
        or raw["graph_id"] != expected_graph_id
        or not isinstance(raw["graph"], dict)
    ):
        raise DramaEventGraphError("event graph envelope is invalid")
    try:
        graph = DramaEventGraph(**raw["graph"])
    except (TypeError, ValueError) as exc:
        raise DramaEventGraphError("event graph payload is invalid") from exc
    if (
        graph.graph_id != raw["graph_id"]
        or graph.graph_fingerprint != raw["graph_fingerprint"]
        or payload != _canonical_graph_bytes(graph)
    ):
        raise DramaEventGraphError("event graph file is noncanonical")
    return graph


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("duplicate JSON member")
        output[key] = value
    return output


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def load_event_graph(workspace: str, graph_id: str) -> DramaEventGraph:
    root = paths.workspace_root(workspace)
    path = event_graph_path(workspace, graph_id)
    try:
        payload = _read_strict_workspace_bytes(
            root,
            path,
            maximum=MAX_DRAMA_EVENT_GRAPH_BYTES,
        )
    except FileNotFoundError:
        raise
    except (OSError, ValueError) as exc:
        raise DramaEventGraphError("event graph cannot be read safely") from exc
    graph = _parse_graph_bytes(payload, expected_graph_id=graph_id)
    if graph.workspace_scope_fingerprint != event_graph_scope_fingerprint(workspace):
        raise DramaEventGraphError("event graph belongs to another workspace scope")
    return graph


def _read_target_at(directory_fd: int, name: str) -> bytes | None:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    file_fd: int | None = None
    try:
        file_fd = os.open(
            name,
            os.O_RDONLY | nofollow | nonblock,
            dir_fd=directory_fd,
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise DramaEventGraphError("event graph target cannot be read safely") from exc
    try:
        info = os.fstat(file_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size <= 0
            or info.st_size > MAX_DRAMA_EVENT_GRAPH_BYTES
        ):
            raise DramaEventGraphError("event graph target shape is invalid")
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
            raise DramaEventGraphError("event graph target changed while reading")
        return payload
    except OSError as exc:
        raise DramaEventGraphError("event graph target cannot be read safely") from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)


def _write_graph_create_once(workspace: str, graph: DramaEventGraph) -> Path:
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    if graph.workspace_scope_fingerprint != event_graph_scope_fingerprint(workspace):
        raise DramaEventGraphError("event graph belongs to another workspace scope")
    target = event_graph_path(workspace, graph.graph_id)
    payload = _canonical_graph_bytes(graph)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory_flag is None:
        raise DramaEventGraphError("strict no-follow writes are unavailable")
    directory_fd: int | None = None
    temp_fd: int | None = None
    temp_name = f".{graph.graph_id}.tmp.{os.getpid()}.{threading.get_ident()}"
    target_name = target.name
    try:
        directory_fd = os.open(str(root), os.O_RDONLY | directory_flag | nofollow)
        for part in _GRAPH_DIRECTORY:
            try:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory_flag | nofollow,
                    dir_fd=directory_fd,
                )
            except FileNotFoundError:
                os.mkdir(part, 0o700, dir_fd=directory_fd)
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory_flag | nofollow,
                    dir_fd=directory_fd,
                )
            os.close(directory_fd)
            directory_fd = next_fd
        existing = _read_target_at(directory_fd, target_name)
        if existing is not None:
            if existing != payload:
                raise DramaEventGraphError("event graph identity already has other bytes")
            _parse_graph_bytes(existing, expected_graph_id=graph.graph_id)
            return target
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
                raise OSError("short event graph write")
            view = view[written:]
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = None
        try:
            os.link(
                temp_name,
                target_name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            existing = _read_target_at(directory_fd, target_name)
            if existing != payload:
                raise DramaEventGraphError("event graph changed concurrently")
        committed = _read_target_at(directory_fd, target_name)
        if committed != payload:
            raise DramaEventGraphError("event graph commit cannot be verified")
        return target
    except DramaEventGraphError:
        raise
    except OSError as exc:
        raise DramaEventGraphError("event graph could not be written safely") from exc
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


def save_event_graph(workspace: str, graph: DramaEventGraph) -> Path:
    """Persist exact canonical bytes once; identical replay is idempotent."""

    try:
        validated = _revalidate_graph(graph)
        with use_workspace(workspace), acquire_write_lock(source="drama-event-graph"):
            return _write_graph_create_once(workspace, validated)
    except WorkspaceLocked as exc:
        raise DramaEventGraphError("event graph workspace is busy") from exc
    except DramaEventGraphError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise DramaEventGraphError("event graph save was rejected") from exc
