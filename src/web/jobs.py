"""iter 026: background job worker for the WebUI.

The dashboard's read-only GETs (iter 025) ran inline. iter 026 adds POST
endpoints that trigger pipeline steps which can take seconds-to-minutes,
so we move the work to a daemon thread and let the HTTP handler return
``{"job_id": "..."}`` immediately. The browser polls
``GET /api/workspace/<name>/job/<job_id>`` for progress.

Design constraints:

* **One job per workspace at a time** (409 on the second concurrent
  start). The pipeline writes to ``entity_graph.json`` and other
  workspace-shared files; two parallel writers race. The WebUI's read
  endpoints are not blocked by a running job — they share workspace_ctx
  but workspace_ctx now uses RLock + finally, so a fast read while a job
  is in-flight still serializes through but doesn't deadlock.
* **Live in-memory pool + bounded durable public ledger**. Active workers are
  keyed by uuid4 in memory; public job snapshots are appended to the
  workspace-local ``logs/web_jobs.jsonl`` ledger. After a restart, terminal
  snapshots remain queryable while non-terminal snapshots are projected as
  ``lost`` because their worker no longer exists.
* **Hard-coded step dispatch table** so a malicious or fat-fingered POST
  can't invoke arbitrary functions. Adding a step = editing this file.
"""

from __future__ import annotations

import threading
import time
import uuid
import json
import hashlib
import math
import fcntl
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..llm_client import LLMExecutionStopped
from .. import auto_pipeline, paths, start_point
from ..auto_bootstrap import bootstrap_all
from ..chapter_splitter import split_all
from ..cli_apply_bootstrap import apply_bootstrap
from ..compressor import compress_all
from ..book_runner import BookRunBlocked, BudgetExceeded, run_write_book
from ..debater import run_debate
from ..extractor import ExtractionBatchFailure, extract_all
from ..plot_planner import OutlineStale, generate_chapter_plan
from ..safe_errors import exception_projection
from ..paid_recovery_states import (
    TEXT_ATTEMPT_STATUSES,
    TEXT_CANONICAL_RECOVERY_STATUSES,
    TEXT_RECONCILIATION_REQUIRED_STATUSES,
)
from ..text_normalizer import normalize_all
from ..writer import write_chapters
from ._naming import validate_workspace_name
from .workspace_ctx import use_workspace


# Per-workspace lock: a workspace can run at most one job at a time.
# Holding the value of the entry would be the running job_id so we can
# point a concurrent POST at the live one if useful; for now the value
# is only checked for truthiness (409 on collision).
_WORKSPACE_JOBS: Dict[str, str] = {}
_WORKSPACE_LOCK = threading.Lock()

# All jobs, keyed by job_id. Survives only as long as the process.
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.RLock()
_JOB_LOG_LOCK = threading.Lock()
_WORKER_THREADS: Dict[str, threading.Thread] = {}
_WORKER_THREADS_LOCK = threading.Lock()
_JOB_EXECUTION_CONTEXTS: Dict[str, Dict[str, Any]] = {}
TERMINAL_STATUSES = {"succeeded", "blocked", "failed", "aborted", "lost", "budget_exceeded"}
_WORKER_RESTART_ERROR = "worker process restarted before this job reached a terminal state"
_MAX_JOB_LOG_BYTES = 4 * 1024 * 1024
_MAX_JOB_LOG_LINE_BYTES = 64 * 1024
_MAX_JOB_LOG_ROWS = 5_000
_MAX_JOB_WORKSPACES = 256

# Provider-attempt caps for Web novel jobs.  These are both server defaults and
# hard per-step maxima, not UI trust: routes validates an explicit lower value
# and persists the resolved value;
# the worker also installs a required LLM scope so an internal caller that
# omits it cannot make an unbounded real-model request.  Purely local steps are
# intentionally absent.
MAX_MODEL_REQUESTS_PER_JOB = 160
NOVEL_MODEL_REQUEST_DEFAULTS: Dict[str, int] = {
    "extract": 10,
    "compress": 10,
    "bootstrap": 10,
    "debate": 45,
    "plan-chapters": 3,
    "write-book": 20,
    "review-chapter": 20,
    "draft-once-dev": 20,
    "auto-pipeline-greenfield": 160,
    "prepare-greenfield": 10,
    # Default continuation window is 10 chapters: extraction (10) plus
    # compress/entity/anchor/persona stages and bounded repair headroom.
    "rebuild-for-start": 32,
    "expand-premise": 2,
    "extract-style": 2,
}
NOVEL_EXECUTION_LIMIT_DEFAULTS: Dict[str, tuple[float, float]] = {
    "extract": (3.0, 15.0),
    "compress": (3.0, 15.0),
    "bootstrap": (3.0, 15.0),
    "debate": (8.0, 60.0),
    "plan-chapters": (2.0, 15.0),
    "write-book": (6.0, 45.0),
    "review-chapter": (6.0, 45.0),
    "draft-once-dev": (6.0, 45.0),
    "auto-pipeline-greenfield": (40.0, 120.0),
    "prepare-greenfield": (3.0, 15.0),
    "rebuild-for-start": (3.0, 15.0),
    "expand-premise": (1.0, 15.0),
    "extract-style": (2.0, 15.0),
}
# Explicit user authorization may raise a model step above its conservative
# default, but the server still owns a finite hard ceiling.  The four-stage
# novel chain sums to at most CNY 95; omitted browser values continue to use
# the lower defaults above.
NOVEL_EXECUTION_LIMIT_MAXIMA: Dict[str, tuple[float, float]] = {
    **NOVEL_EXECUTION_LIMIT_DEFAULTS,
    "rebuild-for-start": (20.0, 15.0),
    "debate": (33.0, 60.0),
    "plan-chapters": (10.0, 15.0),
    "write-book": (32.0, 45.0),
}
_MODEL_TASKS = (
    "extract",
    "compress",
    "debate",
    "write",
    "review",
    "premise_expand",
    "style_extract",
    "plot_planner",
)


def default_model_request_limit(step: str) -> Optional[int]:
    return NOVEL_MODEL_REQUEST_DEFAULTS.get(step)


def default_novel_execution_limits(step: str) -> Optional[tuple[float, float]]:
    return NOVEL_EXECUTION_LIMIT_DEFAULTS.get(step)


def max_novel_execution_limits(step: str) -> Optional[tuple[float, float]]:
    return NOVEL_EXECUTION_LIMIT_MAXIMA.get(step)


class JobCancelled(LLMExecutionStopped):
    """Raised inside a worker when a cooperative cancel checkpoint fires."""


class JobPersistenceError(RuntimeError):
    """Raised when the initial pending row cannot be durably admitted."""


class JobTimeout(JobCancelled):
    """Raised when a job crosses its cooperative timeout deadline."""


def _now() -> float:
    return time.time()


def _as_ts(value: Any) -> float:
    """Coerce a persisted timestamp to float, tolerating corrupt rows.

    ``recent_jobs`` sorts by ``finished_at``/``started_at`` read straight
    from ``web_jobs.jsonl``; a hand-edited or truncated line can carry a
    non-numeric value (e.g. ``"bad"`` or an ISO string). A bare ``float()``
    would raise ValueError and 500 every consumer (jobs page, sidebar
    recent, overview). Treat anything non-numeric as 0.0 (oldest) so the row
    sinks in the sort rather than crashing it. NaN/inf survive float() but would
    silently corrupt the sort order (NaN compares False to everything; inf would
    pin a stale row to the top), so neutralize non-finite values too — mirrors
    the math.isfinite guards on the budget/timeout math elsewhere in this file."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if math.isfinite(out) else 0.0


def _finite_json_safe(value: Any) -> Any:
    """Recursively replace non-finite floats (NaN/±Inf) with ``None``.

    ``json.dumps`` defaults to ``allow_nan=True`` and emits bare ``NaN`` /
    ``Infinity`` tokens — invalid per RFC 8259, so a strict browser
    ``JSON.parse`` (or any downstream consumer) chokes. A generic step
    (progress fraction, cost estimate, panel score) can let a non-finite
    float slip into a job record, so sanitize both the HTTP response
    (``routes._json``) and the persisted ``web_jobs.jsonl`` row
    (``_persist_job``) — otherwise the dirty value just round-trips back out
    of ``recent_jobs`` on the next read. Only floats are touched; dict/list/
    tuple recurse, everything else passes through unchanged."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _finite_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_json_safe(v) for v in value]
    return value


# Fields safe to surface on the public /jobs/active HTTP response. The raw
# job record also carries ``params`` (the user's POST body) plus internal
# diagnostics (trace_id, result_summary, cancel_*); the leave-guard only
# reads id/status/step, so we allowlist the display-relevant fields and never
# leak the rest off-box.
_PUBLIC_JOB_FIELDS = (
    "job_id",
    "workspace",
    "step",
    "status",
    "current_step",
    "progress",
    "started_at",
    "finished_at",
)


def public_job_view(job: Dict[str, Any]) -> Dict[str, Any]:
    """Project a job record down to the allowlisted public fields."""
    projected = {key: job.get(key) for key in _PUBLIC_JOB_FIELDS}
    projected["current_step"] = _public_current_step(
        job.get("current_step"), step=job.get("step")
    )
    return projected


# iter073 (codex D2/D3): explicit allowlists for the list + detail endpoints,
# so /jobs/recent and /job/<id> stop raw-passthrough'ing the whole record (a
# future internal field would auto-leak). The summary (list) view keeps
# ``params`` because the jobs-table drawer's "用相同参数重试" button reposts
# ``{step, params}`` straight from the list object (and jobChapterNumber falls
# back to params.resume_from) — dropping it would silently retry with empty
# params. It drops only the internal cancel_* flags, which no list consumer
# renders. The detail view adds cancel_* for the /job/<id> poll banner. The
# real params-drop is at the **overview** endpoint (public_job_view), the
# multi-workspace home that otherwise leaked every workspace's POST body.
# trace_id stays on both as a copy-able correlation id.
_PUBLIC_JOB_SUMMARY_FIELDS = _PUBLIC_JOB_FIELDS + (
    "error",
    "trace_id",
    "result_summary",
    "params",
    "persistence_degraded",
)
_PUBLIC_JOB_DETAIL_FIELDS = _PUBLIC_JOB_SUMMARY_FIELDS + (
    "cancel_requested",
    "cancel_reason",
)


_RETRY_PARAM_KEYS_BY_STEP: Dict[str, frozenset[str]] = {
    "normalize": frozenset({"lang"}),
    "split": frozenset({"lang"}),
    "extract": frozenset({"limit", "force", "reextract", "max_model_requests"}),
    "compress": frozenset({"max_model_requests"}),
    "bootstrap": frozenset({"max_model_requests"}),
    "apply-bootstrap": frozenset({"name", "apply"}),
    "debate": frozenset({"force", "max_model_requests"}),
    "plan-chapters": frozenset({"target_chapters", "force", "max_model_requests"}),
    "write-book": frozenset(
        {
            "chapters",
            "resume_from",
            "tier",
            "budget_cny",
            "min_confidence",
            "require_plan",
            "from_chapter",
            "max_model_requests",
        }
    ),
    "review-chapter": frozenset({"chapter", "tier", "budget_cny", "max_model_requests"}),
    "draft-once-dev": frozenset({"chapter", "max_model_requests"}),
    "auto-pipeline-greenfield": frozenset(
        {"extract_limit", "chapters", "force", "skip_extract", "max_model_requests"}
    ),
    "prepare-import": frozenset(),
    "prepare-greenfield": frozenset(
        {"extract_limit", "budget_cny", "force", "max_model_requests"}
    ),
    "rebuild-for-start": frozenset(
        {"chapter", "window", "budget_cny", "force", "max_model_requests"}
    ),
    "expand-premise": frozenset({"force", "max_model_requests"}),
}
for _model_retry_step in NOVEL_MODEL_REQUEST_DEFAULTS:
    if _model_retry_step in _RETRY_PARAM_KEYS_BY_STEP and _model_retry_step != "extract-style":
        _RETRY_PARAM_KEYS_BY_STEP[_model_retry_step] = frozenset(
            set(_RETRY_PARAM_KEYS_BY_STEP[_model_retry_step])
            | {"budget_cny", "timeout_minutes", "max_model_requests"}
        )
_NON_RETRYABLE_STEPS = frozenset({"extract-style"})
_RETRY_BOOL_KEYS = frozenset(
    {
        "apply",
        "force",
        "reextract",
        "require_plan",
        "skip_extract",
    }
)
_RETRY_INT_KEYS = frozenset(
    {
        "chapter",
        "chapters",
        "extract_limit",
        "from_chapter",
        "limit",
        "resume_from",
        "target_chapters",
        "window",
        "max_model_requests",
    }
)
_RETRY_FLOAT_KEYS = frozenset({"budget_cny", "min_confidence", "timeout_minutes"})
_RETRY_TOKEN_KEYS = frozenset({"lang", "name", "tier"})
_PUBLIC_RESULT_KEYS = frozenset(
    {
        "acceptance_level",
        "applied",
        "blocked",
        "budget_cny",
        "chapter",
        "chapters",
        "chapters_written",
        "cost_cny",
        "count",
        "error_code",
        "estimated",
        "extracted",
        "fact_count",
        "failure_reason",
        "first_blocked",
        "holder",
        "keys",
        "partial",
        "progress",
        "ratio",
        "reason",
        "skipped",
        "status",
        "strict_failures",
        "source",
        "verdict",
        "window",
        "workspace_locked",
    }
)
_PUBLIC_FAILURE_REASONS = frozenset(
    {
        "submission_unknown",
        "provider_unavailable",
        "request_limit_exhausted",
        "context_too_large",
        "job_timeout",
        "generation_failed",
        "response_validation_failed",
        "accounting_unavailable",
        "task_failed",
    }
)
_PUBLIC_CURRENT_STEP_EXACT = frozenset(
    {
        "expand", "normalize", "split", "extract", "compress", "bootstrap",
        "apply-bootstrap", "debate", "debate-decisions", "debate-ballot",
        "debate-outline", "plan", "plan-chapters", "write", "review", "polish",
        "sync-meta", "done", "succeeded", "failed", "cancelled", "timeout",
        "blocked", "budget_exceeded",
    }
)


def _public_current_step(value: Any, *, step: Any) -> Optional[str]:
    """Project progress to content-free tokens before HTTP or persistence."""

    raw = value if isinstance(value, str) else ""
    if raw in _PUBLIC_CURRENT_STEP_EXACT:
        return raw
    if raw.startswith("extract:"):
        return "extract:chapter"
    if raw.startswith("compress:"):
        return "compress:stage"
    if raw.startswith("bootstrap:"):
        return "bootstrap:item"
    if re.fullmatch(r"debate-round-[0-9]{1,3}", raw):
        return raw
    if raw.startswith(("debate-", "debate:")):
        return "debate"
    if re.fullmatch(r"replan-after-[0-9]{1,4}", raw):
        return "plan-chapters"
    if re.fullmatch(r"chapter-[0-9]{1,4}", raw):
        return raw
    if re.fullmatch(
        r"chapter-[0-9]{1,4}(?:/retry-[0-9]{1,3})?/(?:write-attempt-[0-9]{1,3}|review-attempt-[0-9]{1,3}|review-done-attempt-[0-9]{1,3}|polish|style-rewrite|style-rewrite-review|finalize|sync-meta|caveat_continue)",
        raw,
    ):
        return raw
    return step if isinstance(step, str) and step in STEP_HANDLERS else None


def _bounded_public_value(
    value: Any,
    *,
    depth: int = 0,
    field: Optional[str] = None,
) -> Any:
    if depth > 4:
        return None
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        text = value.strip()
        if field == "failure_reason":
            return text if text in _PUBLIC_FAILURE_REASONS else None
        if re.fullmatch(r"[\w.:/+@-]{0,160}", text, flags=re.UNICODE) and not (
            "://" in text
            or text.startswith(("/", "~"))
            or _looks_like_credential(text)
        ):
            return text
        return "[redacted]"
    if isinstance(value, list):
        return [
            _bounded_public_value(item, depth=depth + 1, field=field)
            for item in value[:32]
        ]
    if isinstance(value, dict):
        return {
            key: _bounded_public_value(item, depth=depth + 1, field=key)
            for key, item in value.items()
            if isinstance(key, str) and key in _PUBLIC_RESULT_KEYS
        }
    return None


def _looks_like_credential(text: str) -> bool:
    """Reject credential grammars even when the surrounding field looks safe."""

    if re.search(
        r"(?i)(?:bearer|api[_-]?key|token|secret|password|"
        r"sk-|AIza[0-9A-Za-z_-]{20,}|AKIA[0-9A-Z]{16}|"
        r"gh[pousr]_[0-9A-Za-z]{20,}|xox[baprs]-|"
        r"(?:sk|rk|pk)_live_[0-9A-Za-z]+|-----BEGIN)",
        text,
    ):
        return True
    return bool(
        re.fullmatch(
            r"eyJ[0-9A-Za-z_-]{8,}\.[0-9A-Za-z_-]{8,}\.[0-9A-Za-z_-]{8,}",
            text,
        )
    )


def _typed_retry_value(key: str, value: Any) -> Any:
    if key in _RETRY_BOOL_KEYS:
        return value if isinstance(value, bool) else None
    if key in _RETRY_INT_KEYS:
        return (
            value
            if isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= 10_000
            else None
        )
    if key in _RETRY_FLOAT_KEYS:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        maximum = 40.0 if key == "budget_cny" else 120.0 if key == "timeout_minutes" else 1.0
        lower_ok = number >= 0 if key == "min_confidence" else number > 0
        return value if lower_ok and number <= maximum else None
    if key in _RETRY_TOKEN_KEYS:
        text = value.strip() if isinstance(value, str) else ""
        if (
            re.fullmatch(r"[\w.-]{1,80}", text, flags=re.UNICODE)
            and _bounded_public_value(text) != "[redacted]"
        ):
            return text
        return None
    return None


def _public_retry_params(value: Any, *, step: Any = None) -> Dict[str, Any]:
    """Return replayable parameters without one-shot paid authorization.

    Job history is durable and the UI can repost these parameters months later.
    A confirmation is consent for one invocation, not reusable job state, so no
    ``confirm_*`` field may cross this projection boundary.
    """

    allowed = _RETRY_PARAM_KEYS_BY_STEP.get(step)
    if not isinstance(value, dict) or allowed is None:
        return {}
    projected: Dict[str, Any] = {}
    for key in allowed:
        if key not in value:
            continue
        item = _typed_retry_value(key, value[key])
        if item is not None:
            projected[key] = item
    return projected


def _job_retryable(job: Dict[str, Any]) -> bool:
    status = str(job.get("status") or "")
    if status in {"lost", "submission_unknown"} or status not in (
        {"pending", "running"} | TERMINAL_STATUSES
    ):
        return False
    summary = job.get("result_summary")
    if isinstance(summary, dict) and summary.get("failure_reason") == "submission_unknown":
        return False
    if type(job.get("retryable")) is bool:
        return bool(job["retryable"])
    step = job.get("step")
    if step in _NON_RETRYABLE_STEPS or step not in _RETRY_PARAM_KEYS_BY_STEP:
        return False
    if step == "debate" and job.get("params", {}).get("topic") not in (None, ""):
        return False
    params = job.get("params")
    if not isinstance(params, dict):
        return False
    allowed = _RETRY_PARAM_KEYS_BY_STEP[step]
    if any(
        not isinstance(key, str)
        or key not in allowed
        or key.startswith("confirm_")
        for key in params
    ):
        return False
    projected = _public_retry_params(params, step=step)
    return projected == params


def _public_result_summary(value: Any) -> Any:
    return _bounded_public_value(value)


def _public_error(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if value in {
        "workspace locked",
        "job timed out",
        "user requested cancel",
    }:
        return str(value)
    return "job_failed"


def _public_reconciliation_reason(job: Dict[str, Any]) -> Optional[str]:
    """Expose a bounded recovery enum without leaking the raw exception."""

    if job.get("status") == "lost" and job.get("error") == _WORKER_RESTART_ERROR:
        return "worker_restart"
    return None


def public_job_summary_view(job: Dict[str, Any]) -> Dict[str, Any]:
    """Project for /jobs/recent (sidebar + jobs table) — drops internal cancel_*."""
    projected = {key: job.get(key) for key in _PUBLIC_JOB_SUMMARY_FIELDS}
    projected["current_step"] = _public_current_step(
        job.get("current_step"), step=job.get("step")
    )
    projected["params"] = _public_retry_params(job.get("params"), step=job.get("step"))
    projected["retryable"] = _job_retryable(job)
    projected["error"] = _public_error(job.get("error"))
    projected["result_summary"] = _public_result_summary(job.get("result_summary"))
    reconciliation_reason = _public_reconciliation_reason(job)
    if reconciliation_reason is not None:
        projected["reconciliation_reason"] = reconciliation_reason
    if not isinstance(job.get("persistence_degraded"), bool):
        projected.pop("persistence_degraded", None)
    return projected


def public_job_detail_view(job: Dict[str, Any]) -> Dict[str, Any]:
    """Project for /job/<id> — adds cancel_* (poll banner) on top of summary."""
    projected = {key: job.get(key) for key in _PUBLIC_JOB_DETAIL_FIELDS}
    projected["current_step"] = _public_current_step(
        job.get("current_step"), step=job.get("step")
    )
    projected["params"] = _public_retry_params(job.get("params"), step=job.get("step"))
    projected["retryable"] = _job_retryable(job)
    projected["error"] = _public_error(job.get("error"))
    projected["result_summary"] = _public_result_summary(job.get("result_summary"))
    reconciliation_reason = _public_reconciliation_reason(job)
    if reconciliation_reason is not None:
        projected["reconciliation_reason"] = reconciliation_reason
    if not isinstance(job.get("persistence_degraded"), bool):
        projected.pop("persistence_degraded", None)
    return projected


def _new_job_record(workspace: str, step: str, params: Dict[str, Any]) -> Dict[str, Any]:
    record = {
        "job_id": uuid.uuid4().hex,
        "workspace": workspace,
        "step": step,
        "params": dict(params),
        "status": "pending",
        "current_step": None,
        "progress": 0.0,
        "started_at": None,
        "finished_at": None,
        "error": None,
        "trace_id": None,
        "result_summary": None,
        "cancel_requested": False,
        "cancel_reason": None,
    }
    return record


def _job_log_path(workspace: str) -> Path:
    return paths.WORKSPACE_DIR / workspace / "logs" / "web_jobs.jsonl"


def _open_job_logs_directory(workspace: str, *, create: bool) -> Optional[int]:
    try:
        paths.workspace_root(workspace)
    except ValueError:
        return None
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        return None
    root_fd: Optional[int] = None
    workspace_fd: Optional[int] = None
    try:
        root_fd = os.open(
            str(paths.WORKSPACE_DIR),
            os.O_RDONLY | directory | nofollow,
        )
        workspace_fd = os.open(
            workspace,
            os.O_RDONLY | directory | nofollow,
            dir_fd=root_fd,
        )
        try:
            return os.open(
                "logs",
                os.O_RDONLY | directory | nofollow,
                dir_fd=workspace_fd,
            )
        except FileNotFoundError:
            if not create:
                return None
            os.mkdir("logs", mode=0o700, dir_fd=workspace_fd)
            return os.open(
                "logs",
                os.O_RDONLY | directory | nofollow,
                dir_fd=workspace_fd,
            )
    except (FileNotFoundError, NotADirectoryError, OSError):
        return None
    finally:
        if workspace_fd is not None:
            os.close(workspace_fd)
        if root_fd is not None:
            os.close(root_fd)


def _read_job_rows(workspace: str) -> list[Dict[str, Any]]:
    # Avoid a false empty projection when a local worker is in the tiny append
    # critical section.  The file-level lock below remains non-blocking, so an
    # unrelated process can never hold this request indefinitely.
    with _JOB_LOG_LOCK:
        return _read_job_rows_unlocked(workspace)


def _job_log_current(workspace: str, directory_fd: int, before: Any, workspace_identity: Any) -> bool:
    try:
        current = os.stat("web_jobs.jsonl", dir_fd=directory_fd, follow_symlinks=False)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
        return (stat.S_ISREG(current.st_mode) and identity(current) == identity(before)
                and workspace_identity is not None and paths.workspace_identity_matches(workspace_identity))
    except OSError:
        return False


def _read_job_rows_unlocked(workspace: str) -> list[Dict[str, Any]]:
    workspace_identity = paths.probe_workspace_identity(workspace)
    directory_fd = _open_job_logs_directory(workspace, create=False)
    if directory_fd is None:
        return []
    file_fd: Optional[int] = None
    try:
        file_fd = os.open(
            "web_jobs.jsonl",
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory_fd,
        )
        fcntl.flock(file_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_JOB_LOG_BYTES:
            return []
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(64 * 1024, _MAX_JOB_LOG_BYTES + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_JOB_LOG_BYTES:
                return []
            chunks.append(chunk)
        after = os.fstat(file_fd)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
        if identity(before) != identity(after):
            return []
        lines = b"".join(chunks).splitlines()
        if len(lines) > _MAX_JOB_LOG_ROWS:
            return []
        rows: list[Dict[str, Any]] = []
        for line in lines:
            if len(line) > _MAX_JOB_LOG_LINE_BYTES:
                return []
            try:
                row = json.loads(line)
            except (UnicodeDecodeError, ValueError, RecursionError):
                return []
            if not isinstance(row, dict):
                return []
            rows.append(row)
        return rows if _job_log_current(workspace, directory_fd, before, workspace_identity) else []
    except (FileNotFoundError, OSError):
        return []
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)


def _read_job_rows_for_recovery(workspace: str) -> tuple[str, list[Dict[str, Any]]]:
    """Read the paid-write ledger without collapsing uncertainty to empty.

    General UI projections historically degrade a damaged/busy ledger to an
    empty list.  Recovery admission cannot: empty means "safe to submit" while
    an unreadable ledger may hide a pending or submission-unknown paid job.
    Return ``absent`` only for a genuinely missing logs directory/file,
    ``ok`` for a fully verified snapshot, and ``indeterminate`` for every
    unsafe, oversized, locked, malformed, or racing state.
    """

    with _JOB_LOG_LOCK:
        workspace_identity = paths.probe_workspace_identity(workspace)
        logs_path = paths.WORKSPACE_DIR / workspace / "logs"
        try:
            logs_stat = os.lstat(logs_path)
        except FileNotFoundError:
            return "absent", []
        except OSError:
            return "indeterminate", []
        if not stat.S_ISDIR(logs_stat.st_mode) or stat.S_ISLNK(logs_stat.st_mode):
            return "indeterminate", []

        directory_fd = _open_job_logs_directory(workspace, create=False)
        if directory_fd is None:
            # The directory existed at lstat time but could not be opened with
            # the no-follow identity walk.  Treat the race/identity mismatch as
            # unknown rather than as a clean workspace.
            return "indeterminate", []
        file_fd: Optional[int] = None
        try:
            try:
                file_fd = os.open(
                    "web_jobs.jsonl",
                    os.O_RDONLY
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_NONBLOCK", 0),
                    dir_fd=directory_fd,
                )
            except FileNotFoundError:
                return "absent", []
            fcntl.flock(file_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_JOB_LOG_BYTES:
                return "indeterminate", []
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(file_fd, min(64 * 1024, _MAX_JOB_LOG_BYTES + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_JOB_LOG_BYTES:
                    return "indeterminate", []
                chunks.append(chunk)
            after = os.fstat(file_fd)
            identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
            if identity(before) != identity(after):
                return "indeterminate", []
            lines = b"".join(chunks).splitlines()
            if len(lines) > _MAX_JOB_LOG_ROWS:
                return "indeterminate", []
            rows: list[Dict[str, Any]] = []
            for line in lines:
                if len(line) > _MAX_JOB_LOG_LINE_BYTES:
                    return "indeterminate", []
                try:
                    row = json.loads(line)
                except (UnicodeDecodeError, ValueError, RecursionError):
                    return "indeterminate", []
                if not isinstance(row, dict):
                    return "indeterminate", []
                rows.append(row)
            if not _job_log_current(workspace, directory_fd, before, workspace_identity):
                return "indeterminate", []
            return "ok", rows
        except OSError:
            return "indeterminate", []
        finally:
            if file_fd is not None:
                os.close(file_fd)
            os.close(directory_fd)


def _logical_job_rows(rows: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """Lossless per-job latest projection with an append-history digest.

    First insertion order remains creation order. Compaction changes neither
    this projection nor recovery CAS; even an A->B->A update changes its hash.
    """
    latest: dict[str, Dict[str, Any]] = {}
    for row in rows:
        jid = row.get("job_id")
        if not isinstance(jid, str) or not jid:
            raise ValueError("job ledger identity missing")
        previous = latest.get(jid, {})
        item = dict(row)
        digest = item.get("_history_digest")
        if digest is not None:
            if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
                raise ValueError("job ledger history invalid")
        else:
            encoded = json.dumps(item, sort_keys=True, ensure_ascii=False,
                                 separators=(",", ":"), allow_nan=False).encode("utf-8")
            item["_history_digest"] = hashlib.sha256(
                str(previous.get("_history_digest", "")).encode("ascii") + b"\x00" + encoded
            ).hexdigest()
        latest[jid] = item
    return list(latest.values())


def _persist_job(job: Dict[str, Any]) -> bool:
    """Append one durable job row, restoring the prior length on failure."""
    try:
        workspace = str(job.get("workspace") or "")
        durable = {key: job.get(key) for key in _PUBLIC_JOB_DETAIL_FIELDS}
        durable["current_step"] = _public_current_step(
            job.get("current_step"), step=job.get("step")
        )
        if not isinstance(job.get("persistence_degraded"), bool):
            durable.pop("persistence_degraded", None)
        durable["params"] = _public_retry_params(
            job.get("params"),
            step=job.get("step"),
        )
        durable["retryable"] = _job_retryable(job)
        durable["error"] = _public_error(job.get("error"))
        durable["result_summary"] = _public_result_summary(job.get("result_summary"))
        payload = (
            json.dumps(
                _finite_json_safe(durable),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        if len(payload) > _MAX_JOB_LOG_LINE_BYTES:
            return False
        with _JOB_LOG_LOCK:
            directory_fd = _open_job_logs_directory(workspace, create=True)
            if directory_fd is None:
                return False
            file_fd: Optional[int] = None
            original_size: Optional[int] = None
            lock_fd: Optional[int] = None
            temp_name: Optional[str] = None
            try:
                lock_fd = os.open("web_jobs.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory_fd)
                if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
                    return False
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                file_fd = os.open(
                    "web_jobs.jsonl",
                    os.O_RDWR
                    | os.O_APPEND
                    | os.O_CREAT
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_NONBLOCK", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
                fcntl.flock(file_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                info = os.fstat(file_fd)
                if not stat.S_ISREG(info.st_mode):
                    return False
                if info.st_size > _MAX_JOB_LOG_BYTES:
                    return False
                raw = os.pread(file_fd, _MAX_JOB_LOG_BYTES + 1, 0)
                lines = raw.splitlines()
                if any(len(line) > _MAX_JOB_LOG_LINE_BYTES for line in lines):
                    return False
                rows = [json.loads(line) for line in lines]
                if any(not isinstance(row, dict) for row in rows):
                    return False
                logical = _logical_job_rows(rows)
                # The new row extends its job's logical history exactly once.
                previous = next((row for row in logical if row.get("job_id") == durable.get("job_id")), {})
                encoded = json.dumps(_finite_json_safe(durable), sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")
                durable["_history_digest"] = hashlib.sha256(
                    str(previous.get("_history_digest", "")).encode("ascii") + b"\x00" + encoded
                ).hexdigest()
                payload = json.dumps(_finite_json_safe(durable), ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":")).encode("utf-8") + b"\n"
                if len(payload) > _MAX_JOB_LOG_LINE_BYTES:
                    return False
                if info.st_size + len(payload) > _MAX_JOB_LOG_BYTES or len(lines) + 1 > _MAX_JOB_LOG_ROWS:
                    compacted = _logical_job_rows(logical + [durable])
                    compact_bytes = b"".join(json.dumps(row, ensure_ascii=False, allow_nan=False,
                        separators=(",", ":")).encode("utf-8") + b"\n" for row in compacted)
                    # Never evict active/unknown or recovery authority to make room.
                    if len(compacted) > _MAX_JOB_LOG_ROWS or len(compact_bytes) > _MAX_JOB_LOG_BYTES:
                        return False
                    temp_name = "web_jobs." + uuid.uuid4().hex + ".tmp"
                    tmp_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     0o600, dir_fd=directory_fd)
                    try:
                        with os.fdopen(tmp_fd, "wb") as handle:
                            handle.write(compact_bytes)
                            handle.flush()
                            os.fsync(handle.fileno())
                        current = os.stat("web_jobs.jsonl", dir_fd=directory_fd, follow_symlinks=False)
                        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                            return False
                        os.replace(temp_name, "web_jobs.jsonl", src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
                        temp_name = None
                        os.fsync(directory_fd)
                        return True
                    finally:
                        if temp_name is not None:
                            os.unlink(temp_name, dir_fd=directory_fd)
                            temp_name = None
                original_size = info.st_size
                written = os.write(file_fd, payload)
                if written != len(payload):
                    raise OSError("short job persistence write")
                os.fsync(file_fd)
                return True
            except OSError:
                if file_fd is not None and original_size is not None:
                    try:
                        os.ftruncate(file_fd, original_size)
                        os.fsync(file_fd)
                    except OSError:
                        pass
                return False
            finally:
                if file_fd is not None:
                    os.close(file_fd)
                if lock_fd is not None:
                    os.close(lock_fd)
                os.close(directory_fd)
    except (OSError, TypeError, ValueError, RecursionError, OverflowError):
        return False


def _mark_persistence_degraded(job_id: str) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job["persistence_degraded"] = True


def _load_persisted_job(job_id: str) -> Optional[Dict[str, Any]]:
    latest: Optional[Dict[str, Any]] = None
    try:
        with os.scandir(paths.WORKSPACE_DIR) as entries:
            names = [
                entry.name
                for entry in entries
                if entry.is_dir(follow_symlinks=False)
            ]
    except OSError:
        return None
    if len(names) > _MAX_JOB_WORKSPACES:
        return None
    for workspace in sorted(names):
        for row in _read_job_rows(workspace):
            if row.get("workspace") == workspace and row.get("job_id") == job_id:
                latest = row
    return latest


def _load_persisted_job_for_workspace(
    workspace: str,
    job_id: str,
) -> Optional[Dict[str, Any]]:
    """Read exactly one validated workspace ledger for an HTTP lookup."""

    latest: Optional[Dict[str, Any]] = None
    for row in _read_job_rows(workspace):
        if row.get("workspace") == workspace and row.get("job_id") == job_id:
            latest = row
    return latest


def recent_jobs(workspace: str, limit: int = 5) -> list[Dict[str, Any]]:
    """Return the latest persisted jobs for a workspace.

    The dashboard uses this after a browser refresh, when in-memory job
    state may be gone but ``logs/web_jobs.jsonl`` still has terminal rows.
    """

    limit = max(1, min(int(limit or 5), 50))
    latest_by_id: Dict[str, Dict[str, Any]] = {}
    for row in _read_job_rows(workspace):
        if not isinstance(row, dict) or row.get("workspace") != workspace:
            continue
        job_id = str(row.get("job_id") or "")
        if not job_id:
            continue
        latest_by_id[job_id] = row
    def _sort_key(item: Dict[str, Any]) -> tuple[int, float]:
        # iter073 (codex C): sort AFTER lost-reconciliation (below). A
        # pending/running row whose worker is gone is reconciled to "lost"
        # (terminal) first, so it no longer counts as active=1 and can't pin a
        # stale row above a newer succeeded job — that was the overview limit=1
        # bug (旧 lost 长期压过新成功). Genuinely-live pending/running keep
        # active=1 (iter072 #5 intent). ``_as_ts`` swallows corrupt timestamps
        # so one bad jsonl row can't 500 the whole list.
        active = 1 if item.get("status") in {"pending", "running"} else 0
        return (active, _as_ts(item.get("finished_at")) or _as_ts(item.get("started_at")))

    # Reconcile lost-ness BEFORE sorting/slicing. Snapshot the in-memory pool
    # ONCE (not get_job per row): the persisted row is already in hand, so
    # get_job's persisted-fallback glob would be wasted, and an in-memory record
    # is always at least as fresh as the jsonl row (use it as-is, running OR
    # already-terminal). One lock acquire keeps a hot poll endpoint cheap and
    # gives a consistent instant. No live record ⇒ the worker restarted before
    # reaching a terminal state ⇒ lost.
    with _JOBS_LOCK:
        live_pool = dict(_JOBS)
    reconciled: list[Dict[str, Any]] = []
    for job_id, row in latest_by_id.items():
        snapshot = dict(row)
        if snapshot.get("status") in {"pending", "running"}:
            live = live_pool.get(job_id)
            if live is not None:
                snapshot = dict(live)
            else:
                snapshot["status"] = "lost"
                snapshot["error"] = _WORKER_RESTART_ERROR
        reconciled.append(snapshot)

    reconciled.sort(key=_sort_key, reverse=True)
    return reconciled[:limit]


def _latest_write_job_from_rows(
    workspace: str,
    chapter: int,
    rows: list[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    latest_by_id: Dict[str, Dict[str, Any]] = {}
    creation_order: Dict[str, int] = {}
    for sequence, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("workspace") != workspace or row.get("step") != "write-book":
            continue
        params = row.get("params")
        if not isinstance(params, dict):
            continue
        try:
            first = int(params.get("resume_from", 1))
            count = int(params.get("chapters", 1))
        except (TypeError, ValueError, OverflowError):
            continue
        if count < 1 or not first <= int(chapter) < first + count:
            continue
        job_id = str(row.get("job_id") or "")
        if job_id:
            creation_order.setdefault(job_id, sequence)
            latest_by_id[job_id] = row
    if not latest_by_id:
        return None
    # Pending rows deliberately have no timestamp.  Picking by started/finished
    # time would therefore let an older terminal row hide a newer lost pending
    # write after restart and incorrectly reopen the paid recovery entrypoint.
    # The ledger is append-only and the workspace slot serializes jobs, so the
    # first-seen row order is the authoritative creation order.
    latest_job_id = max(creation_order, key=creation_order.__getitem__)
    latest = latest_by_id[latest_job_id]
    snapshot = dict(latest)
    if snapshot.get("status") in {"pending", "running"}:
        with _JOBS_LOCK:
            live = _JOBS.get(str(snapshot.get("job_id") or ""))
            snapshot = dict(live) if live is not None else snapshot
        if live is None:
            snapshot["status"] = "lost"
            snapshot["error"] = _WORKER_RESTART_ERROR
    return snapshot


def latest_write_job_for_chapter(workspace: str, chapter: int) -> Optional[Dict[str, Any]]:
    """Return the untruncated latest write job whose range covers ``chapter``.

    This compatibility helper retains the UI reader's degraded-empty behavior.
    Paid recovery admission must call ``write_recovery_job_ledger`` instead so
    an unreadable ledger cannot be mistaken for no prior job.
    """

    return _latest_write_job_from_rows(workspace, chapter, _read_job_rows(workspace))


def write_recovery_job_ledger(
    workspace: str,
    chapter: int,
) -> tuple[str, Optional[Dict[str, Any]]]:
    """Return ``(absent|ok|indeterminate, latest_chapter_write)`` safely."""

    ledger_state, latest, _claim = write_recovery_job_claim(workspace, chapter)
    return ledger_state, latest


def write_recovery_job_claim(
    workspace: str,
    chapter: int,
    *,
    exclude_job_id: str = "",
    require_excluded_active_row: bool = False,
) -> tuple[str, Optional[Dict[str, Any]], Optional[str]]:
    """Return strict ledger state, latest write, and a durable CAS digest.

    The digest covers every verified ledger row except rows for the supplied
    current recovery job.  A worker can therefore prove that no foreign job
    was appended or updated between HTTP admission and its write-lock-held
    precondition, even when process-local workspace slots cannot see another
    Web process.
    """

    ledger_state, rows = _read_job_rows_for_recovery(workspace)
    if ledger_state == "indeterminate":
        return ledger_state, None, None
    excluded_rows = [
        row
        for row in rows
        if exclude_job_id and str(row.get("job_id") or "") == exclude_job_id
    ]
    if require_excluded_active_row:
        own = excluded_rows[-1] if excluded_rows else None
        own_params = own.get("params") if isinstance(own, dict) else None
        try:
            own_first = int(own_params.get("resume_from", 1))
            own_count = int(own_params.get("chapters", 1))
        except (AttributeError, TypeError, ValueError, OverflowError):
            return "indeterminate", None, None
        if not (
            ledger_state == "ok"
            and isinstance(own, dict)
            and own.get("workspace") == workspace
            and own.get("step") == "write-book"
            and own.get("status") in {"pending", "running"}
            and own_count == 1
            and own_first == chapter
        ):
            return "indeterminate", None, None
    claim_rows = [
        row
        for row in rows
        if not exclude_job_id or str(row.get("job_id") or "") != exclude_job_id
    ]
    # The worker's own pending/running row is not prior recovery authority.
    # Compute both the CAS digest and the latest predecessor from the exact
    # same filtered row set so a newly admitted recovery job cannot authorize
    # itself.
    latest = _latest_write_job_from_rows(workspace, chapter, claim_rows)
    try:
        encoded = json.dumps(
            _logical_job_rows(claim_rows),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        return "indeterminate", None, None
    claim = hashlib.sha256(b"write-recovery-ledger-v2\x00" + encoded).hexdigest()
    return ledger_state, latest, claim


def is_exact_write_recovery_terminal(job: Any, chapter: int) -> bool:
    """Whether ``job`` durably records retry exhaustion for this chapter."""

    if not isinstance(job, dict) or type(chapter) is not int:
        return False
    summary = job.get("result_summary")
    first = summary.get("first_blocked") if isinstance(summary, dict) else None
    return bool(
        job.get("step") == "write-book"
        and job.get("status") == "blocked"
        and isinstance(first, dict)
        and first.get("reason") == "retry_exhausted"
        and type(first.get("chapter")) is int
        and first.get("chapter") == chapter
    )


def active_jobs(workspace: str) -> list[Dict[str, Any]]:
    """Return the workspace's live pending/running jobs from the in-memory pool.

    iter071 (codex F2): the leave-guard must answer "is a job in flight here?"
    completely. ``recent_jobs`` can't: it sorts by ``finished_at || started_at
    || 0`` and truncates to ``limit``, so a just-enqueued pending job (whose
    ``started_at`` is still ``None`` → sort key 0) sinks to the bottom and falls
    off ``?n=10`` once there are enough terminal rows. ``start_job`` registers a
    job in ``_JOBS`` the instant it's enqueued (status ``pending``), so scanning
    ``_JOBS`` is the authoritative, untruncated source — no log read, no sort,
    no recency window. A workspace holds at most one active job (the
    ``_WORKSPACE_JOBS`` slot + 409 on the second start), so this returns 0 or 1
    item; we keep the list shape to match ``recent_jobs`` / the ``{jobs: [...]}``
    contract the leave-guard already consumes. After a process restart ``_JOBS``
    is empty → ``[]`` → the guard fails open, which is correct: those jobs are no
    longer running, so warning "leaving won't stop them" would be a lie."""
    with _JOBS_LOCK:
        return [
            dict(job)
            for job in _JOBS.values()
            if job.get("workspace") == workspace
            and job.get("status") in {"pending", "running"}
        ]


def _update(job_id: str, **fields: Any) -> None:
    snapshot: Optional[Dict[str, Any]] = None
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job.update(fields)
        snapshot = dict(job)
        if snapshot is not None and not _persist_job(snapshot):
            _mark_persistence_degraded(job_id)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Return a snapshot of the job record, or None if unknown."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            return dict(job)
    persisted = _load_persisted_job(job_id)
    if persisted and persisted.get("status") in {"pending", "running"}:
        persisted = dict(persisted)
        persisted["status"] = "lost"
        persisted["error"] = "worker process restarted before this job reached a terminal state"
    return persisted


def get_job_for_workspace(workspace: str, job_id: str) -> Optional[Dict[str, Any]]:
    """Return a job only from the named workspace's memory/ledger boundary."""

    if not validate_workspace_name(workspace):
        return None
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            return dict(job) if job.get("workspace") == workspace else None
    persisted = _load_persisted_job_for_workspace(workspace, job_id)
    if persisted and persisted.get("status") in {"pending", "running"}:
        persisted = dict(persisted)
        persisted["status"] = "lost"
        persisted["error"] = "worker process restarted before this job reached a terminal state"
    return persisted


def request_cancel(
    job_id: str,
    reason: str = "user requested cancel",
    *,
    workspace: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Set the cooperative cancel flag and return the updated job snapshot.

    The worker checks this flag at progress boundaries. We intentionally do
    not kill the thread because the pipeline may be inside filesystem writes
    or a provider call; the next checkpoint moves the job to ``aborted``.
    """

    snapshot: Optional[Dict[str, Any]] = None
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return None
        if workspace is not None and job.get("workspace") != workspace:
            return None
        if str(job.get("status") or "") not in {"pending", "running"}:
            return None
        job["cancel_requested"] = True
        job["cancel_reason"] = reason
        snapshot = dict(job)
        if snapshot is not None and not _persist_job(snapshot):
            _mark_persistence_degraded(job_id)
            snapshot["persistence_degraded"] = True
    return snapshot


def _cancel_requested(job_id: str) -> Optional[str]:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return None
        if job.get("cancel_requested"):
            return str(job.get("cancel_reason") or "user requested cancel")
    return None


def _timeout_deadline(params: Dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    value = params.get("timeout_minutes")
    if value is None or value == "":
        return None, None
    try:
        timeout_minutes = float(value)
    except (TypeError, ValueError):
        return None, None
    # iter060 (Codex B): NaN/±inf survive the `<= 0` test below (IEEE-754 makes
    # every comparison with NaN False), producing a non-None but useless deadline
    # that _check_cancelled can never trip (`monotonic > nan` is always False).
    # Treat a non-finite timeout as "no timeout" so it can't silently disable the
    # guard even if a value reaches here outside the route validation.
    if not math.isfinite(timeout_minutes):
        return None, None
    if timeout_minutes <= 0:
        return None, None
    return time.monotonic() + timeout_minutes * 60.0, timeout_minutes


def _check_cancelled(job_id: str, deadline: Optional[float], timeout_minutes: Optional[float]) -> None:
    if deadline is not None and time.monotonic() > deadline:
        label = f"timeout after {timeout_minutes:g} minute(s)"
        request_cancel(job_id, label)
        raise JobTimeout(label)
    reason = _cancel_requested(job_id)
    if reason:
        raise JobCancelled(reason)


def _complete_job(job_id: str, terminal: str, step: str, result: Any) -> None:
    """Record a terminal result without racing a late cancel request."""

    snapshot: Optional[Dict[str, Any]] = None
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        committed = isinstance(result, dict) and result.get("committed") is True
        if job.get("cancel_requested") and not committed:
            job.update(
                {
                    "status": "aborted",
                    "current_step": "cancelled",
                    "error": str(job.get("cancel_reason") or "user requested cancel"),
                    "finished_at": _now(),
                }
            )
        else:
            terminal_error = "job_failed" if terminal == "failed" else job.get("error")
            job.update(
                {
                    "status": terminal,
                    "current_step": terminal,
                    "progress": 1.0,
                    "error": terminal_error,
                    "finished_at": _now(),
                    "result_summary": _summarize_result(step, result),
                }
            )
        snapshot = dict(job)
        if snapshot is not None and not _persist_job(snapshot):
            _mark_persistence_degraded(job_id)


def workspace_busy(workspace: str) -> Optional[str]:
    """Return the running job_id if ``workspace`` already has one,
    otherwise None. Cheap pre-check before starting a job."""
    with _WORKSPACE_LOCK:
        return _WORKSPACE_JOBS.get(workspace)


def workspace_running_job(workspace: str) -> Optional[str]:
    """Return the running job_id for ``workspace`` if any, else None."""
    with _WORKSPACE_LOCK:
        return _WORKSPACE_JOBS.get(workspace)


@contextmanager
def workspace_reserved(workspace: str):
    """Reserve a workspace slot for a destructive operation.

    Raises ``RuntimeError("workspace_busy:<jid>")`` if a job is already
    active. While reserved, ``start_job`` sees the workspace as busy and
    fails the same way, closing the delete-vs-job-start race.
    """

    marker = "__reserved_delete__"
    with _WORKSPACE_LOCK:
        existing = _WORKSPACE_JOBS.get(workspace)
        if existing:
            raise RuntimeError(f"workspace_busy:{existing}")
        _WORKSPACE_JOBS[workspace] = marker
    try:
        yield
    finally:
        with _WORKSPACE_LOCK:
            if _WORKSPACE_JOBS.get(workspace) == marker:
                del _WORKSPACE_JOBS[workspace]


# ---- step dispatch ---------------------------------------------------------


# iter 048d (A4): each prep step now reports a friendly ``blocked`` dict
# when its prerequisite artifact is missing, instead of letting a raw
# FileNotFoundError bubble up to ``failed``. The workbench UI surfaces the
# ``reason`` field directly to the user, so the step graph stays
# self-explanatory even when the user clicks out of order. Pattern lifted
# from ``_step_plan_chapters``.
def _blocked(reason: str, error: str, **extra: Any) -> Dict[str, Any]:
    item = {"reason": reason, "error": error}
    item.update(extra)
    return {"status": "blocked", "blocked": [item]}


def _workspace_locked_blocked(exc: BaseException | str) -> Dict[str, Any]:
    """Project raw WorkspaceLocked diagnostics to a Web-safe blocker.

    ``WorkspaceLocked`` messages intentionally include local CLI diagnostics
    (absolute lock path and argv) for terminal users. Web job rows are exposed
    through /job and /jobs/recent, so persist only an allowlisted holder summary.
    """
    msg = str(exc)
    holder: Dict[str, str] = {}
    source_match = re.search(r"\bsource=([^)\s]+)", msg)
    since_match = re.search(r"\bsince=([^)\s]+)", msg)
    if source_match:
        holder["source"] = source_match.group(1)
    if since_match:
        holder["started_at"] = since_match.group(1)
    return _blocked(
        "workspace_locked",
        "workspace locked",
        workspace_locked=True,
        holder=holder,
    )


# Each step function takes a workspace-scoped context (the worker
# already set ``WORKSPACE_NAME`` via use_workspace) and the POST body's
# ``params`` dict. The function should accept ``progress_cb`` if it
# can report sub-progress; otherwise the worker reports only entry +
# exit (progress 0.0 → 1.0).
def _step_normalize(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    # normalize has no prep prerequisite — the raw .txt in 小说txt/ is the
    # entry point. If the dir is empty normalize_all returns [] silently
    # and the user sees "0 normalized" downstream.
    return normalize_all(lang=params.get("lang"))


def _step_split(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    norm_dir = paths.normalized_dir()
    # iter059 #9: normalize_all writes `<volume>.txt` (text_normalizer), so a
    # `*.md`-only gate left single-step split permanently blocked as
    # `normalized_missing` even after a successful normalize. Recognize the
    # actual `.txt` output (keep `.md` for forward-compat). The auto-pipeline
    # path calls split_all() directly and never hit this gate.
    if not norm_dir.exists() or not (
        any(norm_dir.glob("*.txt")) or any(norm_dir.glob("*.md"))
    ):
        return _blocked(
            "normalized_missing",
            "no normalized chapters found; run `normalize` first",
        )
    return split_all(lang=params.get("lang"))


def _step_extract(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    if not paths.chapter_manifest_path().exists():
        return _blocked(
            "manifest_missing",
            "chapter manifest not found; run `split` first",
        )
    # iter058 #2: surface per-chapter extraction failures instead of silently
    # returning a short results list (raise_on_failure=False used to swallow
    # them into data/extraction_failures/ and report success). Chapters that DID
    # extract are already on disk, so re-running this step resumes only the
    # failures. The standalone step degrades to a friendly, retryable blocker;
    # the onboarding pipeline instead aborts loudly (see auto_pipeline).
    try:
        return extract_all(
            volume=params.get("volume", "all"),
            limit=params.get("limit"),
            force=bool(params.get("force", False)),
            raise_on_failure=True,
            progress_cb=progress_cb,
        )
    except ExtractionBatchFailure as exc:
        return _blocked("extraction_failures", str(exc))


def _step_compress(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    ex_dir = paths.extracted_dir()
    if not ex_dir.exists() or not any(ex_dir.glob("*.json")):
        return _blocked(
            "extractions_missing",
            "no extracted JSON found; run `extract` first",
        )
    return compress_all(progress_cb=progress_cb)


def _step_bootstrap_all(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    ex_dir = paths.extracted_dir()
    if not ex_dir.exists() or not any(ex_dir.glob("*.json")):
        return _blocked(
            "extractions_missing",
            "no extracted JSON found; run `extract` first",
        )
    return bootstrap_all(force=bool(params.get("force", False)), progress_cb=progress_cb)


def _step_apply_bootstrap(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    name = params.get("name")
    if not name:
        raise ValueError("apply-bootstrap requires params.name")
    proposal_path = paths.proposals_dir() / f"{name}.json"
    if not proposal_path.exists():
        return _blocked(
            "proposal_missing",
            f"proposal '{name}' not found; run `bootstrap` first",
        )
    return apply_bootstrap(name, confirm=True)


def _step_debate(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    # iter 048d (A4): KB readiness check — without this, run_debate raises
    # FileNotFoundError and the job ends in ``failed`` rather than a
    # user-facing ``blocked``. This is the path the red-team flagged as
    # "user clicks debate before compress → cryptic failure".
    if not paths.kb_path().exists():
        return _blocked(
            "kb_missing",
            "global knowledge base not found; run `compress` (or `prepare-greenfield`) first",
        )
    topic = params.get("topic")
    # iter 053a: force = archive trio + fresh debate (passthrough of the CLI
    # `debate --force` semantics).
    force = bool(params.get("force", False))
    return (
        run_debate(topic=topic, force=force, progress_cb=progress_cb)
        if topic
        else run_debate(force=force, progress_cb=progress_cb)
    )


def _step_plan_chapters(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    require_start = bool(params.get("require_start_point", True))
    if require_start and not start_point.get_start_chapter_id():
        return {
            "status": "blocked",
            "blocked": [{"reason": "start_point_missing", "error": "start point is required before plan-chapters"}],
        }
    try:
        return generate_chapter_plan(
            target_chapters=int(params.get("target_chapters", 5)),
            force=bool(params.get("force", False)),
            append_count=int(params.get("append_count", 0)),
            from_chapter=int(params.get("from_chapter", 0)),
            require_start_point=require_start,
        )
    except (FileNotFoundError, ValueError) as exc:
        msg = str(exc)
        if require_start and "start point is required" in msg:
            return {
                "status": "blocked",
                "blocked": [{"reason": "start_point_missing", "error": msg}],
            }
        if "outline not found" in msg:
            return {
                "status": "blocked",
                "blocked": [{"reason": "outline_missing", "error": msg}],
            }
        # iter068 (Cluster E): plot_planner hard-raises this for a start-window
        # extraction gap (iter054b). Map it to a structured extraction_coverage_
        # missing card whose CTA is rebuild-for-start, instead of letting it fall
        # through to ``raise`` → a generic ``failed`` job.
        if "extraction coverage gap before start point" in msg:
            return {
                "status": "blocked",
                "blocked": [{"reason": "extraction_coverage_missing", "error": msg}],
            }
        # iter063 A1: plot_planner raises this when the existing debate outline
        # was built against a different start point (a deliberate hard block —
        # the 052 cross-timeline accident). Surface it as a blocked readiness
        # card with a "regenerate outline" CTA instead of a raw ValueError
        # dumped into the UI. iter064 #2: prefer the typed OutlineStale (⊂
        # ValueError, shared with the CLI path); keep the substring as a defense
        # so any plain ValueError carrying the message still maps correctly.
        if isinstance(exc, OutlineStale) or "stale debate outline" in msg:
            reason = exc.kind if isinstance(exc, OutlineStale) else "outline_stale"
            return {
                "status": "blocked",
                "blocked": [{"reason": reason, "error": msg}],
            }
        raise


def _step_draft_once_dev(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    # iter078 收官审查修复：dev 直写步骤同样是 drafts 写者，必须过 P1-7 写锁
    # （此前只有 run_write_book 包装拿锁，本步骤直调 write_chapters 旁路互斥，
    # CLI 长跑期间提交该 job 会双写）。WorkspaceLocked 以 Web-safe blocker
    # 暴露，不把本机 path/argv 诊断写入 job JSON。
    from src.workspace_lock import WorkspaceLocked, acquire_write_lock

    try:
        with acquire_write_lock(source="web-draft-once-dev"):
            return write_chapters(
                chapters=int(params.get("chapters", 1)),
                force=bool(params.get("force", False)),
                resume_from=int(params.get("resume_from", 1)),
            )
    except WorkspaceLocked as exc:
        return _workspace_locked_blocked(exc)


def _default_budget_cny() -> float:
    """iter 050 (F): web-started write jobs are no longer unguarded by
    default. ``budget_cny=0.0`` (no cap) used to be the silent default for
    any workbench/API caller that omitted the field — with a real model
    configured that's an open-ended spend. The default cap comes from
    ``NOVEL_DEFAULT_BUDGET_CNY`` (else 10.0元); callers can still pass an
    explicit ``budget_cny`` (0 = uncapped, CLI semantics unchanged).

    iter 051b: parsing/validation (incl. the iter 050d L-3 nan/inf/negative
    rules) moved to ``config.budget_cny_from_env`` — the single source of
    truth shared with ``_review_budget_cny`` and preflight's budget guard."""
    from ..config import budget_cny_from_env

    return budget_cny_from_env("NOVEL_DEFAULT_BUDGET_CNY", 10.0)


def _budget_guard(params: Dict[str, Any]) -> "tuple[float, Optional[Callable[[], None]], int]":
    """iter068 (Cluster D): shared budget-check factory for the prepare /
    rebuild composite steps (was copy-pasted in both). Returns
    ``(budget_cny, budget_check_or_None, initial_log_lines)``:

    * ``budget_cny`` — the resolved cap (omitted → NOVEL_DEFAULT_BUDGET_CNY,
      explicit 0 → uncapped, CLI semantics);
    * ``budget_check`` — a closure that settles cost via ``estimate_cost_since``
      and raises ``BudgetExceeded`` on breach, or ``None`` when uncapped;
    * ``initial_log_lines`` — the llm-log offset captured BEFORE any spend, so a
      caller can settle the final cost for its result summary.
    """
    from ..book_runner import _llm_log_line_count
    from ..cost_estimator import estimate_cost_since

    budget_cny = _float_param(params, "budget_cny", _default_budget_cny())
    initial_log_lines = _llm_log_line_count()
    budget_check: Optional[Callable[[], None]] = None
    if budget_cny > 0:

        def budget_check() -> None:
            cost = float(estimate_cost_since(initial_log_lines).get("cost_cny", 0.0))
            if cost > budget_cny:
                raise BudgetExceeded(budget_cny=budget_cny, cost_cny=cost)

    return budget_cny, budget_check, initial_log_lines


def _review_budget_cny() -> float:
    """iter 051b: independent cap for the review-chapter job. Review is
    user-triggerable in a loop from the draft editor (「保存并重新评审」), so
    sharing ``NOVEL_DEFAULT_BUDGET_CNY`` with write-book would let the two
    job families crowd each other out of one ceiling. A single-chapter
    review round is much cheaper than write+retry, hence the lower 5.0元
    fallback. Same semantics as the write default: env unset/garbage →
    fallback, explicit 0 = uncapped, params.budget_cny still wins."""
    from ..config import budget_cny_from_env

    return budget_cny_from_env("NOVEL_REVIEW_BUDGET_CNY", 5.0)


def _step_write_book(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    precondition: Optional[Callable[[], None]] = None
    force = params.get("force") is True
    expected_recovery_fingerprint = params.get("expected_recovery_fingerprint")
    expected_recovery_ledger_claim = params.get("expected_recovery_ledger_claim")
    expected_prior_job_id = params.get("expected_recovery_prior_job_id")
    recovery_chapter = params.get("recovery_chapter")
    active_job_id = params.get("_active_job_id")
    recovery_context_complete = bool(
        isinstance(expected_recovery_fingerprint, str)
        and expected_recovery_fingerprint
        and isinstance(expected_recovery_ledger_claim, str)
        and expected_recovery_ledger_claim
        and isinstance(expected_prior_job_id, str)
        and type(recovery_chapter) is int
        and isinstance(active_job_id, str)
        and active_job_id
        and params.get("chapters") == 1
        and params.get("resume_from") == recovery_chapter
        and params.get("max_retries") == 0
        and params.get("auto_advance") is True
        and params.get("require_plan") is True
        and params.get("require_external_review") is True
        and type(params.get("require_start_point")) is bool
    )
    if force and not recovery_context_complete:
        raise BookRunBlocked("write_recovery_state_changed")
    if force:
        def _recovery_precondition() -> None:
            import hmac

            from .write_recovery import current_fingerprint

            try:
                chapter_no = int(recovery_chapter)
            except (TypeError, ValueError, OverflowError) as exc:
                raise BookRunBlocked("write_recovery_state_changed") from exc
            ledger_state, latest, actual_ledger_claim = write_recovery_job_claim(
                paths.workspace_name(),
                chapter_no,
                exclude_job_id=active_job_id,
                require_excluded_active_row=True,
            )
            actual_prior_job_id = str(latest.get("job_id") or "") if latest else ""
            if (
                ledger_state != "ok"
                or actual_prior_job_id != expected_prior_job_id
                or (latest is not None and not is_exact_write_recovery_terminal(latest, chapter_no))
                or not isinstance(actual_ledger_claim, str)
                or not hmac.compare_digest(
                    actual_ledger_claim, expected_recovery_ledger_claim
                )
            ):
                raise BookRunBlocked("write_recovery_state_changed")
            actual = current_fingerprint(paths.workspace_name(), chapter_no)
            if actual is None or not hmac.compare_digest(actual, expected_recovery_fingerprint):
                raise BookRunBlocked("write_recovery_state_changed")

        precondition = _recovery_precondition
    return run_write_book(
        chapters=int(params.get("chapters", 1)),
        resume_from=int(params.get("resume_from", 1)),
        force=force,
        max_retries=int(params.get("max_retries", 2)),
        budget_cny=_float_param(params, "budget_cny", _default_budget_cny()),
        replan_every=int(params.get("replan_every", 0)),
        min_confidence=_float_param(params, "min_confidence", 0.7),
        auto_advance=bool(params.get("auto_advance", True)),
        require_start_point=bool(params.get("require_start_point", True)),
        require_plan=bool(params.get("require_plan", True)),
        require_external_review=bool(params.get("require_external_review", True)),
        progress_cb=progress_cb,
        tier=params.get("tier"),
        precondition=precondition,
        # iter078 P1-7: workspace 写锁 holder 标签——被拒的 CLI 侧能从报错
        # 看出持有方是 Web job。
        lock_source="web-job",
    )


def _step_review_chapter(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    """iter 050 (B2): standalone re-review of one written chapter — the
    job behind「保存并重新评审」after an in-place draft edit.

    Chains the existing pieces end-to-end: ``reviewer.review_target`` (reads
    draft_sha256 + run_context from meta — it never re-hashes, which is why
    the draft PUT endpoint must have synced meta first) →
    ``book_runner._sync_meta_with_external_review`` → strict
    ``chapter_status`` against the CURRENT plan's expected context. After a
    successful round-trip the ``external_review_stale`` /
    ``draft_hash_mismatch`` failures from the edit disappear; the verdict
    itself is whatever the review panel says.

    iter 051b — budget gate (v1 semantics): a single-chapter review has no
    inter-chapter checkpoint to stop at, so the cap is enforced by
    settlement-after-the-fact: record the llm_calls.jsonl line offset at job
    start, run the review round-trip, then settle with
    ``estimate_cost_since``; over budget → terminal ``budget_exceeded`` with
    cost_cny/budget_cny — the exact semantics of write-book's end-of-chapter
    check (book_runner.run_write_book), which likewise only trips AFTER the
    spend that crossed the line. ``params.budget_cny`` wins when provided
    (0 = uncapped); otherwise ``NOVEL_REVIEW_BUDGET_CNY`` (else 5.0元)."""
    try:
        chapter_no = int(params.get("chapter"))
    except (TypeError, ValueError):
        raise ValueError("review-chapter requires integer params.chapter")
    if not 1 <= chapter_no <= 9999:
        raise ValueError("params.chapter out of range")

    from ..book_runner import (
        _build_review_context,
        _llm_log_line_count,
        _sync_meta_with_external_review,
    )
    from ..chapter_status import chapter_status
    from ..cost_estimator import estimate_cost_since
    from ..reviewer import review_target
    from ..workspace_lock import WorkspaceLocked, acquire_write_lock
    from ..writer import (
        ChapterPlanInvalid,
        _chapter_plan_item,
        _enforce_checklist_for_plan,
        _load_chapter_plan,
        _run_context,
    )

    budget_cny = float(_float_param(params, "budget_cny", _review_budget_cny()) or 0.0)
    # Offset BEFORE any spend so the settlement below only counts this job's
    # calls (mirrors book_runner.run_write_book's initial_log_lines usage).
    initial_log_lines = _llm_log_line_count()

    drafts_dir = paths.drafts_dir()
    md_path = drafts_dir / f"chapter_{chapter_no:02d}.md"
    if not md_path.exists():
        return _blocked(
            "draft_missing",
            f"chapter_{chapter_no:02d}.md not found; write the chapter first",
        )
    # iter059 #4: corrupt chapter_plan.json -> clean chapter_plan_invalid blocker
    # instead of a JSONDecodeError that fails the review-chapter job.
    try:
        plan = _load_chapter_plan()
    except ChapterPlanInvalid as exc:
        return _blocked(
            "chapter_plan_invalid",
            f"chapter_plan.json is corrupt ({exc}); regenerate it via plan-chapters",
        )
    if plan is None:
        return _blocked(
            "chapter_plan_missing",
            "chapter_plan.json not found; run `plan-chapters` first",
        )
    try:
        item = _chapter_plan_item(plan, chapter_no)
    except ValueError as exc:
        return _blocked("chapter_plan_missing", str(exc))

    try:
        with acquire_write_lock(source="web-review-chapter"):
            from ..story_memory import require_current
            require_current(drafts_dir, chapter_no)
            progress_cb("review", 0.1)
            review_target(
                md_path,
                # iter073 (codex review): match book_runner's external review — derive
                # warn_only for broad-cast chapters + run plan-compliance — so a chapter
                # reviewed via the Web review-chapter job gets the same verdict as via
                # run_write_book (no strict-Reject divergence / no missed plan block).
                enforce_relationship_checklist=_enforce_checklist_for_plan(item),
                tier=params.get("tier"),
                chapter_plan_item=item,
                **_build_review_context(item),
            )
            progress_cb("sync-meta", 0.8)
            meta = _sync_meta_with_external_review(drafts_dir, chapter_no)
            status = chapter_status(
                chapter_no,
                drafts_dir,
                validate_context=True,
                require_external_review=True,
                expected_context=_run_context(item, chapter_no=chapter_no),
            )
            memory_only = (status.get("strict_failures") == ["story_memory_stale"]
                           and status.get("verdict") == "Approve" and not status.get("needs_review")
                           and not status.get("failure"))
            if status.get("approved") or memory_only:
                from ..story_memory import refresh_after_review
                progress_cb("refresh-memory", 0.95)
                refresh_after_review(drafts_dir, chapter_no)
                status = chapter_status(chapter_no, drafts_dir, validate_context=True,
                    require_external_review=True, expected_context=_run_context(item, chapter_no=chapter_no))
    except WorkspaceLocked as exc:
        return _workspace_locked_blocked(exc)
    # iter 051b: settlement — cost of THIS job only (since initial offset).
    # cost fields ride along on the success path too so the workbench can
    # show what the round-trip actually cost.
    cost_cny = float(estimate_cost_since(initial_log_lines).get("cost_cny", 0.0))
    result: Dict[str, Any] = {
        "status": "succeeded",
        "chapter": chapter_no,
        "verdict": meta.get("verdict") if isinstance(meta, dict) else None,
        "chapter_status": status,
        "cost_cny": cost_cny,
        "budget_cny": budget_cny,
    }
    if budget_cny > 0 and cost_cny > budget_cny:
        # Same terminal contract as write-book: _worker maps this status to
        # the budget_exceeded terminal state (already in TERMINAL_STATUSES).
        result["status"] = "budget_exceeded"
    return result


def _step_auto_pipeline(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    # iter058 #1: onboarding used to ignore budget_cny entirely — the wizard put
    # it in job_params but run_auto_pipeline had no such parameter, so a real
    # model burned past any cap (audit §3.1: ¥0.001 cap → 9 calls / 293s). Mirror
    # _step_write_book: default to the shared NOVEL_DEFAULT_BUDGET_CNY cap
    # (explicit 0 = uncapped, CLI semantics), and map BudgetExceeded to the
    # write-book-style budget_exceeded terminal status (already in
    # TERMINAL_STATUSES, so _worker lands it as terminal).
    budget_cny = _float_param(params, "budget_cny", _default_budget_cny())
    from ..workspace_lock import WorkspaceLocked

    try:
        return auto_pipeline.run_auto_pipeline(
            target_chapters=int(params.get("chapters", 1)),
            progress_cb=progress_cb,
            skip_extract=bool(params.get("skip_extract", False)),
            extract_limit=params.get("extract_limit", 5),
            force=bool(params.get("force", False)),
            plan_chapters_target=params.get("plan_chapters_target"),
            require_start_point=bool(params.get("require_start_point", True)),
            budget_cny=budget_cny,
        )
    except BudgetExceeded as exc:
        return {
            "status": "budget_exceeded",
            "budget_cny": exc.budget_cny,
            "cost_cny": exc.cost_cny,
        }
    except WorkspaceLocked as exc:
        return _workspace_locked_blocked(exc)


def _step_auto_pipeline_greenfield(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    merged = dict(params)
    merged["require_start_point"] = False
    return _step_auto_pipeline(merged, progress_cb)


def _step_prepare_import(
    params: Dict[str, Any],
    progress_cb: Callable[[str, float], None],
) -> Any:
    """Prepare an imported continuation without inventing a start point.

    Only normalize and split the uploaded source.  Extraction/KB/bootstrap are
    intentionally deferred until the user selects the continuation start and
    runs ``rebuild-for-start``; debate/plan/write must never run on an imported
    book with no authoritative start.
    """

    from ..workspace_lock import acquire_write_lock

    with acquire_write_lock(source="web-prepare-import"):
        progress_cb("normalize", 0.0)
        normalized = normalize_all()
        progress_cb("split", 0.5)
        chapters = split_all()
        if not chapters:
            raise ValueError(
                "uploaded text produced 0 chapters after split; no recognizable "
                "chapter headings (第N章 / Chapter N) were found"
            )
        progress_cb("done", 1.0)
        return {
            "status": "succeeded",
            "normalized": len(normalized) if isinstance(normalized, list) else None,
            "chapters": len(chapters),
        }


def _step_expand_premise(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    """iter 051a: expand the one-sentence premise into the structured,
    user-editable expansion artifact (``data/premise_expansion.json``).

    Reads the premise back from ``小说txt/seed.txt`` (written by
    ``wizard.start_premise_workspace`` with the「第一章 缘起」wrapper) so the
    job needs no payload. Idempotent unless ``params.force`` —「重新扩写」
    passes force=true and overwrites, including user edits (the frontend
    confirms first)."""
    seed_path = paths.raw_txt_dir() / "seed.txt"
    if not seed_path.exists():
        return _blocked(
            "seed_missing",
            "小说txt/seed.txt not found; this step only applies to premise-start workspaces",
        )
    try:
        seed_text = seed_path.read_text(encoding="utf-8")
    except OSError as exc:
        return _blocked("seed_unreadable", f"failed to read seed.txt: {exc}")
    premise = seed_text
    prefix = "第一章 缘起\n\n"
    if premise.startswith(prefix):
        premise = premise[len(prefix):]
    premise = premise.strip()
    if not premise:
        return _blocked("seed_empty", "seed.txt contains no premise text")

    from ..premise_expansion import expand_premise

    progress_cb("expand", 0.1)
    record = expand_premise(premise[:2000], force=bool(params.get("force", False)))
    return {
        "status": "succeeded",
        "generated_by": record.get("generated_by"),
        "edited": bool(record.get("edited")),
    }


def _step_extract_style(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    """iter 056: 从临时样本文件提取作家风格卡（仅 premise 自创书）。

    上传端点先把样本写到 ``data/.writer_style_sample.tmp``（gitignored），本步
    读取后提取并落 ``data/writer_style.json``，然后删除临时样本——样本不持久化，
    不进仓库/快照（P0-A 版权护栏）。``force`` 默认 True（提取即为得到新卡）。"""
    # iter060 (#11) + iter061 (P0): the upload route stages each request's sample
    # to a unique path inside data/ and passes only its random TOKEN here. We
    # rebuild the path INSIDE data_dir from a validated 32-hex token, so a caller
    # can NOT POST /run with params.sample_path=<arbitrary path> and get this step
    # to read+delete a file outside the workspace — the path is never taken from
    # caller-controlled input. Unknown/invalid token -> legacy fixed path.
    token = params.get("sample_token")
    # iter063 ⑥: require a valid token. The legacy fixed-path fallback
    # (.writer_style_sample.tmp) reopened the #11 clobber window — a caller that
    # bypasses the route (or an old client) could plant the fixed file and have
    # this step read+delete it. The route always threads a token now, so the
    # fallback had no legitimate user; an invalid/missing token is just blocked.
    if not (isinstance(token, str) and re.fullmatch(r"[0-9a-f]{32}", token)):
        return _blocked("sample_missing", "no uploaded sample found; upload a writing sample first")
    sample_path = paths.writer_style_sample_path().with_name(f".writer_style_sample.{token}.tmp")
    # iter063 ①: sweep orphaned per-request samples left by EARLIER extract jobs
    # that were cancelled (or cancelled while queued) before their handler's
    # finally could delete them. The unique-token path (iter060 #11) means such
    # orphans would otherwise accumulate forever, violating the P0-A copyright
    # guardrail "samples never persist". Safe to sweep all-but-mine: this job
    # holds the workspace reservation, so no concurrent extract job for this
    # workspace can own another in-flight sample.
    try:
        for stale in sample_path.parent.glob(".writer_style_sample.*.tmp"):
            if stale != sample_path:
                stale.unlink(missing_ok=True)
    except OSError:
        pass
    if not sample_path.exists():
        return _blocked("sample_missing", "no uploaded sample found; upload a writing sample first")
    # iter063 ①: the sample read + progress checkpoint + extract are all wrapped
    # so a JobCancelled raised by progress_cb (or any failure) still unlinks the
    # sample. finally does NOT swallow the exception, so cancel still propagates.
    try:
        try:
            sample = sample_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            return _blocked("sample_unreadable", f"failed to read sample: {exc}")
        if not sample:
            return _blocked("sample_empty", "uploaded sample is empty")

        from ..writer_style import extract_style_card
        from ..workspace_lock import WorkspaceLocked, acquire_write_lock

        try:
            with acquire_write_lock(source="web-extract-style"):
                progress_cb("extract", 0.1)
                record = extract_style_card(sample, force=bool(params.get("force", True)))
        except WorkspaceLocked as exc:
            return _workspace_locked_blocked(exc)
    finally:
        sample_path.unlink(missing_ok=True)  # 样本不持久化 (P0-A)：成功/取消/异常都删
    return {
        "status": "succeeded",
        "generated_by": record.get("generated_by"),
        "scrubbed_fields": record.get("_scrubbed_fields", []),
        "incomplete_fields": record.get("_incomplete_fields", []),
    }


def _step_prepare_greenfield(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    """iter 048a: workbench stage ① — run only the 6 prep steps
    (normalize → apply-bootstrap) as a single composite job, then stop.

    Greenfield onboarding has no prior start point, and the workbench
    drives debate / plan-chapters / write-book as their own later-stage
    jobs — so this step deliberately does NOT continue past
    apply-bootstrap. ``total=6, emit_done=True`` remaps the shared prep
    fractions onto a self-contained 0→100% bar so the stage ① card fills
    cleanly instead of stalling at 5/9 (which a naive ``index/9`` reuse
    would produce). See ``auto_pipeline._run_prepare_steps``.

    iter068 (Cluster D, P0 安全): prepare used to call _run_prepare_steps
    WITHOUT budget_check — a real model could burn past any cap during
    extract/compress/bootstrap (the same hole iter058 #1 closed for
    auto-pipeline). Mirror run_auto_pipeline's _budget_check closure:
    default to NOVEL_DEFAULT_BUDGET_CNY (explicit 0 = uncapped, CLI
    semantics), settle cost via estimate_cost_since between LLM-spending
    steps, and map BudgetExceeded to the budget_exceeded terminal status."""
    _budget_cny, _budget_check, _ = _budget_guard(params)
    try:
        return auto_pipeline._run_prepare_steps(
            progress_cb=progress_cb,
            total=6,
            emit_done=True,
            skip_extract=bool(params.get("skip_extract", False)),
            extract_limit=params.get("extract_limit", 5),
            force=bool(params.get("force", False)),
            budget_check=_budget_check,
        )
    except BudgetExceeded as exc:
        return {
            "status": "budget_exceeded",
            "budget_cny": exc.budget_cny,
            "cost_cny": exc.cost_cny,
        }


def _step_rebuild_for_start(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    """iter068 (Cluster A): workbench stage ① for an EXISTING book — rebuild the
    continuation base after the start point moved (补提取起点窗口 → recompress →
    bootstrap entity_graph/anchor --force → apply). Wraps the same
    ``auto_pipeline.rebuild_for_start`` the CLI ``rebuild-for-start`` uses, so
    the WebUI and CLI never drift on step ordering.

    Greenfield (no start point) has nothing to rebuild against. We PRE-CHECK the
    start point and return a friendly blocked card rather than blanket-catching
    ValueError — a blanket catch would also swallow a genuine apply/bootstrap
    ValueError and mislabel it ``start_point_missing``. Budget mirrors
    _step_prepare_greenfield: default to NOVEL_DEFAULT_BUDGET_CNY (explicit
    0 = uncapped), settle in-loop between rebuild stages via budget_check, and
    map BudgetExceeded → the budget_exceeded terminal status."""
    if not start_point.get_start_chapter_id():
        return _blocked(
            "start_point_missing",
            "rebuild-for-start 需要先设置续写起点（set-start-point）；自创书请走「生成设定」",
        )

    # Offset captured BEFORE any spend so the settlement below only counts this
    # job's calls (mirrors run_auto_pipeline / _step_review_chapter).
    budget_cny, _budget_check, initial_log_lines = _budget_guard(params)
    try:
        result = auto_pipeline.rebuild_for_start(
            window=int(params.get("window", 10)),
            reextract=bool(params.get("reextract", False)),
            no_chunk=bool(params.get("no_chunk", False)),
            apply=bool(params.get("apply", True)),
            progress_cb=progress_cb,
            budget_check=_budget_check,
        )
    except BudgetExceeded as exc:
        return {
            "status": "budget_exceeded",
            "budget_cny": exc.budget_cny,
            "cost_cny": exc.cost_cny,
        }
    except ExtractionBatchFailure as exc:
        # 起点窗口某些章节抽取失败（如 relay 530 中断）；已抽的留盘，重跑只补失败项。
        # 不在劣化的提取集上重建底座（与 rebuild_for_start raise_on_failure 一致）。
        preview = ", ".join(exc.failed_ids[:5])
        return _blocked(
            "extraction_failures",
            f"起点窗口提取失败 {len(exc.failed_ids)} 章（{exc.extracted} 成功）：{preview}",
        )

    if isinstance(result, dict):
        from ..cost_estimator import estimate_cost_since

        result["status"] = "succeeded"
        result["cost_cny"] = float(estimate_cost_since(initial_log_lines).get("cost_cny", 0.0))
        result["budget_cny"] = budget_cny
    return result












def _open_strict_parent_directory(path: Path, *, create: bool) -> int | None:
    """Open ``path.parent`` component-by-component without following links."""

    target = path if path.is_absolute() else path.absolute()
    # macOS exposes /var and /tmp as trusted top-level compatibility links.
    # Normalize only those OS aliases; never resolve workspace-controlled
    # descendants, which would defeat the component-wise no-follow contract.
    if target.parts[:2] == ("/", "var"):
        target = Path("/private").joinpath(*target.parts[1:])
    elif target.parts[:2] == ("/", "tmp"):
        target = Path("/private").joinpath(*target.parts[1:])
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise ValueError("strict no-follow text ledger access is unavailable")
    current = os.open(target.anchor or "/", os.O_RDONLY | directory | nofollow)
    try:
        parts = target.parent.parts[1:] if target.anchor else target.parent.parts
        for part in parts:
            try:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=current,
                )
            except FileNotFoundError:
                if not create:
                    os.close(current)
                    return None
                os.mkdir(part, 0o700, dir_fd=current)
                next_fd = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow,
                    dir_fd=current,
                )
            os.close(current)
            current = next_fd
        return current
    except BaseException:
        try:
            os.close(current)
        except OSError:
            pass
        raise






















































# Hard-coded whitelist. Adding a step here = a code review event.
STEP_HANDLERS: Dict[str, Callable[[Dict[str, Any], Callable[[str, float], None]], Any]] = {
    "normalize": _step_normalize,
    "split": _step_split,
    "extract": _step_extract,
    "compress": _step_compress,
    "bootstrap": _step_bootstrap_all,
    "apply-bootstrap": _step_apply_bootstrap,
    "debate": _step_debate,
    "plan-chapters": _step_plan_chapters,
    "write-book": _step_write_book,
    "review-chapter": _step_review_chapter,
    "draft-once-dev": _step_draft_once_dev,
    "auto-pipeline-greenfield": _step_auto_pipeline_greenfield,
    "prepare-import": _step_prepare_import,
    "prepare-greenfield": _step_prepare_greenfield,
    "rebuild-for-start": _step_rebuild_for_start,
    "expand-premise": _step_expand_premise,
    "extract-style": _step_extract_style,
}


def is_known_step(step: str) -> bool:
    return step in STEP_HANDLERS


# ---- worker ----------------------------------------------------------------


def _cleanup_extract_sample(workspace: str, params: Dict[str, Any]) -> None:
    """iter063 ① (审查补漏): the extract-style handler's try/finally only runs
    if the handler runs. A job cancelled while QUEUED (before the pre-handler
    ``_check_cancelled`` lets it start) would leak its staged writer-style
    sample — violating the P0-A copyright guardrail "samples never persist".
    Delete this job's own token sample from the worker finally too, covering
    every terminal path incl. queued-cancel. Per-token (not a sweep), so no
    concurrency risk with other workspaces' in-flight samples."""
    token = params.get("sample_token")
    if not (isinstance(token, str) and re.fullmatch(r"[0-9a-f]{32}", token)):
        return
    try:
        (paths.workspace_root(workspace) / "data" / f".writer_style_sample.{token}.tmp").unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def _worker(job_id: str, expected_identity: Any = None) -> None:
    """Thread body. Runs the step inside ``use_workspace``, surfaces
    progress + final status / error via ``_update``, and clears the
    per-workspace lock when finished."""

    with _JOBS_LOCK:
        job = dict(_JOBS[job_id])
        admitted = dict(_JOB_EXECUTION_CONTEXTS.get(job_id) or {})
    workspace = job["workspace"]
    step = str(admitted.get("step") or job["step"])
    params = dict(admitted.get("params") or job["params"])
    deadline = admitted.get("deadline")
    timeout_minutes = admitted.get("timeout_minutes")
    if "deadline" not in admitted:
        deadline, timeout_minutes = _timeout_deadline(params)
    model_configs = admitted.get("model_configs")
    handler = STEP_HANDLERS.get(step)
    if handler is None:
        _update(
            job_id,
            status="failed",
            error=f"unknown step: {step}",
            finished_at=_now(),
        )
        with _WORKSPACE_LOCK:
            _WORKSPACE_JOBS.pop(workspace, None)
        return

    if expected_identity is not None and not paths.workspace_identity_matches(
        expected_identity
    ):
        # The workspace no longer names the directory approved by start_job.
        # Keep the terminal state in memory only: persisting it through the
        # replaced path would itself be an unauthorized write.
        with _JOBS_LOCK:
            current = _JOBS.get(job_id)
            if current is not None:
                current.update(
                    status="failed",
                    error="RuntimeError: job failed",
                    finished_at=_now(),
                )
        with _WORKSPACE_LOCK:
            _WORKSPACE_JOBS.pop(workspace, None)
        return

    def _progress(sub_step: str, fraction: float) -> None:
        _check_cancelled(job_id, deadline, timeout_minutes)
        _update(job_id, current_step=sub_step, progress=float(fraction))

    _update(job_id, status="running", started_at=_now(), current_step=step)
    try:
        from ..llm_client import (
            LLMBudgetLimitExceeded,
            LLMAccountingUnavailable,
            LLMPricingUnavailable,
            llm_accounting_degraded,
            llm_budget_limit_scope,
            llm_deadline_scope,
            llm_model_config_scope,
            llm_request_limit_scope,
            llm_request_check_scope,
        )

        with use_workspace(workspace):
            from ..book_runner import _llm_log_line_count
            from ..cost_estimator import estimate_cost_since

            model_step = step in NOVEL_MODEL_REQUEST_DEFAULTS
            initial_log_lines = _llm_log_line_count()

            def _known_job_cost() -> float:
                return float(
                    estimate_cost_since(
                        initial_log_lines,
                        paths.workspace_root(),
                    ).get("cost_cny", 0.0)
                )

            with (
                llm_request_check_scope(lambda: _check_cancelled(job_id, deadline, timeout_minutes)),
                llm_model_config_scope(model_configs),
                llm_deadline_scope(deadline),
                llm_request_limit_scope(
                    params.get("max_model_requests"),
                    required=model_step,
                ),
                llm_budget_limit_scope(
                    params.get("budget_cny"),
                    _known_job_cost,
                    required=model_step,
                    require_known_pricing=model_step,
                ),
            ):
                _check_cancelled(job_id, deadline, timeout_minutes)
                execution_params = params
                if params.get("expected_recovery_fingerprint"):
                    execution_params = dict(params)
                    # Worker identity is intentionally in-memory only.  It is
                    # never part of retry params or the durable public ledger.
                    execution_params["_active_job_id"] = job_id
                result = handler(execution_params, _progress)
                if model_step and llm_accounting_degraded():
                    raise LLMAccountingUnavailable(
                        "paid model accounting became unavailable"
                    )
                if not (isinstance(result, dict) and result.get("committed") is True):
                    _check_cancelled(job_id, deadline, timeout_minutes)
                budget = params.get("budget_cny")
                if model_step and budget is not None and float(budget) > 0:
                    settled_cost = _known_job_cost()
                    if settled_cost > float(budget):
                        raise LLMBudgetLimitExceeded(
                            budget_cny=float(budget),
                            cost_cny=settled_cost,
                        )
    except JobTimeout:
        _update(
            job_id,
            status="failed",
            current_step="timeout",
            error="job timed out",
            result_summary={"status": "failed", "failure_reason": "job_timeout"},
            cancel_requested=False,
            cancel_reason=None,
            finished_at=_now(),
        )
    except JobCancelled as exc:
        _update(
            job_id,
            status="aborted",
            current_step="cancelled",
            error=str(exc),
            finished_at=_now(),
        )
    except BookRunBlocked as exc:
        if str(exc).startswith("workspace_locked:"):
            result = _workspace_locked_blocked(exc)
            _update(
                job_id,
                status="blocked",
                current_step="blocked",
                error="workspace locked",
                result_summary=_summarize_result(step, result),
                finished_at=_now(),
            )
            return
        _update(
            job_id,
            status="blocked",
            error=str(exc),
            finished_at=_now(),
        )
    except (LLMPricingUnavailable, LLMAccountingUnavailable) as exc:
        reason = (
            "accounting_unavailable"
            if isinstance(exc, LLMAccountingUnavailable)
            else "preflight_failed"
        )
        _update(
            job_id,
            status="blocked",
            current_step="blocked",
            error=(
                "model accounting unavailable"
                if reason == "accounting_unavailable"
                else "model pricing unavailable"
            ),
            result_summary={
                "status": "blocked",
                "first_blocked": {
                    "reason": reason,
                    "status": "blocked",
                },
            },
            finished_at=_now(),
        )
    except LLMBudgetLimitExceeded as exc:
        _update(
            job_id,
            status="budget_exceeded",
            current_step="budget_exceeded",
            error="model budget limit exhausted",
            result_summary={
                "status": "budget_exceeded",
                "budget_cny": exc.budget_cny,
                "cost_cny": exc.cost_cny,
            },
            finished_at=_now(),
        )
    except Exception as exc:
        from ..llm_client import public_llm_failure_reason

        reason = (
            public_llm_failure_reason(exc)
            if step in NOVEL_MODEL_REQUEST_DEFAULTS
            else "task_failed"
        )
        projection = exception_projection(exc, reason=reason)
        trace_id = projection["trace_id"]

        _update(
            job_id,
            status="failed",
            error=f"{projection['error_type']}: job failed",
            trace_id=trace_id,
            result_summary={
                "status": "failed",
                "failure_reason": reason,
                "error_type": projection["error_type"],
                "trace_id": trace_id,
                **({"attempts": projection["attempts"]} if "attempts" in projection else {}),
            },
            finished_at=_now(),
        )
        # Do not print the exception text or traceback: provider exceptions may
        # contain credentials, signed URLs, prompts, responses and local paths.
        import sys

        sys.stderr.write(
            f"[jobs] job_id={job_id} trace_id={trace_id} "
            f"error_type={projection['error_type']}\n"
        )
    else:
        terminal = "succeeded"
        if isinstance(result, dict) and result.get("status") in {"blocked", "failed", "succeeded", "aborted", "budget_exceeded"}:
            terminal = str(result.get("status"))
        _complete_job(job_id, terminal, step, result)
    finally:
        # iter063 ① (审查补漏): belt-and-suspenders cleanup of the staged
        # writer-style sample for queued-cancel (handler never ran). The
        # handler's own try/finally already covers the running-cancel path.
        if step == "extract-style":
            _cleanup_extract_sample(workspace, params)
        with _WORKSPACE_LOCK:
            _WORKSPACE_JOBS.pop(workspace, None)


def _worker_entry(job_id: str, expected_identity: Any) -> None:
    """Own one worker handle until all job and workspace cleanup is complete."""

    try:
        _worker(job_id, expected_identity)
    finally:
        with _JOBS_LOCK:
            _JOB_EXECUTION_CONTEXTS.pop(job_id, None)
        with _WORKER_THREADS_LOCK:
            _WORKER_THREADS.pop(job_id, None)


def _summarize_result(step: str, result: Any) -> Any:
    """Coerce step-native return types into a JSON-safe summary the
    client can render without needing the full payload."""
    if step in {"auto-pipeline-greenfield", "auto-pipeline"} and isinstance(result, dict):
        write_part = result.get("write") or []
        summary: Dict[str, Any] = {"chapters_written": len(write_part)}
        # iter058 #1: a budget_exceeded run returns a status/cost snapshot
        # instead of the step-keyed dict; surface those so the workbench can
        # show why it stopped. The success path has no "status" key → the
        # summary stays exactly {"chapters_written": N}.
        if result.get("status"):
            summary["status"] = result.get("status")
            summary["cost_cny"] = result.get("cost_cny")
            summary["budget_cny"] = result.get("budget_cny")
        return summary
    if step == "write-book" and isinstance(result, dict):
        blocked = result.get("blocked") or []
        first_blocked = blocked[0] if blocked and isinstance(blocked[0], dict) else None
        return {
            "status": result.get("status"),
            "chapters": len(result.get("chapters") or []),
            "blocked": len(blocked),
            "first_blocked": first_blocked,
            "cost_cny": result.get("cost_cny"),
            "budget_cny": result.get("budget_cny"),
            "partial": result.get("partial"),
            "failure_reason": result.get("failure_reason"),
            "error": result.get("error"),
            "snapshot_path": result.get("snapshot_path"),
        }
    if step == "review-chapter" and isinstance(result, dict):
        status = result.get("chapter_status") or {}
        blocked = result.get("blocked") or []
        return {
            "status": result.get("status"),
            "chapter": result.get("chapter"),
            "verdict": result.get("verdict"),
            "strict_failures": status.get("strict_failures"),
            "first_blocked": blocked[0] if blocked and isinstance(blocked[0], dict) else None,
            # iter 051b: budget settlement fields (None on blocked paths that
            # return before the gate ran).
            "cost_cny": result.get("cost_cny"),
            "budget_cny": result.get("budget_cny"),
        }
    if step == "expand-premise" and isinstance(result, dict):
        blocked = result.get("blocked") or []
        return {
            "status": result.get("status"),
            "generated_by": result.get("generated_by"),
            "first_blocked": blocked[0] if blocked and isinstance(blocked[0], dict) else None,
        }
    if step == "plan-chapters" and isinstance(result, dict):
        blocked = result.get("blocked") or []
        return {
            "status": result.get("status", "succeeded"),
            "blocked": len(blocked),
            "first_blocked": blocked[0] if blocked and isinstance(blocked[0], dict) else None,
        }
    if step == "prepare-greenfield" and isinstance(result, dict):
        # iter068 (Cluster D): the old generic {"keys": [...]} summary hid what
        # the round-trip cost / produced. Surface budget + counts so the stage ①
        # card shows 抽了几章 / 应用了哪些 proposal / 是否撞预算.
        blocked = result.get("blocked") or []
        if result.get("status") in ("budget_exceeded", "blocked"):
            return {
                "status": result.get("status"),
                "cost_cny": result.get("cost_cny"),
                "budget_cny": result.get("budget_cny"),
                "first_blocked": blocked[0] if blocked and isinstance(blocked[0], dict) else None,
            }
        extract_part = result.get("extract")
        applied = result.get("apply-bootstrap") or {}
        return {
            "status": "succeeded",
            "extracted": len(extract_part) if isinstance(extract_part, list) else None,
            "applied": sorted(applied.keys()) if isinstance(applied, dict) else None,
        }
    if step == "rebuild-for-start" and isinstance(result, dict):
        blocked = result.get("blocked") or []
        window_ids = result.get("window_chapter_ids")
        applied_steps = result.get("steps") if isinstance(result.get("steps"), dict) else {}
        return {
            "status": result.get("status"),
            "cost_cny": result.get("cost_cny"),
            "budget_cny": result.get("budget_cny"),
            "start_chapter_id": result.get("start_chapter_id"),
            "window": len(window_ids) if isinstance(window_ids, list) else None,
            "applied": ("apply_entity_graph" in applied_steps and "apply_anchor" in applied_steps),
            "first_blocked": blocked[0] if blocked and isinstance(blocked[0], dict) else None,
        }
    if isinstance(result, list):
        return {"count": len(result)}
    if isinstance(result, dict):
        blocked = result.get("blocked") or []
        if result.get("status") == "blocked" and isinstance(blocked, list):
            return {
                "status": "blocked",
                "blocked": len(blocked),
                "first_blocked": blocked[0] if blocked and isinstance(blocked[0], dict) else None,
            }
        return {"keys": sorted(result.keys())}
    return str(result)[:200]


def start_job(workspace: str, step: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Reserve the per-workspace slot, register the job, and spawn the
    daemon thread. Returns the job snapshot. Raises ``RuntimeError``
    with code ``"workspace_busy"`` if the workspace already has a
    running job — the route handler maps this to HTTP 409.
    """
    params = dict(params or {})
    if not is_known_step(step):
        raise ValueError(f"unknown step: {step}")
    model_configs: Dict[str, Dict[str, Any]] | None = None
    if step in NOVEL_MODEL_REQUEST_DEFAULTS:
        from ..config import get_model_config

        model_configs = {task: dict(get_model_config(task)) for task in _MODEL_TASKS}
    deadline, timeout_minutes = _timeout_deadline(params)
    recovery_keys = {
        "expected_recovery_fingerprint",
        "expected_recovery_ledger_claim",
        "expected_recovery_prior_job_id",
        "recovery_chapter",
    }
    if step == "write-book" and params.get("force") is not True and recovery_keys & params.keys():
        raise RuntimeError("write_recovery_state_changed")
    if step == "write-book" and params.get("force") is True:
        chapter = params.get("recovery_chapter")
        fingerprint = params.get("expected_recovery_fingerprint")
        ledger_claim = params.get("expected_recovery_ledger_claim")
        prior_job_id = params.get("expected_recovery_prior_job_id")
        if not (
            type(chapter) is int
            and 1 <= chapter <= 9999
            and isinstance(fingerprint, str)
            and re.fullmatch(r"[0-9a-f]{64}", fingerprint)
            and isinstance(ledger_claim, str)
            and re.fullmatch(r"[0-9a-f]{64}", ledger_claim)
            and isinstance(prior_job_id, str)
            and (prior_job_id == "" or re.fullmatch(r"[0-9a-f]{32}", prior_job_id))
            and params.get("chapters") == 1
            and params.get("resume_from") == chapter
            and params.get("max_retries") == 0
            and params.get("auto_advance") is True
            and params.get("require_plan") is True
            and params.get("require_external_review") is True
            and type(params.get("require_start_point")) is bool
        ):
            raise RuntimeError("write_recovery_state_changed")

    identity = paths.probe_workspace_identity(workspace)
    if identity is None:
        raise RuntimeError(f"workspace_not_found:{workspace}")

    # Iter165: creation mode is a server-side execution contract, not a UI
    # hint.  Keep this guard below every in-process caller (wizard/plugins/tests)
    # and before record allocation/persistence so a conflicting request creates
    # no job and consumes no workspace slot.
    from .workspace_meta import read as _meta_read

    meta = _meta_read(workspace)
    if meta.get("_metadata_status") == "invalid":
        raise RuntimeError("workspace_metadata_invalid")
    if meta.get("type") != "novel":
        raise RuntimeError(f"workspace_not_found:{workspace}")
    mode = str(meta.get("creation_mode") or "continuation")
    requires_start = mode != "greenfield"
    with use_workspace(workspace):
        from ..start_point import get_start_chapter_id

        has_start = bool(get_start_chapter_id())
    if step in {"prepare-greenfield", "auto-pipeline-greenfield", "expand-premise"} and requires_start:
        raise RuntimeError("creation_mode_conflict:continuation_requires_start_point")
    if step in {"prepare-import", "rebuild-for-start"} and not requires_start:
        raise RuntimeError("creation_mode_conflict:greenfield_has_no_import_start")
    start_gated_steps = {
        "extract", "compress", "bootstrap", "apply-bootstrap", "debate",
        "plan-chapters", "write-book", "review-chapter", "draft-once-dev",
        "rebuild-for-start",
    }
    if requires_start and not has_start and step in start_gated_steps:
        raise RuntimeError("creation_mode_conflict:start_point_required")
    if step in {"plan-chapters", "write-book"}:
        if "require_start_point" in params:
            supplied = params.get("require_start_point")
            if type(supplied) is not bool or supplied != requires_start:
                raise RuntimeError("creation_mode_conflict:require_start_point")
        params["require_start_point"] = requires_start

    with _WORKSPACE_LOCK:
        if workspace in _WORKSPACE_JOBS:
            existing = _WORKSPACE_JOBS[workspace]
            raise RuntimeError(f"workspace_busy:{existing}")
        if not paths.workspace_identity_matches(identity):
            raise RuntimeError(f"workspace_not_found:{workspace}")
        record = _new_job_record(workspace, step, params)
        # iter072 (#3): register in _JOBS *before* reserving the workspace
        # slot, so the invariant "_WORKSPACE_JOBS[ws] set ⟹ _JOBS already has
        # the record" holds with no gap. Previously _WORKSPACE_JOBS was
        # written first and _JOBS_LOCK acquired only after releasing
        # _WORKSPACE_LOCK; a concurrent /jobs/active (which scans _JOBS only)
        # could land in that window — see the workspace busy yet report zero
        # active jobs — and let the leave-guard slip. Nesting _JOBS_LOCK
        # inside _WORKSPACE_LOCK is lock-order-safe: every other site that
        # touches both takes WORKSPACE→JOBS, never the reverse.
        with _JOBS_LOCK:
            _JOBS[record["job_id"]] = record
            _JOB_EXECUTION_CONTEXTS[record["job_id"]] = {
                "step": step,
                "params": dict(params),
                "deadline": deadline,
                "timeout_minutes": timeout_minutes,
                "model_configs": model_configs,
            }
        _WORKSPACE_JOBS[workspace] = record["job_id"]

    # Close the deterministic probe-to-persist replacement window.  The
    # persistence call may legitimately create a previously absent logs/
    # directory, so capture a refreshed identity afterwards while requiring
    # the root and every pre-existing canonical directory to be unchanged.
    if not paths.workspace_identity_matches(identity):
        with _WORKSPACE_LOCK:
            _WORKSPACE_JOBS.pop(workspace, None)
        with _JOBS_LOCK:
            _JOBS.pop(record["job_id"], None)
            _JOB_EXECUTION_CONTEXTS.pop(record["job_id"], None)
        raise RuntimeError(f"workspace_not_found:{workspace}")
    if not _persist_job(record):
        with _WORKSPACE_LOCK:
            _WORKSPACE_JOBS.pop(workspace, None)
        with _JOBS_LOCK:
            _JOBS.pop(record["job_id"], None)
            _JOB_EXECUTION_CONTEXTS.pop(record["job_id"], None)
        with _WORKER_THREADS_LOCK:
            _WORKER_THREADS.pop(record["job_id"], None)
        raise JobPersistenceError("job_persistence_failed")
    worker_identity = paths.probe_workspace_identity(workspace)
    if (
        worker_identity is None
        or not paths.workspace_identity_preserves(identity, worker_identity)
    ):
        with _WORKSPACE_LOCK:
            _WORKSPACE_JOBS.pop(workspace, None)
        with _JOBS_LOCK:
            _JOBS.pop(record["job_id"], None)
            _JOB_EXECUTION_CONTEXTS.pop(record["job_id"], None)
        raise RuntimeError(f"workspace_not_found:{workspace}")

    # Iter 027 P2 (review #8 fix): if thread.start() fails (OS thread
    # limit reached, fork restrictions, etc.), the _WORKSPACE_JOBS entry
    # would otherwise dangle forever — the worker never runs, so the
    # ``finally`` cleanup inside _worker never fires, and every future
    # POST to this workspace returns 409 pointing at a dead job_id.
    # Roll back both tables on failure and re-raise so the caller
    # surfaces the underlying error.
    thread = threading.Thread(
        target=_worker_entry,
        args=(record["job_id"], worker_identity),
        daemon=True,
        name=f"job-{record['job_id'][:8]}",
    )
    try:
        with _WORKER_THREADS_LOCK:
            _WORKER_THREADS[record["job_id"]] = thread
            thread.start()
    except RuntimeError:
        with _WORKER_THREADS_LOCK:
            _WORKER_THREADS.pop(record["job_id"], None)
        with _WORKSPACE_LOCK:
            _WORKSPACE_JOBS.pop(workspace, None)
        with _JOBS_LOCK:
            _JOBS.pop(record["job_id"], None)
            _JOB_EXECUTION_CONTEXTS.pop(record["job_id"], None)
        raise
    return dict(record)


def reset_for_tests(*, timeout_seconds: float = 5.0) -> None:
    """Drain test workers before clearing state.

    Tests patch the process-global workspace root.  Clearing the tables while
    an old daemon still runs lets that worker resolve paths inside the next
    fixture.  Cancellation is cooperative; if a worker ignores it beyond the
    bounded deadline we fail closed and preserve the tables for diagnosis.
    """

    timeout = float(timeout_seconds)
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("timeout_seconds must be finite and non-negative")
    with _WORKER_THREADS_LOCK:
        workers = list(_WORKER_THREADS.items())
    for job_id, thread in workers:
        alive = getattr(thread, "is_alive", lambda: False)()
        if alive:
            request_cancel(job_id, "test reset requested cancel")
    deadline = time.monotonic() + timeout
    for _job_id, thread in workers:
        alive = getattr(thread, "is_alive", lambda: False)()
        if not alive:
            continue
        if thread is threading.current_thread():
            raise RuntimeError("test job workers did not stop")
        join = getattr(thread, "join", None)
        if callable(join):
            join(timeout=max(0.0, deadline - time.monotonic()))
    with _WORKER_THREADS_LOCK:
        live = [
            job_id
            for job_id, thread in _WORKER_THREADS.items()
            if getattr(thread, "is_alive", lambda: False)()
        ]
        if live:
            raise RuntimeError("test job workers did not stop")
        _WORKER_THREADS.clear()
    with _WORKSPACE_LOCK:
        _WORKSPACE_JOBS.clear()
    with _JOBS_LOCK:
        _JOBS.clear()
        _JOB_EXECUTION_CONTEXTS.clear()


def _float_param(params: Dict[str, Any], key: str, default: float) -> float:
    value = params.get(key, default)
    if value is None or value == "":
        return float(default)
    out = float(value)
    # iter058 #6b defense-in-depth: routes/wizard reject non-finite input at the
    # HTTP boundary, but this is the last hop before the budget/timeout math
    # (where a NaN budget would silently disable the cost gate). Fall back to the
    # finite default rather than let a non-finite value through.
    if not math.isfinite(out):
        return float(default)
    return out
