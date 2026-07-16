"""Shared paid-operation state vocabulary for crash-safe drama recovery.

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

IMAGE_ATTEMPT_STATUSES = frozenset({
    "started",
    "artifact_received",
    "succeeded",
    "timeout",
    "network_error",
    "provider_error",
    "local_error",
})
IMAGE_RECEIPT_STATUSES = frozenset({"artifact_received", "succeeded"})

# Stage-C3 shot-image attempts intentionally reuse the established image
# vocabulary.  They keep a separate ledger schema, not a second set of status
# strings whose recovery classification could drift.
SHOT_IMAGE_ATTEMPT_STATUSES = IMAGE_ATTEMPT_STATUSES
SHOT_IMAGE_RECEIPT_STATUSES = IMAGE_RECEIPT_STATUSES

VIDEO_LEDGER_STATUSES = frozenset({"submitting", "submitted", "failed", "succeeded"})
VIDEO_TASK_ID_STATUSES = frozenset({"submitted", "failed", "succeeded"})
VIDEO_PAID_SUBMISSION_STATUSES = VIDEO_TASK_ID_STATUSES
VIDEO_NON_RESUMABLE_STATUSES = frozenset({"submitting", "failed"})
VIDEO_INCOMPLETE_STATUSES = frozenset({"submitting", "submitted", "failed"})
