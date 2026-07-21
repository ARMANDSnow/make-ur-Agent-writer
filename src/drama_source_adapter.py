"""Stage H2 adapter from bounded novel state snapshots to the H1 event graph.

The adapter consumes caller-supplied bytes so authority and filesystem policy stay
with the caller.  Source prose is used only while hashing/validating the snapshot;
the returned graph contains opaque ids and hashes, never summary or chapter text.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from . import paths
from .drama_event_graph import (
    DramaEventGraphError,
    build_event_fact,
    build_event_graph,
    build_source_event,
    event_graph_scope_fingerprint,
)
from .drama_schemas import (
    DramaEventGraph,
    _canonical_sha256,
    drama_event_graph_family_scope_fingerprint,
)
from .drama_store import _read_strict_workspace_bytes, _validate_render_workspace_root
from .entity_advance import parse_chapter_anchor
from .web.workspace_ctx import use_workspace


MAX_SOURCE_SNAPSHOT_BYTES = 4 * 1024 * 1024
MAX_SOURCE_CHAPTERS = 1000
MAX_SOURCE_ENTITIES = 1000
MAX_SOURCE_RELATIONSHIPS = 5000
MAX_TIMELINE_ENTRIES = 100
_ATOM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_CHAPTER_KEYS = frozenset(
    {
        "chapter_id",
        "chapter_no",
        "summary",
        "key_events",
        "ending_state",
        "text_snippet",
    }
)


class DramaSourceAdapterError(ValueError):
    """Bounded adapter error that never includes source text or local paths."""


@dataclass(frozen=True)
class DramaSourceAdapterResult:
    status: Literal["ready", "insufficient_source"]
    graph: DramaEventGraph | None
    source_snapshot_fingerprint: str | None
    source_chapter_ids: tuple[str, ...]
    degraded_reasons: tuple[str, ...] = ()


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise DramaSourceAdapterError("source snapshot contains duplicate keys")
        output[key] = value
    return output


def _reject_json_constant(_value: str) -> None:
    raise DramaSourceAdapterError("source snapshot contains a non-finite number")


def _parse_json_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise DramaSourceAdapterError("source snapshot contains a non-finite number")
    return number


def _parse_snapshot(payload: bytes | None, *, name: str) -> Any | None:
    if payload is None:
        return None
    if not isinstance(payload, bytes):
        raise DramaSourceAdapterError(f"{name} snapshot must be bytes")
    if len(payload) > MAX_SOURCE_SNAPSHOT_BYTES:
        raise DramaSourceAdapterError(f"{name} snapshot exceeds its byte limit")
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_members,
            parse_constant=_reject_json_constant,
            parse_float=_parse_json_float,
        )
    except DramaSourceAdapterError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise DramaSourceAdapterError(f"{name} snapshot is invalid") from exc


def _bounded_text(value: Any, *, name: str, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise DramaSourceAdapterError(f"{name} must be a bounded string")
    return value


def _chapter_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping) or set(value) - {"chapters", "compressed_older"}:
        raise DramaSourceAdapterError("rolling summary snapshot schema is invalid")
    rows = value.get("chapters", [])
    if not isinstance(rows, list) or len(rows) > MAX_SOURCE_CHAPTERS:
        raise DramaSourceAdapterError("rolling summary chapters are invalid")
    compressed = value.get("compressed_older", [])
    if not isinstance(compressed, list) or len(compressed) > MAX_SOURCE_CHAPTERS:
        raise DramaSourceAdapterError("rolling summary compact history is invalid")
    compact_numbers: set[int] = set()
    for item in compressed:
        if isinstance(item, str):
            if len(item) > 4000:
                raise DramaSourceAdapterError("rolling summary compact row is invalid")
            continue
        if not isinstance(item, Mapping) or set(item) != {"chapter_no", "text"}:
            raise DramaSourceAdapterError("rolling summary compact row is invalid")
        number = item["chapter_no"]
        text = item["text"]
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or number < 1
            or number > 100_000
            or number in compact_numbers
            or not isinstance(text, str)
            or len(text) > 4000
        ):
            raise DramaSourceAdapterError("rolling summary compact row is invalid")
        compact_numbers.add(number)

    output: list[dict[str, Any]] = []
    seen_numbers: set[int] = set()
    seen_ids: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping) or set(raw) - _CHAPTER_KEYS:
            raise DramaSourceAdapterError("rolling summary chapter schema is invalid")
        number = raw.get("chapter_no")
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or number < 1
            or number > 100_000
            or number in seen_numbers
        ):
            raise DramaSourceAdapterError("rolling summary chapter number is invalid")
        chapter_id = raw.get("chapter_id", f"chapter_{number:06d}")
        if (
            not isinstance(chapter_id, str)
            or _ATOM_RE.fullmatch(chapter_id) is None
            or chapter_id in seen_ids
        ):
            raise DramaSourceAdapterError("rolling summary chapter id is invalid")
        summary = _bounded_text(raw.get("summary", ""), name="chapter summary", maximum=20_000)
        ending = _bounded_text(raw.get("ending_state", ""), name="chapter ending", maximum=10_000)
        snippet = _bounded_text(raw.get("text_snippet", ""), name="chapter snippet", maximum=20_000)
        events = raw.get("key_events", [])
        if (
            not isinstance(events, list)
            or len(events) > 64
            or any(not isinstance(item, str) or len(item) > 4000 for item in events)
        ):
            raise DramaSourceAdapterError("chapter key events are invalid")
        canonical = {
            "chapter_id": chapter_id,
            "chapter_no": number,
            "summary": summary,
            "key_events": list(events),
            "ending_state": ending,
            "text_snippet": snippet,
        }
        output.append(canonical)
        seen_numbers.add(number)
        seen_ids.add(chapter_id)
    output.sort(key=lambda item: (item["chapter_no"], item["chapter_id"]))
    return output


def _entity_index(value: Any | None) -> tuple[dict[str, str], list[dict[str, Any]]]:
    if value is None:
        return {}, []
    if not isinstance(value, Mapping):
        raise DramaSourceAdapterError("entity graph snapshot must be an object")
    entities = value.get("entities", [])
    relationships = value.get("relationships", [])
    if (
        not isinstance(entities, list)
        or len(entities) > MAX_SOURCE_ENTITIES
        or not isinstance(relationships, list)
        or len(relationships) > MAX_SOURCE_RELATIONSHIPS
    ):
        raise DramaSourceAdapterError("entity graph collections are invalid")
    ids: dict[str, str] = {}
    for raw in entities:
        if not isinstance(raw, Mapping):
            raise DramaSourceAdapterError("entity graph entity is invalid")
        entity_id = raw.get("id")
        if not isinstance(entity_id, str) or _ATOM_RE.fullmatch(entity_id) is None:
            raise DramaSourceAdapterError("entity graph entity id is invalid")
        if entity_id in ids:
            raise DramaSourceAdapterError("entity graph entity ids must be unique")
        ids[entity_id] = entity_id
    safe_relationships: list[dict[str, Any]] = []
    for raw in relationships:
        if not isinstance(raw, Mapping):
            raise DramaSourceAdapterError("entity graph relationship is invalid")
        source = raw.get("src_id")
        target = raw.get("dst_id")
        timeline = raw.get("timeline", [])
        if source not in ids or target not in ids or not isinstance(timeline, list):
            raise DramaSourceAdapterError("entity graph relationship identity is invalid")
        if len(timeline) > MAX_TIMELINE_ENTRIES:
            raise DramaSourceAdapterError("entity graph relationship timeline exceeds its limit")
        safe_relationships.append(
            {
                "src_id": source,
                "dst_id": target,
                "relation_type": raw.get("relation_type", ""),
                "timeline": timeline,
            }
        )
    return ids, safe_relationships


def _relationship_fact_index(
    relationships: Sequence[Mapping[str, Any]],
    *,
    chapter_no_by_id: Mapping[str, int],
) -> tuple[dict[int, tuple[tuple[str, ...], tuple[Any, ...]]], bool]:
    participants_by_chapter: dict[int, set[str]] = {}
    facts_by_chapter: dict[int, dict[str, Any]] = {}
    chapter_numbers = set(chapter_no_by_id.values())
    unresolved_anchor = False
    for relationship in relationships:
        relation_type = relationship.get("relation_type", "")
        if not isinstance(relation_type, str) or len(relation_type) > 1000:
            raise DramaSourceAdapterError("entity relationship type is invalid")
        for item in relationship["timeline"]:
            if not isinstance(item, Mapping):
                raise DramaSourceAdapterError("entity relationship timeline row is invalid")
            if "active" in item and type(item["active"]) is not bool:
                raise DramaSourceAdapterError("entity relationship active flag is invalid")
            for field, maximum in (("state", 10_000), ("trigger_event", 10_000)):
                if field in item and (
                    not isinstance(item[field], str) or len(item[field]) > maximum
                ):
                    raise DramaSourceAdapterError(
                        f"entity relationship {field} is invalid"
                    )
            chapter_ids = [
                item[field]
                for field in ("chapter_id", "source_chapter")
                if item.get(field) is not None
            ]
            if any(
                not isinstance(value, str) or _ATOM_RE.fullmatch(value) is None
                for value in chapter_ids
            ) or len(set(chapter_ids)) > 1:
                raise DramaSourceAdapterError("entity relationship chapter id is invalid")
            row_number = item.get("chapter_no")
            if row_number is not None and (
                not isinstance(row_number, int)
                or isinstance(row_number, bool)
                or row_number < 1
                or row_number > 100_000
            ):
                raise DramaSourceAdapterError("entity relationship chapter number is invalid")
            resolved_numbers: list[int] = []
            if chapter_ids and chapter_ids[0] in chapter_no_by_id:
                resolved_numbers.append(chapter_no_by_id[chapter_ids[0]])
            if row_number is not None:
                resolved_numbers.append(row_number)
            anchor = item.get("anchor_chapter")
            if anchor is not None and (
                not isinstance(anchor, str) or len(anchor) > 80
            ):
                raise DramaSourceAdapterError("entity relationship chapter anchor is invalid")
            parsed = parse_chapter_anchor(anchor or "")
            if parsed is not None:
                resolved_numbers.append(parsed)
            elif anchor:
                unresolved_anchor = True
            if (
                chapter_ids
                and chapter_ids[0] not in chapter_no_by_id
                and (row_number is not None or parsed is not None)
            ):
                raise DramaSourceAdapterError(
                    "entity relationship source identities conflict"
                )
            if len(set(resolved_numbers)) > 1:
                raise DramaSourceAdapterError("entity relationship source identities conflict")
            if not resolved_numbers:
                continue
            resolved_number = resolved_numbers[0]
            if resolved_number not in chapter_numbers:
                continue
            source = relationship["src_id"]
            target = relationship["dst_id"]
            participants_by_chapter.setdefault(resolved_number, set()).update(
                (source, target)
            )
            state_identity = _canonical_sha256(
                {
                    "relation_type": relation_type,
                    "state": item.get("state"),
                    "active": item.get("active"),
                }
            )
            fact = build_event_fact(
                kind="effect",
                subject_id=source,
                predicate="relationship",
                object_id=target,
                value=f"rel_{state_identity[:24]}",
            )
            facts_by_chapter.setdefault(resolved_number, {})[fact.fact_id] = fact
    output = {
        number: (
            tuple(sorted(participants_by_chapter.get(number, set()))),
            tuple(
                sorted(
                    facts_by_chapter.get(number, {}).values(),
                    key=lambda item: item.fact_id,
                )
            ),
        )
        for number in set(participants_by_chapter) | set(facts_by_chapter)
    }
    return output, unresolved_anchor


def build_source_event_graph(
    *,
    workspace: str,
    graph_family_id: str,
    rolling_summary_bytes: bytes | None,
    entity_graph_bytes: bytes | None = None,
    max_spoiler_boundary: int = 100_000,
) -> DramaSourceAdapterResult:
    """Build a minimal H1 graph from exact entity/summary snapshot bytes.

    Missing or empty rolling state is an ordinary graceful-degrade outcome.
    Non-empty malformed input is rejected because silently treating corruption as
    absence would make a stale production snapshot look current.
    """

    if not isinstance(graph_family_id, str) or _ATOM_RE.fullmatch(graph_family_id) is None:
        raise DramaSourceAdapterError("graph family id is invalid")
    if (
        not isinstance(max_spoiler_boundary, int)
        or isinstance(max_spoiler_boundary, bool)
        or max_spoiler_boundary < 1
        or max_spoiler_boundary > 100_000
    ):
        raise DramaSourceAdapterError("maximum spoiler boundary is invalid")
    workspace_scope = event_graph_scope_fingerprint(workspace)
    rolling = _parse_snapshot(rolling_summary_bytes, name="rolling summary")
    if rolling is None:
        return DramaSourceAdapterResult("insufficient_source", None, None, ())
    entity = _parse_snapshot(entity_graph_bytes, name="entity graph")
    chapters = _chapter_rows(rolling)
    if not chapters:
        return DramaSourceAdapterResult("insufficient_source", None, None, ())
    _entities, relationships = _entity_index(entity)
    rolling_sha = hashlib.sha256(rolling_summary_bytes or b"").hexdigest()
    entity_sha = (
        hashlib.sha256(entity_graph_bytes).hexdigest()
        if entity_graph_bytes is not None and entity_graph_bytes != b""
        else None
    )
    snapshot_fingerprint = _canonical_sha256(
        {
            "adapter_version": 1,
            "workspace_scope_fingerprint": workspace_scope,
            "rolling_summary_bytes_sha256": rolling_sha,
            "entity_graph_bytes_sha256": entity_sha,
        }
    )
    family_scope = drama_event_graph_family_scope_fingerprint(
        workspace_scope_fingerprint=workspace_scope,
        graph_family_id=graph_family_id,
    )
    built = []
    chapter_no_by_id = {
        chapter["chapter_id"]: chapter["chapter_no"] for chapter in chapters
    }
    relationship_index, unresolved_anchor = _relationship_fact_index(
        relationships,
        chapter_no_by_id=chapter_no_by_id,
    )
    for order, chapter in enumerate(chapters, start=1):
        participants, effects = relationship_index.get(
            chapter["chapter_no"],
            ((), ()),
        )
        source_hash = _canonical_sha256(
            {
                "source_snapshot_fingerprint": snapshot_fingerprint,
                "chapter": chapter,
            }
        )
        try:
            event = build_source_event(
                workspace_scope_fingerprint=workspace_scope,
                scope_fingerprint=family_scope,
                source_kind="source_derived",
                adaptation_status="selected",
                chronology_order=order,
                source_chapters=[
                    {
                        "chapter_id": chapter["chapter_id"],
                        "chapter_no": chapter["chapter_no"],
                        "source_hash": source_hash,
                    }
                ],
                participant_ids=participants,
                scene_ids=(),
                prop_ids=(),
                clue_ids=(),
                preconditions=(),
                effects=effects,
                causal_parent_ids=(),
                causality_complete=False,
                lineage_operation="original",
                lineage_parent_event_ids=(),
            )
        except DramaEventGraphError as exc:
            raise DramaSourceAdapterError("source event projection is invalid") from exc
        built.append(event)
    try:
        graph = build_event_graph(
            workspace_scope_fingerprint=workspace_scope,
            scope_fingerprint=family_scope,
            events=built,
        )
    except DramaEventGraphError as exc:
        raise DramaSourceAdapterError("source event graph is invalid") from exc
    return DramaSourceAdapterResult(
        "ready",
        graph,
        snapshot_fingerprint,
        tuple(chapter["chapter_id"] for chapter in chapters),
        tuple(
            reason
            for reason, applies in (
                ("entity_graph_missing", entity is None),
                ("unresolved_chapter_anchor", unresolved_anchor),
            )
            if applies
        ),
    )


def load_production_source_event_graph(
    *,
    workspace: str,
    graph_family_id: str,
    max_spoiler_boundary: int = 100_000,
) -> DramaSourceAdapterResult:
    """Read one stable named-workspace entity/summary pair by exact double-read.

    The strict workspace reader rejects symlinks, directories and path escape.
    A surrounding workspace lock strengthens this for cooperating writers, while
    the double-read also detects concurrent non-cooperating byte changes. Missing
    optional state is passed to the pure builder and degrades without
    fabricating an empty graph.  No chapter source files are opened.
    """

    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    with use_workspace(workspace):
        def read_optional(path: Any, *, name: str) -> bytes | None:
            try:
                return _read_strict_workspace_bytes(
                    root,
                    path,
                    maximum=MAX_SOURCE_SNAPSHOT_BYTES,
                )
            except FileNotFoundError:
                return None
            except (OSError, ValueError) as exc:
                raise DramaSourceAdapterError(
                    f"{name} production snapshot is invalid"
                ) from exc

        rolling_path = paths.rolling_summary_path()
        entity_path = paths.entity_graph_path()
        rolling = read_optional(rolling_path, name="rolling summary")
        entity = read_optional(entity_path, name="entity graph")
        rolling_check = read_optional(rolling_path, name="rolling summary")
        entity_check = read_optional(entity_path, name="entity graph")
        if rolling != rolling_check or entity != entity_check:
            raise DramaSourceAdapterError("production source snapshot changed during read")
        return build_source_event_graph(
            workspace=workspace,
            graph_family_id=graph_family_id,
            rolling_summary_bytes=rolling,
            entity_graph_bytes=entity,
            max_spoiler_boundary=max_spoiler_boundary,
        )
