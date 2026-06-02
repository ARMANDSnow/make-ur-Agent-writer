"""iter 025: route table + handler functions.

Design:

* ``dispatch(method, path) -> (status, headers, body)`` is the single
  entrypoint. ``server.BaseHTTPRequestHandler`` only converts wire-format
  to/from this tuple shape.
* Each handler is a pure function so unit tests can call them directly
  without spinning up an HTTP server.
* JSON responses are always shaped ``{"key": value}`` or ``{"error": "..."}``
  — never bare arrays — so future fields can be added without breaking
  clients.

iter 026 will add POST/PUT entries to ``_ROUTES``; iter 025 ships GET-only.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

from .. import paths, start_point
from ..book_runner import check_write_readiness
from ..cli_workspace import list_workspaces
from ..cost_estimator import estimate_cost
from ..observability import collect_status
from ..utils import read_json, read_json_optional
from . import jobs, settings as settings_mod, static, templates, wizard
from ._naming import RESERVED_NAMES as _RESERVED_WORKSPACE_NAMES_SHARED  # noqa: F401
from ._naming import (
    WORKSPACE_NAME_RE as _WORKSPACE_NAME_RE_SHARED,  # noqa: F401
)
from ._naming import (
    validate_workspace_name as _shared_validate_workspace_name,
)
from .reviews_aggregator import aggregate_reviews
from .workspace_ctx import use_workspace

# A handler returns (status_code, content_type, body_bytes). Routes whose
# pattern captures named groups receive them as kwargs.
Handler = Callable[..., Tuple[int, str, bytes]]

_OVERVIEW_CACHE_TTL_SECONDS = 3.0
_OVERVIEW_CACHE_LOCK = threading.Lock()
_OVERVIEW_CACHE: Dict[Tuple[Any, ...], Tuple[float, Dict[str, Any]]] = {}


# ---- helpers ----------------------------------------------------------------


# Iter 027 P2 (review #7): regex + reserved set now live in
# ``src/web/_naming.py`` so routes.py and wizard.py share one source.
# The module-level aliases below are kept for any test / external code
# that imported the old names from this module.
_WORKSPACE_NAME_RE = _WORKSPACE_NAME_RE_SHARED
_RESERVED_WORKSPACE_NAMES = _RESERVED_WORKSPACE_NAMES_SHARED


def _json(status: int, payload: Dict[str, Any]) -> Tuple[int, str, bytes]:
    # ``collect_status`` and ``estimate_cost`` embed ``pathlib.Path`` values
    # (and a few sets/datetimes show up via reviewer plumbing). The default
    # ``str`` coercion turns them into stable repo-relative-ish strings
    # without needing per-handler post-processing.
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    return status, "application/json; charset=utf-8", body


def _html(status: int, html: str) -> Tuple[int, str, bytes]:
    return status, "text/html; charset=utf-8", html.encode("utf-8")


def _validate_workspace_name(name: str) -> bool:
    """Thin wrapper around the shared validator (iter 027 P2 #7)."""
    return _shared_validate_workspace_name(name)


def _workspace_exists(name: str) -> bool:
    return (paths.WORKSPACE_DIR / name).is_dir()


def _workspace_error(name: str) -> Optional[Tuple[int, str, bytes]]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    return None


# ---- handlers ---------------------------------------------------------------


def render_index() -> Tuple[int, str, bytes]:
    return _html(200, templates.render_index(list_workspaces()))


def render_workspace(name: str) -> Tuple[int, str, bytes]:
    if not _validate_workspace_name(name):
        return _html(400, "<h1>400</h1><p>invalid workspace name</p>")
    if not _workspace_exists(name):
        return _html(404, f"<h1>404</h1><p>workspace not found: {name}</p>")
    return _html(200, templates.render_workspace(name))


def render_static_css() -> Tuple[int, str, bytes]:
    return 200, "text/css; charset=utf-8", static.CSS_BODY.encode("utf-8")


def render_static_js() -> Tuple[int, str, bytes]:
    return 200, "application/javascript; charset=utf-8", static.JS_DASHBOARD.encode("utf-8")


def render_static_wizard_js() -> Tuple[int, str, bytes]:
    return 200, "application/javascript; charset=utf-8", static.JS_WIZARD.encode("utf-8")


def api_workspaces() -> Tuple[int, str, bytes]:
    return _json(200, {"workspaces": list_workspaces()})


def api_workspaces_overview() -> Tuple[int, str, bytes]:
    names = list_workspaces()
    key = _overview_cache_key(names)
    now = time.monotonic()
    with _OVERVIEW_CACHE_LOCK:
        cached = _OVERVIEW_CACHE.get(key)
        if cached and cached[0] > now:
            return _json(200, cached[1])

    payload = {"workspaces": [_workspace_overview(name) for name in names]}
    with _OVERVIEW_CACHE_LOCK:
        _OVERVIEW_CACHE.clear()
        _OVERVIEW_CACHE[key] = (now + _OVERVIEW_CACHE_TTL_SECONDS, payload)
    return _json(200, payload)


def _overview_cache_key(names: List[str]) -> Tuple[Any, ...]:
    root = paths.WORKSPACE_DIR
    stamps = []
    for name in names:
        ws = root / name
        stamps.append(
            (
                name,
                _mtime_ns(ws / "data" / "chapter_manifest.json"),
                _mtime_ns(ws / "outputs" / "debate" / "chapter_plan.json"),
                _mtime_ns(ws / "data" / "manual_overrides" / "start_chapter.json"),
                _mtime_ns(ws / "outputs" / "drafts"),
                _mtime_ns(ws / "outputs" / "reviews"),
                _mtime_ns(ws / "logs" / "web_jobs.jsonl"),
                _mtime_ns(ws / "logs" / "llm_calls.jsonl"),
            )
        )
    return (str(root), tuple(stamps))


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _clear_overview_cache() -> None:
    with _OVERVIEW_CACHE_LOCK:
        _OVERVIEW_CACHE.clear()


def _workspace_overview(name: str) -> Dict[str, Any]:
    root = paths.WORKSPACE_DIR / name
    overview: Dict[str, Any] = {
        "name": name,
        "path": str(root),
        "exists": root.is_dir(),
        "chapter_count": 0,
        "draft_count": 0,
        "review_total": 0,
        "review_accepted": 0,
        "review_blocked": 0,
        "start_point": {"has_start_point": False, "start_chapter_id": ""},
        "plan": {"exists": False, "chapters": 0, "has_fingerprint": False},
        "readiness": {"status": "blocked", "blockers": ["workspace_missing"], "warnings": [], "recommended_commands": []},
        "recent_job": None,
    }
    if not root.is_dir():
        return overview
    with use_workspace(name):
        try:
            manifest = read_json_optional(paths.chapter_manifest_path(), [])
            if isinstance(manifest, dict):
                manifest = manifest.get("chapters", manifest.get("entries", []))
            overview["chapter_count"] = len(manifest) if isinstance(manifest, list) else 0
            overview["draft_count"] = len(list(paths.drafts_dir().glob("chapter_*.md")))
            overview["start_point"] = start_point.get_start_point_metadata()
            plan_path = paths.chapter_plan_path()
            plan_error = ""
            try:
                plan = read_json(plan_path, {})
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                plan = {}
                plan_error = f"{type(exc).__name__}: {exc}"
            if isinstance(plan, dict):
                overview["plan"] = {
                    "exists": bool(plan) or bool(plan_error),
                    "chapters": len(plan.get("chapters") or []),
                    "has_fingerprint": bool(plan.get("plan_fingerprint")),
                    "start_chapter_id": plan.get("start_chapter_id", ""),
                }
                if plan_error:
                    overview["plan"]["error"] = plan_error
            reviews = aggregate_reviews(paths.drafts_dir())
            stats = reviews.get("stats", {}) if isinstance(reviews, dict) else {}
            total = int(stats.get("total") or 0)
            accepted = int(stats.get("accepted") or 0)
            overview["review_total"] = total
            overview["review_accepted"] = accepted
            overview["review_blocked"] = max(total - accepted, 0)
            overview["readiness"] = _safe_readiness(chapters=1, resume_from=1)
            recent = jobs.recent_jobs(name, limit=1)
            overview["recent_job"] = recent[0] if recent else None
        except Exception as exc:
            overview["error"] = f"{type(exc).__name__}: {exc}"
            overview["readiness"] = {
                "status": "blocked",
                "blockers": [f"overview_error:{type(exc).__name__}: {exc}"],
                "warnings": [],
                "recommended_commands": ["inspect workspace data and rerun the failing preparation step"],
            }
    return overview


def api_workspace_status(name: str) -> Tuple[int, str, bytes]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    with use_workspace(name):
        return _json(200, collect_status())


def api_workspace_cost(name: str) -> Tuple[int, str, bytes]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    with use_workspace(name):
        return _json(200, estimate_cost())


def api_workspace_manifest(name: str) -> Tuple[int, str, bytes]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    with use_workspace(name):
        manifest = read_json(paths.chapter_manifest_path(), [])
    return _json(200, {"chapters": manifest if isinstance(manifest, list) else []})


def api_workspace_start_point(name: str) -> Tuple[int, str, bytes]:
    error = _workspace_error(name)
    if error:
        return error
    with use_workspace(name):
        return _json(200, {"start_point": start_point.get_start_point_metadata()})


def api_workspace_set_start_point(name: str, body: bytes) -> Tuple[int, str, bytes]:
    error = _workspace_error(name)
    if error:
        return error
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})
    value = payload.get("start_point") or payload.get("name")
    if not isinstance(value, str) or not value.strip():
        return _json(400, {"error": "missing or invalid start_point"})
    with use_workspace(name):
        start_point.set_start_point(value)
        _clear_overview_cache()
        readiness = _safe_readiness(chapters=1, resume_from=1)
        return _json(
            200,
            {
                "start_point": start_point.get_start_point_metadata(),
                "readiness": readiness,
            },
        )


def api_workspace_reviews(name: str) -> Tuple[int, str, bytes]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    with use_workspace(name):
        return _json(200, aggregate_reviews(paths.drafts_dir()))


def api_workspace_readiness(
    name: str,
    chapters: int = 1,
    resume_from: int = 1,
    replan_every: int = 0,
) -> Tuple[int, str, bytes]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    with use_workspace(name):
        result = _safe_readiness(chapters=chapters, resume_from=resume_from, replan_every=replan_every)
    return _json(200, result)


def _safe_readiness(**kwargs: Any) -> Dict[str, Any]:
    try:
        return check_write_readiness(**kwargs)
    except Exception as exc:
        chapters = int(kwargs.get("chapters", 1) or 1)
        resume_from = int(kwargs.get("resume_from", 1) or 1)
        return {
            "status": "blocked",
            "chapters": chapters,
            "resume_from": resume_from,
            "plan_window": chapters,
            "blockers": [f"readiness_error:{type(exc).__name__}: {exc}"],
            "warnings": [],
            "recommended_commands": ["inspect chapter_plan.json and rerun plan-chapters --force --require-start-point"],
        }


def api_workspace_logs_tail(name: str, n: int = 50) -> Tuple[int, str, bytes]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    n = max(1, min(n, 1000))
    with use_workspace(name):
        log_path = paths.llm_calls_log_path()
        lines = _tail_jsonl(log_path, n)
    return _json(200, {"lines": lines})


def api_workspace_recent_jobs(name: str, limit: int = 5) -> Tuple[int, str, bytes]:
    error = _workspace_error(name)
    if error:
        return error
    return _json(200, {"jobs": jobs.recent_jobs(name, limit=limit)})


def api_workspace_drafts(name: str) -> Tuple[int, str, bytes]:
    error = _workspace_error(name)
    if error:
        return error
    with use_workspace(name):
        drafts = [_draft_summary(path) for path in sorted(paths.drafts_dir().glob("chapter_*.md"))]
    return _json(200, {"drafts": [item for item in drafts if item]})


def api_workspace_draft(name: str, chapter: str) -> Tuple[int, str, bytes]:
    error = _workspace_error(name)
    if error:
        return error
    try:
        chapter_no = int(chapter)
    except ValueError:
        return _json(400, {"error": "chapter must be an integer"})
    if chapter_no < 1 or chapter_no > 9999:
        return _json(400, {"error": "chapter out of range"})
    with use_workspace(name):
        md_path = paths.drafts_dir() / f"chapter_{chapter_no:02d}.md"
        if not md_path.exists():
            return _json(404, {"error": f"draft not found: chapter_{chapter_no:02d}"})
        text = md_path.read_text(encoding="utf-8", errors="replace")
        meta = read_json(paths.drafts_dir() / f"chapter_{chapter_no:02d}.meta.json", {})
        review = read_json(paths.reviews_dir() / f"chapter_{chapter_no:02d}.review.json", {})
    return _json(
        200,
        {
            "chapter": chapter_no,
            "path": str(md_path),
            "content": text,
            "meta": meta if isinstance(meta, dict) else {},
            "review": review if isinstance(review, dict) else {},
        },
    )


def _draft_summary(path: Path) -> Optional[Dict[str, Any]]:
    match = re.match(r"chapter_(\d+)\.md$", path.name)
    if not match:
        return None
    chapter_no = int(match.group(1))
    meta = read_json(path.with_suffix(".meta.json"), {})
    review = read_json(path.parent.parent / "reviews" / f"chapter_{chapter_no:02d}.review.json", {})
    return {
        "chapter": chapter_no,
        "path": str(path),
        "chars": len(path.read_text(encoding="utf-8", errors="replace")),
        "verdict": meta.get("verdict") if isinstance(meta, dict) else None,
        "needs_human_review": bool(meta.get("needs_human_review")) if isinstance(meta, dict) else False,
        "rewrite_count": meta.get("rewrite_count") if isinstance(meta, dict) else None,
        "review_verdict": review.get("verdict") if isinstance(review, dict) else None,
        "snapshot_path": meta.get("snapshot_path") if isinstance(meta, dict) else None,
    }


def _tail_jsonl(path: Path, n: int) -> List[Dict[str, Any]]:
    """Iter 026 code-review #3: read the LAST n lines without loading
    the whole file. ``llm_calls.jsonl`` grows monotonically across a
    pipeline run (longzu already has thousands of entries) and the
    iter 025 implementation called ``fh.readlines()`` which pulled the
    entire file into RAM on every poll.

    Strategy: seek to end, read 8 KB blocks backward, accumulate until
    we have ``n+1`` newlines (or hit start of file), then split and
    take the trailing ``n`` lines. O(n * line_length) memory instead
    of O(file_size)."""
    if not path.exists() or not path.is_file():
        return []
    if n <= 0:
        return []
    chunk_size = 8192
    raw_tail = b""
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)  # end
            position = fh.tell()
            # Collect blocks until we have ``n + 1`` newlines so we can
            # discard the partial-first-line and keep exactly the last
            # ``n`` complete lines.
            while position > 0 and raw_tail.count(b"\n") <= n:
                read_size = min(chunk_size, position)
                position -= read_size
                fh.seek(position)
                raw_tail = fh.read(read_size) + raw_tail
    except OSError:
        return []
    lines = raw_tail.splitlines()
    # Iter 027 P2 (review #5 fix): when ``position > 0`` the first byte
    # of ``raw_tail`` is mid-record — the read started inside a JSON
    # line because the file is bigger than our backward read. Drop that
    # half-line so we never surface ``{"raw": "...partial json..."}``
    # rows to the dashboard. When ``position == 0`` we read from byte 0
    # and the first line IS complete.
    if position > 0 and lines:
        lines = lines[1:]
    if len(lines) > n:
        lines = lines[-n:]
    out: List[Dict[str, Any]] = []
    for raw in lines:
        try:
            text = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            continue
        if not text:
            continue
        try:
            out.append(json.loads(text))
        except json.JSONDecodeError:
            out.append({"raw": text})
    return out


# ---- POST handlers (iter 026) ----------------------------------------------


def api_wizard_start(body: bytes, headers: Dict[str, str]) -> Tuple[int, str, bytes]:
    """POST /api/wizard/start — multipart upload + auto-pipeline kick-off."""

    content_type = headers.get("content-type", "")
    return wizard.start_upload(body, content_type)


def render_wizard_page() -> Tuple[int, str, bytes]:
    return _html(200, templates.render_wizard())


def render_settings_page() -> Tuple[int, str, bytes]:
    return _html(200, templates.render_settings())


def api_settings_get() -> Tuple[int, str, bytes]:
    return settings_mod.get_settings()


def api_settings_put(body: bytes) -> Tuple[int, str, bytes]:
    return settings_mod.put_settings(body)


def api_run_step(name: str, body: bytes) -> Tuple[int, str, bytes]:
    """POST /api/workspace/<name>/run — kick off a background job.

    Body: ``{"step": "...", "params": {...}}``. Returns
    ``202 {"job_id": "..."}`` on success, ``409`` if the workspace
    already has a running job, ``400`` for unknown step / bad JSON,
    ``404`` if the workspace doesn't exist.
    """

    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})
    step = payload.get("step")
    if not step or not isinstance(step, str):
        return _json(400, {"error": "missing or invalid 'step' field"})
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return _json(400, {"error": "'params' must be an object"})
    params_error, params = _validated_run_params(step, params)
    if params_error:
        return _json(400, {"error": params_error})
    try:
        job = jobs.start_job(name, step, params)
    except ValueError as exc:
        return _json(400, {"error": str(exc)})
    except RuntimeError as exc:
        msg = str(exc)
        if msg.startswith("workspace_busy:"):
            return _json(
                409,
                {
                    "error": "workspace already has a running job",
                    "running_job_id": msg.split(":", 1)[1],
                },
            )
        raise
    return _json(202, {"job_id": job["job_id"], "status": job["status"], "step": step})


def _validated_run_params(step: str, params: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    if step == "write-book":
        error, out = _validate_write_book_params(params)
        return error, out
    if step == "plan-chapters":
        error, out = _validate_plan_chapters_params(params)
        return error, out
    return None, params


def _validate_write_book_params(params: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    out: Dict[str, Any] = {}
    for key, default, minimum in (
        ("chapters", 1, 1),
        ("resume_from", 1, 1),
        ("max_retries", 2, 0),
        ("replan_every", 0, 0),
    ):
        error, value = _int_param(params, key, default, minimum=minimum)
        if error:
            return error, {}
        out[key] = value
    error, budget = _float_param(params, "budget_cny", 0.0, minimum=0.0)
    if error:
        return error, {}
    error, confidence = _float_param(params, "min_confidence", 0.7, minimum=0.0, maximum=1.0)
    if error:
        return error, {}
    out["budget_cny"] = budget
    out["min_confidence"] = confidence
    for key, default in (
        ("force", False),
        ("auto_advance", True),
        ("require_start_point", True),
        ("require_plan", True),
        ("require_external_review", True),
    ):
        error, value = _bool_param(params, key, default)
        if error:
            return error, {}
        out[key] = value
    return None, out


def _validate_plan_chapters_params(params: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    raw_target = params.get("target_chapters", params.get("chapters", 5))
    error, target = _int_value(raw_target, "target_chapters", minimum=1, maximum=200)
    if error:
        return error, {}
    return None, {
        "target_chapters": target,
        "force": True,
        "append_count": 0,
        "from_chapter": 0,
        "require_start_point": True,
    }


def _int_param(params: Dict[str, Any], key: str, default: int, *, minimum: int = 0, maximum: Optional[int] = None) -> Tuple[Optional[str], int]:
    return _int_value(params.get(key, default), key, minimum=minimum, maximum=maximum)


def _int_value(value: Any, key: str, *, minimum: int = 0, maximum: Optional[int] = None) -> Tuple[Optional[str], int]:
    try:
        out = int(value)
    except (TypeError, ValueError):
        return f"{key} must be an integer", 0
    if out < minimum:
        return f"{key} must be >= {minimum}", 0
    if maximum is not None and out > maximum:
        return f"{key} must be <= {maximum}", 0
    return None, out


def _float_param(params: Dict[str, Any], key: str, default: float, *, minimum: float = 0.0, maximum: Optional[float] = None) -> Tuple[Optional[str], float]:
    try:
        out = float(params.get(key, default))
    except (TypeError, ValueError):
        return f"{key} must be a number", 0.0
    if out < minimum:
        return f"{key} must be >= {minimum}", 0.0
    if maximum is not None and out > maximum:
        return f"{key} must be <= {maximum}", 0.0
    return None, out


def _bool_param(params: Dict[str, Any], key: str, default: bool) -> Tuple[Optional[str], bool]:
    value = params.get(key, default)
    if isinstance(value, bool):
        return None, value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return None, True
        if lowered in {"0", "false", "no", "off"}:
            return None, False
    return f"{key} must be a boolean", False


def api_job_status(name: str, job_id: str) -> Tuple[int, str, bytes]:
    """GET /api/workspace/<name>/job/<job_id> — poll job state."""

    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    job = jobs.get_job(job_id)
    if job is None:
        return _json(404, {"error": "job not found"})
    if job.get("workspace") != name:
        # Don't leak existence of a job belonging to another workspace.
        return _json(404, {"error": "job not found"})
    return _json(200, job)


# ---- dispatcher -------------------------------------------------------------


# (method, compiled regex, handler). Named groups in the regex become
# kwargs passed to the handler.
_ROUTES: List[Tuple[str, "re.Pattern[str]", Handler]] = [
    ("GET", re.compile(r"^/$"), lambda **_: render_index()),
    ("GET", re.compile(r"^/static/app\.css$"), lambda **_: render_static_css()),
    ("GET", re.compile(r"^/static/app\.js$"), lambda **_: render_static_js()),
    ("GET", re.compile(r"^/static/wizard\.js$"), lambda **_: render_static_wizard_js()),
    ("GET", re.compile(r"^/workspace/(?P<name>[^/]+)/?$"), lambda name, **_: render_workspace(name)),
    ("GET", re.compile(r"^/api/workspaces/overview/?$"), lambda **_: api_workspaces_overview()),
    ("GET", re.compile(r"^/api/workspaces/?$"), lambda **_: api_workspaces()),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/status/?$"), lambda name, **_: api_workspace_status(name)),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/cost/?$"), lambda name, **_: api_workspace_cost(name)),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/manifest/?$"), lambda name, **_: api_workspace_manifest(name)),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/start-point/?$"), lambda name, **_: api_workspace_start_point(name)),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/start-point/?$"),
        lambda name, _body=b"", **_: api_workspace_set_start_point(name, _body),
    ),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/reviews/?$"), lambda name, **_: api_workspace_reviews(name)),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/drafts/?$"), lambda name, **_: api_workspace_drafts(name)),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/draft/(?P<chapter>\d+)/?$"),
        lambda name, chapter, **_: api_workspace_draft(name, chapter),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/readiness/?$"),
        lambda name, _query=None, **_: api_workspace_readiness(
            name,
            chapters=_parse_int(_query, "chapters", 1),
            resume_from=_parse_int(_query, "resume_from", 1),
            replan_every=_parse_int(_query, "replan_every", 0),
        ),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/logs/tail/?$"),
        lambda name, _query=None, **_: api_workspace_logs_tail(name, n=_parse_n(_query)),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/jobs/recent/?$"),
        lambda name, _query=None, **_: api_workspace_recent_jobs(name, limit=_parse_n(_query)),
    ),
    # iter 026: POST /run (start a job) + GET /job/<id> (poll progress)
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/run/?$"),
        lambda name, _body=b"", **_: api_run_step(name, _body),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/job/(?P<job_id>[a-f0-9]{32})/?$"),
        lambda name, job_id, **_: api_job_status(name, job_id),
    ),
    # iter 026: onboarding wizard — single multipart POST that starts an
    # auto-pipeline job; client then polls the job_id from above.
    ("GET", re.compile(r"^/wizard/?$"), lambda **_: render_wizard_page()),
    (
        "POST",
        re.compile(r"^/api/wizard/start/?$"),
        lambda _body=b"", _headers=None, **_: api_wizard_start(_body, _headers or {}),
    ),
    # iter 026 P4: model-switch panel
    ("GET", re.compile(r"^/settings/?$"), lambda **_: render_settings_page()),
    ("GET", re.compile(r"^/static/settings\.js$"), lambda **_: (200, "application/javascript; charset=utf-8", static.JS_SETTINGS.encode("utf-8"))),
    ("GET", re.compile(r"^/api/settings/?$"), lambda **_: api_settings_get()),
    ("PUT", re.compile(r"^/api/settings/?$"), lambda _body=b"", **_: api_settings_put(_body)),
]


def _parse_n(query: Dict[str, List[str]] | None) -> int:
    if not query:
        return 50
    raw = query.get("n", ["50"])
    try:
        return int(raw[0])
    except (TypeError, ValueError):
        return 50


def _parse_int(query: Dict[str, List[str]] | None, key: str, default: int) -> int:
    if not query:
        return default
    raw = query.get(key, [str(default)])
    try:
        return int(raw[0])
    except (TypeError, ValueError):
        return default


def dispatch(
    method: str,
    path_with_query: str,
    body: bytes = b"",
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[int, str, bytes]:
    """Match (method, path) against the route table and call the handler.

    ``path_with_query`` may include ``?n=50`` etc.; we split it once and
    pass the parsed query through as ``_query`` so a handler that needs
    query params can opt in via lambda. ``body`` is the raw POST/PUT
    payload bytes (empty for GET); handlers that need it opt in via
    ``_body``. ``headers`` is the lowercase-keyed request headers dict
    used by the wizard multipart parser; handlers opt in via
    ``_headers``. Handlers that don't care accept ``**_`` and drop them.
    """

    split = urlsplit(path_with_query)
    query = parse_qs(split.query) if split.query else None
    # Iter 025 code-review #8: ``BaseHTTPRequestHandler.path`` keeps
    # percent-encoded bytes, so a CJK workspace like ``/workspace/龙族/``
    # arrives as ``/workspace/%E9%BE%99%E6%97%8F/`` and never matches the
    # ``[^/]+`` capture against the literal name on disk. We decode the
    # path once here so handlers receive the original Unicode name; the
    # ``/`` separator survives because ``unquote`` is applied AFTER
    # ``urlsplit`` has already extracted the path component.
    decoded_path = unquote(split.path)
    matched_any_method = False
    for route_method, pattern, handler in _ROUTES:
        match = pattern.match(decoded_path)
        if match is None:
            continue
        if route_method != method:
            matched_any_method = True
            continue
        kwargs = match.groupdict()
        kwargs["_query"] = query
        kwargs["_body"] = body
        kwargs["_headers"] = headers or {}
        try:
            return handler(**kwargs)
        except FileNotFoundError as exc:
            return _json(404, {"error": str(exc)})
        except ValueError as exc:
            return _json(400, {"error": str(exc)})
        except Exception:
            # Iter 026 code-review #7 hardening: don't leak ``str(exc)``
            # to the client. Log the full exception server-side with a
            # trace_id the user can quote when reporting bugs.
            import sys
            import traceback as _tb
            import uuid as _uuid

            trace_id = _uuid.uuid4().hex
            sys.stderr.write(f"[web] dispatch trace_id={trace_id}\n")
            _tb.print_exc(file=sys.stderr)
            return _json(500, {"error": "internal server error", "trace_id": trace_id})

    # Path matched but method didn't: 405. Otherwise 404.
    if matched_any_method:
        return _json(405, {"error": f"method {method} not allowed for this path"})
    # Unmatched paths under /api/* return JSON 404; HTML pages get a tiny
    # text/html 404 so accidental browser typos render readable text.
    if decoded_path.startswith("/api/"):
        return _json(404, {"error": "no such route"})
    return _html(404, "<h1>404</h1><p>no such route</p>")
