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
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .. import auto_pipeline, paths, start_point
from ..auto_bootstrap import bootstrap_all
from ..chapter_splitter import split_all
from ..cli_apply_bootstrap import apply_bootstrap
from ..compressor import compress_all
from ..book_runner import BookRunBlocked, run_write_book
from ..debater import run_debate
from ..extractor import extract_all
from ..plot_planner import generate_chapter_plan
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
    jobs = sorted(
        latest_by_id.values(),
        key=lambda item: float(item.get("finished_at") or item.get("started_at") or 0),
        reverse=True,
    )
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
    if not norm_dir.exists() or not any(norm_dir.glob("*.md")):
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
    return extract_all(
        volume=params.get("volume", "all"),
        limit=params.get("limit"),
        force=bool(params.get("force", False)),
    )


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
    return run_debate(topic=topic, force=force) if topic else run_debate(force=force)


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
    from ..writer import _chapter_plan_item, _load_chapter_plan, _run_context

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
    plan = _load_chapter_plan()
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
    return auto_pipeline.run_auto_pipeline(
        target_chapters=int(params.get("chapters", 1)),
        progress_cb=progress_cb,
        skip_extract=bool(params.get("skip_extract", False)),
        extract_limit=params.get("extract_limit", 5),
        force=bool(params.get("force", False)),
        plan_chapters_target=params.get("plan_chapters_target"),
        require_start_point=bool(params.get("require_start_point", True)),
    )


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


def _step_prepare_greenfield(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    """iter 048a: workbench stage ① — run only the 6 prep steps
    (normalize → apply-bootstrap) as a single composite job, then stop.

    Greenfield onboarding has no prior start point, and the workbench
    drives debate / plan-chapters / write-book as their own later-stage
    jobs — so this step deliberately does NOT continue past
    apply-bootstrap. ``total=6, emit_done=True`` remaps the shared prep
    fractions onto a self-contained 0→100% bar so the stage ① card fills
    cleanly instead of stalling at 5/9 (which a naive ``index/9`` reuse
    would produce). See ``auto_pipeline._run_prepare_steps``."""
    return auto_pipeline._run_prepare_steps(
        progress_cb=progress_cb,
        total=6,
        emit_done=True,
        skip_extract=bool(params.get("skip_extract", False)),
        extract_limit=params.get("extract_limit", 5),
        force=bool(params.get("force", False)),
    )


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
    "expand-premise": _step_expand_premise,
}


def is_known_step(step: str) -> bool:
    return step in STEP_HANDLERS


# ---- worker ----------------------------------------------------------------


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
        with _WORKSPACE_LOCK:
            _WORKSPACE_JOBS.pop(workspace, None)


def _summarize_result(step: str, result: Any) -> Any:
    """Coerce step-native return types into a JSON-safe summary the
    client can render without needing the full payload."""
    if step in {"auto-pipeline-greenfield", "auto-pipeline"} and isinstance(result, dict):
        write_part = result.get("write") or []
        return {"chapters_written": len(write_part)}
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
        _WORKSPACE_JOBS[workspace] = record["job_id"]

    with _JOBS_LOCK:
        _JOBS[record["job_id"]] = record
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
    return float(value)
