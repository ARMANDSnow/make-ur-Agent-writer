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

import hmac
import json
import math
import os
import re
import stat
import threading
import time
from dataclasses import dataclass
from fnmatch import fnmatchcase
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

from .. import paths, review_tier, run_params, search as search_mod, start_point, workspace_files
from ..book_runner import check_write_readiness
from ..cli_workspace import list_workspaces
from ..config import get_model_config
from ..cost_estimator import estimate_cost
from ..observability import collect_status
from ..safe_jsonl import tail_jsonl as _safe_tail_jsonl
from ..utils import read_json, read_json_optional
from . import auth, chapter_diff as chapter_diff_mod, diag, errors, jobs, settings as settings_mod, static, templates, wizard
from .safe_log import log_exception as _safe_log_exception
from ._naming import RESERVED_NAMES as _RESERVED_WORKSPACE_NAMES_SHARED  # noqa: F401
from ._naming import (
    WORKSPACE_NAME_RE as _WORKSPACE_NAME_RE_SHARED,  # noqa: F401
)
from ._naming import (
    validate_workspace_name as _shared_validate_workspace_name,
)
from .reviews_aggregator import aggregate_reviews
from .workspace_ctx import use_workspace

# All handlers return ``(status_code, content_type, body_bytes)``.
WebResponse = Tuple[int, str, bytes]
Handler = Callable[..., WebResponse]

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

_WEB_MUTATION_BODY_LIMIT = 64 * 1024
_KB_FILE_MAX_BYTES = 500_000 * 4
_DRAFT_FILE_MAX_BYTES = 1_000_000 * 4 + 1
_DRAFT_JSON_MAX_BYTES = 1_000_000


@dataclass(frozen=True)
class MutationPolicy:
    """Wire-level contract for one state-changing HTTP route."""

    content_type: str
    max_bytes: int
    intent_header: str
    intent_value: str
    require_json_object: bool = True
    require_empty_object: bool = False


_POLICY_WORKSPACE = MutationPolicy(
    "application/json", _WEB_MUTATION_BODY_LIMIT,
    "x-workspace-mutation-intent", "mutate-v1",
)
_POLICY_MODEL_RUN = MutationPolicy(
    "application/json", _WEB_MUTATION_BODY_LIMIT,
    "x-model-action-intent", "run-v1",
)
_POLICY_MODEL_DIAG = MutationPolicy(
    "application/json", _WEB_MUTATION_BODY_LIMIT,
    "x-model-action-intent", "diagnose-v1",
    require_empty_object=True,
)
_POLICY_STYLE_EXTRACT = MutationPolicy(
    "multipart/form-data", 2_000_000,
    "x-model-action-intent", "extract-style-v1",
    require_json_object=False,
)
_POLICY_WIZARD_IMPORT = MutationPolicy(
    "multipart/form-data", 50 * 1024 * 1024,
    "x-onboarding-intent", "import-v1",
    require_json_object=False,
)
_POLICY_WIZARD_PREMISE = MutationPolicy(
    "application/json", _WEB_MUTATION_BODY_LIMIT,
    "x-onboarding-intent", "premise-v1",
)
_POLICY_SETTINGS = MutationPolicy(
    "application/json", _WEB_MUTATION_BODY_LIMIT,
    "x-settings-mutation-intent", "update-v1",
)
_POLICY_WRITE_RECOVERY = MutationPolicy(
    "application/json", _WEB_MUTATION_BODY_LIMIT,
    "x-write-recovery-intent", "archive-and-regenerate-v1",
)

_MUTATION_POLICIES: Dict[Tuple[str, str], MutationPolicy] = {}


def _json(status: int, payload: Dict[str, Any]) -> Tuple[int, str, bytes]:
    # ``collect_status`` and ``estimate_cost`` embed ``pathlib.Path`` values
    # (and a few sets/datetimes show up via reviewer plumbing). The default
    # ``str`` coercion turns them into stable repo-relative-ish strings
    # without needing per-handler post-processing.
    # iter073 (codex D1): ``_finite_json_safe`` strips NaN/±Inf floats →
    # ``None`` so every response is RFC-8259-valid JSON; ``allow_nan`` default
    # would otherwise emit bare ``NaN``/``Infinity`` that breaks JSON.parse.
    body = json.dumps(
        jobs._finite_json_safe(payload), ensure_ascii=False, default=str
    ).encode("utf-8")
    return status, "application/json; charset=utf-8", body


def _html(status: int, html: str) -> Tuple[int, str, bytes]:
    return status, "text/html; charset=utf-8", html.encode("utf-8")


def _log_degraded(where: str, exc: BaseException) -> None:
    """Record only bounded metadata for a degraded Web path."""
    event = f"degraded.{where}" if re.fullmatch(r"[a-z0-9_.-]{1,48}", where) else "degraded.invalid"
    _safe_log_exception(event, exc)


def _validate_workspace_name(name: str) -> bool:
    """Thin wrapper around the shared validator (iter 027 P2 #7)."""
    return _shared_validate_workspace_name(name)


def _workspace_exists(name: str) -> bool:
    return paths.probe_workspace_identity(name) is not None


def _web_mutation_request_error(
    body: bytes,
    headers: Dict[str, str],
    *,
    policy: MutationPolicy,
    check_body: bool = True,
) -> Optional[Tuple[int, str, bytes]]:
    """Reject browser cross-site/simple requests before protected mutations.

    ``dispatch(..., headers=None)`` remains a trusted in-process seam for the
    existing domain tests.  The HTTP server always supplies request headers,
    so every wire request must carry JSON plus one explicit mutation intent.
    Job cancellation additionally requires a valid top-level JSON object;
    dedicated endpoints retain their narrower body validation and error
    precedence.
    """

    if len(body) > policy.max_bytes:
        return _json(413, {"error": "mutation payload too large"})
    content_type = str(headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type != policy.content_type:
        return _json(415, {"error": f"Content-Type must be {policy.content_type}"})
    if check_body and policy.require_json_object:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _json(400, {"error": "mutation body must be valid JSON"})
        if not isinstance(payload, dict):
            return _json(400, {"error": "mutation body must be a JSON object"})
        if policy.require_empty_object and payload:
            return _json(400, {"error": "mutation body must be an empty JSON object"})
    if str(headers.get(policy.intent_header) or "") != policy.intent_value:
        return _json(403, {"error": "explicit mutation intent required"})
    fetch_site = str(headers.get("sec-fetch-site") or "").strip().lower()
    if fetch_site and fetch_site not in {"same-origin", "same-site", "none"}:
        return _json(403, {"error": "cross-site mutation rejected"})
    origin = str(headers.get("origin") or "").strip()
    if origin:
        try:
            parsed = urlsplit(origin)
            hostname = parsed.hostname
            # Accessing ``port`` also validates malformed bracket/port forms.
            parsed.port
        except (TypeError, ValueError):
            return _json(403, {"error": "cross-origin mutation rejected"})
        if (
            parsed.scheme != "http"
            or hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            return _json(403, {"error": "cross-origin mutation rejected"})
        host = str(headers.get("host") or "").strip().lower()
        if host and parsed.netloc.lower() != host:
            return _json(403, {"error": "cross-origin mutation rejected"})
    return None


def mutation_policy_for(method: str, decoded_path: str) -> Optional[MutationPolicy]:
    """Return the exact registered policy for a concrete mutation path."""

    for (route_method, pattern_text), policy in _MUTATION_POLICIES.items():
        if route_method == method and re.fullmatch(pattern_text, decoded_path):
            return policy
    return None


def mutation_route_missing_policy(method: str, decoded_path: str) -> bool:
    """Detect a registered mutation route that bypassed ``_mutation_route``."""

    if method not in {"POST", "PUT"}:
        return False
    if mutation_policy_for(method, decoded_path) is not None:
        return False
    return any(
        route_method == method and pattern.fullmatch(decoded_path) is not None
        for route_method, pattern, _handler in _ROUTES
    )


def mutation_header_error(
    method: str,
    decoded_path: str,
    headers: Dict[str, str],
) -> Optional[WebResponse]:
    """Header-only preflight used by the HTTP server before it reads body."""

    policy = mutation_policy_for(method, decoded_path)
    if policy is None:
        return None
    return _web_mutation_request_error(b"", headers, policy=policy, check_body=False)


def _trusted_in_process_mutation_headers(headers: Dict[str, str]) -> bool:
    """Preserve pure handler tests while never weakening an actual wire call."""

    wire_markers = {
        "host", "content-length", "origin", "sec-fetch-site",
        "x-workspace-mutation-intent", "x-model-action-intent",
        "x-onboarding-intent", "x-settings-mutation-intent",
        "x-write-recovery-intent",
    }
    return not any(key in headers for key in wire_markers)


def _workspace_error(name: str) -> Optional[Tuple[int, str, bytes]]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    if _public_workspace_type(name) != "novel":
        return _json(404, {"error": f"workspace not found: {name}"})
    return None


@contextmanager
def _workspace_write_guard(name: str, source: str):
    """Reserve the Web job slot and the cross-process workspace flock.

    ``jobs.workspace_reserved`` protects against concurrent writes inside this
    Web process; ``workspace_lock`` protects against CLI/driver writers in
    other processes. Both are needed for manual edit endpoints.
    """
    from ..workspace_lock import acquire_write_lock

    identity = paths.probe_workspace_identity(name)
    if identity is None or _public_workspace_type(name) != "novel":
        raise RuntimeError(f"workspace_not_found:{name}")
    with jobs.workspace_reserved(name):
        with use_workspace(name):
            with acquire_write_lock(source=source):
                if not paths.workspace_identity_matches(identity):
                    raise RuntimeError(f"workspace_not_found:{name}")
                yield


def _write_conflict_response(exc: RuntimeError) -> Optional[Tuple[int, str, bytes]]:
    msg = str(exc)
    if msg.startswith("workspace_busy:"):
        return _json(409, {"error": "workspace busy", "running_job_id": msg.split(":", 1)[1]})
    if msg.startswith("workspace_locked:"):
        holder: Dict[str, str] = {}
        source_match = re.search(r"\bsource=([^)\s]+)", msg)
        since_match = re.search(r"\bsince=([^)\s]+)", msg)
        if source_match:
            holder["source"] = source_match.group(1)
        if since_match:
            holder["started_at"] = since_match.group(1)
        return _json(409, {"error": "workspace locked", "workspace_locked": True, "holder": holder})
    if msg.startswith("workspace_not_found:"):
        return _json(404, {"error": "workspace not found"})
    return None


# ---- handlers ---------------------------------------------------------------


def render_landing() -> Tuple[int, str, bytes]:
    return _html(200, templates.render_landing())


def render_index() -> Tuple[int, str, bytes]:
    return _html(200, templates.render_index(list_workspaces()))


def render_trash_page() -> Tuple[int, str, bytes]:
    return _html(200, templates.render_trash(list_workspaces()))


def _redirect(location: str, status: int = 301) -> Tuple[int, str, bytes]:
    """Iter 032: 301 to the new IA. We synthesize the response as a
    text/html body so the unit tests can still introspect the status
    code; the WebHandler sets the Location header separately via the
    ``redirect_to`` field embedded in the body. To keep the dispatcher
    contract (status, content_type, body), we return a tiny HTML body
    with a meta-refresh and a clickable link; ``server.py`` looks at the
    status and the body's ``data-redirect-to`` to forward as Location."""

    href = escape_html(location)
    body = (
        f'<!doctype html><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0;url={href}">'
        f'<title>301 Moved</title>'
        f'<link rel="canonical" href="{href}">'
        f'<p data-redirect-to="{href}">Moved to <a href="{href}">{href}</a></p>'
    )
    return status, "text/html; charset=utf-8", body.encode("utf-8")


def escape_html(s: str) -> str:
    """Local minimal escaping for the Location URL embedded in 301 body."""

    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def render_workspace_redirect(name: str) -> Tuple[int, str, bytes]:
    """``/workspace/<name>`` is the legacy URL. We 301 it to
    the new ``/w/<name>/`` overview so old bookmarks survive but the new
    IA shows everywhere."""

    if not _validate_workspace_name(name):
        return _html(400, "<h1>400</h1><p>invalid workspace name</p>")
    if not _workspace_exists(name):
        return _html(404, f"<h1>404</h1><p>workspace not found: {name}</p>")
    if _public_workspace_type(name) != "novel":
        return _html(404, f"<h1>404</h1><p>workspace not found: {name}</p>")
    return _redirect(f"/w/{name}/")


def _workspace_html_guard(name: str) -> Optional[Tuple[int, str, bytes]]:
    if not _validate_workspace_name(name):
        return _html(400, "<h1>400</h1><p>invalid workspace name</p>")
    if not _workspace_exists(name):
        return _html(404, f"<h1>404</h1><p>workspace not found: {name}</p>")
    if _public_workspace_type(name) != "novel":
        return _html(404, f"<h1>404</h1><p>workspace not found: {name}</p>")
    return None


def _workspace_html_guard_novel_only(name: str) -> Optional[Tuple[int, str, bytes]]:
    """Guard routes that only make sense for novel workspaces."""

    base = _workspace_html_guard(name)
    if base:
        return base
    return None


def render_workspace_overview(name: str) -> Tuple[int, str, bytes]:
    guard = _workspace_html_guard(name)
    if guard:
        return guard
    return _html(200, templates.render_workspace_overview(name, list_workspaces()))




















def render_workspace_continue(name: str) -> Tuple[int, str, bytes]:
    guard = _workspace_html_guard_novel_only(name)
    if guard:
        return guard
    return _html(200, templates.render_workspace_continue(name, list_workspaces()))


def render_workspace_chapters(name: str) -> Tuple[int, str, bytes]:
    guard = _workspace_html_guard_novel_only(name)
    if guard:
        return guard
    return _html(200, templates.render_workspace_chapters(name, list_workspaces()))


def render_workspace_search_page(name: str) -> Tuple[int, str, bytes]:
    # iter075: 全文搜索只消费小说正文语料。
    guard = _workspace_html_guard_novel_only(name)
    if guard:
        return guard
    return _html(200, templates.render_workspace_search(name, list_workspaces()))


def render_workspace_chapter_detail(name: str, chapter: str) -> Tuple[int, str, bytes]:
    guard = _workspace_html_guard_novel_only(name)
    if guard:
        return guard
    try:
        chapter_no = int(chapter)
    except ValueError:
        return _html(400, "<h1>400</h1><p>chapter must be an integer</p>")
    if chapter_no < 1 or chapter_no > 9999:
        return _html(400, "<h1>400</h1><p>chapter out of range</p>")
    return _html(200, templates.render_workspace_chapter_detail(name, chapter_no, list_workspaces()))


def render_workspace_reviews_page(name: str) -> Tuple[int, str, bytes]:
    guard = _workspace_html_guard_novel_only(name)
    if guard:
        return guard
    return _html(200, templates.render_workspace_reviews(name, list_workspaces()))


def render_workspace_insights_page(name: str) -> Tuple[int, str, bytes]:
    guard = _workspace_html_guard_novel_only(name)
    if guard:
        return guard
    return _html(200, templates.render_workspace_insights(name, list_workspaces()))


def render_workspace_plan_page(name: str) -> Tuple[int, str, bytes]:
    guard = _workspace_html_guard_novel_only(name)
    if guard:
        return guard
    return _html(200, templates.render_workspace_plan(name, list_workspaces()))


def render_workspace_workbench_page(name: str) -> Tuple[int, str, bytes]:
    """iter 048b: novel-only four-stage workbench page."""
    guard = _workspace_html_guard_novel_only(name)
    if guard:
        return guard
    return _html(200, templates.render_workspace_workbench(name, list_workspaces()))


def render_workspace_jobs_page(name: str) -> Tuple[int, str, bytes]:
    guard = _workspace_html_guard_novel_only(name)
    if guard:
        return guard
    return _html(200, templates.render_workspace_jobs(name, list_workspaces()))


def render_static_css() -> Tuple[int, str, bytes]:
    return 200, "text/css; charset=utf-8", static.CSS_BODY.encode("utf-8")


def render_static_js() -> Tuple[int, str, bytes]:
    return 200, "application/javascript; charset=utf-8", static.JS_DASHBOARD.encode("utf-8")


def render_static_wizard_js() -> Tuple[int, str, bytes]:
    return 200, "application/javascript; charset=utf-8", static.JS_WIZARD.encode("utf-8")


def api_workspaces() -> Tuple[int, str, bytes]:
    return _json(200, {"workspaces": list_workspaces()})


def api_preflight() -> Tuple[int, str, bytes]:
    """Return a small secret-free runtime mode summary for onboarding UI."""

    from ..cost_estimator import has_known_model_pricing

    model = str(get_model_config("write").get("model") or "mock")
    is_mock = not model or model == "mock" or model.startswith("mock/")
    pricing_known = is_mock or has_known_model_pricing(model)
    return _json(
        200,
        {
            "model": model,
            "is_mock": is_mock,
            "pricing_known": pricing_known,
            "real_ready": (not is_mock) and pricing_known,
        },
    )


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


def api_workspace_delete(name: str, body: bytes) -> Tuple[int, str, bytes]:
    """POST /api/workspace/<name>/delete — soft-delete a workspace.

    Body: ``{"confirm": "<name>"}``. The confirm field must equal the
    workspace name verbatim — defense-in-depth against an accidental
    fetch() without a typed-in confirmation in the UI.
    """
    error = _workspace_error(name)
    if error:
        return error
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict) or payload.get("confirm") != name:
        return _json(400, {"error": "confirm field must equal the workspace name"})
    from . import trash as _trash

    try:
        with _workspace_write_guard(name, "web-manual-delete"):
            ok, msg = _trash.soft_delete_workspace(name)
            if not ok:
                return _json(404 if msg == "workspace_not_found" else 500, {"error": msg})
            _clear_overview_cache()
            return _json(200, {"trashed_to": msg})
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        raise


def api_trash_list() -> Tuple[int, str, bytes]:
    from . import trash as _trash

    return _json(200, {"entries": _trash.list_trash_entries()})


_TRASH_ENTRY_RE = re.compile(r"^[A-Za-z0-9_一-鿿][A-Za-z0-9_一-鿿-]{0,63}__[0-9]{8}_[0-9]{6}(?:_\d+)?$")


def _validate_trash_entry(entry: str) -> bool:
    return bool(_TRASH_ENTRY_RE.fullmatch(entry))


def api_trash_restore(entry: str) -> Tuple[int, str, bytes]:
    if not _validate_trash_entry(entry):
        return _json(400, {"error": "invalid trash entry"})
    from . import trash as _trash

    ok, msg = _trash.restore_trash_entry(entry)
    if not ok:
        public_msg = "entry_not_found" if msg == "unsupported_workspace_type" else msg
        code = {
            "entry_not_found": 404,
            "name_collision": 409,
            "malformed_entry": 400,
            "reserved_name": 400,
        }.get(public_msg, 500)
        return _json(code, {"error": public_msg})
    _clear_overview_cache()
    return _json(200, {"restored_to": msg})


def api_trash_purge(entry: str, body: bytes) -> Tuple[int, str, bytes]:
    if not _validate_trash_entry(entry):
        return _json(400, {"error": "invalid trash entry"})
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict) or payload.get("confirm") != entry:
        return _json(400, {"error": "confirm field must equal the entry name"})
    from . import trash as _trash

    ok, msg = _trash.purge_trash_entry(entry)
    if not ok:
        public_msg = "entry_not_found" if msg == "unsupported_workspace_type" else msg
        code = {
            "entry_not_found": 404,
            "malformed_entry": 400,
            "reserved_name": 400,
        }.get(public_msg, 500)
        return _json(code, {"error": public_msg})
    return _json(200, {"purged": entry})


def _overview_cache_key(names: List[str]) -> Tuple[Any, ...]:
    root = paths.WORKSPACE_DIR
    stamps = []
    for name in names:
        # The selector may have observed a safe workspace immediately before
        # this call.  Re-probe before any stat so a symlink/replacement cannot
        # turn the cache key itself into an external-path metadata reader.
        if paths.probe_workspace_identity(name) is None:
            stamps.append((name, "unsafe"))
            continue
        ws = root / name
        stamps.append(
            (
                name,
                _mtime_ns(ws / "data" / "workspace.json"),
                # Legacy creation-mode inference depends on the exact
                # seed/upload directory-entry shape.  Use lstat signatures so
                # the cache observes additions/replacements without following
                # a hostile or broken symlink outside the workspace.
                _lstat_signature(ws / "小说txt"),
                _lstat_signature(ws / "小说txt" / "seed.txt"),
                _lstat_signature(ws / "小说txt" / "upload.txt"),
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


def _lstat_signature(path: Path) -> Tuple[Any, ...]:
    """Return a no-follow cache signature for one directory entry."""

    try:
        info = path.lstat()
    except FileNotFoundError:
        return ("missing",)
    except OSError as exc:
        return ("error", type(exc).__name__)
    return (
        "entry",
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_dev,
        info.st_ino,
    )


def _open_public_subdir(root_fd: int, parts: Tuple[str, ...]) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    current_fd = os.dup(root_fd)
    try:
        for part in parts:
            next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _public_relative_mtime_ns(root_fd: int, parts: Tuple[str, ...]) -> int:
    if not parts:
        return os.fstat(root_fd).st_mtime_ns
    parent_fd = -1
    try:
        parent_fd = _open_public_subdir(root_fd, parts[:-1])
        info = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        return 0 if stat.S_ISLNK(info.st_mode) else info.st_mtime_ns
    except (OSError, TypeError, ValueError):
        return 0
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)


def _workspace_updated_at(root: Path) -> str:
    """Return a bounded, path-free timestamp for the public library view."""
    candidates = (
        (),
        ("data",),
        ("data", "workspace.json"),
        ("data", "chapter_manifest.json"),
        ("data", "entity_graph.json"),
        ("data", "premise_expansion.json"),
        ("data", "writer_style.json"),
        ("data", "manual_overrides", "start_chapter.json"),
        ("data", "manual_overrides", "global_facts.json"),
        ("data", "manual_overrides", "continuation_anchor.txt"),
        ("data", "manual_overrides", "personas.json"),
        ("outputs",),
        ("outputs", "debate", "outline.md"),
        ("outputs", "debate", "chapter_plan.json"),
        ("outputs", "debate", "decisions.json"),
        ("outputs", "drafts", "rolling_chapter_summary.json"),
        ("outputs", "reviews", "review_summary.md"),
        ("logs", "web_jobs.jsonl"),
    )
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except (OSError, TypeError, ValueError):
        return ""
    try:
        latest_ns = max((_public_relative_mtime_ns(root_fd, parts) for parts in candidates), default=0)
        # Existing-file edits do not advance the parent directory mtime.  Scan
        # only direct, named artifact families through no-follow directory fds.
        for directory, patterns in (
            (("outputs", "drafts"), ("chapter_*.md", "chapter_*.meta.json")),
            (("outputs", "reviews"), ("chapter_*.json", "chapter_*.md")),
        ):
            directory_fd = -1
            try:
                directory_fd = _open_public_subdir(root_fd, directory)
                matched = 0
                inspected = 0
                with os.scandir(directory_fd) as entries:
                    for entry in entries:
                        inspected += 1
                        if inspected > 2048 or matched >= 512:
                            break
                        if not any(fnmatchcase(entry.name, pattern) for pattern in patterns):
                            continue
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISLNK(info.st_mode):
                            continue
                        matched += 1
                        latest_ns = max(latest_ns, info.st_mtime_ns)
            except (OSError, RuntimeError, TypeError, ValueError):
                continue
            finally:
                if directory_fd >= 0:
                    os.close(directory_fd)
    finally:
        os.close(root_fd)
    if latest_ns <= 0:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(latest_ns / 1_000_000_000))


def _public_workspace_type(name: str) -> str:
    """Distinguish valid legacy novels from corrupt or unknown metadata."""
    from .workspace_meta import VALID_TYPES

    identity = paths.probe_workspace_identity(name)
    if identity is None:
        return "unknown"
    root_fd = data_fd = file_fd = -1
    try:
        root_fd = os.open(identity.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            data_fd = _open_public_subdir(root_fd, ("data",))
        except FileNotFoundError:
            return "novel" if paths.workspace_identity_matches(identity) else "unknown"
        try:
            file_fd = os.open(
                "workspace.json",
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
                dir_fd=data_fd,
            )
        except FileNotFoundError:
            return "novel" if paths.workspace_identity_matches(identity) else "unknown"
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024:
            return "unknown"
        raw = os.read(file_fd, 64 * 1024 + 1)
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return "unknown"
    finally:
        for fd in (file_fd, data_fd, root_fd):
            if fd >= 0:
                os.close(fd)
    if (
        not paths.workspace_identity_matches(identity)
        or not isinstance(payload, dict)
        or payload.get("type") not in VALID_TYPES
    ):
        return "unknown"
    return str(payload["type"])


def _novel_workspace_error(name: str) -> Optional[Tuple[int, str, bytes]]:
    """Fail closed before projecting novel-only Phase E data."""
    error = _workspace_error(name)
    if error:
        return error
    if _public_workspace_type(name) != "novel":
        return _json(
            409,
            errors.error_body(
                errors.build_card(
                    "invalid_value",
                    detail="作品类型待确认；没有读取小说内容，请返回作品列表后重新尝试。",
                )
            ),
        )
    return None


def _clear_overview_cache() -> None:
    with _OVERVIEW_CACHE_LOCK:
        _OVERVIEW_CACHE.clear()


def _novel_creation_policy(name: str) -> Tuple[str, bool]:
    """Return the server-authoritative novel creation/start-point policy."""

    from .workspace_meta import read as _meta_read

    mode = str(_meta_read(name).get("creation_mode") or "continuation")
    if mode not in {"greenfield", "continuation"}:
        mode = "continuation"
    return mode, mode == "continuation"


def _unavailable_workspace_overview(name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "unknown",
        "creation_mode": "continuation",
        "requires_start_point": True,
        "workbench_stage": "unknown",
        "creation_stage": "unknown",
        "updated_at": "",
        "exists": False,
        "chapter_count": 0,
        "draft_count": 0,
        "review_total": 0,
        "review_accepted": 0,
        "review_blocked": 0,
        "start_point": {"has_start_point": False, "start_chapter_id": ""},
        "plan": {"exists": False, "chapters": 0, "has_fingerprint": False},
        "readiness": {"status": "unknown", "blockers": [], "warnings": [], "recommended_commands": []},
        "recent_job": None,
    }


def _workspace_overview(name: str) -> Dict[str, Any]:
    root = paths.WORKSPACE_DIR / name
    identity = paths.probe_workspace_identity(name)
    if identity is None:
        return _unavailable_workspace_overview(name)
    if not paths.workspace_identity_matches(identity):
        return _unavailable_workspace_overview(name)
    public_type = _public_workspace_type(name)
    if not paths.workspace_identity_matches(identity):
        return _unavailable_workspace_overview(name)
    updated_at = _workspace_updated_at(root)
    if not paths.workspace_identity_matches(identity):
        return _unavailable_workspace_overview(name)
    overview: Dict[str, Any] = {
        "name": name,
        "type": public_type,
        "updated_at": updated_at,
        "exists": True,
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
    if public_type == "unknown":
        overview["readiness"] = {
            "status": "unknown",
            "blockers": [],
            "warnings": [],
            "recommended_commands": [],
        }
        return overview if paths.workspace_identity_matches(identity) else _unavailable_workspace_overview(name)
    with use_workspace(name):
        try:
            creation_mode, requires_start_point = _novel_creation_policy(name)
            overview["creation_mode"] = creation_mode
            overview["requires_start_point"] = requires_start_point
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
                _log_degraded("overview_plan", exc)
                plan_error = errors.card_for_exception(exc)
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
            workbench = _collect_workbench_status_current(name)
            overview["workbench_stage"] = workbench["stage"]
            overview["creation_stage"] = workbench["stage"]
            overview["workbench"] = workbench
            overview["readiness"] = _safe_readiness(
                chapters=1,
                resume_from=1,
                require_start_point=requires_start_point,
            )
            recent = jobs.recent_jobs(name, limit=1)
            overview["recent_job"] = jobs.public_job_view(recent[0]) if recent else None
        except Exception as exc:
            _log_degraded("overview", exc)
            overview["error"] = errors.card_for_exception(exc)
            overview["readiness"] = {
                "status": "blocked",
                "blockers": ["overview_error"],
                "warnings": [],
                "recommended_commands": ["inspect workspace data and rerun the failing preparation step"],
            }
    return overview if paths.workspace_identity_matches(identity) else _unavailable_workspace_overview(name)


def api_workspace_status(name: str) -> Tuple[int, str, bytes]:
    error = _workspace_error(name)
    if error:
        return error
    with use_workspace(name):
        return _json(200, collect_status())


def api_workspace_cost(name: str) -> Tuple[int, str, bytes]:
    error = _workspace_error(name)
    if error:
        return error
    with use_workspace(name):
        return _json(200, estimate_cost())


def api_workspace_manifest(name: str) -> Tuple[int, str, bytes]:
    error = _workspace_error(name)
    if error:
        return error
    with use_workspace(name):
        manifest = read_json_optional(paths.chapter_manifest_path(), [])
    return _json(200, {"chapters": manifest if isinstance(manifest, list) else []})


def api_workspace_start_point(name: str) -> Tuple[int, str, bytes]:
    error = _novel_workspace_error(name)
    if error:
        return error
    with use_workspace(name):
        return _json(200, {"start_point": start_point.get_start_point_metadata()})


def api_workspace_set_start_point(name: str, body: bytes) -> Tuple[int, str, bytes]:
    error = _novel_workspace_error(name)
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
    # iter060 (#7): without a reservation /start-point wrote through even while a
    # job (e.g. write-book auto_advance) held the workspace — the 409 mutex other
    # write endpoints honor was bypassed, so a start-point flip could race the
    # running pipeline's reads. Hold the same reservation as draft_save.
    try:
        with _workspace_write_guard(name, "web-manual-start-point"):
            start_point.set_start_point(value)
            _clear_overview_cache()
            creation_mode, requires_start_point = _novel_creation_policy(name)
            readiness = _safe_readiness(
                chapters=1,
                resume_from=1,
                require_start_point=requires_start_point,
            )
            readiness["creation_mode"] = creation_mode
            readiness["requires_start_point"] = requires_start_point
            return _json(
                200,
                {
                    "start_point": start_point.get_start_point_metadata(),
                    "readiness": readiness,
                },
            )
    except RuntimeError as exc:
        msg = str(exc)
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        if msg.startswith("workspace_not_found:"):
            return _json(404, {"error": f"workspace not found: {name}"})
        raise


def api_workspace_reviews(name: str) -> Tuple[int, str, bytes]:
    error = _novel_workspace_error(name)
    if error:
        return error
    with use_workspace(name):
        return _json(200, aggregate_reviews(paths.drafts_dir()))


def api_workspace_insights(name: str) -> Tuple[int, str, bytes]:
    error = _novel_workspace_error(name)
    if error:
        return error

    from .insights import collect_insights

    with use_workspace(name):
        return _json(200, collect_insights())


def api_workspace_plan(name: str) -> Tuple[int, str, bytes]:
    error = _novel_workspace_error(name)
    if error:
        return error
    from .plan_view import collect_plan

    with use_workspace(name):
        return _json(200, collect_plan())


def _collect_workbench_status_current(name: str) -> Dict[str, Any]:
    """Collect the shared four-stage gate inside an active workspace context."""

    from ..start_point import get_start_chapter_id

    creation_mode, requires_start_point = _novel_creation_policy(name)
    has_start_point = bool(get_start_chapter_id())
    expansion_m = _mtime_ns(paths.premise_expansion_path())
    start_point_m = _mtime_ns(paths.manual_overrides_dir() / "start_chapter.json")
    kb_m = _mtime_ns(paths.kb_path())
    outline_m = _mtime_ns(paths.outline_path())
    plan_path = paths.chapter_plan_path()
    plan_m = _mtime_ns(plan_path)
    drafts = paths.drafts_dir()
    draft_files = sorted(drafts.glob("chapter_*.md")) if drafts.exists() else []
    draft_count = len(draft_files)
    plan_data = read_json_optional(plan_path, {})
    plan_chapters = plan_data.get("chapters") if isinstance(plan_data, dict) else None

    has_expansion = expansion_m > 0
    preparation_source_m = max(expansion_m, start_point_m if requires_start_point else 0)
    has_kb = kb_m > 0 and kb_m >= preparation_source_m
    # Staleness is transitive: once an authoritative source input changes,
    # every downstream artifact is unusable even when its own mtime remains
    # newer than the now-stale immediate predecessor.
    has_outline = has_kb and outline_m > 0 and outline_m >= kb_m
    has_plan = (
        has_outline
        and bool(plan_chapters)
        and plan_m >= outline_m
        and _chapter_plan_is_self_consistent(plan_data)
        and not start_point.enforce_consistency(
            require_start_point=requires_start_point,
            plan_data=plan_data if isinstance(plan_data, dict) else {},
        )
    )
    authoritative_plan = None
    if has_plan:
        try:
            from ..writer import _load_chapter_plan

            authoritative_plan = _load_chapter_plan()
            if not authoritative_plan:
                has_plan = False
        except (OSError, RuntimeError, TypeError, ValueError):
            # A malformed or schema-invalid plan is not a current plan.  Keep
            # the workbench at the plan stage instead of allowing a newer
            # unrelated draft to mask the damaged authority.
            has_plan = False
    write_state = "not_started"
    retry_chapter: Optional[int] = None
    if has_plan and draft_count > 0:
        from ..chapter_status import chapter_status
        from ..writer import _chapter_plan_item, _run_context

        chapter_numbers = []
        for draft_path in draft_files:
            match = re.fullmatch(r"chapter_(\d+)\.md", draft_path.name)
            if match:
                chapter_numbers.append(int(match.group(1)))
        statuses = []
        for chapter_no in sorted(set(chapter_numbers)):
            try:
                item = _chapter_plan_item(authoritative_plan, chapter_no)
                expected = _run_context(item, chapter_no=chapter_no)
            except (OSError, TypeError, ValueError):
                statuses.append(
                    {
                        "chapter_no": chapter_no,
                        "approved": False,
                        "panel_halt_reason": "",
                        "strict_failures": ["chapter_plan_item_missing_or_invalid"],
                    }
                )
                continue
            statuses.append(
                chapter_status(
                    chapter_no,
                    drafts,
                    validate_context=True,
                    require_start_point=requires_start_point,
                    require_plan=True,
                    require_external_review=True,
                    expected_context=expected,
                )
            )
        retry_required = [
            status
            for status in statuses
            if not status.get("approved") and status.get("panel_halt_reason") == "retry_exhausted"
        ]
        unapproved = [status for status in statuses if not status.get("approved")]
        if retry_required:
            write_state = "retry_required"
            retry_chapter = int(retry_required[0].get("chapter_no") or 1)
        elif not unapproved and statuses:
            write_state = "approved"
        elif unapproved:
            write_state = "needs_review"

    if requires_start_point and not has_start_point:
        stage = "start"
    elif not has_kb:
        stage = "prepare"
    elif not has_outline:
        stage = "outline"
    elif not has_plan:
        stage = "plan"
    elif write_state != "approved":
        stage = "write"
    else:
        stage = "done"

    return {
        "stage": stage,
        "creation_stage": stage,
        "creation_mode": creation_mode,
        "requires_start_point": requires_start_point,
        "has_kb": has_kb,
        "has_outline": has_outline,
        "has_plan": has_plan,
        "draft_count": draft_count,
        "write_state": write_state,
        "retry_chapter": retry_chapter,
        "has_expansion": has_expansion,
        "expansion_stale": has_expansion and kb_m > 0 and kb_m < expansion_m,
        "has_start_point": has_start_point,
    }


def _chapter_plan_is_self_consistent(value: Any) -> bool:
    """Fail closed on missing, reordered or stale stored plan fingerprints."""

    if not isinstance(value, dict):
        return False
    chapters = value.get("chapters")
    target = value.get("target_chapters")
    if not isinstance(chapters, list) or isinstance(target, bool) or not isinstance(target, int):
        return False
    if target <= 0 or len(chapters) != target:
        return False
    try:
        from ..plot_planner import chapter_plan_item_fingerprint, plan_fingerprint

        if value.get("plan_fingerprint") != plan_fingerprint(value):
            return False
        numbers: list[int] = []
        for item in chapters:
            if not isinstance(item, dict):
                return False
            chapter_no = item.get("chapter_no")
            if isinstance(chapter_no, bool) or not isinstance(chapter_no, int):
                return False
            numbers.append(chapter_no)
            if item.get("chapter_plan_item_fingerprint") != chapter_plan_item_fingerprint(item):
                return False
        return numbers == list(range(1, target + 1))
    except (TypeError, ValueError):
        return False


def api_workbench_status(name: str) -> Tuple[int, str, bytes]:
    """GET the server-authoritative novel creation stage and artifact gates."""

    error = _novel_workspace_error(name)
    if error:
        return error
    with use_workspace(name):
        return _json(200, _collect_workbench_status_current(name))


def _write_recovery_snapshot(name: str, chapter: int) -> Dict[str, Any]:
    """Overlay the disk generation with the untruncated job ledger state."""

    from .write_recovery import inspect_recovery_state

    snapshot = inspect_recovery_state(name, chapter)
    if jobs.workspace_busy(name):
        snapshot["state"] = "busy"
        snapshot["state_fingerprint"] = None
        return snapshot
    ledger_state, latest, ledger_claim = jobs.write_recovery_job_claim(name, chapter)
    if ledger_state == "indeterminate":
        snapshot["state"] = "reconciliation_required"
        snapshot["state_fingerprint"] = None
        return snapshot
    snapshot["_ledger_claim"] = ledger_claim
    snapshot["_prior_job_id"] = ""
    if latest is None:
        return snapshot
    status = str(latest.get("status") or "")
    if status in {"pending", "running"}:
        snapshot["state"] = "busy"
        snapshot["state_fingerprint"] = None
    elif status == "lost" or status not in {
        "blocked",
        "failed",
        "succeeded",
        "aborted",
        "budget_exceeded",
    }:
        snapshot["state"] = "reconciliation_required"
        snapshot["state_fingerprint"] = None
    elif not jobs.is_exact_write_recovery_terminal(latest, chapter):
        # Only the explicit retry_exhausted/blocked terminal is a recoverable
        # write failure.  General failure, cancellation, budget exhaustion and
        # an inconsistent "succeeded" row never acquire a force entrypoint.
        snapshot["state"] = "blocked"
        snapshot["state_fingerprint"] = None
    else:
        snapshot["_prior_job_id"] = str(latest.get("job_id") or "")
    return snapshot


def _public_write_recovery(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "state": snapshot.get("state") or "blocked",
        "chapter": snapshot.get("chapter"),
        "draft_available": bool(snapshot.get("draft_available")),
        "review_state": snapshot.get("review_state") or "unknown",
        "state_fingerprint": snapshot.get("state_fingerprint"),
    }


def api_workspace_write_recovery_get(name: str, raw_chapter: Any) -> Tuple[int, str, bytes]:
    error = _novel_workspace_error(name)
    if error:
        return error
    int_error, chapter = _int_value(raw_chapter, "chapter", minimum=1, maximum=9999)
    if int_error:
        return _json(400, {"error": int_error})
    return _json(200, _public_write_recovery(_write_recovery_snapshot(name, chapter)))


def api_workspace_write_recovery_post(name: str, body: bytes) -> Tuple[int, str, bytes]:
    """Start a one-shot, single-chapter force rewrite after exact revalidation."""

    error = _novel_workspace_error(name)
    if error:
        return error
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})
    allowed = {
        "chapter",
        "tier",
        "budget_cny",
        "timeout_minutes",
        "max_model_requests",
        "state_fingerprint",
        "confirm_archive_and_regenerate",
    }
    unknown = set(payload) - allowed
    if unknown:
        return _json(400, {"error": f"unknown recovery fields: {', '.join(sorted(unknown))}"})
    if payload.get("confirm_archive_and_regenerate") is not True:
        return _json(
            400,
            {
                "error": "explicit archive and regenerate confirmation required",
                "code": "write_recovery_confirmation_required",
            },
        )
    int_error, chapter = _int_value(payload.get("chapter"), "chapter", minimum=1, maximum=9999)
    if int_error:
        return _json(400, {"error": int_error})
    supplied_fingerprint = payload.get("state_fingerprint")
    if not isinstance(supplied_fingerprint, str) or not re.fullmatch(
        r"[0-9a-f]{64}", supplied_fingerprint
    ):
        return _json(400, {"error": "state_fingerprint must be a sha256 digest"})
    try:
        tier = review_tier.resolve_tier(str(payload.get("tier") or review_tier.DEFAULT_TIER))
    except ValueError as exc:
        return _json(400, {"error": str(exc)})
    budget_error, budget_cny = _float_param(
        payload, "budget_cny", 0.0, minimum=0.000001, maximum=6.0
    )
    if budget_error:
        return _json(400, {"error": budget_error})
    timeout_error, timeout_minutes = _float_param(
        payload, "timeout_minutes", 0.0, minimum=0.000001, maximum=45.0
    )
    if timeout_error:
        return _json(400, {"error": timeout_error})
    request_error, max_model_requests = _model_request_int_value(
        payload.get("max_model_requests"),
    )
    if request_error:
        return _json(400, {"error": request_error})
    if max_model_requests > 20:
        return _json(400, {"error": "max_model_requests must be between 1 and 20 for write recovery"})

    snapshot = _write_recovery_snapshot(name, chapter)
    state = snapshot.get("state")
    if state == "busy":
        return _json(409, {"error": "workspace busy", "code": "write_recovery_busy"})
    if state == "reconciliation_required":
        return _json(
            409,
            {
                "error": "write job requires reconciliation before recovery",
                "code": "write_recovery_reconciliation_required",
            },
        )
    actual_fingerprint = snapshot.get("state_fingerprint")
    ledger_claim = snapshot.get("_ledger_claim")
    if (
        state != "eligible"
        or not isinstance(actual_fingerprint, str)
        or not isinstance(ledger_claim, str)
        or not hmac.compare_digest(actual_fingerprint, supplied_fingerprint)
    ):
        return _json(
            409,
            {
                "error": "write recovery state changed",
                "code": "write_recovery_state_changed",
            },
        )

    # Deliberately omit confirm_archive_and_regenerate.  Consent is one-shot;
    # it must never enter the persisted job ledger or generic replay params.
    params: Dict[str, Any] = {
        "chapters": 1,
        "resume_from": chapter,
        "force": True,
        "max_retries": 0,
        "tier": tier,
        "budget_cny": budget_cny,
        "timeout_minutes": timeout_minutes,
        "max_model_requests": max_model_requests,
        "auto_advance": True,
        "require_start_point": bool(snapshot.get("requires_start_point")),
        "require_plan": True,
        "require_external_review": True,
        "expected_recovery_fingerprint": actual_fingerprint,
        "expected_recovery_ledger_claim": ledger_claim,
        "expected_recovery_prior_job_id": str(snapshot.get("_prior_job_id") or ""),
        "recovery_chapter": chapter,
    }
    try:
        job = jobs.start_job(name, "write-book", params)
    except RuntimeError as exc:
        msg = str(exc)
        if msg.startswith("workspace_busy:"):
            return _json(409, {"error": "workspace busy", "code": "write_recovery_busy"})
        if msg.startswith("write_recovery_state_changed"):
            return _json(
                409,
                {
                    "error": "write recovery state changed",
                    "code": "write_recovery_state_changed",
                },
            )
        if msg.startswith(("creation_mode_conflict:", "workspace_metadata_invalid")):
            return _json(
                409,
                {
                    "error": "write recovery state changed",
                    "code": "write_recovery_state_changed",
                },
            )
        if msg.startswith("workspace_not_found:"):
            return _json(404, {"error": f"workspace not found: {name}"})
        raise
    return _json(
        202,
        {"job_id": job["job_id"], "status": job["status"], "step": "write-book"},
    )


def api_workspace_outline_save(name: str, body: bytes) -> Tuple[int, str, bytes]:
    """PUT /api/workspace/<name>/outline — overwrite the story outline
    (iter 048b, workbench stage ②). Plain-text atomic write; rejects an
    empty body (which would silently break the stage gate).

    iter 048d (A2): the busy guard now wraps the write inside
    ``workspace_reserved`` instead of a one-shot ``workspace_busy`` check.
    The old single-check left a TOCTOU window between the check and the
    write, during which the debater job could start and write outline.md
    concurrently. ``workspace_reserved`` atomically reserves the slot for
    the duration of the write, so ``start_job`` from any concurrent job is
    refused while we hold it — closing the race in both directions."""
    error = _novel_workspace_error(name)
    if error:
        return error
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})
    outline = payload.get("outline")
    if not isinstance(outline, str) or not outline.strip():
        return _json(400, {"error": "missing or invalid 'outline'"})
    if len(outline) > 200_000:
        return _json(400, {"error": "'outline' too long (max 200000 chars)"})
    # iter 050 (C3c): same control-char gate as every other edit endpoint.
    if _contains_control_chars(outline):
        return _json(400, {"error": "'outline' must not contain control characters"})
    from ..state import write_text_atomic

    try:
        with _workspace_write_guard(name, "web-manual-outline"):
            try:
                from .. import start_point
                from ..utils import sha256_text
                try:
                    old_outline = workspace_files.read_text(name, "outputs/debate/outline.md", max_bytes=800_000)
                except FileNotFoundError:
                    old_outline = ""
                decisions = workspace_files.read_json_optional(
                    name, "outputs/debate/decisions.json", None, max_bytes=2_000_000
                )
                if decisions is None:
                    if paths.debate_decisions_path().exists():
                        return _json(409, {"error": "outline_metadata_invalid"})
                    decisions = {}
                if not isinstance(decisions, dict):
                    return _json(409, {"error": "outline_metadata_invalid"})
                failures = start_point.outline_consistency_failures(decisions, outline_text=old_outline)
                hard = [code for code in failures if code != start_point.OUTLINE_METADATA_MISSING]
                if hard or (start_point.OUTLINE_METADATA_MISSING in failures and start_point.get_start_chapter_id()):
                    return _json(409, {"error": "outline_stale", "codes": hard or failures})
                outline = outline.replace("\r\n", "\n").replace("\r", "\n")
                previous_edit = decisions.get("manual_edit")
                revision = previous_edit.get("revision", 0) if isinstance(previous_edit, dict) else 0
                if type(revision) is not int or revision < 0:
                    return _json(409, {"error": "outline_metadata_invalid"})
                decisions["manual_edit"] = {
                    "source": "web", "revision": revision + 1,
                    "base_sha256": sha256_text(old_outline),
                    "content_sha256": sha256_text(outline),
                    "edited_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                decisions["outline_sha256"] = sha256_text(outline)
                workspace_files.write_text_atomic(name, "outputs/debate/outline.md", outline, max_bytes=800_000)
                workspace_files.write_json_atomic(name, "outputs/debate/decisions.json", decisions, max_bytes=2_000_000)
            except (OSError, ValueError) as exc:
                return _json(500, errors.error_body(errors.card_for_exception(exc)))
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        raise
    _clear_overview_cache()
    return _json(200, {"saved": True, "chars": len(outline)})


# Iter 050 (C3c): reject C0/C1 control characters (except \t \n \r) in any
# user-supplied text that gets persisted — they corrupt prompts, diffs and
# terminal output downstream. Shared by every edit endpoint.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _contains_control_chars(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_CONTROL_CHARS_RE.search(value))
    if isinstance(value, (list, tuple)):
        return any(_contains_control_chars(v) for v in value)
    if isinstance(value, dict):
        return any(_contains_control_chars(v) for v in value.values())
    return False


def api_workspace_chapter_plan_save(name: str, chapter: str, body: bytes) -> Tuple[int, str, bytes]:
    """PUT /api/workspace/<name>/chapter-plan/<chapter> — structured edit of
    one chapter's plan item (iter 050, workbench stage ③).

    Body: ``{"fields": {<EDITABLE_PLAN_ITEM_FIELDS subset>}}``. Validation
    and fingerprint recomputation live in
    ``plot_planner.apply_chapter_plan_item_edit`` (the single fingerprint
    truth source — this endpoint never touches fingerprints itself).

    The response reports ``written_chapters_invalidated``: iter057 (P0-A)
    narrowed ``plan_fingerprint`` to global context only, so editing a chapter
    strict-expires **that chapter itself** (if already written) via its
    ``chapter_plan_item_fingerprint`` — NOT every written chapter. The list
    therefore contains the edited chapter only (empty if it isn't written yet);
    the frontend warns before saving when it is non-empty. This replaces the old
    全局 strict-expire (which was the root cause of replan-append blocking every
    written chapter); per-chapter consistency is now owned by item fingerprints.
    """
    error = _novel_workspace_error(name)
    if error:
        return error
    try:
        chapter_no = int(chapter)
    except (TypeError, ValueError):
        return _json(400, {"error": "invalid chapter number"})
    if not 1 <= chapter_no <= 9999:
        return _json(400, {"error": "chapter number out of range"})
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})
    fields = payload.get("fields")
    if not isinstance(fields, dict) or not fields:
        return _json(400, {"error": "missing or invalid 'fields'"})
    if _contains_control_chars(fields):
        return _json(400, {"error": "fields must not contain control characters"})
    # iter 050d (M-4): plan items are injected into writer prompts —
    # Pydantic validates ranges but not string lengths, so cap here.
    if len(body) > 100_000:
        return _json(400, {"error": "payload too large (max 100000 bytes)"})

    from ..plot_planner import apply_chapter_plan_item_edit

    try:
        with _workspace_write_guard(name, "web-manual-chapter-plan"):
            drafts = paths.drafts_dir()
            # iter057 (P0-A): plan_fingerprint 收窄为只哈希全局上下文后,编辑某章
            # 只让**该章**(若已写)strict-expire——via chapter_plan_item_fingerprint
            # (被编辑章 item 指纹变)——不再波及其他已写章(它们 draft+plan item 都没变)。
            # 故失效列表只含被编辑章本身,而非所有已写章(旧全局语义正是 replan 卡死之源)。
            edited_md = drafts / f"chapter_{chapter_no:02d}.md"
            written = [chapter_no] if edited_md.exists() else []
            try:
                data = apply_chapter_plan_item_edit(chapter_no, fields)
            except FileNotFoundError as exc:
                return _json(404, errors.exception_body(exc))
            except KeyError as exc:
                return _json(404, {"error": str(exc.args[0]) if exc.args else "chapter not found"})
            except ValueError as exc:
                return _json(400, errors.exception_body(exc))
            except OSError as exc:
                _log_degraded("write_chapter_plan", exc)
                return _json(500, errors.error_body(errors.card_for_exception(exc)))
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        raise
    _clear_overview_cache()
    return _json(
        200,
        {
            "saved": True,
            "plan_fingerprint": data.get("plan_fingerprint", ""),
            "written_chapters_invalidated": written,
        },
    )


def api_workspace_draft_save(name: str, chapter: str, body: bytes) -> Tuple[int, str, bytes]:
    """PUT /api/workspace/<name>/draft/<chapter> — in-place edit of a written
    chapter (iter 050, B1).

    The md write and the meta update happen inside ONE ``workspace_reserved``
    hold: ``reviewer.review_target`` trusts ``meta.draft_sha256`` (it never
    re-hashes the file), so persisting the draft without syncing meta would
    leave the chapter permanently ``draft_hash_mismatch``. After this call
    the strict status is ``external_review_stale`` (review.json still hashes
    the OLD text) — which is exactly the「需要重新评审」signal the frontend
    surfaces via「保存并重新评审」(the review-chapter job)."""
    error = _novel_workspace_error(name)
    if error:
        return error
    try:
        chapter_no = int(chapter)
    except (TypeError, ValueError):
        return _json(400, {"error": "invalid chapter number"})
    if not 1 <= chapter_no <= 9999:
        return _json(400, {"error": "chapter number out of range"})
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return _json(400, {"error": "missing or invalid 'content'"})
    if len(content) > 1_000_000:
        return _json(400, {"error": "'content' too long (max 1000000 chars)"})
    if _contains_control_chars(content):
        return _json(400, {"error": "'content' must not contain control characters"})

    from ..utils import sha256_text

    # Normalize to the writer's on-disk shape (text + single trailing \n)
    # so the meta sha follows writer._draft_file_sha256's convention.
    draft = content.rstrip("\n")
    try:
        with _workspace_write_guard(name, "web-manual-draft"):
            md_relative = f"outputs/drafts/chapter_{chapter_no:02d}.md"
            meta_relative = f"outputs/drafts/chapter_{chapter_no:02d}.meta.json"
            try:
                current_bytes = workspace_files.read_bytes(name, md_relative, max_bytes=_DRAFT_FILE_MAX_BYTES)
            except FileNotFoundError:
                return _json(404, {"error": f"chapter_{chapter_no:02d}.md not found"})
            except workspace_files.WorkspaceFileError as exc:
                _safe_log_exception("draft.read_target", exc)
                return _json(409, {"error": "workspace draft layout is unsafe"})
            expected = payload.get("expected_sha256")
            if not isinstance(expected, str) or re.fullmatch(r"[a-f0-9]{64}", expected) is None:
                return _json(428, {"error": "请先加载当前正文再保存", "code": "draft_version_required"})
            import hashlib
            if hashlib.sha256(current_bytes).hexdigest() != expected:
                return _json(409, {"error": "正文已在别处更新，请保留修改并重新加载核对", "code": "draft_version_conflict"})
            try:
                meta = workspace_files.read_json_optional(
                    name, meta_relative, {}, max_bytes=_DRAFT_JSON_MAX_BYTES
                )
            except workspace_files.WorkspaceFileError as exc:
                _safe_log_exception("draft.read_meta", exc)
                return _json(409, {"error": "workspace draft layout is unsafe"})
            if not isinstance(meta, dict):
                meta = {}
            try:
                from ..story_memory import invalidate_from
                invalidate_from(paths.drafts_dir(), chapter_no)
                meta["story_memory_invalidated"] = True
                workspace_files.write_text_atomic(
                    name, md_relative, draft + "\n", max_bytes=_DRAFT_FILE_MAX_BYTES
                )
            except (OSError, ValueError) as exc:
                trace_id = _safe_log_exception("draft.write", exc)
                return _json(
                    500,
                    errors.error_body(errors.build_card("server_error", trace_id=trace_id)),
                )
            meta["chapter_no"] = chapter_no
            meta["draft_sha256"] = sha256_text(draft + "\n")
            meta["edited"] = True
            meta["edited_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            # An edited draft must not coast on a pre-edit Approve.
            meta["needs_human_review"] = True
            # Iter087: every style artifact is tied to the exact draft hash.
            # Manual edits invalidate both the current score and the automatic
            # rewrite audit; keeping them would present stale evidence as if it
            # described the newly saved prose.
            for key in (
                "style_fingerprint",
                "style_drift",
                "baseline_hash",
                "style_rewrite_count",
                "style_rewrite_applied",
                "style_rewrite_status",
                "style_drift_before",
                "style_drift_after",
                "style_drift_improvement",
                "style_drift_unresolved",
            ):
                meta.pop(key, None)
            try:
                workspace_files.write_json_atomic(
                    name, meta_relative, meta, max_bytes=_DRAFT_JSON_MAX_BYTES
                )
            except (OSError, ValueError) as exc:
                # iter 050d (M-1): the md IS saved at this point; saying
                # "保存失败" would be a lie. The chapter sits at
                # draft_hash_mismatch (fail-safe) until a re-save lands
                # the meta sync.
                # iter063 A2 / iter157: return the friendly card and emit only
                # bounded exception metadata plus a trace ID.
                _safe_log_exception("draft.meta_sync", exc)
                return _json(500, errors.error_body(errors.build_card("draft_meta_unsynced")))
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        raise
    _clear_overview_cache()
    return _json(
        200,
        {
            "saved": True,
            "chars": len(draft) + 1,
            "draft_sha256": meta["draft_sha256"],
            "review_stale": True,
        },
    )


def api_workspace_kb_get(name: str) -> Tuple[int, str, bytes]:
    """GET /api/workspace/<name>/kb — raw global knowledge base markdown
    (iter 050, B3 editor source). Full-KB view is intentional here: this is
    the EDIT surface for the book's own settings, not a writing prompt — the
    start-safe spoiler filtering (047b) applies to LLM-facing views."""
    error = _novel_workspace_error(name)
    if error:
        return error
    try:
        content = workspace_files.read_text(
            name,
            "data/knowledge_base/global_knowledge.md",
            max_bytes=_KB_FILE_MAX_BYTES,
        )
    except FileNotFoundError:
        return _json(404, {"error": "knowledge base not found; run prepare first"})
    except workspace_files.WorkspaceFileError as exc:
        _safe_log_exception("kb.read", exc)
        return _json(409, {"error": "workspace knowledge-base layout is unsafe"})
    return _json(200, {"content": content})


def api_workspace_kb_save(name: str, body: bytes) -> Tuple[int, str, bytes]:
    """PUT /api/workspace/<name>/kb — overwrite the global knowledge base
    (iter 050, B3). Mirrors the outline PUT. Saving the KB bumps its mtime,
    which makes the workbench mtime chain mark outline/plan stale — kept on
    purpose (048b red-team fix ③: a changed KB makes downstream artifacts
    suspect); the frontend explains this instead of hacking mtimes."""
    error = _novel_workspace_error(name)
    if error:
        return error
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return _json(400, {"error": "missing or invalid 'content'"})
    if len(content) > 500_000:
        return _json(400, {"error": "'content' too long (max 500000 chars)"})
    if _contains_control_chars(content):
        return _json(400, {"error": "'content' must not contain control characters"})
    try:
        with _workspace_write_guard(name, "web-manual-kb"):
            try:
                workspace_files.write_text_atomic(
                    name,
                    "data/knowledge_base/global_knowledge.md",
                    content,
                    max_bytes=_KB_FILE_MAX_BYTES,
                )
            except workspace_files.WorkspaceFileError as exc:
                trace_id = _safe_log_exception("kb.write", exc)
                return _json(
                    500,
                    errors.error_body(errors.build_card("server_error", trace_id=trace_id)),
                )
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        raise
    _clear_overview_cache()
    return _json(200, {"saved": True, "chars": len(content)})


def api_workspace_premise_expansion_get(name: str) -> Tuple[int, str, bytes]:
    """GET /api/workspace/<name>/premise-expansion — the structured premise
    expansion artifact for the stage ① editor (iter 051a)."""
    error = _novel_workspace_error(name)
    if error:
        return error
    from ..premise_expansion import load_expansion

    with use_workspace(name):
        record = load_expansion()
    if record is None:
        return _json(404, {"error": "premise expansion not found; run expand-premise first"})
    return _json(
        200,
        {
            "fields": record.get("fields") or {},
            "premise": record.get("premise") or "",
            "generated_by": record.get("generated_by") or "",
            "edited": bool(record.get("edited")),
            "edited_at": record.get("edited_at") or "",
            # iter 053: 扩写时重试后仍空的字段（record 层标记），stage ①
            # 编辑器据此显示"建议补全"。
            "_incomplete_fields": record.get("_incomplete_fields") or [],
        },
    )


def api_workspace_premise_expansion_save(name: str, body: bytes) -> Tuple[int, str, bytes]:
    """PUT /api/workspace/<name>/premise-expansion — edit the expansion
    fields (iter 051a, 050 edit-loop pattern: Pydantic validation → atomic
    write → mtime chain marks downstream KB/outline/plan stale).

    Body: ``{"fields": {<PremiseExpansion fields>}}``. Creating from scratch
    is allowed — a user may hand-write the expansion without the agent.
    Per-field length caps live in the ``PremiseExpansion`` schema; the
    payload cap here is the M-4 style outer gate."""
    error = _novel_workspace_error(name)
    if error:
        return error
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})
    fields = payload.get("fields")
    if not isinstance(fields, dict) or not fields:
        return _json(400, {"error": "missing or invalid 'fields'"})
    unknown = set(fields) - {
        "genre_tone", "protagonist", "world_notes",
        "central_conflict", "ending_anchor", "arc_hints",
    }
    if unknown:
        return _json(400, {"error": f"unknown fields: {', '.join(sorted(unknown))}"})
    if _contains_control_chars(fields):
        return _json(400, {"error": "fields must not contain control characters"})
    if len(body) > 100_000:
        return _json(400, {"error": "payload too large (max 100000 bytes)"})

    from ..premise_expansion import save_expansion_fields

    try:
        with _workspace_write_guard(name, "web-manual-premise-expansion"):
            try:
                record = save_expansion_fields(fields)
            except ValueError as exc:
                return _json(400, errors.exception_body(exc))
            except OSError as exc:
                _log_degraded("write_premise_expansion", exc)
                return _json(500, errors.error_body(errors.card_for_exception(exc)))
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        raise
    _clear_overview_cache()
    return _json(200, {"saved": True, "edited_at": record.get("edited_at", "")})


# iter 056: 作家风格卡——预置库 + 激活 + 编辑 + 上传样本提取（仅 premise 自创书）
_WRITER_STYLE_FIELDS = {
    "name", "category", "rhythm", "sentence", "diction",
    "imagery", "dialogue", "subtext", "narration", "signatures", "taboo",
}


def api_workspace_style_presets(name: str) -> Tuple[int, str, bytes]:
    """GET /api/workspace/<name>/style-presets — 全局只读预置风格卡库。"""
    error = _novel_workspace_error(name)
    if error:
        return error
    from ..writer_style import load_presets

    return _json(200, {"presets": load_presets()})


def api_workspace_writer_style_get(name: str) -> Tuple[int, str, bytes]:
    """GET /api/workspace/<name>/writer-style — 当前激活的风格卡（iter056）。"""
    error = _novel_workspace_error(name)
    if error:
        return error
    from ..writer_style import load_card

    with use_workspace(name):
        record = load_card()
    if record is None:
        return _json(404, {"error": "no writer style card; activate a preset or extract from a sample"})
    return _json(
        200,
        {
            "fields": record.get("fields") or {},
            "source": record.get("source") or "",
            "preset_id": record.get("preset_id") or "",
            "generated_by": record.get("generated_by") or "",
            "edited": bool(record.get("edited")),
            "edited_at": record.get("edited_at") or "",
            "_incomplete_fields": record.get("_incomplete_fields") or [],
            "_scrubbed_fields": record.get("_scrubbed_fields") or [],
        },
    )


def api_workspace_writer_style_save(name: str, body: bytes) -> Tuple[int, str, bytes]:
    """PUT /api/workspace/<name>/writer-style — 编辑/手写风格卡（050 edit-loop）。
    不接 mtime 失效链：风格卡只喂 writer 逐章 prompt、不喂 KB/大纲生成链，
    改卡只下一章生效、不回炉已写章节。"""
    error = _novel_workspace_error(name)
    if error:
        return error
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})
    fields = payload.get("fields")
    if not isinstance(fields, dict) or not fields:
        return _json(400, {"error": "missing or invalid 'fields'"})
    unknown = set(fields) - _WRITER_STYLE_FIELDS
    if unknown:
        return _json(400, {"error": f"unknown fields: {', '.join(sorted(unknown))}"})
    if _contains_control_chars(fields):
        return _json(400, {"error": "fields must not contain control characters"})
    if len(body) > 100_000:
        return _json(400, {"error": "payload too large (max 100000 bytes)"})

    from ..writer_style import save_card_fields

    try:
        with _workspace_write_guard(name, "web-manual-writer-style"):
            try:
                record = save_card_fields(fields)
            except ValueError as exc:
                return _json(400, errors.exception_body(exc))
            except OSError as exc:
                _log_degraded("write_writer_style", exc)
                return _json(500, errors.error_body(errors.card_for_exception(exc)))
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        raise
    return _json(200, {"saved": True, "edited_at": record.get("edited_at", "")})


def api_workspace_writer_style_activate(name: str, body: bytes) -> Tuple[int, str, bytes]:
    """POST /api/workspace/<name>/writer-style/activate — 选中预置卡（快照入
    workspace，非引用 id）。body: ``{"preset_id": "..."}``。"""
    error = _novel_workspace_error(name)
    if error:
        return error
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    preset_id = payload.get("preset_id") if isinstance(payload, dict) else None
    if not isinstance(preset_id, str) or not preset_id.strip():
        return _json(400, {"error": "missing or invalid 'preset_id'"})

    from ..writer_style import activate_preset

    try:
        with _workspace_write_guard(name, "web-manual-writer-style-activate"):
            try:
                record = activate_preset(preset_id.strip())
            except ValueError as exc:
                return _json(400, errors.exception_body(exc))
            except OSError as exc:
                _log_degraded("activate_preset", exc)
                return _json(500, errors.error_body(errors.card_for_exception(exc)))
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        raise
    return _json(200, {"saved": True, "preset_id": preset_id.strip(), "fields": record.get("fields")})


def api_workspace_writer_style_extract(name: str, body: bytes, headers: Dict[str, str]) -> Tuple[int, str, bytes]:
    """POST /api/workspace/<name>/writer-style/extract — multipart 上传样本
    （文件 ``sample`` 或文本 ``text``）→ 临时落盘 → 起 extract-style job（前端
    pollJob）。样本不持久化：提取后即删（P0-A 版权护栏）。"""
    error = _novel_workspace_error(name)
    if error:
        return error
    content_type = headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        return _json(415, {"error": "Content-Type must be multipart/form-data"})
    if len(body) > 2_000_000:
        return _json(413, {"error": "sample upload exceeds 2000000 bytes"})

    from . import wizard

    try:
        fields = wizard._parse_multipart(body, content_type)
    except ValueError as exc:
        return _json(400, {"error": f"multipart parse failed: {exc}"})

    sample = ""
    file_field = fields.get("sample")
    if isinstance(file_field, dict):
        mime = (file_field.get("content_type") or "").lower()
        fname = (file_field.get("filename") or "").lower()
        is_text = (not mime) or mime.startswith("text/") or fname.endswith((".txt", ".md"))
        if not is_text:
            return _json(415, {"error": "sample must be a text file (.txt/.md)"})
        try:
            sample = (file_field.get("content") or b"").decode("utf-8")
        except UnicodeDecodeError:
            return _json(400, {"error": "sample must be valid UTF-8 text"})
    text_field = fields.get("text")
    if isinstance(text_field, str) and text_field.strip():
        sample = text_field

    sample = (sample or "").strip()
    if len(sample) < 200:
        return _json(400, {"error": "sample too short (min 200 chars)"})
    if _contains_control_chars(sample):
        return _json(400, {"error": "sample must not contain control characters"})
    sample = sample[:60000]

    import uuid

    from ..state import write_text_atomic
    from ..workspace_lock import acquire_write_lock

    try:
        with use_workspace(name):
            with acquire_write_lock(source="web-manual-writer-style-extract-stage"):
                # iter060 (#11): stage the sample to a per-request UNIQUE path
                # (was a fixed .writer_style_sample.tmp). Two concurrent
                # extracts used to write the same file, so the loser overwrote
                # the winner's sample before the winner's job read it.
                # write_text_atomic avoids a torn read; the job is handed its
                # own path via params.
                # iter061 (P0): pass only the random token, not a
                # caller-influenced path — the handler rebuilds the path inside
                # data_dir from it, so /run can't be abused to read+delete an
                # arbitrary file.
                sample_token = uuid.uuid4().hex
                sample_path = paths.writer_style_sample_path().with_name(
                    f".writer_style_sample.{sample_token}.tmp"
                )
                sample_path.parent.mkdir(parents=True, exist_ok=True)
                write_text_atomic(sample_path, sample)
        try:
            job = jobs.start_job(
                name,
                "extract-style",
                {
                    "force": True,
                    "sample_token": sample_token,
                    "max_model_requests": 2,
                    "budget_cny": 2.0,
                    "timeout_minutes": 15.0,
                },
            )
        except BaseException:
            sample_path.unlink(missing_ok=True)  # don't leak the staged sample
            raise
    except RuntimeError as exc:
        msg = str(exc)
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        if msg.startswith("workspace_not_found:"):
            return _json(404, {"error": "workspace not found"})
        raise
    except OSError as exc:
        return _json(500, errors.error_body(errors.card_for_exception(exc)))
    return _json(202, {"job_id": job.get("job_id"), "name": name})


def api_workspace_entity_graph(name: str) -> Tuple[int, str, bytes]:
    """GET /api/workspace/<name>/entity-graph — raw graph for the stage ①
    editor (iter 050, B3)."""
    error = _novel_workspace_error(name)
    if error:
        return error
    with use_workspace(name):
        graph = read_json_optional(paths.entity_graph_path(), {})
    if not isinstance(graph, dict):
        graph = {}
    return _json(200, graph)


# iter 050 (B3): per-field whitelists for entity_graph edits. ``id`` / ``type``
# / ``src_id`` / ``dst_id`` / ``relation_type`` and timeline ``chapter_id`` /
# ``order`` / ``active`` stay immutable — entities.py's spoiler filter and the
# writer's auto_advance chain key off them (entities.py:41-141).
_ENTITY_EDITABLE_FIELDS = frozenset({"name", "aliases", "tags", "key_facts", "description"})
_ENTITY_LIST_FIELDS = frozenset({"aliases", "tags", "key_facts"})


def api_workspace_entity_save(name: str, entity_id: str, body: bytes) -> Tuple[int, str, bytes]:
    """PUT /api/workspace/<name>/entity/<entity_id> — edit one entity's
    descriptive fields (iter 050, B3)."""
    error = _novel_workspace_error(name)
    if error:
        return error
    # iter 050d (L-2): no unquote here — dispatch already decodes the whole
    # path before route matching; a second decode would corrupt ids that
    # contain literal % sequences.
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})
    fields = payload.get("fields")
    if not isinstance(fields, dict) or not fields:
        return _json(400, {"error": "missing or invalid 'fields'"})
    unknown = set(fields) - _ENTITY_EDITABLE_FIELDS
    if unknown:
        return _json(400, {"error": "non-editable fields: " + ", ".join(sorted(map(str, unknown)))})
    # iter 050d (M-4): hard size caps — entity_graph gets rendered whole into
    # writer/planner prompts, so an unbounded field is an unbounded token bill
    # (every other edit endpoint already caps its payload).
    _ENTITY_FIELD_MAX = {"name": 200, "description": 5000}
    for key, value in fields.items():
        if key in _ENTITY_LIST_FIELDS:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                return _json(400, {"error": f"'{key}' must be a list of strings"})
            if len(value) > 50:
                return _json(400, {"error": f"'{key}' too long (max 50 items)"})
            if any(len(v) > 500 for v in value):
                return _json(400, {"error": f"'{key}' items too long (max 500 chars each)"})
        else:
            if not isinstance(value, str):
                return _json(400, {"error": f"'{key}' must be a string"})
            limit = _ENTITY_FIELD_MAX.get(key, 5000)
            if len(value) > limit:
                return _json(400, {"error": f"'{key}' too long (max {limit} chars)"})
    if fields.get("name") is not None and not str(fields.get("name")).strip():
        return _json(400, {"error": "'name' must not be empty"})
    if _contains_control_chars(fields):
        return _json(400, {"error": "fields must not contain control characters"})
    from ..utils import write_json

    try:
        with _workspace_write_guard(name, "web-manual-entity"):
            graph_path = paths.entity_graph_path()
            graph = read_json_optional(graph_path, {})
            if not isinstance(graph, dict) or not graph.get("entities"):
                return _json(404, {"error": "entity_graph not found; run prepare first"})
            target = next(
                (
                    ent
                    for ent in graph.get("entities") or []
                    if isinstance(ent, dict) and str(ent.get("id")) == entity_id
                ),
                None,
            )
            if target is None:
                return _json(404, {"error": f"entity not found: {entity_id}"})
            target.update(fields)
            try:
                write_json(graph_path, graph)
            except OSError as exc:
                return _json(500, errors.error_body(errors.card_for_exception(exc)))
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        raise
    _clear_overview_cache()
    return _json(200, {"saved": True, "entity_id": entity_id})


def api_workspace_relationship_save(name: str, index: str, body: bytes) -> Tuple[int, str, bytes]:
    """PUT /api/workspace/<name>/relationship/<index> — edit the ACTIVE
    timeline entry's ``state`` text of one relationship (iter 050, B3).

    Relationships carry no stable id (shape: src_id/dst_id/relation_type/
    timeline), so the contract is the index into the CURRENT relationships
    array as served by GET /entity-graph; the ``workspace_reserved`` hold
    prevents the array shifting under the write (e.g. write-book's
    auto_advance). ``state`` is the one field the writer actually consumes
    (entities.py:render_active_state); chapter_id/order/active stay immutable
    because the spoiler filter keys off them."""
    error = _novel_workspace_error(name)
    if error:
        return error
    try:
        rel_index = int(index)
    except (TypeError, ValueError):
        return _json(400, {"error": "invalid relationship index"})
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})
    state = payload.get("state")
    if not isinstance(state, str) or not state.strip():
        return _json(400, {"error": "missing or invalid 'state'"})
    if len(state) > 2000:
        return _json(400, {"error": "'state' too long (max 2000 chars)"})
    if _contains_control_chars(state):
        return _json(400, {"error": "'state' must not contain control characters"})
    # iter 050d (M-2): the index was taken when the panel rendered; if the
    # graph was regenerated since (re-run prepare) the same index may now be
    # a DIFFERENT relationship. Require the client to echo src_id/dst_id and
    # reject on mismatch instead of silently editing the wrong object.
    echo_src = payload.get("src_id")
    echo_dst = payload.get("dst_id")
    if not isinstance(echo_src, str) or not isinstance(echo_dst, str) or not echo_src or not echo_dst:
        return _json(400, {"error": "missing 'src_id'/'dst_id' echo for index validation"})
    from ..utils import write_json

    try:
        with _workspace_write_guard(name, "web-manual-relationship"):
            graph_path = paths.entity_graph_path()
            graph = read_json_optional(graph_path, {})
            rels = graph.get("relationships") if isinstance(graph, dict) else None
            if not isinstance(rels, list) or not 0 <= rel_index < len(rels):
                return _json(404, {"error": f"relationship not found: index {rel_index}"})
            rel = rels[rel_index]
            if not isinstance(rel, dict) or str(rel.get("src_id")) != echo_src or str(rel.get("dst_id")) != echo_dst:
                return _json(
                    409,
                    {
                        "error": "relationship at this index has changed (graph was regenerated); reload the panel",
                        "stale_index": True,
                    },
                )
            timeline = rel.get("timeline") if isinstance(rel, dict) else None
            active = next(
                (
                    item
                    for item in (timeline or [])
                    if isinstance(item, dict) and item.get("active")
                ),
                None,
            )
            if active is None:
                return _json(404, {"error": "relationship has no active timeline entry"})
            active["state"] = state
            try:
                write_json(graph_path, graph)
            except OSError as exc:
                return _json(500, errors.error_body(errors.card_for_exception(exc)))
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        raise
    _clear_overview_cache()
    return _json(200, {"saved": True, "index": rel_index})






























































def _parse_json_object_body(body: bytes) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, str, bytes]]]:
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return None, _json(400, {"error": "body must be a JSON object"})
    return payload, None


















































































def api_workspace_readiness(
    name: str,
    chapters: int = 1,
    resume_from: int = 1,
    replan_every: int = 0,
) -> Tuple[int, str, bytes]:
    error = _novel_workspace_error(name)
    if error:
        return error
    # iter060 (Codex A): the GET query parser (_parse_int) is a bare int() with
    # no ceiling, so chapters=999999999 would reach check_write_readiness ->
    # list(range(...)) and try to materialise ~1e9 ints (resource exhaustion).
    # Clamp here to the same caps write-book enforces (iter059 #6a:
    # chapters/replan_every<=2000, resume_from<=10000) so readiness reflects what
    # a real run would accept; mirrors the handler-level clamp in
    # api_workspace_logs_tail.
    raw_chapters, raw_resume, raw_replan = int(chapters), int(resume_from), int(replan_every)
    chapters = max(1, min(raw_chapters, 2000))
    resume_from = max(1, min(raw_resume, 10000))
    replan_every = max(0, min(raw_replan, 2000))
    # iter063 ⑤: don't clamp silently. write-book rejects an over-limit value with
    # 400; readiness is a read-only probe so it clamps and keeps going — but it
    # now reports what was requested vs applied so the caller (and UI) can tell
    # the readiness reflects a capped window, not their literal input.
    clamped: Dict[str, Any] = {}
    for key, raw, applied in (
        ("chapters", raw_chapters, chapters),
        ("resume_from", raw_resume, resume_from),
        ("replan_every", raw_replan, replan_every),
    ):
        if raw != applied:
            clamped[key] = {"requested": raw, "applied": applied}
    creation_mode, requires_start_point = _novel_creation_policy(name)
    with use_workspace(name):
        result = _safe_readiness(
            chapters=chapters,
            resume_from=resume_from,
            replan_every=replan_every,
            require_start_point=requires_start_point,
        )
    if isinstance(result, dict):
        result["creation_mode"] = creation_mode
        result["requires_start_point"] = requires_start_point
    if clamped and isinstance(result, dict):
        result["clamped"] = clamped
    return _json(200, result)


def _safe_readiness(**kwargs: Any) -> Dict[str, Any]:
    try:
        return check_write_readiness(**kwargs)
    except Exception as exc:
        _log_degraded("readiness", exc)
        chapters = int(kwargs.get("chapters", 1) or 1)
        resume_from = int(kwargs.get("resume_from", 1) or 1)
        return {
            "status": "blocked",
            "chapters": chapters,
            "resume_from": resume_from,
            "plan_window": chapters,
            "blockers": ["readiness_error"],
            "warnings": [],
            "recommended_commands": ["inspect chapter_plan.json and rerun plan-chapters --force --require-start-point"],
            "error": errors.card_for_exception(exc),
        }


def api_workspace_logs_tail(name: str, n: int = 50) -> Tuple[int, str, bytes]:
    error = _workspace_error(name)
    if error:
        return error
    n = max(1, min(n, 1000))
    with use_workspace(name):
        # Both the durable writer and this read-side view are metadata-only;
        # the extra allowlist remains defense in depth for legacy rows.
        rows = _safe_tail_jsonl(paths.workspace_root(), "logs/llm_calls.jsonl", n)
        lines = [_public_llm_call_view(row) for row in rows]
    return _json(200, {"lines": lines})


def _public_llm_call_view(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return the small, non-sensitive LLM summary used by the desktop UI."""

    if not isinstance(row, dict):
        return {}
    out: Dict[str, Any] = {}
    for field in ("task", "operation", "status"):
        value = row.get(field)
        limit = 80 if field != "status" else 40
        if (
            isinstance(value, str)
            and 0 < len(value) <= limit
            and re.fullmatch(r"[A-Za-z0-9._-]+", value)
        ):
            out[field] = value
    model = row.get("model")
    # Normal model ids are provider/name tokens.  Reject URL/userinfo/query
    # shapes and free text rather than trying to redact every possible secret
    # syntax after a settings mistake or a damaged legacy log line.
    if (
        isinstance(model, str)
        and 0 < len(model) <= 160
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", model)
        and not re.search(
            r"(?:^|/)sk-[A-Za-z0-9_-]{16,}(?:$|/)", model, flags=re.IGNORECASE
        )
    ):
        out["model"] = model
    for field in (
        "duration_ms", "prompt_tokens", "response_tokens",
        "cache_read_tokens", "cache_write_tokens", "attempt",
    ):
        value = row.get(field)
        if (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
            and 0 <= float(value) <= 1_000_000_000
        ):
            out[field] = value
    return out


def api_workspace_recent_jobs(name: str, limit: int = 5) -> Tuple[int, str, bytes]:
    error = _workspace_error(name)
    if error:
        return error
    return _json(
        200,
        {"jobs": [jobs.public_job_summary_view(j) for j in jobs.recent_jobs(name, limit=limit)]},
    )


def api_workspace_active_jobs(name: str) -> Tuple[int, str, bytes]:
    # iter071 (codex F2): authoritative "is a job in flight?" for the leave-guard.
    # Unlike /jobs/recent this never truncates or sorts by timestamp, so a freshly
    # enqueued pending job (started_at=None) is always reported.
    error = _workspace_error(name)
    if error:
        return error
    # iter072 (#4): project to the public allowlist — the raw record carries
    # the user's POST ``params`` plus internal diagnostics the leave-guard
    # never needs; only id/status/step/progress/timestamps go off-box.
    return _json(200, {"jobs": [jobs.public_job_view(j) for j in jobs.active_jobs(name)]})


def api_workspace_drafts(name: str) -> Tuple[int, str, bytes]:
    error = _novel_workspace_error(name)
    if error:
        return error
    try:
        names = workspace_files.list_regular_names(
            name,
            "outputs/drafts",
            accept=lambda value: bool(re.fullmatch(r"chapter_\d+(?:\.partial)?\.md", value)),
        )
        drafts = [_draft_summary(name, filename) for filename in names]
    except workspace_files.WorkspaceFileError as exc:
        _safe_log_exception("draft.list", exc)
        return _json(409, {"error": "workspace draft layout is unsafe"})
    return _json(200, {"drafts": [item for item in drafts if item]})


def api_workspace_draft(name: str, chapter: str, variant: str = "") -> Tuple[int, str, bytes]:
    error = _novel_workspace_error(name)
    if error:
        return error
    try:
        chapter_no = int(chapter)
    except ValueError:
        return _json(400, {"error": "chapter must be an integer"})
    if chapter_no < 1 or chapter_no > 9999:
        return _json(400, {"error": "chapter out of range"})
    variant = (variant or "").strip().lower()
    if variant not in {"", "final", "partial"}:
        return _json(400, {"error": "unknown draft variant"})
    filename = f"chapter_{chapter_no:02d}.partial.md" if variant == "partial" else f"chapter_{chapter_no:02d}.md"
    relative = f"outputs/drafts/{filename}"
    try:
        try:
            text = workspace_files.read_text(name, relative, max_bytes=_DRAFT_FILE_MAX_BYTES)
        except FileNotFoundError:
            return _json(404, {"error": f"draft not found: {filename}"})
        if variant == "partial":
            meta = workspace_files.read_json_optional(
                name,
                f"outputs/drafts/chapter_{chapter_no:02d}.failure.json",
                {},
                max_bytes=_DRAFT_JSON_MAX_BYTES,
            )
            review = {}
        else:
            meta = workspace_files.read_json_optional(
                name,
                f"outputs/drafts/chapter_{chapter_no:02d}.meta.json",
                {},
                max_bytes=_DRAFT_JSON_MAX_BYTES,
            )
            review = workspace_files.read_json_optional(
                name,
                f"outputs/reviews/chapter_{chapter_no:02d}.review.json",
                {},
                max_bytes=_DRAFT_JSON_MAX_BYTES,
            )
        # iter076 / iter157：path 类字段只做显式 workspace 相对投影；外部绝对
        # 路径失败关闭为 null，磁盘上的 meta.json 原样不动。
        meta_out = dict(meta) if isinstance(meta, dict) else {}
        for key in ("snapshot_path", "failure_path"):
            if meta_out.get(key):
                meta_out[key] = _workspace_relative_projection(name, meta_out[key])
        payload = {
            "chapter": chapter_no,
            "variant": variant or "final",
            "path": relative,
            "content": text,
            "draft_sha256": __import__("hashlib").sha256(text.encode("utf-8")).hexdigest(),
            "meta": meta_out,
            "review": review if isinstance(review, dict) else {},
        }
    except workspace_files.WorkspaceFileError as exc:
        _safe_log_exception("draft.get", exc)
        return _json(409, {"error": "workspace draft layout is unsafe"})
    return _json(200, payload)


def api_workspace_chapter_versions(name: str, chapter: str) -> Tuple[int, str, bytes]:
    """GET /api/workspace/<name>/chapter/<n>/versions — list a chapter's
    on-disk versions (current draft + retry snapshots) for the diff picker
    (iter 074)."""
    error = _novel_workspace_error(name)
    if error:
        return error
    try:
        chapter_no = int(chapter)
    except (TypeError, ValueError):
        return _json(400, {"error": "chapter must be an integer"})
    if not 1 <= chapter_no <= 9999:
        return _json(400, {"error": "chapter out of range"})
    with use_workspace(name):
        versions = chapter_diff_mod.list_chapter_versions(paths.drafts_dir(), chapter_no)
    return _json(200, {"chapter": chapter_no, "versions": versions})


def api_workspace_chapter_diff(
    name: str, chapter: str, v1: str = "", v2: str = ""
) -> Tuple[int, str, bytes]:
    """GET /api/workspace/<name>/chapter/<n>/diff?v1=&v2= — unified diff
    between two enumerated versions (iter 074).

    Both ids must appear in ``list_chapter_versions`` (rejects unknown /
    path-traversal ids); ``resolve_version_text`` re-gates by regex + a
    stays-inside-snapshots check as defense-in-depth."""
    error = _novel_workspace_error(name)
    if error:
        return error
    try:
        chapter_no = int(chapter)
    except (TypeError, ValueError):
        return _json(400, {"error": "chapter must be an integer"})
    if not 1 <= chapter_no <= 9999:
        return _json(400, {"error": "chapter out of range"})
    v1 = (v1 or "").strip()
    v2 = (v2 or chapter_diff_mod.CURRENT_VERSION_ID).strip()
    with use_workspace(name):
        drafts_dir = paths.drafts_dir()
        versions = chapter_diff_mod.list_chapter_versions(drafts_dir, chapter_no)
        valid_ids = {entry["id"] for entry in versions}
        if v1 not in valid_ids or v2 not in valid_ids:
            return _json(400, {"error": "unknown version id"})
        old_text = chapter_diff_mod.resolve_version_text(drafts_dir, chapter_no, v1)
        new_text = chapter_diff_mod.resolve_version_text(drafts_dir, chapter_no, v2)
    if old_text is None or new_text is None:
        return _json(404, {"error": "version content not found"})
    labels = {entry["id"]: entry["label"] for entry in versions}
    result = chapter_diff_mod.compute_diff(
        old_text,
        new_text,
        old_label=labels.get(v1, v1),
        new_label=labels.get(v2, v2),
    )
    return _json(200, {"chapter": chapter_no, "v1": v1, "v2": v2, **result})


def api_workspace_search(
    name: str, q: str = "", sources: Optional[str] = None
) -> Tuple[int, str, bytes]:
    """GET /api/workspace/<name>/search?q=&sources= — 跨章全文检索（iter075）。

    ``sources``：逗号分隔的来源子集（original/draft/kb），缺省时搜全部三语料。前端
    据用户勾选传入，让后端**按范围检索**——``truncated`` 因而反映真实范围，且不做无谓
    全扫（评审 iter075 #3）。空 q → 200 + 空结果（空搜索是正常态，前端显示引导态，不是
    400）。search 模块内部已 fail-open；这里再包最外层兜底把任何未预期异常收成 200 空
    结果，确保连贯性核查工具永不把页面打挂（铁律④）。"""
    error = _novel_workspace_error(name)
    if error:
        return error
    q = (q or "").strip()
    empty = {
        "query": "",
        "total_matches": 0,
        "hit_count": 0,
        "hits": [],
        "truncated": False,
        "truncated_reasons": [],
    }
    if not q:
        return _json(200, empty)
    # 参数缺省 → None（搜全部）；显式传入 → 逗号拆分（可能为空列表 = 一个都不搜）。
    src_list = None if sources is None else [s for s in sources.split(",") if s]
    try:
        with use_workspace(name):
            result = search_mod.search_workspace(q, sources=src_list)
    except Exception as exc:
        _log_degraded("api_workspace_search", exc)
        return _json(200, {**empty, "query": q})
    return _json(200, result.to_dict())


def _ws_relative(p: Any) -> Any:
    """iter076（codex 审查低风险项）：API 投影不暴露本机绝对路径。

    workspace 内的路径转成相对 workspace 根的形式（display-only 字段，前端只
    展示不回传）；不在 workspace 内 / 已是相对 / 解析失败则原样返回。"""
    if not p:
        return p
    try:
        return str(Path(str(p)).resolve().relative_to(paths.workspace_root().resolve()))
    except Exception:
        return p


def _workspace_relative_projection(workspace: str, value: Any) -> Any:
    """Project a stored path without ever returning an outside absolute path."""
    if not value:
        return value
    try:
        candidate = Path(str(value))
        if candidate.is_absolute():
            root = Path(os.path.abspath(paths.workspace_root(workspace)))
            candidate = Path(os.path.abspath(candidate)).relative_to(root)
        if any(part in {"", ".", ".."} for part in candidate.parts):
            return None
        return candidate.as_posix()
    except (OSError, TypeError, ValueError):
        return None


def _draft_summary(workspace: str, filename: str) -> Optional[Dict[str, Any]]:
    match = re.match(r"chapter_(\d+)(\.partial)?\.md$", filename)
    if not match:
        return None
    chapter_no = int(match.group(1))
    is_partial = bool(match.group(2))
    text = workspace_files.read_text(
        workspace, f"outputs/drafts/{filename}", max_bytes=_DRAFT_FILE_MAX_BYTES
    )
    if is_partial:
        failure = workspace_files.read_json_optional(
            workspace,
            f"outputs/drafts/chapter_{chapter_no:02d}.failure.json",
            {},
            max_bytes=_DRAFT_JSON_MAX_BYTES,
        )
        return {
            "chapter": chapter_no,
            "variant": "partial",
            "path": f"outputs/drafts/{filename}",
            "chars": len(text),
            "verdict": "failure",
            "needs_human_review": True,
            "rewrite_count": None,
            "review_verdict": None,
            "failure_stage": failure.get("stage") if isinstance(failure, dict) else None,
            "failure_error": failure.get("last_error") if isinstance(failure, dict) else None,
        }
    meta = workspace_files.read_json_optional(
        workspace,
        f"outputs/drafts/chapter_{chapter_no:02d}.meta.json",
        {},
        max_bytes=_DRAFT_JSON_MAX_BYTES,
    )
    review = workspace_files.read_json_optional(
        workspace,
        f"outputs/reviews/chapter_{chapter_no:02d}.review.json",
        {},
        max_bytes=_DRAFT_JSON_MAX_BYTES,
    )
    return {
        "chapter": chapter_no,
        "variant": "final",
        "path": f"outputs/drafts/{filename}",
        "chars": len(text),
        "verdict": meta.get("verdict") if isinstance(meta, dict) else None,
        "needs_human_review": bool(meta.get("needs_human_review")) if isinstance(meta, dict) else False,
        "rewrite_count": meta.get("rewrite_count") if isinstance(meta, dict) else None,
        "review_verdict": review.get("verdict") if isinstance(review, dict) else None,
        "snapshot_path": _workspace_relative_projection(workspace, meta.get("snapshot_path")) if isinstance(meta, dict) else None,
    }


def _tail_jsonl(path: Path, n: int) -> List[Dict[str, Any]]:
    """Compatibility wrapper around the shared fail-closed reader."""

    value = Path(path)
    return _safe_tail_jsonl(value.parent, value.name, n)


# ---- POST handlers (iter 026) ----------------------------------------------


def api_wizard_start(body: bytes, headers: Dict[str, str]) -> Tuple[int, str, bytes]:
    """POST /api/wizard/start — multipart upload + auto-pipeline kick-off."""

    content_type = headers.get("content-type", "")
    return wizard.start_upload(body, content_type)




def api_wizard_premise_start(body: bytes, headers: Dict[str, str]) -> Tuple[int, str, bytes]:
    """POST /api/wizard/premise-start — create a novel workspace from a
    one-sentence premise (iter 048a). Starts no job; the four-stage
    workbench drives prepare-greenfield / debate / plan / write."""

    content_type = headers.get("content-type", "")
    return wizard.start_premise_workspace(body, content_type)


def api_diag_models() -> Tuple[int, str, bytes]:
    """Protected POST model-key connectivity matrix.

    User-triggered diagnostics: probes each distinct configured model once
    (max_tokens=1), mock-short-circuits offline, never echoes the api_key.
    """

    return _json(200, diag.collect_model_diagnostics())


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

    error = _workspace_error(name)
    if error:
        return error
    from .workspace_meta import read as _meta_read
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
    # Validate the request shape before evaluating workspace-dependent policy.
    # This preserves the public 400 contract for malformed/non-finite values
    # and avoids masking a bad request behind a creation-mode conflict.
    require_start_point_supplied = "require_start_point" in params
    params_error, params = _validated_run_params(step, params)
    if params_error:
        return _json(400, {"error": params_error})
    workspace_meta = _meta_read(name)
    if workspace_meta.get("_metadata_status") == "invalid":
        if paths.probe_workspace_identity(name) is None:
            return _json(404, {"error": f"workspace not found: {name}"})
        return _json(409, {
            "error": "作品类型或创作模式元数据损坏，请先修复 workspace.json；当前没有启动任务。",
            "code": "workspace_metadata_invalid",
        })
    if workspace_meta.get("type") != "novel":
        return _json(404, {"error": f"workspace not found: {name}"})
    creation_mode, requires_start_point = _novel_creation_policy(name)
    with use_workspace(name):
        from ..start_point import get_start_chapter_id

        has_start_point = bool(get_start_chapter_id())
    conflict = None
    if step in {"prepare-greenfield", "auto-pipeline-greenfield", "expand-premise"} and requires_start_point:
        conflict = "导入续写作品不能运行原创开书步骤；请先选择续写起点。"
    elif step in {"prepare-import", "rebuild-for-start"} and not requires_start_point:
        conflict = "原创作品没有原作续写起点，不能运行导入续写步骤。"
    elif requires_start_point and not has_start_point and step in {
        "extract", "compress", "bootstrap", "apply-bootstrap", "debate",
        "plan-chapters", "write-book", "review-chapter", "draft-once-dev",
        "rebuild-for-start",
    }:
        conflict = "导入续写作品需要先选择续写起点；当前没有启动任务。"
    elif step in {"plan-chapters", "write-book"}:
        if require_start_point_supplied:
            supplied = params.get("require_start_point")
            if supplied != requires_start_point:
                conflict = "请求的续写起点策略与当前作品模式不一致。"
        params = dict(params)
        params["require_start_point"] = requires_start_point
    if conflict:
        return _json(
            409,
            {
                "error": "creation mode conflict",
                "code": "creation_mode_conflict",
                "detail": conflict,
                "creation_mode": creation_mode,
                "requires_start_point": requires_start_point,
            },
        )
    try:
        job = jobs.start_job(name, step, params)
    except ValueError as exc:
        # iter063 A2: attach a card so /run failures show a human title.
        return _json(400, errors.exception_body(exc))
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
        if msg.startswith("workspace_not_found:"):
            return _json(404, {"error": f"workspace not found: {name}"})
        if msg == "workspace_metadata_invalid":
            return _json(
                409,
                {
                    "error": "作品类型或创作模式元数据在任务启动前发生变化；当前没有启动任务。",
                    "code": "workspace_metadata_invalid",
                },
            )
        if msg.startswith("creation_mode_conflict:"):
            return _json(
                409,
                {
                    "error": "creation mode conflict",
                    "code": "creation_mode_conflict",
                    "detail": "请求步骤与当前作品模式不一致，未启动任务。",
                },
            )
        raise
    return _json(202, {"job_id": job["job_id"], "status": job["status"], "step": step})


def _validated_run_params(step: str, params: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    # iter060 (Codex B): timeout_minutes applies to every step (jobs._timeout_deadline
    # reads it off the job params), but only write-book/plan-chapters ran any
    # param validation — so a non-finite/negative timeout slipped through on
    # every other step and silently disabled the timeout guard (a NaN deadline
    # makes every `monotonic > deadline` False). Reject it at the boundary for
    # all steps, mirroring _float_param's finite guard (iter058 #6b).
    raw_timeout = params.get("timeout_minutes")
    if raw_timeout is not None and raw_timeout != "":
        # iter063 ③: cap at 1440min (24h) to match the wizard's two entry points.
        # An unbounded finite timeout (e.g. 1e9) is a fake deadline that never
        # fires — the maximum closes the sibling hole to Codex-B's NaN guard.
        error, _ = _float_param(params, "timeout_minutes", 0.0, minimum=0.0, maximum=1440.0)
        if error:
            return error, {}
    if step == "write-book":
        error, out = _validate_write_book_params(params)
    elif step == "plan-chapters":
        error, out = _validate_plan_chapters_params(params)
    elif step in ("prepare-greenfield", "rebuild-for-start"):
        error, out = _validate_prepare_params(step, params)
    elif step == "prepare-import":
        out: Dict[str, Any] = {}
        error, timeout = _float_param(
            params,
            "timeout_minutes",
            0.0,
            minimum=0.0,
            maximum=1440.0,
        )
        if error:
            return error, {}
        if timeout > 0:
            out["timeout_minutes"] = timeout
        error = None
    else:
        error, out = None, dict(params)
    if error:
        return error, {}
    return _with_model_request_limit(step, params, out)


def _with_model_request_limit(
    step: str,
    incoming: Dict[str, Any],
    validated: Dict[str, Any],
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Resolve a finite provider-attempt cap for every Web novel model step.

    Browser values are never trusted: an explicit value must be an integer no
    greater than the step-specific iter166 allowance (and the worker enforces
    it again).  When omitted, the same value is applied as the default, so an
    old browser cannot silently create an uncapped real-model job.
    """

    default = jobs.default_model_request_limit(step)
    if default is None:
        return None, validated
    raw = incoming.get("max_model_requests", default)
    error, value = _model_request_int_value(raw)
    if error:
        return error, {}
    if value > default:
        return (
            f"max_model_requests must be between 1 and {default} for {step}",
            {},
        )
    out = dict(validated)
    out["max_model_requests"] = value
    execution_defaults = jobs.default_novel_execution_limits(step)
    if execution_defaults is None:
        return None, out
    default_budget, default_timeout = execution_defaults
    execution_maxima = jobs.max_novel_execution_limits(step) or execution_defaults
    max_budget, max_timeout = execution_maxima
    budget_input = dict(incoming)
    if "budget_cny" not in budget_input:
        budget_input["budget_cny"] = default_budget
    budget_error, budget = _float_param(
        budget_input,
        "budget_cny",
        default_budget,
        minimum=0.000001,
        maximum=max_budget,
    )
    if budget_error:
        return budget_error, {}
    timeout_input = dict(incoming)
    if "timeout_minutes" not in timeout_input:
        timeout_input["timeout_minutes"] = default_timeout
    timeout_error, timeout = _float_param(
        timeout_input,
        "timeout_minutes",
        default_timeout,
        minimum=0.000001,
        maximum=max_timeout,
    )
    if timeout_error:
        return timeout_error, {}
    out["budget_cny"] = budget
    out["timeout_minutes"] = timeout
    return None, out


def _model_request_int_value(value: Any) -> Tuple[Optional[str], int]:
    """Strict integer parser for a paid-attempt cap (no float truncation)."""

    if isinstance(value, bool) or not (
        isinstance(value, int)
        or (isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()))
    ):
        return "max_model_requests must be an integer", 0
    return _int_value(
        value,
        "max_model_requests",
        minimum=1,
        maximum=jobs.MAX_MODEL_REQUESTS_PER_JOB,
    )


def _validate_prepare_params(step: str, params: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    """iter068 (Cluster D): prepare-greenfield / rebuild-for-start 参数守门。

    **关键 fail-open 修复**：``budget_cny`` 只在调用方**显式传入**时才校验并落字段。
    若像 ``_validate_write_book_params`` 那样无条件 ``out["budget_cny"]=budget``，
    缺省会被规范化成 0 —— jobs 层 ``_float_param(params,"budget_cny",
    _default_budget_cny())`` 见 key 在且为 0，便当成「显式无限额」，绕过
    NOVEL_DEFAULT_BUDGET_CNY 默认 cap。故：缺省→不写字段→jobs 层兜默认 cap；
    显式 0→uncapped（CLI 语义）。其余参数从空 ``out`` 重建（mirror 既有
    validator），未显式传的交给 handler 默认值。"""
    out: Dict[str, Any] = {}
    # 两个 step 可能携带的布尔开关；未传则不写，handler 读其自身默认。
    for key in ("force", "skip_extract", "reextract", "no_chunk", "apply"):
        if key in params:
            error, value = _bool_param(params, key, False)
            if error:
                return error, {}
            out[key] = value
    # extract_limit（prepare-greenfield）：显式 None = 不设上限；否则 >=1。
    if "extract_limit" in params:
        raw_limit = params.get("extract_limit")
        if raw_limit is None:
            out["extract_limit"] = None
        else:
            error, limit = _int_param(params, "extract_limit", 5, minimum=1, maximum=100000)
            if error:
                return error, {}
            out["extract_limit"] = limit
    # window（仅 rebuild-for-start）：起点窗口章数。
    if step == "rebuild-for-start" and "window" in params:
        error, window = _int_param(params, "window", 10, minimum=1, maximum=200)
        if error:
            return error, {}
        out["window"] = window
    # budget_cny：validate-only-if-present（上述 fail-open 守门）。
    raw_budget = params.get("budget_cny")
    if raw_budget is not None and str(raw_budget).strip() != "":
        error, budget = _float_param(params, "budget_cny", 0.0, minimum=0.0)
        if error:
            return error, {}
        out["budget_cny"] = budget
    # carry 已校验的 timeout_minutes（mirror write-book/plan-chapters，否则
    # jobs._timeout_deadline 不武装）。0 = 无 cap，不落字段。
    error, timeout = _float_param(params, "timeout_minutes", 0.0, minimum=0.0, maximum=1440.0)
    if error:
        return error, {}
    if timeout > 0:
        out["timeout_minutes"] = timeout
    return None, out


def _validate_write_book_params(params: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    out: Dict[str, Any] = {}
    if params.get("force") is True:
        return "force write-book must use the dedicated write-recovery endpoint", {}
    # iter059 #6a: upper bounds so a pathological chapters=999999999 can't be
    # accepted (resource exhaustion). Caps are well above any real run; the
    # default path is unchanged. plan-chapters already capped target at 200.
    # iter064 #1: the cap numbers now live in src/run_params.INT_CAPS so the
    # CLI/driver enforce the exact same bounds (single source of truth).
    for key in run_params.WRITE_BOOK_INT_FIELDS:
        default, minimum, maximum = run_params.INT_CAPS[key]
        error, value = _int_param(params, key, default, minimum=minimum, maximum=maximum)
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
    raw_tier = params.get("tier")
    if raw_tier is not None and str(raw_tier).strip():
        try:
            out["tier"] = review_tier.resolve_tier(str(raw_tier))
        except ValueError as exc:
            return str(exc), {}
    else:
        out["tier"] = review_tier.DEFAULT_TIER
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
    # iter063 A5 (= 后端审查②): carry the validated timeout_minutes into the
    # rebuilt params. _validated_run_params validated it but this dict-rebuild
    # used to drop it, so jobs._timeout_deadline never armed — the longest step
    # silently ran without a timeout. Only carry a positive value (0 = no cap).
    error, timeout = _float_param(params, "timeout_minutes", 0.0, minimum=0.0, maximum=1440.0)
    if error:
        return error, {}
    if timeout > 0:
        out["timeout_minutes"] = timeout
    return None, out


def _validate_plan_chapters_params(params: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    raw_target = params.get("target_chapters", params.get("chapters", 5))
    error, target = _int_value(raw_target, "target_chapters", minimum=1, maximum=200)
    if error:
        return error, {}
    # iter 048b: honor require_start_point from params (default True keeps the
    # continue page's behavior) so the greenfield workbench can pass False —
    # otherwise plan-chapters hard-blocks on start_point_missing for a
    # premise-seeded book that has no prior start point.
    error, require_start = _bool_param(params, "require_start_point", True)
    if error:
        return error, {}
    out: Dict[str, Any] = {
        "target_chapters": target,
        "force": True,
        "append_count": 0,
        "from_chapter": 0,
        "require_start_point": require_start,
    }
    # iter063 A5 (= 后端审查②): carry the validated timeout_minutes (see
    # _validate_write_book_params). plan-chapters is the other long step whose
    # rebuilt params used to drop it.
    error, timeout = _float_param(params, "timeout_minutes", 0.0, minimum=0.0, maximum=1440.0)
    if error:
        return error, {}
    if timeout > 0:
        out["timeout_minutes"] = timeout
    return None, out


def _int_param(params: Dict[str, Any], key: str, default: int, *, minimum: int = 0, maximum: Optional[int] = None) -> Tuple[Optional[str], int]:
    return _int_value(params.get(key, default), key, minimum=minimum, maximum=maximum)


def _int_value(value: Any, key: str, *, minimum: int = 0, maximum: Optional[int] = None) -> Tuple[Optional[str], int]:
    # iter064 #1: thin wrapper over the core-level validator (src/run_params.py)
    # so the WebUI and the CLI/driver share one source of truth for the
    # finite/range guard (iter059 #6a/NEW-A). Behavior unchanged — the
    # finite-guard regression tests call this directly.
    return run_params.validate_int(value, key, minimum=minimum, maximum=maximum)


def _float_param(params: Dict[str, Any], key: str, default: float, *, minimum: float = 0.0, maximum: Optional[float] = None) -> Tuple[Optional[str], float]:
    # iter064 #1: thin wrapper over src/run_params.validate_float. allow_blank
    # stays False to preserve the original params-dict semantics (iter058 #6b:
    # reject NaN/±Infinity that otherwise disable the cost/timeout gates).
    return run_params.validate_float(
        params.get(key, default), key, default, minimum=minimum, maximum=maximum, allow_blank=False
    )


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

    error = _workspace_error(name)
    if error:
        return error
    job = jobs.get_job_for_workspace(name, job_id)
    if job is None:
        return _json(404, {"error": "job not found"})
    # iter073 (codex D3): explicit detail allowlist instead of raw passthrough.
    return _json(200, jobs.public_job_detail_view(job))


def api_job_cancel(name: str, job_id: str) -> Tuple[int, str, bytes]:
    """POST /api/workspace/<name>/job/<job_id>/cancel.

    Cancellation is cooperative: the worker sees the flag at its next
    progress/deadline checkpoint and then marks the job ``aborted``.
    """

    error = _workspace_error(name)
    if error:
        return error
    job = jobs.get_job_for_workspace(name, job_id)
    if job is None:
        return _json(404, {"error": "job not found"})
    status = str(job.get("status") or "")
    if status not in {"pending", "running"}:
        return _json(409, {"error": "job is not cancellable", "status": status})
    snapshot = jobs.request_cancel(job_id, workspace=name)
    if snapshot is None:
        latest = jobs.get_job_for_workspace(name, job_id)
        if latest is None:
            return _json(404, {"error": "job not found"})
        return _json(
            409,
            {
                "error": "job is not cancellable",
                "status": latest.get("status"),
            },
        )
    return _json(
        202,
        {
            "job_id": job_id,
            "status": snapshot.get("status"),
            "cancel_requested": True,
            "requested_at": time.time(),
        },
    )


# ---- dispatcher -------------------------------------------------------------


def _mutation_route(
    method: str,
    pattern_text: str,
    handler: Handler,
    policy: MutationPolicy,
) -> Tuple[str, "re.Pattern[str]", Handler]:
    """Register a mutation and its wire policy as one inseparable operation."""

    if method not in {"POST", "PUT"}:
        raise ValueError("mutation routes must use POST or PUT")
    key = (method, pattern_text)
    if key in _MUTATION_POLICIES:
        raise ValueError(f"duplicate mutation policy: {method} {pattern_text}")
    _MUTATION_POLICIES[key] = policy
    return method, re.compile(pattern_text), handler


# (method, compiled regex, handler). Named groups in the regex become
# kwargs passed to the handler.
_ROUTES: List[Tuple[str, "re.Pattern[str]", Handler]] = [
    ("GET", re.compile(r"^/$"), lambda **_: render_landing()),
    ("GET", re.compile(r"^/library/?$"), lambda **_: render_index()),
    ("GET", re.compile(r"^/trash/?$"), lambda **_: render_trash_page()),
    ("GET", re.compile(r"^/static/app\.css$"), lambda **_: render_static_css()),
    ("GET", re.compile(r"^/static/app\.js$"), lambda **_: render_static_js()),
    ("GET", re.compile(r"^/static/wizard\.js$"), lambda **_: render_static_wizard_js()),
    # Legacy /workspace/<name> → 301 to /w/<name>/
    ("GET", re.compile(r"^/workspace/(?P<name>[^/]+)/?$"), lambda name, **_: render_workspace_redirect(name)),
    # Workspace-scoped IA
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/?$"), lambda name, **_: render_workspace_overview(name)),
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/continue/?$"), lambda name, **_: render_workspace_continue(name)),
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/chapters/?$"), lambda name, **_: render_workspace_chapters(name)),
    # iter075: 全文搜索页
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/search/?$"), lambda name, **_: render_workspace_search_page(name)),
    (
        "GET",
        re.compile(r"^/w/(?P<name>[^/]+)/chapter/(?P<chapter>\d+)/?$"),
        lambda name, chapter, **_: render_workspace_chapter_detail(name, chapter),
    ),
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/reviews/?$"), lambda name, **_: render_workspace_reviews_page(name)),
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/plan/?$"), lambda name, **_: render_workspace_plan_page(name)),
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/workbench/?$"), lambda name, **_: render_workspace_workbench_page(name)),
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/insights/?$"), lambda name, **_: render_workspace_insights_page(name)),
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/jobs/?$"), lambda name, **_: render_workspace_jobs_page(name)),
    ("GET", re.compile(r"^/api/workspaces/overview/?$"), lambda **_: api_workspaces_overview()),
    ("GET", re.compile(r"^/api/workspaces/?$"), lambda **_: api_workspaces()),
    _mutation_route(
        "POST", r"^/api/workspace/(?P<name>[^/]+)/delete/?$",
        lambda name, _body=b"", **_: api_workspace_delete(name, _body),
        _POLICY_WORKSPACE,
    ),
    ("GET", re.compile(r"^/api/trash/?$"), lambda **_: api_trash_list()),
    _mutation_route(
        "POST", r"^/api/trash/(?P<entry>[^/]+)/restore/?$",
        lambda entry, **_: api_trash_restore(entry), _POLICY_WORKSPACE,
    ),
    _mutation_route(
        "POST", r"^/api/trash/(?P<entry>[^/]+)/purge/?$",
        lambda entry, _body=b"", **_: api_trash_purge(entry, _body),
        _POLICY_WORKSPACE,
    ),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/status/?$"), lambda name, **_: api_workspace_status(name)),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/cost/?$"), lambda name, **_: api_workspace_cost(name)),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/manifest/?$"), lambda name, **_: api_workspace_manifest(name)),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/start-point/?$"), lambda name, **_: api_workspace_start_point(name)),
    _mutation_route(
        "POST", r"^/api/workspace/(?P<name>[^/]+)/start-point/?$",
        lambda name, _body=b"", **_: api_workspace_set_start_point(name, _body),
        _POLICY_WORKSPACE,
    ),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/reviews/?$"), lambda name, **_: api_workspace_reviews(name)),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/plan/?$"), lambda name, **_: api_workspace_plan(name)),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/workbench/?$"), lambda name, **_: api_workbench_status(name)),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/write-recovery/?$"),
        lambda name, _query=None, **_: api_workspace_write_recovery_get(
            name, ((_query or {}).get("chapter", [""])[0])
        ),
    ),
    _mutation_route(
        "POST", r"^/api/workspace/(?P<name>[^/]+)/write-recovery/?$",
        lambda name, _body=b"", **_: api_workspace_write_recovery_post(name, _body),
        _POLICY_WRITE_RECOVERY,
    ),
    _mutation_route(
        "PUT", r"^/api/workspace/(?P<name>[^/]+)/outline/?$",
        lambda name, _body=b"", **_: api_workspace_outline_save(name, _body),
        _POLICY_WORKSPACE,
    ),
    # iter 050: structured per-chapter plan edit (workbench stage ③)
    _mutation_route(
        "PUT", r"^/api/workspace/(?P<name>[^/]+)/chapter-plan/(?P<chapter>\d+)/?$",
        lambda name, chapter, _body=b"", **_: api_workspace_chapter_plan_save(name, chapter, _body),
        _POLICY_WORKSPACE,
    ),
    # iter 050 (B1/B3): draft + KB + entity_graph edit surfaces
    _mutation_route(
        "PUT", r"^/api/workspace/(?P<name>[^/]+)/draft/(?P<chapter>\d+)/?$",
        lambda name, chapter, _body=b"", **_: api_workspace_draft_save(name, chapter, _body),
        _POLICY_WORKSPACE,
    ),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/kb/?$"), lambda name, **_: api_workspace_kb_get(name)),
    _mutation_route(
        "PUT", r"^/api/workspace/(?P<name>[^/]+)/kb/?$",
        lambda name, _body=b"", **_: api_workspace_kb_save(name, _body),
        _POLICY_WORKSPACE,
    ),
    # iter 051a: premise expansion view + edit (workbench stage ①)
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/premise-expansion/?$"),
        lambda name, **_: api_workspace_premise_expansion_get(name),
    ),
    _mutation_route(
        "PUT", r"^/api/workspace/(?P<name>[^/]+)/premise-expansion/?$",
        lambda name, _body=b"", **_: api_workspace_premise_expansion_save(name, _body),
        _POLICY_WORKSPACE,
    ),
    # iter 056: 作家风格卡（workbench stage ①，仅 premise 自创书）
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/style-presets/?$"),
        lambda name, **_: api_workspace_style_presets(name),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/writer-style/?$"),
        lambda name, **_: api_workspace_writer_style_get(name),
    ),
    _mutation_route(
        "PUT", r"^/api/workspace/(?P<name>[^/]+)/writer-style/?$",
        lambda name, _body=b"", **_: api_workspace_writer_style_save(name, _body),
        _POLICY_WORKSPACE,
    ),
    _mutation_route(
        "POST", r"^/api/workspace/(?P<name>[^/]+)/writer-style/activate/?$",
        lambda name, _body=b"", **_: api_workspace_writer_style_activate(name, _body),
        _POLICY_WORKSPACE,
    ),
    _mutation_route(
        "POST", r"^/api/workspace/(?P<name>[^/]+)/writer-style/extract/?$",
        lambda name, _body=b"", _headers=None, **_: api_workspace_writer_style_extract(name, _body, _headers or {}),
        _POLICY_STYLE_EXTRACT,
    ),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/entity-graph/?$"), lambda name, **_: api_workspace_entity_graph(name)),
    _mutation_route(
        "PUT", r"^/api/workspace/(?P<name>[^/]+)/entity/(?P<entity_id>[^/]+)/?$",
        lambda name, entity_id, _body=b"", **_: api_workspace_entity_save(name, entity_id, _body),
        _POLICY_WORKSPACE,
    ),
    _mutation_route(
        "PUT", r"^/api/workspace/(?P<name>[^/]+)/relationship/(?P<index>\d+)/?$",
        lambda name, index, _body=b"", **_: api_workspace_relationship_save(name, index, _body),
        _POLICY_WORKSPACE,
    ),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/insights/?$"), lambda name, **_: api_workspace_insights(name)),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/drafts/?$"), lambda name, **_: api_workspace_drafts(name)),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/draft/(?P<chapter>\d+)/?$"),
        lambda name, chapter, _query=None, **_: api_workspace_draft(
            name,
            chapter,
            variant=(_query or {}).get("variant", [""])[0],
        ),
    ),
    # iter 074: chapter version diff — enumerate versions + unified diff
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/chapter/(?P<chapter>\d+)/versions/?$"),
        lambda name, chapter, **_: api_workspace_chapter_versions(name, chapter),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/chapter/(?P<chapter>\d+)/diff/?$"),
        lambda name, chapter, _query=None, **_: api_workspace_chapter_diff(
            name,
            chapter,
            v1=(_query or {}).get("v1", [""])[0],
            v2=(_query or {}).get("v2", [""])[0],
        ),
    ),
    # iter075: 全文搜索 API
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/search/?$"),
        lambda name, _query=None, **_: api_workspace_search(
            name,
            q=(_query or {}).get("q", [""])[0],
            sources=(_query or {}).get("sources", [None])[0],
        ),
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
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/jobs/active/?$"),
        lambda name, **_: api_workspace_active_jobs(name),
    ),
    # iter 026: POST /run (start a job) + GET /job/<id> (poll progress)
    _mutation_route(
        "POST", r"^/api/workspace/(?P<name>[^/]+)/run/?$",
        lambda name, _body=b"", **_: api_run_step(name, _body),
        _POLICY_MODEL_RUN,
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/job/(?P<job_id>[a-f0-9]{32})/?$"),
        lambda name, job_id, **_: api_job_status(name, job_id),
    ),
    _mutation_route(
        "POST", r"^/api/workspace/(?P<name>[^/]+)/job/(?P<job_id>[a-f0-9]{32})/cancel/?$",
        lambda name, job_id, **_: api_job_cancel(name, job_id),
        _POLICY_WORKSPACE,
    ),
    # iter 026: onboarding wizard — single multipart POST that starts an
    # auto-pipeline job; client then polls the job_id from above.
    ("GET", re.compile(r"^/wizard/?$"), lambda **_: render_wizard_page()),
    ("GET", re.compile(r"^/api/preflight/?$"), lambda **_: api_preflight()),
    _mutation_route(
        "POST", r"^/api/wizard/start/?$",
        lambda _body=b"", _headers=None, **_: api_wizard_start(_body, _headers or {}),
        _POLICY_WIZARD_IMPORT,
    ),
    _mutation_route(
        "POST", r"^/api/wizard/premise-start/?$",
        lambda _body=b"", _headers=None, **_: api_wizard_premise_start(_body, _headers or {}),
        _POLICY_WIZARD_PREMISE,
    ),
    # iter 048a: workbench "test key" — model-key connectivity matrix
    _mutation_route(
        "POST", r"^/api/diag/models/?$", lambda **_: api_diag_models(),
        _POLICY_MODEL_DIAG,
    ),
    # iter 026 P4: model-switch panel
    ("GET", re.compile(r"^/settings/?$"), lambda **_: render_settings_page()),
    ("GET", re.compile(r"^/static/settings\.js$"), lambda **_: (200, "application/javascript; charset=utf-8", static.JS_SETTINGS.encode("utf-8"))),
    ("GET", re.compile(r"^/api/settings/?$"), lambda **_: api_settings_get()),
    _mutation_route(
        "PUT", r"^/api/settings/?$",
        lambda _body=b"", **_: api_settings_put(_body), _POLICY_SETTINGS,
    ),
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
) -> WebResponse:
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
    # iter076（codex 审查 iter075 #2）：keep_blank_values——`?sources=`（显式空值）必须
    # 到达 handler（→ 空列表 = 一个都不搜），默认丢弃会被误判成「未传 → 全搜」。既有
    # 消费点全部安全：variant/v1/v2/q 走 `or ""` 兜底，_parse_int/_parse_n 对空串
    # catch ValueError 落 default（有回归测试钉住）。
    query = parse_qs(split.query, keep_blank_values=True) if split.query else None
    # Iter 025 code-review #8: ``BaseHTTPRequestHandler.path`` keeps
    # percent-encoded bytes, so a CJK workspace like ``/workspace/龙族/``
    # arrives as ``/workspace/%E9%BE%99%E6%97%8F/`` and never matches the
    # ``[^/]+`` capture against the literal name on disk. We decode the
    # path once here so handlers receive the original Unicode name; the
    # ``/`` separator survives because ``unquote`` is applied AFTER
    # ``urlsplit`` has already extracted the path component.
    decoded_path = unquote(split.path)
    normalized_headers = {
        str(key).lower(): str(value) for key, value in (headers or {}).items()
    }
    if mutation_route_missing_policy(method, decoded_path):
        return _json(500, {"error": "mutation policy missing"})
    policy = mutation_policy_for(method, decoded_path)
    if (
        headers is not None
        and method in {"POST", "PUT"}
        and policy is not None
        and not _trusted_in_process_mutation_headers(normalized_headers)
    ):
        request_error = _web_mutation_request_error(
            body,
            normalized_headers,
            policy=policy,
        )
        if request_error:
            return request_error
    # iter 049: opt-in bearer-token gate (no-op unless NOVEL_API_TOKEN is set).
    # Only /api/* is gated; pages + /w/ deep links stay open for the browser.
    _token = auth.required_token()
    if _token is not None and not auth.is_authorized(decoded_path, normalized_headers, _token):
        return _json(401, {"error": "unauthorized"})
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
        kwargs["_headers"] = normalized_headers
        try:
            return handler(**kwargs)
        except FileNotFoundError as exc:
            return _json(404, errors.exception_body(exc))
        except ValueError as exc:
            return _json(400, errors.exception_body(exc))
        except Exception as exc:
            # Iter 026 code-review #7 hardening: don't leak ``str(exc)``
            # to the client. Log the full exception server-side with a
            # trace_id the user can quote when reporting bugs.
            # iter062: also hand the client a friendly ``card`` (title +
            # next step + the same trace_id) — the ``error`` string stays
            # "internal server error" for backward compatibility.
            trace_id = _safe_log_exception("routes.dispatch", exc)
            return _json(
                500,
                {
                    "error": "internal server error",
                    "trace_id": trace_id,
                    "card": errors.build_card("server_error", trace_id=trace_id),
                },
            )

    # Path matched but method didn't: 405. Otherwise 404.
    if matched_any_method:
        return _json(405, {"error": f"method {method} not allowed for this path"})
    # Unmatched paths under /api/* return JSON 404; HTML pages get a tiny
    # text/html 404 so accidental browser typos render readable text.
    if decoded_path.startswith("/api/"):
        return _json(404, {"error": "no such route"})
    return _html(404, "<h1>404</h1><p>no such route</p>")
