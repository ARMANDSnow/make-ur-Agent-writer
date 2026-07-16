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

# Stage-D3 shot-video attempts use a separate strict ledger from the legacy
# episode-1 high-light job.  These sets classify every persisted D3 status into
# the four recovery outcomes exposed by inspection.
SHOT_VIDEO_ATTEMPT_STATUSES = frozenset({
    "started",
    "not_sent",
    "submission_unknown",
    "submitted",
    "provider_succeeded",
    "provider_failed",
    "artifact_received",
    "succeeded",
    "closed_unknown",
})
SHOT_VIDEO_NOT_SENT_STATUSES = frozenset({"not_sent"})
SHOT_VIDEO_UNKNOWN_STATUSES = frozenset({"started", "submission_unknown"})
SHOT_VIDEO_SUBMITTED_STATUSES = frozenset({
    "submitted",
    "provider_succeeded",
    "artifact_received",
})
SHOT_VIDEO_TERMINAL_STATUSES = frozenset({"provider_failed", "succeeded", "closed_unknown"})

VIDEO_LEDGER_STATUSES = frozenset({"submitting", "submitted", "failed", "succeeded"})
VIDEO_TASK_ID_STATUSES = frozenset({"submitted", "failed", "succeeded"})
VIDEO_PAID_SUBMISSION_STATUSES = VIDEO_TASK_ID_STATUSES
VIDEO_NON_RESUMABLE_STATUSES = frozenset({"submitting", "failed"})
VIDEO_INCOMPLETE_STATUSES = frozenset({"submitting", "submitted", "failed"})
