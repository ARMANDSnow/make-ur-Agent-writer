"""Shared paid-operation state vocabulary for crash-safe novel recovery.

These constants describe the existing persisted strings and their current
classifications.  They intentionally do not introduce a new ledger schema or
perform any serialization so validators and recovery branches cannot drift.
"""

from __future__ import annotations


TEXT_ATTEMPT_STATUSES = frozenset({
    "submitting",
    "response_received",
    "failed_after_submission",
    "succeeded",
    "budget_exceeded",
})
TEXT_CANONICAL_RECOVERY_STATUSES = frozenset({"response_received", "succeeded"})
TEXT_RECONCILIATION_REQUIRED_STATUSES = frozenset({
    "submitting",
    "response_received",
    "failed_after_submission",
    "budget_exceeded",
})
