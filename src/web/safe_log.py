"""Minimal exception telemetry safe for stderr and CI artifacts."""

from __future__ import annotations

import re
import sys
import uuid

from ..safe_errors import safe_exception_type_name


_EVENT_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")


def log_exception(event: str, exc: BaseException, *, trace_id: str | None = None) -> str:
    """Write one bounded metadata-only line and return its trace ID.

    Exception messages, frames, paths and request data are deliberately never
    inspected or serialized here.
    """

    safe_event = event if _EVENT_RE.fullmatch(event) else "invalid_event"
    safe_type = safe_exception_type_name(exc)
    safe_trace = trace_id if trace_id and re.fullmatch(r"[a-f0-9]{32}", trace_id) else uuid.uuid4().hex
    try:
        sys.stderr.write(
            f"[web-safe] event={safe_event} exception={safe_type} trace_id={safe_trace}\n"
        )
    except Exception:
        pass
    return safe_trace
