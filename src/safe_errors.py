"""Metadata-only projections for exceptions crossing persistence boundaries."""

from __future__ import annotations

import re
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit


_REASON_RE = re.compile(r"[a-z0-9_]{1,48}")
_TYPE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_TRACE_RE = re.compile(r"[a-f0-9]{32}")
_TYPE_REASONS = {
    "BudgetExceeded": "budget_exceeded",
    "LLMBudgetLimitExceeded": "budget_exceeded",
    "LLMRequestLimitExceeded": "request_limit_exhausted",
    "LLMCallDeadlineExceeded": "job_timeout",
    "JobTimeout": "job_timeout",
}


def _safe_attr(value: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(value, name, default)
    except BaseException:
        return default


def safe_exception_type_name(exc: BaseException) -> str:
    """Return a bounded exception type even for hostile metaclasses."""

    try:
        name = type(exc).__name__
    except BaseException:
        return "Exception"
    if not isinstance(name, str) or _TYPE_RE.fullmatch(name) is None:
        return "Exception"
    return name


def safe_url(value: Any) -> str | None:
    """Return an origin/path-only URL, dropping userinfo, query and fragment."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is not None:
        host = f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), host, parsed.path or "", "", ""))


def exception_projection(
    exc: BaseException,
    *,
    reason: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """Project an exception without retaining any provider-controlled text."""

    candidate_reason = "operation_failed"
    for candidate in (
        reason,
        _safe_attr(exc, "reason"),
        _TYPE_REASONS.get(safe_exception_type_name(exc)),
    ):
        if isinstance(candidate, str) and _REASON_RE.fullmatch(candidate) is not None:
            candidate_reason = candidate
            break
    error_type = safe_exception_type_name(exc)
    candidate_trace = trace_id or _safe_attr(exc, "trace_id")
    if not isinstance(candidate_trace, str) or _TRACE_RE.fullmatch(candidate_trace) is None:
        candidate_trace = uuid.uuid4().hex
    result: dict[str, Any] = {
        "failure_reason": candidate_reason,
        "error_type": error_type,
        "trace_id": candidate_trace,
    }
    attempts = _safe_attr(exc, "attempts")
    if isinstance(attempts, int) and not isinstance(attempts, bool) and 1 <= attempts <= 160:
        result["attempts"] = attempts
    return result


def safe_exception_text(
    exc: BaseException,
    *,
    reason: str | None = None,
    trace_id: str | None = None,
) -> str:
    """Stable single-line text for legacy string fields in durable artifacts."""

    projected = exception_projection(exc, reason=reason, trace_id=trace_id)
    attempts = (
        f",attempts={projected['attempts']}" if "attempts" in projected else ""
    )
    return (
        f"{projected['failure_reason']}:{projected['error_type']}"
        f"{attempts},trace_id={projected['trace_id']}"
    )
