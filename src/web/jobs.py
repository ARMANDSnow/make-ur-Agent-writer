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
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .. import auto_pipeline
from ..auto_bootstrap import bootstrap_all
from ..chapter_splitter import split_all
from ..cli_apply_bootstrap import apply_bootstrap
from ..compressor import compress_all
from ..book_runner import BookRunBlocked, run_write_book
from ..config import ROOT
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
    }


def _job_log_path(workspace: str) -> Path:
    return ROOT / "workspaces" / workspace / "logs" / "web_jobs.jsonl"


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
    for path in (ROOT / "workspaces").glob("*/logs/web_jobs.jsonl"):
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


def workspace_busy(workspace: str) -> Optional[str]:
    """Return the running job_id if ``workspace`` already has one,
    otherwise None. Cheap pre-check before starting a job."""
    with _WORKSPACE_LOCK:
        return _WORKSPACE_JOBS.get(workspace)


# ---- step dispatch ---------------------------------------------------------


# Each step function takes a workspace-scoped context (the worker
# already set ``WORKSPACE_NAME`` via use_workspace) and the POST body's
# ``params`` dict. The function should accept ``progress_cb`` if it
# can report sub-progress; otherwise the worker reports only entry +
# exit (progress 0.0 → 1.0).
def _step_normalize(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    return normalize_all(lang=params.get("lang"))


def _step_split(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    return split_all(lang=params.get("lang"))


def _step_extract(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    return extract_all(
        volume=params.get("volume", "all"),
        limit=params.get("limit"),
        force=bool(params.get("force", False)),
    )


def _step_compress(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    return compress_all()


def _step_bootstrap_all(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    return bootstrap_all(force=bool(params.get("force", False)))


def _step_apply_bootstrap(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    name = params.get("name")
    if not name:
        raise ValueError("apply-bootstrap requires params.name")
    return apply_bootstrap(name, confirm=True)


def _step_debate(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    topic = params.get("topic")
    return run_debate(topic=topic) if topic else run_debate()


def _step_plan_chapters(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    return generate_chapter_plan(
        target_chapters=int(params.get("target_chapters", 5)),
        force=bool(params.get("force", False)),
        append_count=int(params.get("append_count", 0)),
        from_chapter=int(params.get("from_chapter", 0)),
        require_start_point=bool(params.get("require_start_point", True)),
    )


def _step_draft_once_dev(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    return write_chapters(
        chapters=int(params.get("chapters", 1)),
        force=bool(params.get("force", False)),
        resume_from=int(params.get("resume_from", 1)),
    )


def _step_write_book(params: Dict[str, Any], progress_cb: Callable[[str, float], None]) -> Any:
    return run_write_book(
        chapters=int(params.get("chapters", 1)),
        resume_from=int(params.get("resume_from", 1)),
        force=bool(params.get("force", False)),
        max_retries=int(params.get("max_retries", 2)),
        budget_cny=_float_param(params, "budget_cny", 0.0),
        replan_every=int(params.get("replan_every", 0)),
        min_confidence=_float_param(params, "min_confidence", 0.7),
        auto_advance=bool(params.get("auto_advance", True)),
        require_start_point=bool(params.get("require_start_point", True)),
        require_plan=bool(params.get("require_plan", True)),
        require_external_review=bool(params.get("require_external_review", True)),
        progress_cb=progress_cb,
    )


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
    "draft-once-dev": _step_draft_once_dev,
    "auto-pipeline-greenfield": _step_auto_pipeline_greenfield,
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
        _update(job_id, current_step=sub_step, progress=float(fraction))

    _update(job_id, status="running", started_at=_now(), current_step=step)
    try:
        with use_workspace(workspace):
            result = handler(params, _progress)
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
        _update(
            job_id,
            status=terminal,
            current_step=terminal,
            progress=1.0,
            finished_at=_now(),
            result_summary=_summarize_result(step, result),
        )
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
            "snapshot_path": result.get("snapshot_path"),
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
