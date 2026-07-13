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
* **In-memory job dict** keyed by uuid4. No persistence: if the server
  restarts, in-flight jobs are lost. Acceptable for a single-user local
  dev tool; iter 027+ can promote to ``logs/jobs.jsonl`` if needed.
* **Hard-coded step dispatch table** so a malicious or fat-fingered POST
  can't invoke arbitrary functions. Adding a step = editing this file.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
import json
import math
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .. import auto_pipeline, paths, start_point
from ..auto_bootstrap import bootstrap_all
from ..chapter_splitter import split_all
from ..cli_apply_bootstrap import apply_bootstrap
from ..compressor import compress_all
from ..book_runner import BookRunBlocked, BudgetExceeded, run_write_book
from ..debater import run_debate
from ..extractor import ExtractionBatchFailure, extract_all
from ..plot_planner import OutlineStale, generate_chapter_plan
from ..text_normalizer import normalize_all
from ..writer import write_chapters
from .workspace_ctx import use_workspace


# Per-workspace lock: a workspace can run at most one job at a time.
# Holding the value of the entry would be the running job_id so we can
# point a concurrent POST at the live one if useful; for now the value
# is only checked for truthiness (409 on collision).
_WORKSPACE_JOBS: Dict[str, str] = {}
_WORKSPACE_LOCK = threading.Lock()

# All jobs, keyed by job_id. Survives only as long as the process.
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
TERMINAL_STATUSES = {"succeeded", "blocked", "failed", "aborted", "lost", "budget_exceeded"}


class JobCancelled(RuntimeError):
    """Raised inside a worker when a cooperative cancel checkpoint fires."""


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
    return {key: job.get(key) for key in _PUBLIC_JOB_FIELDS}


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
)
_PUBLIC_JOB_DETAIL_FIELDS = _PUBLIC_JOB_SUMMARY_FIELDS + (
    "cancel_requested",
    "cancel_reason",
)


def _public_retry_params(value: Any) -> Dict[str, Any]:
    """Return replayable parameters without one-shot paid authorization.

    Job history is durable and the UI can repost these parameters months later.
    A confirmation is consent for one invocation, not reusable job state, so no
    ``confirm_*`` field may cross this projection boundary.
    """

    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and not key.startswith("confirm_")
    }


def public_job_summary_view(job: Dict[str, Any]) -> Dict[str, Any]:
    """Project for /jobs/recent (sidebar + jobs table) — drops internal cancel_*."""
    projected = {key: job.get(key) for key in _PUBLIC_JOB_SUMMARY_FIELDS}
    projected["params"] = _public_retry_params(job.get("params"))
    return projected


def public_job_detail_view(job: Dict[str, Any]) -> Dict[str, Any]:
    """Project for /job/<id> — adds cancel_* (poll banner) on top of summary."""
    projected = {key: job.get(key) for key in _PUBLIC_JOB_DETAIL_FIELDS}
    projected["params"] = _public_retry_params(job.get("params"))
    return projected


def _new_job_record(workspace: str, step: str, params: Dict[str, Any]) -> Dict[str, Any]:
    return {
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


def _job_log_path(workspace: str) -> Path:
    return paths.WORKSPACE_DIR / workspace / "logs" / "web_jobs.jsonl"


def _persist_job(job: Dict[str, Any]) -> None:
    try:
        path = _job_log_path(str(job.get("workspace") or ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        durable = dict(job)
        durable["params"] = _public_retry_params(job.get("params"))
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_finite_json_safe(durable), ensure_ascii=False) + "\n")
    except OSError:
        return


def _load_persisted_job(job_id: str) -> Optional[Dict[str, Any]]:
    latest: Optional[Dict[str, Any]] = None
    for path in paths.WORKSPACE_DIR.glob("*/logs/web_jobs.jsonl"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("job_id") == job_id:
                latest = row
    return latest


def recent_jobs(workspace: str, limit: int = 5) -> list[Dict[str, Any]]:
    """Return the latest persisted jobs for a workspace.

    The dashboard uses this after a browser refresh, when in-memory job
    state may be gone but ``logs/web_jobs.jsonl`` still has terminal rows.
    """

    limit = max(1, min(int(limit or 5), 50))
    path = _job_log_path(workspace)
    if not path.exists():
        return []
    latest_by_id: Dict[str, Dict[str, Any]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
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
                snapshot["error"] = "worker process restarted before this job reached a terminal state"
        reconciled.append(snapshot)

    reconciled.sort(key=_sort_key, reverse=True)
    return reconciled[:limit]


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
    _persist_job(snapshot)


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


def request_cancel(job_id: str, reason: str = "user requested cancel") -> Optional[Dict[str, Any]]:
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
        if str(job.get("status") or "") not in {"pending", "running"}:
            return None
        job["cancel_requested"] = True
        job["cancel_reason"] = reason
        snapshot = dict(job)
    _persist_job(snapshot)
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
            job.update(
                {
                    "status": terminal,
                    "current_step": terminal,
                    "progress": 1.0,
                    "finished_at": _now(),
                    "result_summary": _summarize_result(step, result),
                }
            )
        snapshot = dict(job)
    _persist_job(snapshot)


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
    return compress_all()


def _step_bootstrap_all(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    ex_dir = paths.extracted_dir()
    if not ex_dir.exists() or not any(ex_dir.glob("*.json")):
        return _blocked(
            "extractions_missing",
            "no extracted JSON found; run `extract` first",
        )
    return bootstrap_all(force=bool(params.get("force", False)))


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
    return run_write_book(
        chapters=int(params.get("chapters", 1)),
        resume_from=int(params.get("resume_from", 1)),
        force=bool(params.get("force", False)),
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


def _drama_episode_no(params: Dict[str, Any]) -> int:
    from ..drama_schemas import normalize_episode_no

    return normalize_episode_no(params.get("episode_no", 1))


def _drama_job_error(step: str, exc: BaseException) -> Dict[str, Any]:
    """Return a public-safe drama failure without persisting provider text/paths."""
    import sys

    sys.stderr.write(f"[jobs] {step} failed: {type(exc).__name__} (details suppressed)\n")
    return {
        "status": "failed",
        "error_code": "drama_generation_failed",
        "station": step,
    }


_DRAMA_MODEL_TASKS = {
    "drama-plan": "drama_plan",
    "drama-hooks": "drama_hooks",
    "drama-storyboard": "drama_storyboard",
    "drama-characters": "drama_character",
    "drama-review-assemble": "drama_review",
}


def _drama_text_attempt_path(workspace: str) -> Path:
    return paths.workspace_root(workspace) / "logs" / "drama_text_attempts.json"


def _drama_text_provider_fingerprint(task: str) -> str:
    import hashlib
    from ..config import get_model_config

    config = get_model_config(task)
    payload = {
        "model": str(config.get("model") or "mock").strip(),
        "base_url": str(config.get("base_url") or "").strip().rstrip("/"),
        "base_url_env": str(config.get("base_url_env") or ""),
        "api_key_env": str(config.get("api_key_env") or ""),
        "api_key": str(config.get("api_key") or ""),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _drama_text_input_payload(
    step: str,
    workspace: str,
    episode_no: int,
    *,
    stable_recovery: bool,
) -> Dict[str, Any]:
    import hashlib
    from ..drama_schemas import character_paths, episode_paths
    from ..utils import read_json_optional

    ep = episode_paths(workspace, episode_no=episode_no)
    root = paths.workspace_root(workspace)
    snapshot = root / "data" / "creation_standard.snapshot.md"
    try:
        snapshot_sha256 = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    except OSError:
        snapshot_sha256 = "missing"
    sources: Dict[str, Any] = {
        "step": step,
        "episode_no": episode_no,
        "wizard": read_json_optional(root / "data" / "wizard_input.json", None),
        "creation_standard_sha256": snapshot_sha256,
    }
    if step in {"drama-hooks", "drama-storyboard", "drama-characters", "drama-review-assemble"}:
        setup = read_json_optional(ep.setup_path, None)
        if stable_recovery and step == "drama-hooks" and isinstance(setup, dict):
            setup = {key: value for key, value in setup.items() if key != "hook"}
        sources["setup"] = setup
    if step in {"drama-characters", "drama-review-assemble"}:
        sources["storyboard"] = read_json_optional(ep.storyboard_path, None)
    if step == "drama-characters" and not stable_recovery:
        sources["existing_characters"] = read_json_optional(character_paths(workspace).sheet_path, None)
    if step == "drama-hooks" and episode_no > 1:
        sources["previous_hooks"] = [
            read_json_optional(episode_paths(workspace, episode_no=number).setup_path, None)
            for number in range(1, episode_no)
        ]
    if step == "drama-review-assemble":
        sources["characters"] = read_json_optional(character_paths(workspace).sheet_path, None)
    return sources


def _drama_text_input_fingerprint(step: str, workspace: str, episode_no: int) -> str:
    from ..utils import sha256_data

    return sha256_data(_drama_text_input_payload(
        step, workspace, episode_no, stable_recovery=False
    ))


def _drama_text_recovery_fingerprint(step: str, workspace: str, episode_no: int) -> str:
    from ..utils import sha256_data

    return sha256_data(_drama_text_input_payload(
        step, workspace, episode_no, stable_recovery=True
    ))


def _drama_text_recovery_fingerprint_matches(
    step: str,
    workspace: str,
    episode_no: int,
    row: Dict[str, Any],
) -> bool:
    """Accept current recovery identity plus the safe first-sheet legacy shape."""

    from ..utils import sha256_data

    current = _drama_text_recovery_fingerprint(step, workspace, episode_no)
    recorded = row.get("recovery_fingerprint")
    if isinstance(recorded, str):
        return recorded == current
    legacy = row.get("input_fingerprint")
    if legacy == current:
        return True
    if step == "drama-characters":
        # Before recovery_fingerprint existed, the first character generation
        # hashed an explicit null sheet.  That state is reconstructible without
        # trusting the now-written output; later merge inputs remain fail-closed.
        payload = _drama_text_input_payload(
            step, workspace, episode_no, stable_recovery=True
        )
        payload["existing_characters"] = None
        return legacy == sha256_data(payload)
    return False


def _load_drama_text_attempts(workspace: str) -> Dict[str, Any]:
    from ..utils import read_json

    path = _drama_text_attempt_path(workspace)
    try:
        path.lstat()
    except FileNotFoundError:
        return {"schema_version": 1, "attempts": {}}
    except OSError as exc:
        raise ValueError("drama text attempt ledger is unreadable") from exc
    if path.is_symlink() or not path.is_file():
        raise ValueError("drama text attempt ledger must be a regular file")
    try:
        raw = read_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("drama text attempt ledger is unreadable") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("attempts"), dict):
        raise ValueError("drama text attempt ledger is invalid")
    allowed = {
        "submitting", "response_received", "failed_after_submission",
        "succeeded", "budget_exceeded",
    }
    for key, row in raw["attempts"].items():
        if (
            not isinstance(key, str)
            or not isinstance(row, dict)
            or row.get("status") not in allowed
            or row.get("step") not in _DRAMA_MODEL_TASKS
            or type(row.get("episode_no")) is not int
            or row["episode_no"] < 1
            or type(row.get("attempt_count")) is not int
            or row["attempt_count"] < 1
            or key != f'{row["step"]}:{row["episode_no"]}'
        ):
            raise ValueError("drama text attempt ledger row is invalid")
        for field in ("provider_fingerprint", "input_fingerprint"):
            value = row.get(field)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("drama text attempt ledger fingerprint is invalid")
        recovery = row.get("recovery_fingerprint")
        if recovery is not None and (
            not isinstance(recovery, str)
            or re.fullmatch(r"[0-9a-f]{64}", recovery) is None
        ):
            raise ValueError("drama text attempt recovery fingerprint is invalid")
        artifact = row.get("artifact_fingerprint")
        if artifact is not None and (
            not isinstance(artifact, str) or re.fullmatch(r"[0-9a-f]{64}", artifact) is None
        ):
            raise ValueError("drama text attempt artifact fingerprint is invalid")
        candidates = row.get("candidate_fingerprints")
        if candidates is not None and (
            not isinstance(candidates, list)
            or not candidates
            or any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None for value in candidates)
        ):
            raise ValueError("drama text attempt candidate fingerprints are invalid")
    return raw


def _save_drama_text_attempts(workspace: str, ledger: Dict[str, Any]) -> None:
    from ..utils import write_json

    write_json(_drama_text_attempt_path(workspace), ledger)


def _canonical_drama_text_result(
    step: str,
    workspace: str,
    episode_no: int,
    row: Dict[str, Any],
    *,
    allow_selected_hook: bool = False,
) -> Dict[str, Any] | None:
    """Recover a committed station result without another provider call."""
    from ..drama_schemas import character_paths, episode_paths
    from ..utils import read_json_optional, sha256_data

    ep = episode_paths(workspace, episode_no=episode_no)
    if step == "drama-plan":
        value = read_json_optional(ep.setup_path, None)
        candidate = {key: item for key, item in value.items() if key != "hook"} if isinstance(value, dict) else None
    elif step == "drama-hooks":
        value = read_json_optional(ep.hook_candidates_path, None)
        if isinstance(value, dict):
            candidate = value
        elif allow_selected_hook:
            setup = read_json_optional(ep.setup_path, None)
            hook = setup.get("hook") if isinstance(setup, dict) else None
            candidate = {"hooks": [hook]} if isinstance(hook, dict) else None
        else:
            return None
        fingerprints = row.get("candidate_fingerprints") or []
        hooks = candidate.get("hooks") if isinstance(candidate, dict) else None
        if not isinstance(hooks, list) or not hooks or not all(sha256_data(hook) in fingerprints for hook in hooks):
            return None
        return candidate
    elif step == "drama-storyboard":
        candidate = read_json_optional(ep.storyboard_path, None)
    elif step == "drama-characters":
        candidate = read_json_optional(character_paths(workspace).sheet_path, None)
    elif step == "drama-review-assemble":
        candidate = read_json_optional(ep.review_path, None)
    else:
        return None
    if not isinstance(candidate, dict) or sha256_data(candidate) != row.get("artifact_fingerprint"):
        return None
    return candidate


def _begin_drama_text_attempt(step: str, params: Dict[str, Any], episode_no: int) -> tuple[str, Dict[str, Any]] | None:
    from ..config import get_model_config

    task = _DRAMA_MODEL_TASKS[step]
    if str(get_model_config(task).get("model") or "mock").lower().startswith("mock"):
        return None
    workspace = paths.workspace_name()
    ledger = _load_drama_text_attempts(workspace)
    key = f"{step}:{episode_no}"
    existing = ledger["attempts"].get(key)
    provider = _drama_text_provider_fingerprint(task)
    input_fingerprint = _drama_text_input_fingerprint(step, workspace, episode_no)
    recovery_fingerprint = _drama_text_recovery_fingerprint(step, workspace, episode_no)
    if isinstance(existing, dict):
        if (
            existing.get("provider_fingerprint") != provider
            or not _drama_text_recovery_fingerprint_matches(
                step, workspace, episode_no, existing
            )
        ):
            raise ValueError("drama text retry provider or input identity changed")
    if isinstance(existing, dict) and existing.get("status") in {"response_received", "succeeded"}:
        recovered = _canonical_drama_text_result(step, workspace, episode_no, existing)
        if recovered is not None:
            # Ephemeral only: never persist model output in the billing ledger.
            return key, {**existing, "_recovered_result": recovered}
        if existing.get("status") == "succeeded":
            raise ValueError("committed drama text artifact no longer matches its paid attempt")
    if isinstance(existing, dict) and existing.get("input_fingerprint") != input_fingerprint:
        raise ValueError("drama text retry exact input identity changed")
    if isinstance(existing, dict) and existing.get("status") in {
        "submitting", "response_received", "failed_after_submission", "budget_exceeded",
    }:
        if not (
            params.get("confirm_text_retry") is True
            and params.get("confirm_upstream_status_and_billing_checked") is True
        ):
            raise ValueError("drama text retry requires upstream task and billing reconciliation")
    count = int(existing.get("attempt_count") or 0) + 1 if isinstance(existing, dict) else 1
    row = {
        "status": "submitting",
        "step": step,
        "episode_no": episode_no,
        "attempt_count": count,
        "provider_fingerprint": provider,
        "input_fingerprint": input_fingerprint,
        "recovery_fingerprint": recovery_fingerprint,
        "updated_at": int(time.time()),
    }
    ledger["attempts"][key] = row
    _save_drama_text_attempts(workspace, ledger)
    return key, row


def _mark_drama_text_attempt(token: tuple[str, Dict[str, Any]] | None, status: str) -> None:
    if token is None:
        return
    key, expected = token
    workspace = paths.workspace_name()
    ledger = _load_drama_text_attempts(workspace)
    current = ledger["attempts"].get(key)
    if not isinstance(current, dict) or current.get("attempt_count") != expected.get("attempt_count"):
        raise ValueError("drama text attempt ledger changed during generation")
    current["status"] = status
    current["updated_at"] = int(time.time())
    _save_drama_text_attempts(workspace, ledger)


def _bind_drama_text_artifact(
    token: tuple[str, Dict[str, Any]] | None,
    artifact: Dict[str, Any],
    *,
    candidates: list[Dict[str, Any]] | None = None,
) -> None:
    if token is None:
        return
    from ..utils import sha256_data

    key, expected = token
    workspace = paths.workspace_name()
    ledger = _load_drama_text_attempts(workspace)
    current = ledger["attempts"].get(key)
    if not isinstance(current, dict) or current.get("attempt_count") != expected.get("attempt_count"):
        raise ValueError("drama text attempt ledger changed during artifact binding")
    current["artifact_fingerprint"] = sha256_data(artifact)
    if candidates is not None:
        current["candidate_fingerprints"] = [sha256_data(item) for item in candidates]
    current["updated_at"] = int(time.time())
    _save_drama_text_attempts(workspace, ledger)


def _call_drama_text_model(
    step: str,
    params: Dict[str, Any],
    episode_no: int,
    operation: Callable[[], Dict[str, Any]],
) -> tuple[Dict[str, Any], tuple[str, Dict[str, Any]] | None]:
    token = _begin_drama_text_attempt(step, params, episode_no)
    if token is not None and isinstance(token[1].get("_recovered_result"), dict):
        return dict(token[1]["_recovered_result"]), token
    try:
        result = operation()
    except BaseException:
        _mark_drama_text_attempt(token, "failed_after_submission")
        raise
    _mark_drama_text_attempt(token, "response_received")
    return result, token


def _drama_budget_start(step: str, params: Dict[str, Any]) -> tuple[float, int]:
    """Validate the last-hop real-text gate and capture this job's cost offset."""
    from ..book_runner import _llm_log_line_count
    from ..config import get_model_config

    task = _DRAMA_MODEL_TASKS[step]
    real_model = not str(get_model_config(task).get("model") or "mock").lower().startswith("mock")
    budget_cny = _float_param(params, "budget_cny", 0.0)
    timeout_minutes = _float_param(params, "timeout_minutes", 0.0)
    if real_model and params.get("confirm_real_text") is not True:
        raise ValueError("real drama generation requires explicit confirmation")
    if real_model and budget_cny <= 0:
        raise ValueError("real drama generation requires a positive budget")
    if real_model and not 0 < timeout_minutes <= 1440:
        raise ValueError("real drama generation requires a bounded positive timeout")
    if real_model:
        from ..drama_smoke import validate_real_text_tasks_ready

        validate_real_text_tasks_ready()
    return budget_cny, _llm_log_line_count()


def _drama_settle_budget(
    budget_cny: float, line_offset: int, progress_cb: Callable[[str, float], None]
) -> tuple[Optional[Dict[str, Any]], float]:
    """Honor cancel/timeout, then settle cost before any generated artifact write."""
    from ..cost_estimator import estimate_cost_since

    progress_cb("settle-budget", 0.78)
    report = estimate_cost_since(line_offset, paths.workspace_root())
    if int(report.get("dirty_lines") or 0) > 0:
        raise ValueError("drama billing evidence is invalid")
    cost_cny = float(report.get("cost_cny", 0.0))
    if budget_cny > 0 and cost_cny > budget_cny:
        return {
            "status": "budget_exceeded",
            "error_code": "drama_budget_exceeded",
            "budget_cny": budget_cny,
            "cost_cny": cost_cny,
        }, cost_cny
    return None, cost_cny


def _run_locked_drama_step(
    step: str,
    params: Dict[str, Any],
    progress_cb: Callable[[str, float], None],
    operation: Callable[[int], Dict[str, Any]],
) -> Dict[str, Any]:
    from ..workspace_lock import WorkspaceLocked, acquire_write_lock

    episode_no = _drama_episode_no(params)
    progress_cb("validate", 0.05)
    try:
        with acquire_write_lock(source=f"web-job-{step}"):
            progress_cb("generate", 0.15)
            return operation(episode_no)
    except WorkspaceLocked as exc:
        return _workspace_locked_blocked(exc)
    except JobCancelled:
        raise
    except (FileNotFoundError, ValueError) as exc:
        return _blocked("drama_prerequisite_invalid", "drama prerequisite is missing or invalid")
    except Exception as exc:
        return _drama_job_error(step, exc)


def _restore_drama_artifacts(snapshots: Dict[Path, Optional[bytes]]) -> None:
    """Best-effort exact rollback for a station-5 multi-file commit."""
    import os
    import threading

    for path, payload in snapshots.items():
        if payload is None:
            path.unlink(missing_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".rollback.{os.getpid()}.{threading.get_ident()}")
        tmp.write_bytes(payload)
        os.replace(tmp, path)


def _step_drama_plan(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    from .. import drama_planner
    from ..drama_schemas import episode_paths
    from ..utils import write_json

    def _op(episode_no: int) -> Dict[str, Any]:
        if episode_no > 1:
            raise ValueError("later episodes must be initialized through next-episode")
        budget_cny, line_offset = _drama_budget_start("drama-plan", params)
        result, attempt = _call_drama_text_model(
            "drama-plan", params, episode_no,
            lambda: drama_planner.run(paths.workspace_name(), mock=None, episode_no=episode_no),
        )
        exceeded, cost_cny = _drama_settle_budget(budget_cny, line_offset, progress_cb)
        if exceeded:
            _mark_drama_text_attempt(attempt, "budget_exceeded")
            return {**exceeded, "station": "setup", "episode_no": episode_no}
        progress_cb("commit", 0.85)
        ep = episode_paths(paths.workspace_name(), episode_no=episode_no)
        _bind_drama_text_artifact(attempt, {key: value for key, value in result.items() if key != "hook"})
        write_json(ep.setup_path, result)
        ep.hook_candidates_path.unlink(missing_ok=True)
        _mark_drama_text_attempt(attempt, "succeeded")
        return {"status": "succeeded", "station": "setup", "episode_no": episode_no,
                "budget_cny": budget_cny, "cost_cny": cost_cny, "committed": True}

    return _run_locked_drama_step("drama-plan", params, progress_cb, _op)


def _step_drama_hooks(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    from .. import hook_designer
    from ..drama_schemas import episode_paths
    from ..utils import write_json

    def _op(episode_no: int) -> Dict[str, Any]:
        workspace = paths.workspace_name()
        budget_cny, line_offset = _drama_budget_start("drama-hooks", params)
        result, attempt = _call_drama_text_model(
            "drama-hooks", params, episode_no,
            lambda: hook_designer.run(workspace, mock=None, episode_no=episode_no),
        )
        exceeded, cost_cny = _drama_settle_budget(budget_cny, line_offset, progress_cb)
        if exceeded:
            _mark_drama_text_attempt(attempt, "budget_exceeded")
            return {**exceeded, "station": "hook", "episode_no": episode_no}
        progress_cb("commit", 0.85)
        hooks = result.get("hooks") or []
        _bind_drama_text_artifact(attempt, result, candidates=hooks if isinstance(hooks, list) else None)
        write_json(episode_paths(workspace, episode_no=episode_no).hook_candidates_path, result)
        _mark_drama_text_attempt(attempt, "succeeded")
        return {
            "status": "succeeded",
            "station": "hook",
            "episode_no": episode_no,
            "hook_count": len(result.get("hooks") or []),
            "budget_cny": budget_cny,
            "cost_cny": cost_cny,
            "committed": True,
        }

    return _run_locked_drama_step("drama-hooks", params, progress_cb, _op)


def _step_drama_storyboard(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    from .. import storyboard_builder
    from ..drama_schemas import episode_paths
    from ..utils import write_json

    def _op(episode_no: int) -> Dict[str, Any]:
        workspace = paths.workspace_name()
        budget_cny, line_offset = _drama_budget_start("drama-storyboard", params)
        result, attempt = _call_drama_text_model(
            "drama-storyboard", params, episode_no,
            lambda: storyboard_builder.run(workspace, mock=None, episode_no=episode_no),
        )
        exceeded, cost_cny = _drama_settle_budget(budget_cny, line_offset, progress_cb)
        if exceeded:
            _mark_drama_text_attempt(attempt, "budget_exceeded")
            return {**exceeded, "station": "storyboard", "episode_no": episode_no}
        progress_cb("commit", 0.85)
        _bind_drama_text_artifact(attempt, result)
        write_json(episode_paths(workspace, episode_no=episode_no).storyboard_path, result)
        _mark_drama_text_attempt(attempt, "succeeded")
        return {"status": "succeeded", "station": "storyboard", "episode_no": episode_no,
                "budget_cny": budget_cny, "cost_cny": cost_cny, "committed": True}

    return _run_locked_drama_step("drama-storyboard", params, progress_cb, _op)


def _step_drama_characters(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    from .. import character_designer, drama_store
    from ..drama_schemas import (
        DramaStoryboard, character_paths, episode_paths, validate_storyboard_hard,
    )
    from ..utils import read_json_optional, write_json

    def _op(episode_no: int) -> Dict[str, Any]:
        workspace = paths.workspace_name()
        ep = episode_paths(workspace, episode_no=episode_no)
        storyboard_data = read_json_optional(ep.storyboard_path, None)
        if not isinstance(storyboard_data, dict):
            raise ValueError("station 3 storyboard is missing")
        storyboard = DramaStoryboard(**storyboard_data)
        if storyboard.episode_no != episode_no or validate_storyboard_hard(storyboard):
            raise ValueError("station 3 storyboard is invalid")
        setup = read_json_optional(episode_paths(workspace, episode_no=episode_no).setup_path, {})
        introduces_new = bool(setup.get("introduces_new_characters")) if isinstance(setup, dict) else False
        target = character_paths(workspace).sheet_path
        existing = read_json_optional(target, None)
        if episode_no > 1 and not introduces_new and isinstance(existing, dict):
            drama_store.migrate_fresh_episode_fingerprints_v2(workspace)
            result = character_designer.reuse_character_sheet_for_episode(
                existing, episode_no=episode_no
            )
            progress_cb("commit", 0.85)
            write_json(target, result)
            return {"status": "succeeded", "station": "characters", "episode_no": episode_no,
                    "skipped": True, "budget_cny": 0.0, "cost_cny": 0.0,
                    "committed": True}
        budget_cny, line_offset = _drama_budget_start("drama-characters", params)
        incoming, attempt = _call_drama_text_model(
            "drama-characters", params, episode_no,
            lambda: character_designer.run(workspace, mock=None, episode_no=episode_no),
        )
        exceeded, cost_cny = _drama_settle_budget(budget_cny, line_offset, progress_cb)
        if exceeded:
            _mark_drama_text_attempt(attempt, "budget_exceeded")
            return {**exceeded, "station": "characters", "episode_no": episode_no}
        result = character_designer.merge_character_sheet(existing if isinstance(existing, dict) else None, incoming)
        progress_cb("commit", 0.85)
        if isinstance(existing, dict):
            drama_store.migrate_fresh_episode_fingerprints_v2(workspace)
        _bind_drama_text_artifact(attempt, result)
        write_json(target, result)
        _mark_drama_text_attempt(attempt, "succeeded")
        return {"status": "succeeded", "station": "characters", "episode_no": episode_no,
                "skipped": False, "budget_cny": budget_cny, "cost_cny": cost_cny,
                "committed": True}

    return _run_locked_drama_step("drama-characters", params, progress_cb, _op)


def _step_drama_review_assemble(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    from .. import drama_reviewer, drama_store
    from ..drama_schemas import CharacterSheet, character_paths, episode_paths
    from ..utils import read_json_optional, write_json

    def _op(episode_no: int) -> Dict[str, Any]:
        workspace = paths.workspace_name()
        setup = read_json_optional(episode_paths(workspace, episode_no=episode_no).setup_path, {})
        sheet_data = read_json_optional(character_paths(workspace).sheet_path, {})
        sheet = CharacterSheet(**sheet_data)
        if (
            episode_no > 1
            and isinstance(setup, dict)
            and setup.get("introduces_new_characters") is True
            and sheet.episode_no != episode_no
        ):
            raise ValueError("station 4 must generate episode characters before drama review")
        budget_cny, line_offset = _drama_budget_start("drama-review-assemble", params)
        review, attempt = _call_drama_text_model(
            "drama-review-assemble", params, episode_no,
            lambda: drama_reviewer.run(workspace, mock=None, episode_no=episode_no),
        )
        exceeded, cost_cny = _drama_settle_budget(budget_cny, line_offset, progress_cb)
        if exceeded:
            _mark_drama_text_attempt(attempt, "budget_exceeded")
            return {**exceeded, "station": "review", "episode_no": episode_no}
        # Treat an explicit parse failure as a review artifact requiring human
        # attention; settle the already-incurred cost first, but do not publish it.
        if review.get("parse_failed"):
            raise ValueError("drama review parse failed")
        ep = episode_paths(workspace, episode_no=episode_no)
        _bind_drama_text_artifact(attempt, review)
        targets = (ep.review_path, ep.episode_path, ep.meta_path)
        snapshots = {path: path.read_bytes() if path.is_file() else None for path in targets}
        try:
            progress_cb("commit-review", 0.84)
            write_json(ep.review_path, review)
            progress_cb("assemble", 0.9)
            result = drama_store.assemble_episode(workspace, episode_no=episode_no)
        except BaseException:
            _restore_drama_artifacts(snapshots)
            raise
        _mark_drama_text_attempt(attempt, "succeeded")
        return {
            "status": "succeeded",
            "station": "review",
            "episode_no": episode_no,
            "verdict": review.get("verdict"),
            "assembled": bool(result.get("episode")),
            "budget_cny": budget_cny,
            "cost_cny": cost_cny,
            "committed": True,
        }

    return _run_locked_drama_step("drama-review-assemble", params, progress_cb, _op)


def _step_drama_video(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    """Run the bounded episode-1 video pipeline outside the HTTP request."""
    from .. import drama_video

    def _op(episode_no: int) -> Dict[str, Any]:
        if episode_no != 1:
            raise ValueError("video MVP supports episode 1 only")
        try:
            return drama_video.run_video_job(paths.workspace_name(), params, progress_cb)
        except drama_video.DramaVideoTimedOut as exc:
            raise JobTimeout(str(exc)) from exc

    return _run_locked_drama_step("drama-video", params, progress_cb, _op)


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
    "prepare-greenfield": _step_prepare_greenfield,
    "rebuild-for-start": _step_rebuild_for_start,
    "expand-premise": _step_expand_premise,
    "extract-style": _step_extract_style,
    "drama-plan": _step_drama_plan,
    "drama-hooks": _step_drama_hooks,
    "drama-storyboard": _step_drama_storyboard,
    "drama-characters": _step_drama_characters,
    "drama-review-assemble": _step_drama_review_assemble,
    "drama-video": _step_drama_video,
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


def _worker(job_id: str) -> None:
    """Thread body. Runs the step inside ``use_workspace``, surfaces
    progress + final status / error via ``_update``, and clears the
    per-workspace lock when finished."""

    with _JOBS_LOCK:
        job = dict(_JOBS[job_id])
    workspace = job["workspace"]
    step = job["step"]
    params = job["params"]
    deadline, timeout_minutes = _timeout_deadline(params)
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

    def _progress(sub_step: str, fraction: float) -> None:
        _check_cancelled(job_id, deadline, timeout_minutes)
        _update(job_id, current_step=sub_step, progress=float(fraction))

    _update(job_id, status="running", started_at=_now(), current_step=step)
    try:
        from ..llm_client import llm_deadline_scope

        with use_workspace(workspace), llm_deadline_scope(deadline):
            _check_cancelled(job_id, deadline, timeout_minutes)
            result = handler(params, _progress)
            if not (isinstance(result, dict) and result.get("committed") is True):
                _check_cancelled(job_id, deadline, timeout_minutes)
    except JobCancelled as exc:
        _update(
            job_id,
            status="aborted",
            current_step="timeout" if isinstance(exc, JobTimeout) else "cancelled",
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
    except Exception as exc:
        trace_id = uuid.uuid4().hex
        _update(
            job_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            trace_id=trace_id,
            finished_at=_now(),
        )
        # Server-side: full traceback for debugging. Mirror's iter 026
        # P5 hardening pattern for routes.py 500 path.
        import sys

        sys.stderr.write(f"[jobs] job_id={job_id} trace_id={trace_id}\n")
        traceback.print_exc(file=sys.stderr)
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


def _summarize_result(step: str, result: Any) -> Any:
    """Coerce step-native return types into a JSON-safe summary the
    client can render without needing the full payload."""
    if step.startswith("drama-") and isinstance(result, dict):
        return {
            key: result.get(key)
            for key in (
                "status", "station", "episode_no", "hook_count", "skipped",
                "verdict", "assembled", "error_code",
                "budget_cny", "cost_cny",
                "task_id", "provider", "provider_model", "duration_seconds",
                "ratio", "resolution", "file_size_bytes", "network_requests",
            )
            if key in result
        }
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
    params = params or {}
    if not is_known_step(step):
        raise ValueError(f"unknown step: {step}")

    with _WORKSPACE_LOCK:
        if workspace in _WORKSPACE_JOBS:
            existing = _WORKSPACE_JOBS[workspace]
            raise RuntimeError(f"workspace_busy:{existing}")
        if not (paths.WORKSPACE_DIR / workspace).is_dir():
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
        _WORKSPACE_JOBS[workspace] = record["job_id"]

    _persist_job(record)

    # Iter 027 P2 (review #8 fix): if thread.start() fails (OS thread
    # limit reached, fork restrictions, etc.), the _WORKSPACE_JOBS entry
    # would otherwise dangle forever — the worker never runs, so the
    # ``finally`` cleanup inside _worker never fires, and every future
    # POST to this workspace returns 409 pointing at a dead job_id.
    # Roll back both tables on failure and re-raise so the caller
    # surfaces the underlying error.
    thread = threading.Thread(
        target=_worker, args=(record["job_id"],), daemon=True, name=f"job-{record['job_id'][:8]}"
    )
    try:
        thread.start()
    except RuntimeError:
        with _WORKSPACE_LOCK:
            _WORKSPACE_JOBS.pop(workspace, None)
        with _JOBS_LOCK:
            _JOBS.pop(record["job_id"], None)
        raise
    return dict(record)


def reset_for_tests() -> None:
    """Test helper: wipe in-memory job tables between tests so state
    from one test doesn't leak into the next. Not used by production
    code."""
    with _WORKSPACE_LOCK:
        _WORKSPACE_JOBS.clear()
    with _JOBS_LOCK:
        _JOBS.clear()


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
