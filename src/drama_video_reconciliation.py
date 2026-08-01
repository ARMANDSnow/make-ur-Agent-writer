"""Append-only reconciliation evidence for legacy video submission unknowns.

This private ledger never performs provider I/O and never stores response
bodies, prompts, asset identities, or signed URLs.  It binds bounded operator
observations to the exact durable submission marker and keeps negative task-list
observations from being promoted into a false "not sent" conclusion.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
from typing import Any, Dict, Mapping

from . import drama_video
from .utils import sha256_data
from .web.workspace_ctx import use_workspace
from .workspace_lock import acquire_write_lock


RECONCILIATION_SCHEMA_VERSION = 1
MAX_RECONCILIATION_RECEIPTS = 100
_ZERO_FINGERPRINT = "0" * 64
_OUTCOMES = frozenset({"still_unknown", "provider_rejected", "submitted"})
_EVIDENCE_KINDS = frozenset({
    "task_query",
    "billing_query",
    "provider_rejection",
    "task_list_observation",
})
_BILLING_STATES = frozenset({"no_record", "charge_found", "pending", "unknown"})
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class DramaVideoReconciliationError(ValueError):
    """The private reconciliation ledger is invalid or changed concurrently."""


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _submission_identity(submission: Mapping[str, Any]) -> str:
    return sha256_data(dict(submission))


def _submission_stat_identity(
    workspace: str,
    *,
    sample_id: str | None,
) -> str:
    path = drama_video.video_submission_path(workspace, sample_id=sample_id)
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise DramaVideoReconciliationError(
            "video submission source could not be inspected"
        ) from exc
    if not stat.S_ISREG(info.st_mode):
        raise DramaVideoReconciliationError(
            "video submission source must be a regular file"
        )
    return sha256_data({
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "modified_ns": info.st_mtime_ns,
        "changed_ns": info.st_ctime_ns,
    })


def _read_submission_snapshot(
    workspace: str,
    *,
    sample_id: str | None,
) -> tuple[Dict[str, Any] | None, str | None]:
    """Read one stable source snapshot without ever rewriting the source."""

    for _attempt in range(3):
        try:
            before = _submission_stat_identity(
                workspace, sample_id=sample_id
            )
        except DramaVideoReconciliationError:
            if drama_video.read_video_submission(workspace, sample_id=sample_id) is None:
                return None, None
            raise
        submission = drama_video.read_video_submission(
            workspace, sample_id=sample_id
        )
        after = _submission_stat_identity(workspace, sample_id=sample_id)
        if before == after:
            return submission, after
    raise DramaVideoReconciliationError(
        "video submission changed during reconciliation inspection"
    )


def _receipt_payload(receipt: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in receipt.items()
        if key != "receipt_fingerprint"
    }


def _ledger_payload(ledger: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in ledger.items()
        if key != "ledger_fingerprint"
    }


def _validate_optional_identifier(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise DramaVideoReconciliationError(f"{label} is invalid")
    return value


def _validate_optional_token(value: Any, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise DramaVideoReconciliationError(f"{label} is invalid")
    return value


def _validate_receipt(raw: Any, *, expected_sequence: int, previous: str) -> Dict[str, Any]:
    if type(raw) is not dict:
        raise DramaVideoReconciliationError("video reconciliation receipt is invalid")
    allowed = {
        "sequence",
        "previous_receipt_fingerprint",
        "observed_outcome",
        "evidence_kind",
        "evidence_fingerprint",
        "recorded_at_ms",
        "provider_task_id",
        "provider_request_id",
        "http_status",
        "billing_state",
        "rejection_class",
        "receipt_fingerprint",
    }
    if set(raw) - allowed:
        raise DramaVideoReconciliationError("video reconciliation receipt has unknown fields")
    if raw.get("sequence") != expected_sequence:
        raise DramaVideoReconciliationError("video reconciliation sequence is invalid")
    if raw.get("previous_receipt_fingerprint") != previous:
        raise DramaVideoReconciliationError("video reconciliation receipt chain is invalid")
    outcome = raw.get("observed_outcome")
    evidence_kind = raw.get("evidence_kind")
    if outcome not in _OUTCOMES or evidence_kind not in _EVIDENCE_KINDS:
        raise DramaVideoReconciliationError("video reconciliation classification is invalid")
    if not _valid_sha256(raw.get("evidence_fingerprint")):
        raise DramaVideoReconciliationError("video reconciliation evidence fingerprint is invalid")
    recorded_at_ms = raw.get("recorded_at_ms")
    if (
        isinstance(recorded_at_ms, bool)
        or not isinstance(recorded_at_ms, int)
        or not 0 <= recorded_at_ms <= 10_000_000_000_000
    ):
        raise DramaVideoReconciliationError("video reconciliation timestamp is invalid")
    task_id = _validate_optional_identifier(
        raw.get("provider_task_id"), label="provider task id"
    )
    _validate_optional_identifier(
        raw.get("provider_request_id"), label="provider request id"
    )
    rejection_class = _validate_optional_token(
        raw.get("rejection_class"), label="provider rejection class"
    )
    http_status = raw.get("http_status")
    billing_state = raw.get("billing_state")

    if evidence_kind == "task_query":
        if outcome != "submitted" or task_id is None:
            raise DramaVideoReconciliationError(
                "task evidence must bind one submitted provider task"
            )
        if any(
            raw.get(key) is not None
            for key in ("provider_request_id", "http_status", "billing_state", "rejection_class")
        ):
            raise DramaVideoReconciliationError("task evidence contains unrelated fields")
    elif evidence_kind == "provider_rejection":
        if outcome != "provider_rejected" or task_id is not None:
            raise DramaVideoReconciliationError(
                "provider rejection evidence has an invalid conclusion"
            )
        if (
            isinstance(http_status, bool)
            or not isinstance(http_status, int)
            or not 400 <= http_status < 500
        ):
            raise DramaVideoReconciliationError("provider rejection HTTP status is invalid")
        if billing_state is not None or rejection_class is None:
            raise DramaVideoReconciliationError("provider rejection evidence is incomplete")
    elif evidence_kind == "billing_query":
        if outcome != "still_unknown" or task_id is not None:
            raise DramaVideoReconciliationError(
                "billing evidence without an exact task must stay unknown"
            )
        if billing_state not in _BILLING_STATES:
            raise DramaVideoReconciliationError("billing evidence state is invalid")
        if any(raw.get(key) is not None for key in ("provider_request_id", "http_status", "rejection_class")):
            raise DramaVideoReconciliationError("billing evidence contains unrelated fields")
    else:
        # A task-list count or no-match observation is never authoritative
        # evidence that the create request was not sent.
        if outcome != "still_unknown" or any(
            raw.get(key) is not None
            for key in (
                "provider_task_id",
                "provider_request_id",
                "http_status",
                "billing_state",
                "rejection_class",
            )
        ):
            raise DramaVideoReconciliationError(
                "task-list observation cannot resolve a submission"
            )

    expected_fingerprint = sha256_data(_receipt_payload(raw))
    if raw.get("receipt_fingerprint") != expected_fingerprint:
        raise DramaVideoReconciliationError("video reconciliation receipt fingerprint is invalid")
    return dict(raw)


def _validate_ledger(raw: Any) -> Dict[str, Any]:
    if type(raw) is not dict or set(raw) != {
        "schema_version",
        "episode_no",
        "reconciliation_generation",
        "source_revision_fingerprint",
        "submission_fingerprint",
        "revision",
        "receipts",
        "ledger_fingerprint",
    }:
        raise DramaVideoReconciliationError("video reconciliation ledger is invalid")
    if raw.get("schema_version") != RECONCILIATION_SCHEMA_VERSION or raw.get("episode_no") != 1:
        raise DramaVideoReconciliationError("video reconciliation schema is invalid")
    if not _valid_sha256(raw.get("submission_fingerprint")):
        raise DramaVideoReconciliationError("video reconciliation submission identity is invalid")
    generation = raw.get("reconciliation_generation")
    if (
        not isinstance(generation, str)
        or len(generation) != 32
        or any(char not in "0123456789abcdef" for char in generation)
    ):
        raise DramaVideoReconciliationError(
            "video reconciliation generation is invalid"
        )
    if not _valid_sha256(raw.get("source_revision_fingerprint")):
        raise DramaVideoReconciliationError(
            "video reconciliation source revision is invalid"
        )
    receipts = raw.get("receipts")
    if (
        not isinstance(receipts, list)
        or not 1 <= len(receipts) <= MAX_RECONCILIATION_RECEIPTS
        or raw.get("revision") != len(receipts)
    ):
        raise DramaVideoReconciliationError("video reconciliation revision is invalid")
    validated: list[Dict[str, Any]] = []
    previous = _ZERO_FINGERPRINT
    resolved: str | None = None
    seen_evidence: set[str] = set()
    last_recorded_at_ms = -1
    for sequence, receipt in enumerate(receipts, start=1):
        item = _validate_receipt(
            receipt,
            expected_sequence=sequence,
            previous=previous,
        )
        evidence = item["evidence_fingerprint"]
        if item["recorded_at_ms"] <= last_recorded_at_ms:
            raise DramaVideoReconciliationError(
                "video reconciliation receipts are out of order"
            )
        last_recorded_at_ms = item["recorded_at_ms"]
        if evidence in seen_evidence:
            raise DramaVideoReconciliationError("video reconciliation evidence is duplicated")
        seen_evidence.add(evidence)
        outcome = item["observed_outcome"]
        if resolved is not None:
            raise DramaVideoReconciliationError(
                "video reconciliation cannot append after resolution"
            )
        if outcome != "still_unknown":
            resolved = outcome
        previous = item["receipt_fingerprint"]
        validated.append(item)
    if raw.get("ledger_fingerprint") != sha256_data(_ledger_payload(raw)):
        raise DramaVideoReconciliationError("video reconciliation ledger fingerprint is invalid")
    return {**dict(raw), "receipts": validated}


def read_video_reconciliation(
    workspace: str,
    *,
    sample_id: str | None = None,
) -> Dict[str, Any] | None:
    sample_id = drama_video._validate_video_sample_id(sample_id)
    try:
        raw = drama_video._read_video_ledger(
            workspace,
            sample_id=sample_id,
            filename="reconciliation.json",
            label="video reconciliation",
        )
        return None if raw is None else _validate_ledger(raw)
    except DramaVideoReconciliationError:
        raise
    except ValueError as exc:
        raise DramaVideoReconciliationError(
            "video reconciliation ledger is unreadable"
        ) from exc


def inspect_video_reconciliation(
    workspace: str,
    *,
    sample_id: str | None = None,
) -> Dict[str, Any]:
    submission, source_revision_fingerprint = _read_submission_snapshot(
        workspace,
        sample_id=sample_id,
    )
    if submission is None or submission.get("status") not in {
        "submitting",
        "submission_unknown",
    }:
        raise DramaVideoReconciliationError(
            "video submission is not awaiting reconciliation"
        )
    submission_fingerprint = _submission_identity(submission)
    ledger = read_video_reconciliation(workspace, sample_id=sample_id)
    if ledger is not None and ledger["submission_fingerprint"] != submission_fingerprint:
        raise DramaVideoReconciliationError(
            "video reconciliation belongs to a different submission"
        )
    if (
        ledger is not None
        and ledger["source_revision_fingerprint"] != source_revision_fingerprint
    ):
        raise DramaVideoReconciliationError(
            "video reconciliation belongs to a replaced submission source"
        )
    return {
        "reconciliation_generation": (
            None if ledger is None else ledger["reconciliation_generation"]
        ),
        "source_revision_fingerprint": source_revision_fingerprint,
        "submission_fingerprint": submission_fingerprint,
        "revision": 0 if ledger is None else ledger["revision"],
        "ledger_fingerprint": None if ledger is None else ledger["ledger_fingerprint"],
        "observed_outcome": (
            "still_unknown"
            if ledger is None
            else ledger["receipts"][-1]["observed_outcome"]
        ),
        "provider_task_id": (
            None
            if ledger is None
            else ledger["receipts"][-1].get("provider_task_id")
        ),
    }


def append_video_reconciliation_receipt(
    workspace: str,
    *,
    sample_id: str | None = None,
    expected_submission_fingerprint: str,
    expected_reconciliation_generation: str | None,
    expected_source_revision_fingerprint: str,
    expected_revision: int,
    expected_ledger_fingerprint: str | None,
    observed_outcome: str,
    evidence_kind: str,
    evidence_fingerprint: str,
    recorded_at_ms: int,
    provider_task_id: str | None = None,
    provider_request_id: str | None = None,
    http_status: int | None = None,
    billing_state: str | None = None,
    rejection_class: str | None = None,
) -> Dict[str, Any]:
    if not _valid_sha256(expected_submission_fingerprint):
        raise DramaVideoReconciliationError("expected submission fingerprint is invalid")
    if (
        expected_reconciliation_generation is not None
        and (
            not isinstance(expected_reconciliation_generation, str)
            or len(expected_reconciliation_generation) != 32
            or any(
                char not in "0123456789abcdef"
                for char in expected_reconciliation_generation
            )
        )
    ):
        raise DramaVideoReconciliationError("expected reconciliation generation is invalid")
    if not _valid_sha256(expected_source_revision_fingerprint):
        raise DramaVideoReconciliationError("expected source revision is invalid")
    if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 0
    ):
        raise DramaVideoReconciliationError("expected reconciliation revision is invalid")
    if expected_ledger_fingerprint is not None and not _valid_sha256(
        expected_ledger_fingerprint
    ):
        raise DramaVideoReconciliationError("expected ledger fingerprint is invalid")
    sample_id = drama_video._validate_video_sample_id(sample_id)

    with use_workspace(workspace), acquire_write_lock(
        source="drama-video-reconciliation"
    ):
        current = inspect_video_reconciliation(workspace, sample_id=sample_id)
        ledger = read_video_reconciliation(workspace, sample_id=sample_id)
        if current["submission_fingerprint"] != expected_submission_fingerprint:
            raise DramaVideoReconciliationError("video submission changed; refresh before reconcile")
        if current["source_revision_fingerprint"] != expected_source_revision_fingerprint:
            raise DramaVideoReconciliationError("video submission source changed; refresh before reconcile")

        prior_receipt = _ZERO_FINGERPRINT
        if ledger is not None:
            prior_receipt = ledger["receipts"][-1]["receipt_fingerprint"]
        proposed = {
            "sequence": (0 if ledger is None else ledger["revision"]) + 1,
            "previous_receipt_fingerprint": prior_receipt,
            "observed_outcome": observed_outcome,
            "evidence_kind": evidence_kind,
            "evidence_fingerprint": evidence_fingerprint,
            "recorded_at_ms": recorded_at_ms,
        }
        for key, value in (
            ("provider_task_id", provider_task_id),
            ("provider_request_id", provider_request_id),
            ("http_status", http_status),
            ("billing_state", billing_state),
            ("rejection_class", rejection_class),
        ):
            if value is not None:
                proposed[key] = value
        proposed["receipt_fingerprint"] = sha256_data(proposed)
        proposed = _validate_receipt(
            proposed,
            expected_sequence=proposed["sequence"],
            previous=prior_receipt,
        )

        if ledger is not None:
            same_evidence = [
                item
                for item in ledger["receipts"]
                if item["evidence_fingerprint"] == evidence_fingerprint
            ]
            if same_evidence:
                existing = same_evidence[0]
                comparable = {
                    key: value
                    for key, value in proposed.items()
                    if key not in {
                        "sequence",
                        "previous_receipt_fingerprint",
                        "receipt_fingerprint",
                    }
                }
                existing_comparable = {
                    key: value
                    for key, value in existing.items()
                    if key not in {
                        "sequence",
                        "previous_receipt_fingerprint",
                        "receipt_fingerprint",
                    }
                }
                if comparable != existing_comparable:
                    raise DramaVideoReconciliationError(
                        "video reconciliation evidence conflicts with its prior receipt"
                    )
                return ledger

        actual_revision = 0 if ledger is None else ledger["revision"]
        actual_fingerprint = None if ledger is None else ledger["ledger_fingerprint"]
        if (
            current["reconciliation_generation"]
            != expected_reconciliation_generation
            or expected_revision != actual_revision
            or expected_ledger_fingerprint != actual_fingerprint
        ):
            raise DramaVideoReconciliationError(
                "video reconciliation changed; refresh before append"
            )
        receipts = [] if ledger is None else list(ledger["receipts"])
        if len(receipts) >= MAX_RECONCILIATION_RECEIPTS:
            raise DramaVideoReconciliationError("video reconciliation receipt limit reached")
        raw = {
            "schema_version": RECONCILIATION_SCHEMA_VERSION,
            "episode_no": 1,
            "reconciliation_generation": (
                secrets.token_hex(16)
                if ledger is None
                else ledger["reconciliation_generation"]
            ),
            "source_revision_fingerprint": expected_source_revision_fingerprint,
            "submission_fingerprint": expected_submission_fingerprint,
            "revision": len(receipts) + 1,
            "receipts": [*receipts, proposed],
        }
        raw["ledger_fingerprint"] = sha256_data(raw)
        validated = _validate_ledger(raw)
        drama_video._write_video_ledger(
            workspace,
            validated,
            sample_id=sample_id,
            filename="reconciliation.json",
            label="video reconciliation",
        )
        persisted = read_video_reconciliation(workspace, sample_id=sample_id)
        if persisted is None or persisted["ledger_fingerprint"] != validated["ledger_fingerprint"]:
            raise DramaVideoReconciliationError(
                "video reconciliation persistence verification failed"
            )
        return persisted
