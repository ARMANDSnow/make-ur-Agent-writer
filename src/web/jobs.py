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
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(job, ensure_ascii=False) + "\n")
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
        # iter072 (#5): pending/running first (active=1 wins under reverse),
        # then most-recent timestamp. ``_as_ts`` swallows corrupt timestamps
        # so one bad jsonl row can't 500 the whole list.
        active = 1 if item.get("status") in {"pending", "running"} else 0
        return (active, _as_ts(item.get("finished_at")) or _as_ts(item.get("started_at")))

    jobs = sorted(latest_by_id.values(), key=_sort_key, reverse=True)
    out: list[Dict[str, Any]] = []
    for job in jobs[:limit]:
        snapshot = dict(job)
        if snapshot.get("status") in {"pending", "running"}:
            live = get_job(str(snapshot.get("job_id")))
            if live is not None:
                snapshot = live
            else:
                snapshot["status"] = "lost"
                snapshot["error"] = "worker process restarted before this job reached a terminal state"
        out.append(snapshot)
    return out


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
        if job.get("cancel_requested"):
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
def _blocked(reason: str, error: str) -> Dict[str, Any]:
    return {"status": "blocked", "blocked": [{"reason": reason, "error": error}]}


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
    return write_chapters(
        chapters=int(params.get("chapters", 1)),
        force=bool(params.get("force", False)),
        resume_from=int(params.get("resume_from", 1)),
    )


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
    from ..writer import ChapterPlanInvalid, _chapter_plan_item, _load_chapter_plan, _run_context

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

    progress_cb("review", 0.1)
    review_target(
        md_path,
        enforce_relationship_checklist=True,
        tier=params.get("tier"),
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

        progress_cb("extract", 0.1)
        record = extract_style_card(sample, force=bool(params.get("force", True)))
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
        with use_workspace(workspace):
            _check_cancelled(job_id, deadline, timeout_minutes)
            result = handler(params, _progress)
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
