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
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

from .. import paths
from ..book_runner import check_write_readiness
from ..cli_workspace import list_workspaces
from ..cost_estimator import estimate_cost
from ..observability import collect_status
from ..utils import read_json
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
        result = check_write_readiness(chapters=chapters, resume_from=resume_from, replan_every=replan_every)
    return _json(200, result)


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
    ("GET", re.compile(r"^/api/workspaces/?$"), lambda **_: api_workspaces()),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/status/?$"), lambda name, **_: api_workspace_status(name)),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/cost/?$"), lambda name, **_: api_workspace_cost(name)),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/manifest/?$"), lambda name, **_: api_workspace_manifest(name)),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/reviews/?$"), lambda name, **_: api_workspace_reviews(name)),
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
