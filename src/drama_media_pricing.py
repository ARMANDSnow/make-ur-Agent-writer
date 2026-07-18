"""G6 strict media pricing facts, durable store, and safe aggregation.

The generic pricing ledger records only bounded monetary facts and immutable
task/backend identity.  Provider job IDs, account names, endpoints, prompts,
responses, receipts, and credentials remain in their authoritative paid
systems and never appear in the public projection.
"""

from __future__ import annotations

import json
import os
import re
import stat
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import drama_edit_export, drama_media_tasks, paths
from .drama_schemas import (
    DramaMediaBackendBinding,
    DramaMediaKind,
    DramaMediaStage,
    DramaMediaTask,
    _canonical_sha256,
    normalize_episode_no,
)
from .drama_store import (
    _read_strict_workspace_bytes,
    _read_strict_workspace_json,
    _validate_render_workspace_root,
)
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


PricingFactKind = Literal[
    "estimate",
    "authorized",
    "reserved",
    "actual",
    "refunded",
    "unknown",
]
PricingEvidenceKind = Literal[
    "pricing_quote",
    "authorization",
    "budget_reservation",
    "paid_actual",
    "paid_refund",
    "paid_submission_unknown",
]
_EVIDENCE_KIND_BY_FACT: dict[str, str] = {
    "estimate": "pricing_quote",
    "authorized": "authorization",
    "reserved": "budget_reservation",
    "actual": "paid_actual",
    "refunded": "paid_refund",
    "unknown": "paid_submission_unknown",
}

MAX_MEDIA_PRICING_LEDGER_BYTES = 4 * 1024 * 1024
MAX_MEDIA_PRICING_FACTS = 4000
MAX_MEDIA_PRICING_NAMESPACE_ENTRIES = 1000
MAX_MEDIA_PRICING_INSIGHTS_FACTS = 4000
MAX_MEDIA_PRICING_INSIGHTS_TASKS = 1000
MAX_AMOUNT_MICROUNITS = 9_999_999_999_999_999
_MICRO_SCALE = 1_000_000
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_AMOUNT_RE = re.compile(r"^(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,6})?$")
_TASK_ID_RE = re.compile(r"^dmt_[0-9a-f]{24}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PRICING_NAME_RE = re.compile(r"^episode_([0-9]{3})\.pricing\.json$")
_PRICING_RELATIVE_DIRECTORY = "outputs/drama/media_pricing"


class DramaMediaPricingError(ValueError):
    """Bounded public error that never includes private pricing evidence."""


def parse_amount_microunits(value: Any) -> int:
    """Parse one canonical non-negative decimal string without floats."""

    if not isinstance(value, str) or _AMOUNT_RE.fullmatch(value) is None:
        raise DramaMediaPricingError("media pricing amount is invalid")
    whole, dot, fraction = value.partition(".")
    amount = int(whole) * _MICRO_SCALE
    if dot:
        amount += int(fraction.ljust(6, "0"))
    if amount > MAX_AMOUNT_MICROUNITS:
        raise DramaMediaPricingError("media pricing amount exceeds its limit")
    return amount


def format_amount_microunits(value: int) -> str:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or abs(value) > MAX_AMOUNT_MICROUNITS * MAX_MEDIA_PRICING_FACTS
    ):
        raise DramaMediaPricingError("media pricing total is invalid")
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    whole, fraction = divmod(absolute, _MICRO_SCALE)
    return f"{sign}{whole}.{fraction:06d}"


class DramaMediaPricingFact(BaseModel):
    """One append-only monetary fact bound to an exact provider task."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    fact_id: str = Field(pattern=r"^dmpf_[0-9a-f]{24}$")
    sequence: int = Field(ge=1, le=MAX_MEDIA_PRICING_FACTS)
    episode_no: int = Field(ge=1, le=100)
    task_id: str = Field(pattern=r"^dmt_[0-9a-f]{24}$")
    task_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    subject_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
    media_kind: DramaMediaKind
    stage: DramaMediaStage
    backend_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    model_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]{0,119}$")
    provider_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    account_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    endpoint_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    backend_binding_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_kind: PricingFactKind
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount_microunits: Optional[int] = Field(
        default=None, ge=0, le=MAX_AMOUNT_MICROUNITS
    )
    source_evidence_kind: PricingEvidenceKind
    source_evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    recorded_at_ms: int = Field(ge=0, le=9_999_999_999_999)
    fact_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "sequence",
        "episode_no",
        "recorded_at_ms",
        "amount_microunits",
        mode="before",
    )
    @classmethod
    def _pricing_fact_numbers_are_strict(
        cls, value: Any, info: Any
    ) -> Any:
        if value is None and info.field_name == "amount_microunits":
            return value
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @model_validator(mode="after")
    def _pricing_fact_is_content_addressed(
        self,
    ) -> "DramaMediaPricingFact":
        if (self.fact_kind == "unknown") != (
            self.amount_microunits is None
        ):
            raise ValueError("pricing fact amount does not match its kind")
        if self.source_evidence_kind != _EVIDENCE_KIND_BY_FACT[
            self.fact_kind
        ]:
            raise ValueError("pricing evidence does not match its fact kind")
        if (
            ".." in self.model_id
            or "//" in self.model_id
            or self.model_id.startswith("/")
            or self.model_id.endswith("/")
            or any(part in {"", ".", ".."} for part in self.model_id.split("/"))
        ):
            raise ValueError("pricing fact model identity is invalid")
        payload = self.model_dump(
            exclude={"fact_id", "fact_fingerprint"}
        )
        fingerprint = _canonical_sha256(payload)
        if self.fact_fingerprint != fingerprint:
            raise ValueError("pricing fact fingerprint is invalid")
        if self.fact_id != f"dmpf_{fingerprint[:24]}":
            raise ValueError("pricing fact id is invalid")
        return self


class DramaMediaPricingLedger(BaseModel):
    """Episode-scoped append-only pricing facts with guarded semantics."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    episode_no: int = Field(ge=1, le=100)
    revision: int = Field(ge=0, le=1_000_000)
    facts: tuple[DramaMediaPricingFact, ...] = Field(
        max_length=MAX_MEDIA_PRICING_FACTS
    )
    ledger_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("episode_no", "revision", mode="before")
    @classmethod
    def _pricing_ledger_numbers_are_strict(
        cls, value: Any, info: Any
    ) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{info.field_name} must be a strict integer")
        return value

    @field_validator("facts", mode="before")
    @classmethod
    def _pricing_ledger_facts_are_strict(
        cls, value: Any
    ) -> tuple[Any, ...]:
        if not isinstance(value, list):
            raise ValueError("media pricing facts must be a list")
        return tuple(value)

    @model_validator(mode="after")
    def _pricing_ledger_is_guarded(
        self,
    ) -> "DramaMediaPricingLedger":
        if [item.sequence for item in self.facts] != list(
            range(1, len(self.facts) + 1)
        ):
            raise ValueError("media pricing fact sequence is invalid")
        fact_ids = [item.fact_id for item in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("media pricing fact identity is duplicated")
        evidences = [
            item.source_evidence_fingerprint for item in self.facts
        ]
        if len(evidences) != len(set(evidences)):
            raise ValueError("media pricing evidence is reused")

        identities: dict[str, tuple[Any, ...]] = {}
        currencies: dict[str, str] = {}
        seen: dict[str, set[str]] = defaultdict(set)
        last_time: dict[str, int] = {}
        amounts: dict[str, dict[str, int]] = defaultdict(dict)
        refund_totals: dict[str, int] = defaultdict(int)
        for fact in self.facts:
            if fact.episode_no != self.episode_no:
                raise ValueError("media pricing fact belongs to another episode")
            identity = (
                fact.episode_no,
                fact.task_input_fingerprint,
                fact.subject_id,
                fact.media_kind,
                fact.stage,
                fact.backend_id,
                fact.provider_id,
                fact.model_id,
                fact.provider_fingerprint,
                fact.model_fingerprint,
                fact.account_fingerprint,
                fact.endpoint_fingerprint,
                fact.backend_binding_fingerprint,
            )
            prior_identity = identities.setdefault(fact.task_id, identity)
            if prior_identity != identity:
                raise ValueError("media pricing task identity changed")
            prior_currency = currencies.setdefault(
                fact.task_id, fact.currency
            )
            if prior_currency != fact.currency:
                raise ValueError("media pricing currency changed")
            if fact.recorded_at_ms < last_time.get(fact.task_id, 0):
                raise ValueError("media pricing fact time moved backwards")
            last_time[fact.task_id] = fact.recorded_at_ms

            kinds = seen[fact.task_id]
            kind = fact.fact_kind
            amount = fact.amount_microunits
            if kind == "estimate":
                if kinds:
                    raise ValueError("estimate must be the first pricing fact")
            elif kind == "authorized":
                if "estimate" not in kinds or "authorized" in kinds:
                    raise ValueError("authorization pricing transition is invalid")
            elif kind == "reserved":
                if (
                    "authorized" not in kinds
                    or "reserved" in kinds
                    or kinds.intersection(
                        {"actual", "unknown", "refunded"}
                    )
                ):
                    raise ValueError("reservation pricing transition is invalid")
                if amount is not None and amount > amounts[fact.task_id]["authorized"]:
                    raise ValueError("reserved amount exceeds authorization")
            elif kind == "unknown":
                if (
                    "authorized" not in kinds
                    or "unknown" in kinds
                    or "actual" in kinds
                ):
                    raise ValueError("unknown pricing transition is invalid")
            elif kind == "actual":
                if "authorized" not in kinds or "actual" in kinds:
                    raise ValueError("actual pricing transition is invalid")
            elif kind == "refunded":
                if "actual" not in kinds:
                    raise ValueError("refund precedes actual cost")
                if amount is None:
                    raise ValueError("refund amount is missing")
                refund_totals[fact.task_id] += amount
                if refund_totals[fact.task_id] > amounts[fact.task_id]["actual"]:
                    raise ValueError("refund exceeds actual cost")
            if kind != "refunded" and kind in kinds:
                raise ValueError("media pricing fact kind is duplicated")
            kinds.add(kind)
            if amount is not None and kind != "refunded":
                amounts[fact.task_id][kind] = amount

        payload = self.model_dump(exclude={"ledger_fingerprint"})
        if _canonical_sha256(payload) != self.ledger_fingerprint:
            raise ValueError("media pricing ledger fingerprint is invalid")
        return self


def media_pricing_ledger_path(
    workspace: str,
    *,
    episode_no: int = 1,
) -> Path:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    result = (
        root
        / "outputs"
        / "drama"
        / "media_pricing"
        / f"episode_{number:03d}.pricing.json"
    )
    if result.parent.parent.parent.parent != root:
        raise DramaMediaPricingError("media pricing path is invalid")
    return result


def _build_fact(
    *,
    task: DramaMediaTask,
    binding: DramaMediaBackendBinding,
    sequence: int,
    fact_kind: PricingFactKind,
    currency: str,
    amount_microunits: int | None,
    source_evidence_fingerprint: str,
    recorded_at_ms: int,
) -> DramaMediaPricingFact:
    if (
        binding.task_id != task.task_id
        or binding.task_input_fingerprint != task.input_fingerprint
        or binding.backend_id != task.backend_id
        or binding.media_kind != task.media_kind
        or binding.provider_fingerprint != task.provider_fingerprint
        or binding.model_fingerprint != task.model_fingerprint
    ):
        raise DramaMediaPricingError("media pricing task binding is invalid")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "sequence": sequence,
        "episode_no": task.episode_no,
        "task_id": task.task_id,
        "task_input_fingerprint": task.input_fingerprint,
        "subject_id": task.subject_id,
        "media_kind": task.media_kind,
        "stage": task.stage,
        "backend_id": task.backend_id,
        "provider_id": binding.provider_id,
        "model_id": binding.model_id,
        "provider_fingerprint": task.provider_fingerprint,
        "model_fingerprint": task.model_fingerprint,
        "account_fingerprint": task.account_fingerprint,
        "endpoint_fingerprint": task.endpoint_fingerprint,
        "backend_binding_fingerprint": binding.binding_fingerprint,
        "fact_kind": fact_kind,
        "currency": currency,
        "amount_microunits": amount_microunits,
        "source_evidence_kind": _EVIDENCE_KIND_BY_FACT[fact_kind],
        "source_evidence_fingerprint": source_evidence_fingerprint,
        "recorded_at_ms": recorded_at_ms,
    }
    fingerprint = _canonical_sha256(payload)
    payload["fact_id"] = f"dmpf_{fingerprint[:24]}"
    payload["fact_fingerprint"] = fingerprint
    try:
        return DramaMediaPricingFact(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaPricingError("media pricing fact was rejected") from None


def _build_ledger(
    episode_no: int,
    facts: Any,
    *,
    revision: int,
) -> DramaMediaPricingLedger:
    payload = {
        "schema_version": 1,
        "episode_no": episode_no,
        "revision": revision,
        "facts": [
            model_to_dict(item) if isinstance(item, DramaMediaPricingFact) else item
            for item in facts
        ],
    }
    payload["ledger_fingerprint"] = _canonical_sha256(payload)
    try:
        return DramaMediaPricingLedger(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaPricingError(
            "media pricing ledger was rejected"
        ) from None


def _empty_ledger(episode_no: int) -> DramaMediaPricingLedger:
    return _build_ledger(episode_no, (), revision=0)


def _ledger_bytes(ledger: DramaMediaPricingLedger) -> bytes:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "artifact_type": "drama_media_pricing_ledger",
                "ledger_fingerprint": ledger.ledger_fingerprint,
                "ledger": model_to_dict(ledger),
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _task_identity_matches(
    fact: DramaMediaPricingFact,
    task: DramaMediaTask,
    binding: DramaMediaBackendBinding,
) -> bool:
    return (
        fact.episode_no == task.episode_no
        and fact.task_input_fingerprint == task.input_fingerprint
        and fact.subject_id == task.subject_id
        and fact.media_kind == task.media_kind
        and fact.stage == task.stage
        and fact.backend_id == task.backend_id == binding.backend_id
        and fact.provider_id == binding.provider_id
        and fact.model_id == binding.model_id
        and fact.provider_fingerprint
        == task.provider_fingerprint
        == binding.provider_fingerprint
        and fact.model_fingerprint
        == task.model_fingerprint
        == binding.model_fingerprint
        and fact.account_fingerprint == task.account_fingerprint
        and fact.endpoint_fingerprint == task.endpoint_fingerprint
        and fact.backend_binding_fingerprint == binding.binding_fingerprint
        and binding.task_id == task.task_id == fact.task_id
    )


def _read_ledger(
    workspace: str,
    *,
    episode_no: int,
) -> DramaMediaPricingLedger:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    path = media_pricing_ledger_path(workspace, episode_no=number)
    try:
        raw = _read_strict_workspace_bytes(
            root, path, maximum=MAX_MEDIA_PRICING_LEDGER_BYTES
        )
        payload = _read_strict_workspace_json(
            root, path, maximum=MAX_MEDIA_PRICING_LEDGER_BYTES
        )
        return _validate_ledger_payload(
            workspace,
            episode_no=number,
            raw=raw,
            payload=payload,
        )
    except FileNotFoundError:
        raise
    except DramaMediaPricingError:
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaPricingError(
            "media pricing ledger is invalid"
        ) from None


def _validate_ledger_payload(
    workspace: str,
    *,
    episode_no: int,
    raw: bytes,
    payload: Any,
) -> DramaMediaPricingLedger:
    try:
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {
                "schema_version",
                "artifact_type",
                "ledger_fingerprint",
                "ledger",
            }
            or payload.get("schema_version") != 1
            or payload.get("artifact_type")
            != "drama_media_pricing_ledger"
            or not isinstance(payload.get("ledger"), dict)
        ):
            raise ValueError("invalid media pricing envelope")
        ledger = DramaMediaPricingLedger(**payload["ledger"])
        if (
            ledger.episode_no != episode_no
            or payload["ledger_fingerprint"] != ledger.ledger_fingerprint
            or raw != _ledger_bytes(ledger)
        ):
            raise ValueError("media pricing ledger identity mismatch")
        task_ledger = drama_media_tasks.load_media_task_ledger(
            workspace, episode_no=episode_no
        )
        tasks = {item.task_id: item for item in task_ledger.tasks}
        bindings = {
            item.task_id: item for item in task_ledger.backend_bindings
        }
        if any(
            fact.task_id not in tasks
            or fact.task_id not in bindings
            or not _task_identity_matches(
                fact, tasks[fact.task_id], bindings[fact.task_id]
            )
            for fact in ledger.facts
        ):
            raise ValueError("media pricing task identity mismatch")
        return ledger
    except FileNotFoundError:
        raise
    except DramaMediaPricingError:
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaPricingError(
            "media pricing ledger is invalid"
        ) from None


def _read_pricing_bytes_at(directory_fd: int, name: str) -> bytes:
    file_fd: int | None = None
    try:
        file_fd = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory_fd,
        )
    except FileNotFoundError:
        raise
    except OSError:
        raise DramaMediaPricingError(
            "media pricing ledger is invalid"
        ) from None
    try:
        before = os.fstat(file_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size <= 0
            or before.st_size > MAX_MEDIA_PRICING_LEDGER_BYTES
        ):
            raise DramaMediaPricingError(
                "media pricing ledger is invalid"
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, 65_536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_MEDIA_PRICING_LEDGER_BYTES:
                raise DramaMediaPricingError(
                    "media pricing ledger is invalid"
                )
            chunks.append(chunk)
        after = os.fstat(file_fd)
        if (
            total != before.st_size
            or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
        ):
            raise DramaMediaPricingError(
                "media pricing ledger changed concurrently"
            )
        return b"".join(chunks)
    except DramaMediaPricingError:
        raise
    except OSError:
        raise DramaMediaPricingError(
            "media pricing ledger is invalid"
        ) from None
    finally:
        if file_fd is not None:
            os.close(file_fd)


def _read_ledger_at(
    workspace: str,
    *,
    episode_no: int,
    directory_fd: int,
) -> DramaMediaPricingLedger:
    number = normalize_episode_no(episode_no)
    raw = _read_pricing_bytes_at(
        directory_fd, f"episode_{number:03d}.pricing.json"
    )
    try:
        payload = json.loads(raw)
    except (RecursionError, UnicodeDecodeError, json.JSONDecodeError):
        raise DramaMediaPricingError(
            "media pricing ledger is invalid"
        ) from None
    return _validate_ledger_payload(
        workspace,
        episode_no=number,
        raw=raw,
        payload=payload,
    )


def _write_ledger(
    workspace: str,
    ledger: DramaMediaPricingLedger,
    *,
    directory_fd: int,
    directory_identity: tuple[int, int],
    expected_target_token: tuple[Any, ...],
) -> None:
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    name = f"episode_{ledger.episode_no:03d}.pricing.json"
    try:
        if (
            drama_edit_export._target_token_at(
                directory_fd,
                name,
                maximum=MAX_MEDIA_PRICING_LEDGER_BYTES,
            )
            != expected_target_token
        ):
            raise DramaMediaPricingError(
                "media pricing ledger changed concurrently"
            )
        drama_edit_export._require_current_output_directory(
            root,
            _PRICING_RELATIVE_DIRECTORY,
            expected=directory_identity,
        )
        drama_edit_export._atomic_write_at(
            directory_fd,
            name,
            _ledger_bytes(ledger),
            maximum=MAX_MEDIA_PRICING_LEDGER_BYTES,
        )
        drama_edit_export._require_current_output_directory(
            root,
            _PRICING_RELATIVE_DIRECTORY,
            expected=directory_identity,
        )
    except DramaMediaPricingError:
        raise
    except (OSError, drama_edit_export.DramaEditExportError):
        raise DramaMediaPricingError(
            "media pricing ledger could not be committed safely"
        ) from None


def _persist_ledger(
    workspace: str,
    ledger: DramaMediaPricingLedger,
    *,
    directory_fd: int,
    directory_identity: tuple[int, int],
    expected_target_token: tuple[Any, ...],
) -> DramaMediaPricingLedger:
    _write_ledger(
        workspace,
        ledger,
        directory_fd=directory_fd,
        directory_identity=directory_identity,
        expected_target_token=expected_target_token,
    )
    persisted = _read_ledger_at(
        workspace,
        episode_no=ledger.episode_no,
        directory_fd=directory_fd,
    )
    if persisted != ledger:
        raise DramaMediaPricingError(
            "media pricing ledger persistence failed"
        )
    return persisted


def load_media_pricing_ledger(
    workspace: str,
    *,
    episode_no: int = 1,
) -> DramaMediaPricingLedger:
    try:
        return _read_ledger(
            workspace, episode_no=normalize_episode_no(episode_no)
        )
    except FileNotFoundError:
        raise
    except DramaMediaPricingError:
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaPricingError(
            "media pricing ledger could not be loaded"
        ) from None


def record_media_pricing_fact(
    workspace: str,
    *,
    episode_no: int,
    task_id: str,
    fact_kind: PricingFactKind,
    currency: str,
    amount: str | None,
    source_evidence_fingerprint: str,
    recorded_at_ms: int,
    expected_ledger_fingerprint: str | None,
) -> DramaMediaPricingFact:
    """Append or exact-replay one task-bound pricing fact under workspace CAS."""

    try:
        number = normalize_episode_no(episode_no)
        if not isinstance(task_id, str) or _TASK_ID_RE.fullmatch(task_id) is None:
            raise DramaMediaPricingError("media pricing task identity is invalid")
        if fact_kind not in {
            "estimate",
            "authorized",
            "reserved",
            "actual",
            "refunded",
            "unknown",
        }:
            raise DramaMediaPricingError("media pricing fact kind is invalid")
        if not isinstance(currency, str) or _CURRENCY_RE.fullmatch(currency) is None:
            raise DramaMediaPricingError("media pricing currency is invalid")
        if (
            not isinstance(source_evidence_fingerprint, str)
            or _SHA256_RE.fullmatch(source_evidence_fingerprint) is None
        ):
            raise DramaMediaPricingError("media pricing evidence is invalid")
        if (
            not isinstance(recorded_at_ms, int)
            or isinstance(recorded_at_ms, bool)
            or recorded_at_ms < 0
            or recorded_at_ms > 9_999_999_999_999
        ):
            raise DramaMediaPricingError("media pricing time is invalid")
        if fact_kind == "unknown":
            if amount is not None:
                raise DramaMediaPricingError(
                    "unknown pricing fact cannot carry an amount"
                )
            amount_microunits = None
        else:
            amount_microunits = parse_amount_microunits(amount)
        if expected_ledger_fingerprint is not None and (
            not isinstance(expected_ledger_fingerprint, str)
            or _SHA256_RE.fullmatch(expected_ledger_fingerprint) is None
        ):
            raise DramaMediaPricingError(
                "media pricing ledger identity is invalid"
            )

        with use_workspace(workspace), acquire_write_lock(
            source="drama-media-pricing-record"
        ):
            task_ledger = drama_media_tasks.load_media_task_ledger(
                workspace, episode_no=number
            )
            tasks = {item.task_id: item for item in task_ledger.tasks}
            bindings = {
                item.task_id: item for item in task_ledger.backend_bindings
            }
            task = tasks.get(task_id)
            binding = bindings.get(task_id)
            if task is None or binding is None:
                raise DramaMediaPricingError(
                    "media pricing requires a frozen provider task"
                )
            if recorded_at_ms < task.created_at_ms:
                raise DramaMediaPricingError(
                    "media pricing fact predates its task"
                )
            root = paths.workspace_root(workspace)
            _validate_render_workspace_root(root)
            directory_fd = drama_edit_export._open_output_directory(
                root,
                _PRICING_RELATIVE_DIRECTORY,
                create=True,
            )
            try:
                directory_identity = drama_edit_export._directory_identity(
                    directory_fd
                )
                drama_edit_export._require_current_output_directory(
                    root,
                    _PRICING_RELATIVE_DIRECTORY,
                    expected=directory_identity,
                )
                target_name = f"episode_{number:03d}.pricing.json"
                target_token = drama_edit_export._target_token_at(
                    directory_fd,
                    target_name,
                    maximum=MAX_MEDIA_PRICING_LEDGER_BYTES,
                )
                if target_token == ("invalid",):
                    raise DramaMediaPricingError(
                        "media pricing ledger is invalid"
                    )
                try:
                    ledger = _read_ledger_at(
                        workspace,
                        episode_no=number,
                        directory_fd=directory_fd,
                    )
                except FileNotFoundError:
                    ledger = _empty_ledger(number)
                    missing = True
                else:
                    missing = False

                episode_numbers, invalid_entries = (
                    _scan_pricing_namespace_at(directory_fd)
                )
                if invalid_entries:
                    raise DramaMediaPricingError(
                        "media pricing namespace requires reconciliation"
                    )
                for other_number in episode_numbers:
                    if other_number == number:
                        continue
                    try:
                        other = _read_ledger_at(
                            workspace,
                            episode_no=other_number,
                            directory_fd=directory_fd,
                        )
                    except FileNotFoundError:
                        raise DramaMediaPricingError(
                            "media pricing namespace changed concurrently"
                        ) from None
                    if any(
                        item.source_evidence_fingerprint
                        == source_evidence_fingerprint
                        for item in other.facts
                    ):
                        raise DramaMediaPricingError(
                            "media pricing evidence belongs to another task"
                        )

                for existing in ledger.facts:
                    if (
                        existing.task_id == task_id
                        and existing.fact_kind == fact_kind
                        and existing.source_evidence_fingerprint
                        == source_evidence_fingerprint
                    ):
                        if (
                            existing.currency != currency
                            or existing.amount_microunits
                            != amount_microunits
                            or existing.recorded_at_ms != recorded_at_ms
                        ):
                            raise DramaMediaPricingError(
                                "media pricing replay conflicts with persisted fact"
                            )
                        drama_edit_export._require_current_output_directory(
                            root,
                            _PRICING_RELATIVE_DIRECTORY,
                            expected=directory_identity,
                        )
                        return existing

                current = None if missing else ledger.ledger_fingerprint
                if expected_ledger_fingerprint != current:
                    raise DramaMediaPricingError(
                        "media pricing ledger changed; refresh"
                    )
                proposed = _build_fact(
                    task=task,
                    binding=binding,
                    sequence=len(ledger.facts) + 1,
                    fact_kind=fact_kind,
                    currency=currency,
                    amount_microunits=amount_microunits,
                    source_evidence_fingerprint=source_evidence_fingerprint,
                    recorded_at_ms=recorded_at_ms,
                )
                updated = _build_ledger(
                    number,
                    [*ledger.facts, proposed],
                    revision=ledger.revision + 1,
                )
                _persist_ledger(
                    workspace,
                    updated,
                    directory_fd=directory_fd,
                    directory_identity=directory_identity,
                    expected_target_token=target_token,
                )
                return proposed
            finally:
                os.close(directory_fd)
    except WorkspaceLocked:
        raise DramaMediaPricingError(
            "media pricing workspace is busy"
        ) from None
    except DramaMediaPricingError:
        raise
    except drama_edit_export.DramaEditExportError:
        raise DramaMediaPricingError(
            "media pricing namespace could not be accessed safely"
        ) from None
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaPricingError(
            "media pricing fact was rejected"
        ) from None


def _aggregate_facts(
    facts: list[DramaMediaPricingFact],
) -> dict[str, Any]:
    by_task: dict[str, list[DramaMediaPricingFact]] = defaultdict(list)
    for fact in facts:
        by_task[fact.task_id].append(fact)

    rows: list[dict[str, Any]] = []
    for task_id in sorted(by_task):
        task_facts = by_task[task_id]
        first = task_facts[0]
        amounts: dict[str, int] = {}
        refunded = 0
        kinds: set[str] = set()
        for fact in task_facts:
            kinds.add(fact.fact_kind)
            if fact.fact_kind == "refunded":
                if fact.amount_microunits is None:
                    raise DramaMediaPricingError(
                        "media pricing refund amount is invalid"
                    )
                refunded += fact.amount_microunits
            elif fact.amount_microunits is not None:
                amounts[fact.fact_kind] = fact.amount_microunits
        actual = amounts.get("actual")
        estimate = amounts.get("estimate")
        unknown = "unknown" in kinds and actual is None
        rows.append(
            {
                "task_id": task_id,
                "episode_no": first.episode_no,
                "subject_id": first.subject_id,
                "media_kind": first.media_kind,
                "stage": first.stage,
                "provider_id": first.provider_id,
                "model_id": first.model_id,
                "currency": first.currency,
                "fact_count": len(task_facts),
                "estimate": (
                    format_amount_microunits(estimate)
                    if estimate is not None
                    else None
                ),
                "authorized": (
                    format_amount_microunits(amounts["authorized"])
                    if "authorized" in amounts
                    else None
                ),
                "reserved": (
                    format_amount_microunits(amounts["reserved"])
                    if "reserved" in amounts
                    else None
                ),
                "actual_known": (
                    format_amount_microunits(actual)
                    if actual is not None
                    else None
                ),
                "refunded": (
                    format_amount_microunits(refunded)
                    if actual is not None
                    else None
                ),
                "net_actual_known": (
                    format_amount_microunits(actual - refunded)
                    if actual is not None
                    else None
                ),
                "estimate_actual_delta": (
                    format_amount_microunits(actual - estimate)
                    if actual is not None and estimate is not None
                    else None
                ),
                "unknown_submission": unknown,
            }
        )

    currency_rows: list[dict[str, Any]] = []
    for currency in sorted({row["currency"] for row in rows}):
        members = [row for row in rows if row["currency"] == currency]

        def total(field: str) -> int:
            return sum(
                parse_amount_microunits(row[field])
                for row in members
                if row[field] is not None
            )

        unknown_tasks = sum(
            1 for row in members if row["unknown_submission"]
        )
        pending_tasks = sum(
            1
            for row in members
            if row["actual_known"] is None
            and not row["unknown_submission"]
        )
        delta_members = [
            row
            for row in members
            if row["estimate_actual_delta"] is not None
        ]
        delta_micros = sum(
            int(
                row["estimate_actual_delta"].split(".", 1)[0]
            )
            * _MICRO_SCALE
            + (
                -1
                if row["estimate_actual_delta"].startswith("-")
                else 1
            )
            * int(
                row["estimate_actual_delta"]
                .lstrip("-")
                .split(".", 1)[1]
            )
            for row in delta_members
        )
        currency_rows.append(
            {
                "currency": currency,
                "task_count": len(members),
                "estimate": format_amount_microunits(total("estimate")),
                "authorized": format_amount_microunits(total("authorized")),
                "reserved": format_amount_microunits(total("reserved")),
                "actual_known": format_amount_microunits(
                    total("actual_known")
                ),
                "refunded": format_amount_microunits(total("refunded")),
                "net_actual_known": format_amount_microunits(
                    total("net_actual_known")
                ),
                "estimate_actual_delta_known": format_amount_microunits(
                    delta_micros
                ),
                "delta_task_count": len(delta_members),
                "unknown_submission_tasks": unknown_tasks,
                "pending_actual_tasks": pending_tasks,
                "actual_complete": unknown_tasks == 0 and pending_tasks == 0,
            }
        )
    return {
        "fact_count": len(facts),
        "task_count": len(rows),
        "currencies": currency_rows,
        "rows": rows,
    }


def aggregate_media_pricing_ledger(
    ledger: DramaMediaPricingLedger,
) -> dict[str, Any]:
    if not isinstance(ledger, DramaMediaPricingLedger):
        raise DramaMediaPricingError("media pricing ledger is invalid")
    try:
        ledger = DramaMediaPricingLedger(
            **ledger.model_dump(mode="json")
        )
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaPricingError("media pricing ledger is invalid") from None
    result = _aggregate_facts(list(ledger.facts))
    return {
        "schema_version": 1,
        "episode_no": ledger.episode_no,
        **result,
    }


def _scan_pricing_namespace_at(
    directory_fd: int,
) -> tuple[list[int], int]:
    numbers: list[int] = []
    invalid = 0
    try:
        with os.scandir(directory_fd) as entries:
            count = 0
            for entry in entries:
                count += 1
                if count > MAX_MEDIA_PRICING_NAMESPACE_ENTRIES:
                    raise DramaMediaPricingError(
                        "media pricing namespace exceeds its limit"
                    )
                match = _PRICING_NAME_RE.fullmatch(entry.name)
                if (
                    match is None
                    or not entry.is_file(follow_symlinks=False)
                ):
                    invalid += 1
                    continue
                number = int(match.group(1))
                if (
                    number < 1
                    or number > 100
                    or entry.name
                    != f"episode_{number:03d}.pricing.json"
                ):
                    invalid += 1
                    continue
                numbers.append(number)
    except OSError:
        return [], invalid + 1
    if len(numbers) != len(set(numbers)):
        raise DramaMediaPricingError(
            "media pricing namespace identity is ambiguous"
        )
    return sorted(numbers), invalid


def _scan_pricing_namespace(root: Path) -> tuple[list[int], int]:
    directory_fd: int | None = None
    try:
        directory_fd = drama_edit_export._open_output_directory(
            root,
            _PRICING_RELATIVE_DIRECTORY,
            create=False,
        )
    except drama_edit_export.DramaEditExportError:
        current = root
        for part in ("outputs", "drama", "media_pricing"):
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
    try:
        return _scan_pricing_namespace_at(directory_fd)
    finally:
        os.close(directory_fd)


def collect_workspace_media_pricing(
    workspace: str,
) -> dict[str, Any]:
    """Return a safe multi-episode pricing projection for drama Insights."""

    empty = {
        "schema_version": 1,
        "status": "ok",
        "ledger_count": 0,
        "invalid_ledgers": 0,
        "fact_count": 0,
        "task_count": 0,
        "currencies": [],
        "rows": [],
    }
    try:
        root = paths.workspace_root(workspace)
        if not root.exists():
            return empty
        _validate_render_workspace_root(root)
        numbers, invalid = _scan_pricing_namespace(root)
        facts: list[DramaMediaPricingFact] = []
        seen_evidence: set[str] = set()
        valid_ledgers = 0
        for number in numbers:
            try:
                ledger = _read_ledger(workspace, episode_no=number)
            except (FileNotFoundError, DramaMediaPricingError):
                invalid += 1
                continue
            ledger_evidence = {
                item.source_evidence_fingerprint
                for item in ledger.facts
            }
            if seen_evidence.intersection(ledger_evidence):
                return {
                    **empty,
                    "status": "degraded",
                    "invalid_ledgers": invalid + 1,
                }
            if (
                len(facts) + len(ledger.facts)
                > MAX_MEDIA_PRICING_INSIGHTS_FACTS
                or len(
                    {
                        item.task_id
                        for item in [*facts, *ledger.facts]
                    }
                )
                > MAX_MEDIA_PRICING_INSIGHTS_TASKS
            ):
                return {
                    **empty,
                    "status": "degraded",
                    "invalid_ledgers": invalid + 1,
                }
            valid_ledgers += 1
            seen_evidence.update(ledger_evidence)
            facts.extend(ledger.facts)
        aggregate = _aggregate_facts(facts)
        return {
            "schema_version": 1,
            "status": "degraded" if invalid else "ok",
            "ledger_count": valid_ledgers,
            "invalid_ledgers": invalid,
            **aggregate,
        }
    except (OSError, RecursionError, TypeError, ValueError, DramaMediaPricingError):
        return {
            **empty,
            "status": "degraded",
            "invalid_ledgers": 1,
        }
