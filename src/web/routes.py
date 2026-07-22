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
import math
import os
import re
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, unquote, urlsplit

from .. import paths, review_tier, run_params, search as search_mod, start_point
from ..book_runner import check_write_readiness
from ..cli_workspace import list_workspaces
from ..config import get_model_config
from ..cost_estimator import estimate_cost
from ..observability import collect_status
from ..utils import read_json, read_json_optional
from . import auth, chapter_diff as chapter_diff_mod, diag, errors, jobs, settings as settings_mod, static, templates, wizard
from ._naming import RESERVED_NAMES as _RESERVED_WORKSPACE_NAMES_SHARED  # noqa: F401
from ._naming import (
    WORKSPACE_NAME_RE as _WORKSPACE_NAME_RE_SHARED,  # noqa: F401
)
from ._naming import (
    validate_workspace_name as _shared_validate_workspace_name,
)
from .reviews_aggregator import aggregate_reviews
from .workspace_ctx import use_workspace

# Most handlers return ``(status_code, content_type, body_bytes)``. Download
# handlers may add a fourth, fixed response-header mapping. The Web server
# allowlists those headers before writing them to the socket, so ordinary
# route tests and all pre-existing handlers keep the compact three-tuple.
WebResponse = Union[
    Tuple[int, str, bytes],
    Tuple[int, str, bytes, Dict[str, str]],
]
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

_DRAMA_MUTATION_PATH_RE = re.compile(
    r"^/api/workspace/[^/]+/drama/(?!progress(?:/|$)|hook-candidates(?:/|$))[^?]+/?$"
)
_DRAMA_MUTATION_BODY_LIMIT = 64 * 1024
_DRAMA_MUTATION_INTENTS = {
    "x-drama-mutation-intent": {"mutate-v1"},
    "x-drama-asset-intent": {"mutate-v1"},
    "x-drama-shot-image-intent": {"mutate-v1"},
    "x-drama-shot-video-intent": {"mutate-v1"},
    "x-drama-compose-intent": {"run-local-v1"},
    "x-drama-image-intent": {"generate-once-v1"},
}


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
    """iter062: degraded-path handlers used to embed ``str(exc)`` in the
    response (a raw-traceback leak the user couldn't read). We now return a
    friendly ``errors`` card instead — so log the real exception to stderr
    here so debug detail isn't silently dropped."""
    import sys
    import traceback as _tb

    try:
        from ..llm_client import _sanitize_error_text

        detail = _sanitize_error_text(exc, max_chars=1000)
    except Exception:
        detail = f"{type(exc).__name__}: {exc}"
    sys.stderr.write(f"[web] degraded path '{where}': {detail}\n")
    for line in _tb.format_tb(exc.__traceback__):
        sys.stderr.write(line)


def _validate_workspace_name(name: str) -> bool:
    """Thin wrapper around the shared validator (iter 027 P2 #7)."""
    return _shared_validate_workspace_name(name)


def _workspace_exists(name: str) -> bool:
    return (paths.WORKSPACE_DIR / name).is_dir()


def _drama_mutation_request_error(
    body: bytes,
    headers: Dict[str, str],
) -> Optional[Tuple[int, str, bytes]]:
    """Reject browser cross-site/simple requests before any drama mutation.

    ``dispatch(..., headers=None)`` remains a trusted in-process seam for the
    existing domain tests.  The HTTP server always supplies request headers,
    so every wire request must carry JSON plus one explicit drama intent.
    """

    if len(body) > _DRAMA_MUTATION_BODY_LIMIT:
        return _json(413, {"error": "drama mutation payload too large"})
    content_type = str(headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _json(415, {"error": "Content-Type must be application/json"})
    if not any(
        str(headers.get(key) or "") in allowed
        for key, allowed in _DRAMA_MUTATION_INTENTS.items()
    ):
        return _json(403, {"error": "explicit drama mutation intent required"})
    fetch_site = str(headers.get("sec-fetch-site") or "").strip().lower()
    if fetch_site and fetch_site not in {"same-origin", "same-site", "none"}:
        return _json(403, {"error": "cross-site drama mutation rejected"})
    origin = str(headers.get("origin") or "").strip()
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            return _json(403, {"error": "cross-origin drama mutation rejected"})
        host = str(headers.get("host") or "").strip().lower()
        if host and parsed.netloc.lower() != host:
            return _json(403, {"error": "cross-origin drama mutation rejected"})
    return None


def _workspace_error(name: str) -> Optional[Tuple[int, str, bytes]]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
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

    with jobs.workspace_reserved(name):
        with use_workspace(name):
            with acquire_write_lock(source=source):
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
    return _redirect(f"/w/{name}/")


def _workspace_html_guard(name: str) -> Optional[Tuple[int, str, bytes]]:
    if not _validate_workspace_name(name):
        return _html(400, "<h1>400</h1><p>invalid workspace name</p>")
    if not _workspace_exists(name):
        return _html(404, f"<h1>404</h1><p>workspace not found: {name}</p>")
    return None


def _workspace_html_guard_novel_only(name: str) -> Optional[Tuple[int, str, bytes]]:
    """Guard routes that only make sense for novel workspaces."""

    base = _workspace_html_guard(name)
    if base:
        return base
    from .workspace_meta import read as _meta_read

    if _meta_read(name).get("type") != "novel":
        return _html(200, templates.render_workspace_novel_only_empty(name, list_workspaces()))
    return None


def render_workspace_overview(name: str) -> Tuple[int, str, bytes]:
    guard = _workspace_html_guard(name)
    if guard:
        return guard
    return _html(200, templates.render_workspace_overview(name, list_workspaces()))


def render_workspace_write_page(name: str, episode: Any = 1) -> Tuple[int, str, bytes]:
    """Drama-only 4-station write wizard page."""

    guard = _workspace_html_guard(name)
    if guard:
        return guard
    from .workspace_meta import read as _meta_read

    if _meta_read(name).get("type") != "drama":
        return _html(
            404,
            f'<h1>404</h1><p>this page is for drama workspaces only; '
            f'<a href="/w/{escape_html(name)}/">go back to overview</a></p>',
        )
    try:
        episode_no = _parse_episode_no(episode)
    except (TypeError, ValueError):
        return _html(400, "<h1>400</h1><p>invalid episode number</p>")
    return _html(200, templates.render_workspace_write(name, list_workspaces(), episode_no))


def render_workspace_characters_page(name: str) -> Tuple[int, str, bytes]:
    """Drama-only character library page."""

    guard = _workspace_html_guard(name)
    if guard:
        return guard
    from .workspace_meta import read as _meta_read

    if _meta_read(name).get("type") != "drama":
        return _html(
            404,
            f'<h1>404</h1><p>this page is for drama workspaces only; '
            f'<a href="/w/{escape_html(name)}/">go back to overview</a></p>',
        )
    return _html(200, templates.render_workspace_characters(name, list_workspaces()))


def render_workspace_production_page(name: str) -> Tuple[int, str, bytes]:
    """Drama-only, read-only production workbench."""

    guard = _workspace_html_guard(name)
    if guard:
        return guard
    from .workspace_meta import read as _meta_read

    if _meta_read(name).get("type") != "drama":
        return _html(
            404,
            f'<h1>404</h1><p>this page is for drama workspaces only; '
            f'<a href="/w/{escape_html(name)}/">go back to overview</a></p>',
        )
    return _html(200, templates.render_workspace_production(name, list_workspaces()))


def render_workspace_assets_page(name: str) -> Tuple[int, str, bytes]:
    """Drama-only redacted asset governance page."""

    guard = _workspace_html_guard(name)
    if guard:
        return guard
    from .workspace_meta import read as _meta_read

    if _meta_read(name).get("type") != "drama":
        return _html(
            404,
            f'<h1>404</h1><p>this page is for drama workspaces only; '
            f'<a href="/w/{escape_html(name)}/">go back to overview</a></p>',
        )
    return _html(200, templates.render_workspace_assets(name, list_workspaces()))


def render_workspace_shot_images_page(name: str) -> Tuple[int, str, bytes]:
    """Drama-only C2 image candidate comparison and selection page."""

    guard = _workspace_html_guard(name)
    if guard:
        return guard
    from .workspace_meta import read as _meta_read

    if _meta_read(name).get("type") != "drama":
        return _html(
            404,
            f'<h1>404</h1><p>this page is for drama workspaces only; '
            f'<a href="/w/{escape_html(name)}/">go back to overview</a></p>',
        )
    return _html(200, templates.render_workspace_shot_images(name, list_workspaces()))


def render_workspace_shot_videos_page(name: str) -> Tuple[int, str, bytes]:
    """Drama-only D2-D4 video candidate and continuity page."""

    guard = _workspace_html_guard(name)
    if guard:
        return guard
    from .workspace_meta import read as _meta_read

    if _meta_read(name).get("type") != "drama":
        return _html(
            404,
            f'<h1>404</h1><p>this page is for drama workspaces only; '
            f'<a href="/w/{escape_html(name)}/">go back to overview</a></p>',
        )
    return _html(200, templates.render_workspace_shot_videos(name, list_workspaces()))


def render_workspace_compose_page(name: str) -> Tuple[int, str, bytes]:
    guard = _workspace_html_guard(name)
    if guard:
        return guard
    from .workspace_meta import read as _meta_read

    if _meta_read(name).get("type") != "drama":
        return _html(
            404,
            f'<h1>404</h1><p>this page is for drama workspaces only; '
            f'<a href="/w/{escape_html(name)}/">go back to overview</a></p>',
        )
    return _html(200, templates.render_workspace_compose(name, list_workspaces()))


def render_workspace_episodes_page(name: str) -> Tuple[int, str, bytes]:
    """Drama-only episode list page."""

    guard = _workspace_html_guard(name)
    if guard:
        return guard
    from .workspace_meta import read as _meta_read

    if _meta_read(name).get("type") != "drama":
        return _html(
            404,
            f'<h1>404</h1><p>this page is for drama workspaces only; '
            f'<a href="/w/{escape_html(name)}/">go back to overview</a></p>',
        )
    return _html(200, templates.render_workspace_episodes(name, list_workspaces()))


def render_workspace_episode_detail_page(name: str, episode: str) -> Tuple[int, str, bytes]:
    """Drama-only episode detail page."""

    guard = _workspace_html_guard(name)
    if guard:
        return guard
    from .workspace_meta import read as _meta_read

    if _meta_read(name).get("type") != "drama":
        return _html(
            404,
            f'<h1>404</h1><p>this page is for drama workspaces only; '
            f'<a href="/w/{escape_html(name)}/">go back to overview</a></p>',
        )
    try:
        episode_no = _parse_episode_no(episode)
    except (TypeError, ValueError):
        return _html(400, "<h1>400</h1><p>invalid episode number</p>")
    return _html(200, templates.render_workspace_episode_detail(name, list_workspaces(), episode_no))


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
    # iter075: 全文搜索是 novel-only（drama 无正文语料）。
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
    guard = _workspace_html_guard(name)
    if guard:
        return guard
    from .workspace_meta import read as _meta_read

    if _meta_read(name).get("type") == "drama":
        return _html(200, templates.render_workspace_drama_insights(name, list_workspaces()))
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
    guard = _workspace_html_guard(name)
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

    model = str(get_model_config("write").get("model") or "mock")
    return _json(200, {"model": model, "is_mock": (not model or model == "mock" or model.startswith("mock/"))})


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
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
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
        code = {
            "entry_not_found": 404,
            "name_collision": 409,
            "malformed_entry": 400,
            "reserved_name": 400,
        }.get(msg, 500)
        return _json(code, {"error": msg})
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
        code = {"entry_not_found": 404, "malformed_entry": 400, "reserved_name": 400}.get(msg, 500)
        return _json(code, {"error": msg})
    return _json(200, {"purged": entry})


def _overview_cache_key(names: List[str]) -> Tuple[Any, ...]:
    from ..drama_schemas import episode_paths

    root = paths.WORKSPACE_DIR
    stamps = []
    for name in names:
        ws = root / name
        ep = episode_paths(name)
        stamps.append(
            (
                name,
                _mtime_ns(ws / "data" / "workspace.json"),
                _mtime_ns(ws / "data" / "chapter_manifest.json"),
                _mtime_ns(ws / "outputs" / "debate" / "chapter_plan.json"),
                _mtime_ns(ws / "outputs" / "episodes"),
                _mtime_ns(ep.setup_path),
                _mtime_ns(ep.storyboard_path),
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
    from .workspace_meta import read as _meta_read

    meta = _meta_read(name)
    root = paths.WORKSPACE_DIR / name
    overview: Dict[str, Any] = {
        "name": name,
        "type": meta["type"],
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
    if meta["type"] == "drama":
        try:
            from .drama_view import collect_drama_progress

            progress = collect_drama_progress(name)
            stations = progress.get("stations") if isinstance(progress, dict) else []
            station_list = stations if isinstance(stations, list) else []
            overview["drama_progress"] = {
                f"station{idx}": {
                    "id": station.get("id", ""),
                    "label": station.get("label", ""),
                    "status": station.get("status", ""),
                }
                for idx, station in enumerate(station_list[:5], start=1)
                if isinstance(station, dict)
            }
            all_done = bool(station_list) and all(
                isinstance(station, dict) and station.get("status") in {"done", "skipped"}
                for station in station_list
            )
            overview["readiness"] = {
                "status": "ready" if all_done else "warn",
                "blockers": [],
                "warnings": [],
                "recommended_commands": [],
            }
            recent = jobs.recent_jobs(name, limit=1)
            overview["recent_job"] = jobs.public_job_view(recent[0]) if recent else None
        except Exception as exc:
            _log_degraded("drama_progress", exc)
            overview["error"] = errors.card_for_exception(exc)
            overview["readiness"] = {
                "status": "blocked",
                "blockers": ["drama_progress_error"],
                "warnings": [],
                "recommended_commands": [],
            }
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
            overview["readiness"] = _safe_readiness(chapters=1, resume_from=1)
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
        manifest = read_json_optional(paths.chapter_manifest_path(), [])
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
    # iter060 (#7): without a reservation /start-point wrote through even while a
    # job (e.g. write-book auto_advance) held the workspace — the 409 mutex other
    # write endpoints honor was bypassed, so a start-point flip could race the
    # running pipeline's reads. Hold the same reservation as draft_save.
    try:
        with _workspace_write_guard(name, "web-manual-start-point"):
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
    except RuntimeError as exc:
        msg = str(exc)
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        if msg.startswith("workspace_not_found:"):
            return _json(404, {"error": f"workspace not found: {name}"})
        raise


def api_workspace_reviews(name: str) -> Tuple[int, str, bytes]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    with use_workspace(name):
        return _json(200, aggregate_reviews(paths.drafts_dir()))


def api_workspace_insights(name: str) -> Tuple[int, str, bytes]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    from .workspace_meta import read as _meta_read

    if _meta_read(name).get("type") == "drama":
        from .drama_insights import collect_drama_insights

        return _json(200, collect_drama_insights(name))

    from .insights import collect_insights

    with use_workspace(name):
        return _json(200, collect_insights())


def api_workspace_plan(name: str) -> Tuple[int, str, bytes]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    from .plan_view import collect_plan

    with use_workspace(name):
        return _json(200, collect_plan())


def api_workbench_status(name: str) -> Tuple[int, str, bytes]:
    """GET /api/workspace/<name>/workbench — four-stage workbench gate
    status (iter 048b): which stage the workspace can act on next, plus
    per-artifact flags.

    Gating uses an mtime chain, not bare existence: a downstream artifact
    counts only if it is no older than the artifact it derives from. So if
    the user edits the premise and re-runs stage ① (prepare-greenfield
    refreshes the KB), a stale outline/plan left from a prior run is treated
    as invalid and the workbench falls back to the right stage — avoiding
    the "old artifact masquerades as new" trap (red-team finding)."""
    error = _workspace_error(name)
    if error:
        return error
    with use_workspace(name):
        # iter 051a: the premise expansion joins the mtime chain upstream of
        # the KB — editing (or regenerating) the expansion makes the KB and
        # everything below it stale, same semantics as a KB edit staling the
        # outline. Missing expansion → mtime 0 → chain byte-identical to 050.
        from ..start_point import get_start_chapter_id

        # iter056: 仅 premise 自创书（无起点）展示风格卡 UI；续写书前端 gate 隐藏。
        has_start_point = bool(get_start_chapter_id())
        expansion_m = _mtime_ns(paths.premise_expansion_path())
        kb_m = _mtime_ns(paths.kb_path())
        outline_m = _mtime_ns(paths.outline_path())
        plan_path = paths.chapter_plan_path()
        plan_m = _mtime_ns(plan_path)
        drafts = paths.drafts_dir()
        draft_files = sorted(drafts.glob("chapter_*.md")) if drafts.exists() else []
        draft_count = len(draft_files)
        draft_m = max((_mtime_ns(p) for p in draft_files), default=0)
        plan_data = read_json_optional(plan_path, {})
        plan_chapters = plan_data.get("chapters") if isinstance(plan_data, dict) else None

        has_expansion = expansion_m > 0
        has_kb = kb_m > 0 and kb_m >= expansion_m
        has_outline = outline_m > 0 and outline_m >= kb_m
        has_plan = bool(plan_chapters) and plan_m >= outline_m and plan_m >= kb_m
        has_drafts = draft_count > 0 and draft_m >= plan_m

        if not has_kb:
            stage = "prepare"
        elif not has_outline:
            stage = "outline"
        elif not has_plan:
            stage = "plan"
        elif not has_drafts:
            stage = "write"
        else:
            stage = "done"

    return _json(
        200,
        {
            "stage": stage,
            "has_kb": has_kb,
            "has_outline": has_outline,
            "has_plan": has_plan,
            "draft_count": draft_count,
            "has_expansion": has_expansion,
            # explicit hint for the stage ① card: KB exists but predates the
            # (edited) expansion — "扩写稿已更新，需重新生成设定".
            "expansion_stale": has_expansion and kb_m > 0 and kb_m < expansion_m,
            # iter056: premise 自创书（无起点）才展示风格卡；前端据此 gate。
            "has_start_point": has_start_point,
        },
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
    error = _workspace_error(name)
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
                write_text_atomic(paths.outline_path(), outline)
            except OSError as exc:
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
    error = _workspace_error(name)
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
    error = _workspace_error(name)
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

    from ..state import write_text_atomic
    from ..utils import sha256_text, write_json

    # Normalize to the writer's on-disk shape (text + single trailing \n)
    # so the meta sha follows writer._draft_file_sha256's convention.
    draft = content.rstrip("\n")
    try:
        with _workspace_write_guard(name, "web-manual-draft"):
            drafts_dir = paths.drafts_dir()
            md_path = drafts_dir / f"chapter_{chapter_no:02d}.md"
            if not md_path.exists():
                return _json(404, {"error": f"chapter_{chapter_no:02d}.md not found"})
            meta_path = drafts_dir / f"chapter_{chapter_no:02d}.meta.json"
            meta = read_json_optional(meta_path, {})
            if not isinstance(meta, dict):
                meta = {}
            try:
                write_text_atomic(md_path, draft + "\n")
            except OSError as exc:
                return _json(500, errors.error_body(errors.card_for_exception(exc)))
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
                write_json(meta_path, meta)
            except OSError as exc:
                # iter 050d (M-1): the md IS saved at this point; saying
                # "保存失败" would be a lie. The chapter sits at
                # draft_hash_mismatch (fail-safe) until a re-save lands
                # the meta sync.
                # iter063 A2: return the friendly card (was a raw English
                # sentence with `{exc}` appended); log the raw exc to stderr
                # so the leak-free guarantee holds without losing detail.
                import sys as _sys
                _sys.stderr.write(
                    f"[routes] draft meta sync failed (ch={chapter_no}): "
                    f"{type(exc).__name__}: {exc}\n"
                )
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
    error = _workspace_error(name)
    if error:
        return error
    with use_workspace(name):
        kb_path = paths.kb_path()
        if not kb_path.exists():
            return _json(404, {"error": "knowledge base not found; run prepare first"})
        try:
            content = kb_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return _json(500, errors.error_body(errors.card_for_exception(exc)))
    return _json(200, {"content": content})


def api_workspace_kb_save(name: str, body: bytes) -> Tuple[int, str, bytes]:
    """PUT /api/workspace/<name>/kb — overwrite the global knowledge base
    (iter 050, B3). Mirrors the outline PUT. Saving the KB bumps its mtime,
    which makes the workbench mtime chain mark outline/plan stale — kept on
    purpose (048b red-team fix ③: a changed KB makes downstream artifacts
    suspect); the frontend explains this instead of hacking mtimes."""
    error = _workspace_error(name)
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
    from ..state import write_text_atomic

    try:
        with _workspace_write_guard(name, "web-manual-kb"):
            try:
                write_text_atomic(paths.kb_path(), content)
            except OSError as exc:
                return _json(500, errors.error_body(errors.card_for_exception(exc)))
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
    error = _workspace_error(name)
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
    error = _workspace_error(name)
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
    error = _workspace_error(name)
    if error:
        return error
    from ..writer_style import load_presets

    return _json(200, {"presets": load_presets()})


def api_workspace_writer_style_get(name: str) -> Tuple[int, str, bytes]:
    """GET /api/workspace/<name>/writer-style — 当前激活的风格卡（iter056）。"""
    error = _workspace_error(name)
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
    error = _workspace_error(name)
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
    error = _workspace_error(name)
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
    error = _workspace_error(name)
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
                name, "extract-style", {"force": True, "sample_token": sample_token}
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
    error = _workspace_error(name)
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
    error = _workspace_error(name)
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
    error = _workspace_error(name)
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


def _drama_endpoint_error(name: str) -> Optional[Tuple[int, str, bytes]]:
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    from .workspace_meta import read as _meta_read

    if _meta_read(name).get("type") != "drama":
        return _json(400, {"error": "drama-only endpoint"})
    return None


def _drama_asset_mutation_request_error(
    body: bytes,
    headers: Dict[str, str],
) -> Optional[Tuple[int, str, bytes]]:
    """Require a bounded JSON request carrying a same-origin-only intent header.

    The custom header forces a browser cross-origin preflight.  Fetch Metadata
    and Origin/Host checks add defense in depth without making non-browser
    route tests invent a Host header.
    """

    if len(body) > 32 * 1024:
        return _json(413, {"error": "asset mutation payload too large"})
    content_type = str(headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _json(415, {"error": "Content-Type must be application/json"})
    if headers.get("x-drama-asset-intent") != "mutate-v1":
        return _json(403, {"error": "missing asset mutation intent"})
    fetch_site = str(headers.get("sec-fetch-site") or "").strip().lower()
    if fetch_site and fetch_site not in ("same-origin", "same-site", "none"):
        return _json(403, {"error": "cross-site asset mutation rejected"})
    origin = str(headers.get("origin") or "").strip()
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in (
            "127.0.0.1",
            "localhost",
            "::1",
        ):
            return _json(403, {"error": "cross-origin asset mutation rejected"})
        host = str(headers.get("host") or "").strip().lower()
        if host and parsed.netloc.lower() != host:
            return _json(403, {"error": "cross-origin asset mutation rejected"})
    return None


def api_drama_assets_get(
    name: str,
    raw_season_no: Any = 1,
    raw_episode_no: Any = 1,
) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    try:
        season_no = int(raw_season_no)
        episode_no = _parse_episode_no(raw_episode_no)
        if season_no < 1 or isinstance(raw_season_no, bool):
            raise ValueError
    except (TypeError, ValueError):
        return _json(400, {"error": "invalid season_no or episode_no"})
    from ..drama_asset_web import build_asset_web_overview
    from ..schemas import model_to_dict

    return _json(
        200,
        model_to_dict(
            build_asset_web_overview(
                name,
                season_no=season_no,
                episode_no=episode_no,
            )
        ),
    )


def api_drama_production_get(
    name: str,
    raw_episode_no: Any = 1,
) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    try:
        episode_no = _parse_episode_no(raw_episode_no)
    except (TypeError, ValueError):
        return _json(400, {"error": "invalid episode_no"})
    from ..drama_local_demo import inspect_synthetic_local_demo
    from ..drama_production_workbench import build_production_workbench
    from ..schemas import model_to_dict

    try:
        projection = build_production_workbench(name, episode_no=episode_no)
    except (OSError, RuntimeError, TypeError, ValueError, RecursionError):
        return _json(409, {"error": "production workbench projection is unavailable"})
    payload = model_to_dict(projection)
    payload["local_demo"] = inspect_synthetic_local_demo(
        name, episode_no=episode_no
    )
    return _json(200, payload)


def api_drama_production_local_demo(
    name: str,
    body: bytes,
) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    assert payload is not None
    if set(payload) - {"episode_no", "confirm_synthetic_local"}:
        return _json(400, {"error": "unknown local demo params"})
    if payload.get("confirm_synthetic_local") is not True:
        return _json(400, {"error": "confirm_synthetic_local must be true"})
    try:
        episode_no = _parse_episode_no(payload.get("episode_no", 1))
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})
    from ..drama_local_demo import (
        allocate_synthetic_demo_workspace,
        inspect_synthetic_local_demo,
    )

    readiness = inspect_synthetic_local_demo(name, episode_no=episode_no)
    if readiness.get("can_start") is not True:
        return _json(409, {"error": readiness.get("reason") or "local demo is unavailable"})
    demo_workspace = allocate_synthetic_demo_workspace(name, episode_no=episode_no)
    try:
        job = jobs.start_job(name, "drama-local-demo", {
            "episode_no": episode_no,
            "demo_workspace": demo_workspace,
        })
    except ValueError as exc:
        return _json(400, errors.exception_body(exc))
    except RuntimeError as exc:
        msg = str(exc)
        if msg.startswith("workspace_busy:"):
            return _json(409, {
                "error": "workspace already has a running job",
                "running_job_id": msg.split(":", 1)[1],
            })
        raise
    return _json(202, {
        "job_id": job["job_id"],
        "status": job["status"],
        "step": "drama-local-demo",
        "demo_workspace": demo_workspace,
        "demo_episode_no": 1,
    })


def api_drama_assets_select(
    name: str,
    body: bytes,
    headers: Dict[str, str],
) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    request_error = _drama_asset_mutation_request_error(body, headers)
    if request_error:
        return request_error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    from ..drama_asset_web import (
        AssetSelectionRequest,
        DramaAssetWebConflict,
        select_asset_candidate,
    )
    from ..schemas import model_to_dict

    try:
        request = AssetSelectionRequest(**(payload or {}))
        with jobs.workspace_reserved(name):
            result = select_asset_candidate(name, request)
    except DramaAssetWebConflict as exc:
        return _json(409, {"error": str(exc)})
    except ValueError:
        return _json(400, {"error": "invalid asset mutation request"})
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        raise
    return _json(200, model_to_dict(result))


def api_drama_assets_status(
    name: str,
    body: bytes,
    headers: Dict[str, str],
) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    request_error = _drama_asset_mutation_request_error(body, headers)
    if request_error:
        return request_error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    from ..drama_asset_web import (
        AssetStatusRequest,
        DramaAssetWebConflict,
        set_asset_status,
    )
    from ..schemas import model_to_dict

    try:
        request = AssetStatusRequest(**(payload or {}))
        with jobs.workspace_reserved(name):
            result = set_asset_status(name, request)
    except DramaAssetWebConflict as exc:
        return _json(409, {"error": str(exc)})
    except ValueError:
        return _json(400, {"error": "invalid asset mutation request"})
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        raise
    return _json(200, model_to_dict(result))


def api_drama_art_direction_scope(
    name: str,
    body: bytes,
    headers: Dict[str, str],
) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    request_error = _drama_asset_mutation_request_error(body, headers)
    if request_error:
        return request_error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    from ..drama_asset_web import (
        ArtDirectionScopeRequest,
        DramaAssetWebConflict,
        set_art_direction_scope_enabled,
    )
    from ..schemas import model_to_dict

    try:
        request = ArtDirectionScopeRequest(**(payload or {}))
        with jobs.workspace_reserved(name):
            result = set_art_direction_scope_enabled(name, request)
    except DramaAssetWebConflict as exc:
        return _json(409, {"error": str(exc)})
    except ValueError:
        return _json(400, {"error": "invalid asset mutation request"})
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        raise
    return _json(200, model_to_dict(result))


def _drama_shot_image_mutation_request_error(
    body: bytes,
    headers: Dict[str, str],
) -> Optional[Tuple[int, str, bytes]]:
    if len(body) > 32 * 1024:
        return _json(413, {"error": "shot image mutation payload too large"})
    content_type = str(headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _json(415, {"error": "Content-Type must be application/json"})
    if str(headers.get("x-drama-shot-image-intent") or "") != "mutate-v1":
        return _json(403, {"error": "explicit shot image mutation intent required"})
    fetch_site = str(headers.get("sec-fetch-site") or "").strip().lower()
    if fetch_site and fetch_site not in {"same-origin", "same-site", "none"}:
        return _json(403, {"error": "cross-origin shot image mutation rejected"})
    origin = str(headers.get("origin") or "").strip()
    host = str(headers.get("host") or "").strip().lower()
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return _json(403, {"error": "invalid shot image mutation origin"})
        if host and parsed.netloc.lower() != host:
            return _json(403, {"error": "cross-origin shot image mutation rejected"})
    return None


def api_drama_shot_images_get(
    name: str,
    raw_episode_no: Any = 1,
) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    try:
        episode_no = _parse_episode_no(raw_episode_no)
    except (TypeError, ValueError):
        return _json(400, {"error": "invalid episode_no"})
    from ..drama_shot_image_web import build_shot_image_web_overview
    from ..schemas import model_to_dict

    return _json(
        200,
        model_to_dict(build_shot_image_web_overview(name, episode_no=episode_no)),
    )


def api_drama_shot_image_candidate_png(
    name: str,
    raw_episode_no: str,
    shot_id: str,
    candidate_id: str,
) -> WebResponse:
    error = _drama_endpoint_error(name)
    if error:
        return error
    try:
        episode_no = _parse_episode_no(raw_episode_no)
    except (TypeError, ValueError):
        return _json(400, {"error": "invalid episode_no"})
    from ..drama_shot_image_web import load_exact_shot_image_candidate_png

    try:
        payload = load_exact_shot_image_candidate_png(
            name,
            episode_no=episode_no,
            shot_id=shot_id,
            candidate_id=candidate_id,
        )
    except FileNotFoundError:
        return _json(404, {"error": "shot image candidate not found"})
    except ValueError:
        return _json(409, {"error": "shot image candidate is unavailable"})
    return (
        200,
        "image/png",
        payload,
        {"X-Content-Type-Options": "nosniff"},
    )


def api_drama_shot_images_select(
    name: str,
    body: bytes,
    headers: Dict[str, str],
) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    request_error = _drama_shot_image_mutation_request_error(body, headers)
    if request_error:
        return request_error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    from ..drama_shot_image_web import (
        DramaShotImageWebConflict,
        ShotImageSelectionRequest,
        select_shot_image_candidate,
    )
    from ..schemas import model_to_dict

    try:
        request = ShotImageSelectionRequest(**(payload or {}))
        with jobs.workspace_reserved(name):
            result = select_shot_image_candidate(name, request)
    except DramaShotImageWebConflict as exc:
        return _json(409, {"error": str(exc)})
    except ValueError:
        return _json(400, {"error": "invalid shot image mutation request"})
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        raise
    return _json(200, model_to_dict(result))


def _drama_shot_video_mutation_request_error(
    body: bytes,
    headers: Dict[str, str],
) -> Optional[Tuple[int, str, bytes]]:
    if len(body) > 32 * 1024:
        return _json(413, {"error": "shot video mutation payload too large"})
    content_type = str(headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _json(415, {"error": "Content-Type must be application/json"})
    if str(headers.get("x-drama-shot-video-intent") or "") != "mutate-v1":
        return _json(403, {"error": "explicit shot video mutation intent required"})
    fetch_site = str(headers.get("sec-fetch-site") or "").strip().lower()
    if fetch_site and fetch_site not in {"same-origin", "same-site", "none"}:
        return _json(403, {"error": "cross-origin shot video mutation rejected"})
    origin = str(headers.get("origin") or "").strip()
    host = str(headers.get("host") or "").strip().lower()
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return _json(403, {"error": "invalid shot video mutation origin"})
        if host and parsed.netloc.lower() != host:
            return _json(403, {"error": "cross-origin shot video mutation rejected"})
    return None


def api_drama_shot_videos_get(
    name: str,
    raw_episode_no: Any = 1,
) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    try:
        episode_no = _parse_episode_no(raw_episode_no)
    except (TypeError, ValueError):
        return _json(400, {"error": "invalid episode_no"})
    from ..drama_shot_video_web import build_shot_video_web_overview
    from ..schemas import model_to_dict

    try:
        overview = build_shot_video_web_overview(name, episode_no=episode_no)
    except RuntimeError:
        return _json(503, {"error": "shot video overview is busy; retry shortly"})
    return _json(200, model_to_dict(overview))


def _bounded_single_byte_range(raw: str, total: int) -> Optional[Tuple[int, int]]:
    if not raw:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", raw.strip())
    if match is None or (not match.group(1) and not match.group(2)):
        raise ValueError("invalid range")
    if match.group(1):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else total - 1
        if start >= total or end < start:
            raise ValueError("unsatisfiable range")
        return start, min(end, total - 1)
    suffix = int(match.group(2))
    if suffix <= 0:
        raise ValueError("unsatisfiable range")
    return max(0, total - suffix), total - 1


def api_drama_shot_video_candidate_mp4(
    name: str,
    raw_episode_no: str,
    shot_id: str,
    candidate_id: str,
    headers: Dict[str, str],
    *,
    head_only: bool = False,
) -> WebResponse:
    error = _drama_endpoint_error(name)
    if error:
        return error
    try:
        episode_no = _parse_episode_no(raw_episode_no)
    except (TypeError, ValueError):
        return _json(400, {"error": "invalid episode_no"})
    from ..drama_shot_video_web import load_exact_shot_video_candidate_mp4

    try:
        payload = load_exact_shot_video_candidate_mp4(
            name,
            episode_no=episode_no,
            shot_id=shot_id,
            candidate_id=candidate_id,
        )
    except FileNotFoundError:
        return _json(404, {"error": "shot video candidate not found"})
    except RuntimeError:
        return _json(503, {"error": "shot video preview is busy; retry shortly"})
    except ValueError:
        return _json(409, {"error": "shot video candidate is unavailable"})
    total = len(payload)
    try:
        byte_range = _bounded_single_byte_range(
            str(headers.get("range") or ""),
            total,
        )
    except ValueError:
        status, content_type, body = _json(416, {"error": "invalid media range"})
        return (
            status,
            content_type,
            b"" if head_only else body,
            {
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes */{total}",
                "Content-Length": str(len(body)),
                "X-Content-Type-Options": "nosniff",
            },
        )
    response_headers = {
        "Accept-Ranges": "bytes",
        "X-Content-Type-Options": "nosniff",
    }
    if byte_range is None:
        response_headers["Content-Length"] = str(total)
        return 200, "video/mp4", b"" if head_only else payload, response_headers
    start, end = byte_range
    response_headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    response_headers["Content-Length"] = str(end - start + 1)
    return (
        206,
        "video/mp4",
        b"" if head_only else payload[start : end + 1],
        response_headers,
    )


def api_drama_shot_videos_select(
    name: str,
    body: bytes,
    headers: Dict[str, str],
) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    request_error = _drama_shot_video_mutation_request_error(body, headers)
    if request_error:
        return request_error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    from ..drama_shot_video_web import (
        DramaShotVideoWebBusy,
        DramaShotVideoWebConflict,
        ShotVideoSelectionRequest,
        select_shot_video_candidate,
    )
    from ..schemas import model_to_dict

    try:
        request = ShotVideoSelectionRequest(**(payload or {}))
        with jobs.workspace_reserved(name):
            result = select_shot_video_candidate(name, request)
    except DramaShotVideoWebConflict as exc:
        return _json(409, {"error": str(exc)})
    except DramaShotVideoWebBusy as exc:
        return _json(503, {"error": str(exc)})
    except ValueError:
        return _json(400, {"error": "invalid shot video mutation request"})
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        raise
    return _json(200, model_to_dict(result))


def api_drama_compose_overview(
    name: str,
    raw_episode_no: Any = 1,
) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    try:
        episode_no = _parse_episode_no(raw_episode_no)
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})
    from ..drama_compose_web import build_compose_web_overview

    overview = build_compose_web_overview(name, episode_no=episode_no)
    active = next(
        (
            row
            for row in jobs.active_jobs(name)
            if row.get("step") == "drama-compose"
            and (row.get("params") or {}).get("episode_no") == episode_no
        ),
        None,
    )
    if active is not None:
        overview["job"] = jobs.public_job_detail_view(active)
    else:
        recent = next(
            (
                row
                for row in jobs.recent_jobs(name, limit=20)
                if row.get("step") == "drama-compose"
                and (row.get("params") or {}).get("episode_no") == episode_no
            ),
            None,
        )
        overview["job"] = (
            jobs.public_job_detail_view(recent) if recent is not None else None
        )
    return _json(200, overview)


def _drama_compose_request_error(
    body: bytes,
    headers: Dict[str, str],
) -> Optional[Tuple[int, str, bytes]]:
    if len(body) > 32 * 1024:
        return _json(413, {"error": "compose payload too large"})
    content_type = str(headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _json(415, {"error": "Content-Type must be application/json"})
    if headers.get("x-drama-compose-intent") != "run-local-v1":
        return _json(403, {"error": "missing compose intent"})
    fetch_site = str(headers.get("sec-fetch-site") or "").strip().lower()
    if fetch_site and fetch_site not in ("same-origin", "same-site", "none"):
        return _json(403, {"error": "cross-site compose request rejected"})
    return None


def api_drama_compose_start(
    name: str,
    body: bytes,
    headers: Dict[str, str],
) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    request_error = _drama_compose_request_error(body, headers)
    if request_error:
        return request_error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    params_error, params = _validated_drama_compose_params(payload or {})
    if params_error:
        return _json(400, {"error": params_error})
    try:
        job = jobs.start_job(name, "drama-compose", params)
    except ValueError as exc:
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
        raise
    return _json(
        202,
        {
            "job_id": job["job_id"],
            "status": job["status"],
            "step": "drama-compose",
        },
    )


def api_drama_compose_deliverable(
    name: str,
    raw_episode_no: str,
    timeline_fingerprint: str,
    kind: str,
    headers: Dict[str, str],
    *,
    head_only: bool = False,
) -> WebResponse:
    error = _drama_endpoint_error(name)
    if error:
        return error
    try:
        episode_no = _parse_episode_no(raw_episode_no)
    except (TypeError, ValueError):
        return _json(400, {"error": "invalid episode_no"})
    from ..drama_compose_web import (
        DramaComposeWebError,
        load_exact_compose_deliverable,
    )

    try:
        payload, content_type, filename = load_exact_compose_deliverable(
            name,
            episode_no=episode_no,
            timeline_fingerprint=timeline_fingerprint,
            kind=kind,
        )
    except FileNotFoundError:
        return _json(404, {"error": "deliverable not found"})
    except DramaComposeWebError as exc:
        if exc.code == "workspace_busy":
            return _json(503, {"error": "deliverable verification is busy; retry shortly"})
        return _json(409, {"error": "deliverable is unavailable"})
    except RuntimeError:
        return _json(503, {"error": "deliverable verification is busy; retry shortly"})
    except ValueError:
        return _json(409, {"error": "deliverable is unavailable"})

    total = len(payload)
    response_headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
        "Content-Length": str(total),
    }
    if kind != "mp4":
        return 200, content_type, b"" if head_only else payload, response_headers
    response_headers["Accept-Ranges"] = "bytes"
    try:
        byte_range = _bounded_single_byte_range(
            str(headers.get("range") or ""),
            total,
        )
    except ValueError:
        status, error_type, body = _json(416, {"error": "invalid media range"})
        return (
            status,
            error_type,
            b"" if head_only else body,
            {
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes */{total}",
                "Content-Length": str(len(body)),
                "X-Content-Type-Options": "nosniff",
            },
        )
    if byte_range is None:
        return 200, content_type, b"" if head_only else payload, response_headers
    start, end = byte_range
    response_headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    response_headers["Content-Length"] = str(end - start + 1)
    return (
        206,
        content_type,
        b"" if head_only else payload[start : end + 1],
        response_headers,
    )


_DRAMA_STEP_TASKS = {
    "drama-plan": "drama_plan",
    "drama-hooks": "drama_hooks",
    "drama-storyboard": "drama_storyboard",
    "drama-characters": "drama_character",
    "drama-review-assemble": "drama_review",
}
_DRAMA_JOB_STEPS = frozenset((*_DRAMA_STEP_TASKS, "drama-compose"))


def _validated_drama_compose_params(
    params: Dict[str, Any],
) -> Tuple[Optional[str], Dict[str, Any]]:
    unknown = set(params) - {"episode_no"}
    if unknown:
        return f"unknown drama compose params: {', '.join(sorted(unknown))}", {}
    try:
        episode_no = _parse_episode_no(params.get("episode_no", 1))
    except (TypeError, ValueError):
        return "episode_no must be an integer between 1 and 100", {}
    return None, {"episode_no": episode_no}


def api_drama_progress(name: str, raw_episode_no: Any = 1) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    try:
        episode_no = _parse_episode_no(raw_episode_no)
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})
    from .drama_view import collect_drama_progress

    payload = collect_drama_progress(name, episode_no=episode_no)
    # Expose only a boolean mode decision, never provider names, endpoints, or
    # credential-related config.  The UI uses this immediately before each
    # station invocation so one-shot paid authorization is neither guessed nor
    # retained across requests.
    payload["real_text_steps"] = {
        step: str(get_model_config(task).get("model") or "mock") != "mock"
        for step, task in _DRAMA_STEP_TASKS.items()
    }
    return _json(200, payload)


def _validated_drama_params(step: str, params: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    from ..drama_schemas import normalize_episode_no

    if step not in _DRAMA_STEP_TASKS:
        return "unknown drama step", {}
    unknown = set(params) - {
        "episode_no", "confirm_real_text", "confirm_text_retry", "confirm_new_text_revision",
        "confirm_upstream_status_and_billing_checked", "budget_cny", "timeout_minutes",
    }
    if unknown:
        return f"unknown drama params: {', '.join(sorted(unknown))}", {}
    try:
        episode_no = normalize_episode_no(params.get("episode_no", 1))
    except ValueError as exc:
        return str(exc), {}
    out: Dict[str, Any] = {"episode_no": episode_no}
    task = _DRAMA_STEP_TASKS[step]
    real_model = str(get_model_config(task).get("model") or "mock") != "mock"
    if real_model and params.get("confirm_real_text") is not True:
        return "confirm_real_text=true is required for real drama generation", {}
    if "confirm_real_text" in params and not isinstance(params.get("confirm_real_text"), bool):
        return "confirm_real_text must be boolean", {}
    for key in (
        "confirm_text_retry", "confirm_new_text_revision",
        "confirm_upstream_status_and_billing_checked",
    ):
        if key in params and not isinstance(params.get(key), bool):
            return f"{key} must be boolean", {}
    raw_budget = params.get("budget_cny")
    if real_model or raw_budget is not None:
        error, budget = _float_param(params, "budget_cny", 0.0, minimum=0.0, maximum=1_000_000.0)
        if error:
            return error, {}
        if real_model and budget <= 0:
            return "budget_cny must be positive for real drama generation", {}
        if budget > 0:
            out["budget_cny"] = budget
    raw_timeout = params.get("timeout_minutes")
    if real_model or raw_timeout is not None:
        error, timeout = _float_param(params, "timeout_minutes", 0.0, minimum=0.0, maximum=1440.0)
        if error:
            return error, {}
        if real_model and timeout <= 0:
            return "timeout_minutes must be positive for real drama generation", {}
        if timeout > 0:
            out["timeout_minutes"] = timeout
    if real_model:
        out["confirm_real_text"] = True
    for key in (
        "confirm_text_retry", "confirm_new_text_revision",
        "confirm_upstream_status_and_billing_checked",
    ):
        if params.get(key) is True:
            out[key] = True
    return None, out


def _enqueue_drama_job(
    name: str, step: str, episode_no: int, payload: Optional[Dict[str, Any]] = None
) -> Tuple[int, str, bytes]:
    """Start one allowlisted drama job with public-safe, minimal params."""
    params_error, params = _validated_drama_params(
        step, {**(payload or {}), "episode_no": episode_no}
    )
    if params_error:
        return _json(400, {"error": params_error})
    try:
        job = jobs.start_job(name, step, params)
    except ValueError as exc:
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
        raise
    return _json(202, {"job_id": job["job_id"], "status": job["status"], "step": step})


def api_drama_plan(name: str, body: bytes) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    assert payload is not None
    try:
        episode_no = _parse_episode_no(payload.get("episode_no", 1))
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})
    if episode_no > 1:
        return _json(409, {"error": "later episodes must be initialized through next-episode"})
    return _enqueue_drama_job(name, "drama-plan", episode_no, payload)


def api_drama_hooks(name: str, body: bytes) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    assert payload is not None
    try:
        episode_no = _parse_episode_no(payload.get("episode_no", 1))
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})
    return _enqueue_drama_job(name, "drama-hooks", episode_no, payload)


def api_drama_hook_candidates(name: str, raw_episode_no: Any = 1) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    try:
        episode_no = _parse_episode_no(raw_episode_no)
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})
    from ..drama_schemas import DramaHookCandidates, episode_paths
    from ..schemas import model_to_dict

    data = read_json_optional(episode_paths(name, episode_no=episode_no).hook_candidates_path, None)
    if not isinstance(data, dict):
        return _json(200, {"exists": False, "hooks": []})
    try:
        parsed = DramaHookCandidates(**data)
    except Exception:
        return _json(200, {"exists": False, "hooks": []})
    return _json(200, {"exists": True, "hooks": [model_to_dict(item) for item in parsed.hooks]})


def api_drama_setup_save(name: str, body: bytes) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return _json(400, {"error": "body must be a JSON object"})
    try:
        episode_no = _parse_episode_no(payload.get("episode_no", 1))
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})

    # iter060 (#14): hold the reservation across the whole read-modify-write so a
    # concurrent /drama/plan (which rewrites setup.json wholesale) or job can't
    # interleave, and persist atomically via write_json (was a bare write_text).
    from ..drama_schemas import episode_paths
    from ..utils import write_json

    try:
        with _workspace_write_guard(name, "web-manual-drama-setup"):
            ep_paths = episode_paths(name, episode_no=episode_no)
            setup_path = ep_paths.setup_path
            if not setup_path.is_file():
                return _json(400, {"error": "station 1 must run first"})
            try:
                setup = json.loads(setup_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                return _json(500, errors.error_body(errors.card_for_exception(exc)))
            if not isinstance(setup, dict):
                return _json(500, {"error": "setup file must be a JSON object"})

            core_keys = {"logline", "protagonist", "antagonist", "emotional_hook"}
            if any(k in payload for k in core_keys):
                core = setup.setdefault("core_setup", {})
                if not isinstance(core, dict):
                    core = {}
                    setup["core_setup"] = core
                if "logline" in payload:
                    setup["logline"] = payload["logline"]
                for key in ("protagonist", "antagonist", "emotional_hook"):
                    if key in payload:
                        core[key] = payload[key]
            if "hook" in payload:
                if not isinstance(payload["hook"], dict):
                    return _json(400, {"error": "'hook' must be an object"})
                setup["hook"] = payload["hook"]
            if "episode_mainline" in payload:
                if not isinstance(payload["episode_mainline"], str) or len(payload["episode_mainline"]) > 1000:
                    return _json(400, {"error": "episode_mainline must be a string up to 1000 chars"})
                setup["episode_mainline"] = payload["episode_mainline"]
            if "introduces_new_characters" in payload:
                if not isinstance(payload["introduces_new_characters"], bool):
                    return _json(400, {"error": "introduces_new_characters must be boolean"})
                setup["introduces_new_characters"] = payload["introduces_new_characters"]

            write_json(setup_path, setup)
            if "hook" in payload or any(k in payload for k in core_keys | {
                "episode_mainline", "introduces_new_characters"
            }):
                ep_paths.hook_candidates_path.unlink(missing_ok=True)
            _clear_overview_cache()
            return _json(200, {"saved": True})
    except RuntimeError as exc:
        msg = str(exc)
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        if msg.startswith("workspace_not_found:"):
            return _json(404, {"error": f"workspace not found: {name}"})
        raise


def _parse_json_object_body(body: bytes) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, str, bytes]]]:
    try:
        payload = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, _json(400, {"error": "body must be valid JSON"})
    if not isinstance(payload, dict):
        return None, _json(400, {"error": "body must be a JSON object"})
    return payload, None


def _storyboard_payload_response(storyboard: Dict[str, Any], *, exists: bool = True) -> Tuple[int, str, bytes]:
    from ..drama_schemas import (
        DramaStoryboard,
        normalize_storyboard_payload,
        validate_storyboard_hard,
        validate_storyboard_soft,
    )
    from ..schemas import model_to_dict

    board = DramaStoryboard(**normalize_storyboard_payload(storyboard))
    hard_errors = validate_storyboard_hard(board)
    if hard_errors:
        raise ValueError(f"storyboard hard validation failed: {', '.join(hard_errors)}")
    data = model_to_dict(board)
    warnings = validate_storyboard_soft(board)
    data["soft_warnings"] = warnings
    return _json(200, {"exists": exists, "storyboard": data, "soft_warnings": warnings})


def _drama_storyboard_setup(name: str, *, episode_no: int = 1) -> Dict[str, Any]:
    from ..drama_schemas import episode_paths

    setup = read_json_optional(episode_paths(name, episode_no=episode_no).setup_path, None)
    if not isinstance(setup, dict):
        raise FileNotFoundError("station 2 must complete before station 3")
    core = setup.get("core_setup")
    if not isinstance(core, dict) or not core.get("protagonist"):
        raise ValueError("station 1 output missing core_setup.protagonist")
    hook = setup.get("hook")
    if not isinstance(hook, dict) or not hook.get("type"):
        raise ValueError("station 2 must complete before station 3")
    return setup


def _drama_storyboard_prereq_error(name: str, *, episode_no: int = 1) -> Optional[Tuple[int, str, bytes]]:
    try:
        _drama_storyboard_setup(name, episode_no=episode_no)
    except FileNotFoundError:
        return _json(400, {"error": "station 2 must complete before station 3"})
    except ValueError as exc:
        return _json(400, {"error": str(exc)})
    return None


def _storyboard_hook_snapshot(setup: Dict[str, Any]) -> Dict[str, str]:
    hook = setup.get("hook") if isinstance(setup.get("hook"), dict) else {}
    snapshot: Dict[str, str] = {}
    for key, limit in (("type", 80), ("content", 500)):
        raw = hook.get(key)
        if raw is None or isinstance(raw, (dict, list)):
            continue
        snapshot[key] = str(raw)[:limit]
    return snapshot


def _storyboard_hard_error(storyboard: Dict[str, Any]) -> Optional[Tuple[int, str, bytes]]:
    from ..drama_schemas import DramaStoryboard, normalize_storyboard_payload, validate_storyboard_hard

    try:
        board = DramaStoryboard(**normalize_storyboard_payload(storyboard))
    except Exception:
        return None
    hard_errors = validate_storyboard_hard(board)
    if hard_errors:
        return _json(400, {"error": "storyboard hard validation failed: " + ", ".join(hard_errors)})
    return None


def _drama_storyboard_runtime_error(exc: RuntimeError) -> Tuple[int, str, bytes]:
    import sys
    import traceback as _tb

    sys.stderr.write(f"[web] degraded path 'drama_storyboard_runtime': {type(exc).__name__}: suppressed\n")
    for line in _tb.format_tb(exc.__traceback__):
        sys.stderr.write(line)
    return _json(500, errors.error_body(errors.build_card("server_error")))


def api_drama_storyboard_get(name: str, raw_episode_no: Any = 1) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    try:
        episode_no = _parse_episode_no(raw_episode_no)
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})
    prereq = _drama_storyboard_prereq_error(name, episode_no=episode_no)
    if prereq:
        return prereq
    from ..drama_schemas import episode_paths

    p = episode_paths(name, episode_no=episode_no).storyboard_path
    data = read_json_optional(p, None)
    if data is None:
        return _json(200, {"exists": False, "storyboard": None, "soft_warnings": []})
    if not isinstance(data, dict):
        return _json(500, {"error": "storyboard file must be a JSON object"})
    try:
        return _storyboard_payload_response(data)
    except Exception as exc:
        return _json(500, errors.exception_body(exc))


def api_drama_storyboard_generate(name: str, body: bytes) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    assert payload is not None
    try:
        episode_no = _parse_episode_no(payload.get("episode_no", 1))
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})
    return _enqueue_drama_job(name, "drama-storyboard", episode_no, payload)


def api_drama_storyboard_save(name: str, body: bytes) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    assert payload is not None
    try:
        episode_no = _parse_episode_no(payload.get("episode_no", 1))
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})
    raw = payload.get("storyboard") if isinstance(payload.get("storyboard"), dict) else payload
    if not isinstance(raw, dict):
        return _json(400, {"error": "storyboard must be a JSON object"})

    from ..drama_schemas import (
        DramaStoryboard,
        episode_paths,
        normalize_storyboard_payload,
        validate_storyboard_hard,
        validate_storyboard_soft,
    )
    from ..schemas import model_to_dict
    from ..utils import write_json

    try:
        with _workspace_write_guard(name, "web-manual-drama-storyboard-save"):
            try:
                setup = _drama_storyboard_setup(name, episode_no=episode_no)
            except FileNotFoundError:
                return _json(400, {"error": "station 2 must complete before station 3"})
            except ValueError as exc:
                return _json(400, {"error": str(exc)})
            try:
                normalized = normalize_storyboard_payload(raw)
                normalized["episode_no"] = episode_no
                normalized["hook"] = _storyboard_hook_snapshot(setup)
                board = DramaStoryboard(**normalized)
                hard_errors = validate_storyboard_hard(board)
                if hard_errors:
                    return _json(400, {"error": "storyboard hard validation failed: " + ", ".join(hard_errors)})
                data = model_to_dict(board)
                data["soft_warnings"] = validate_storyboard_soft(board)
            except Exception as exc:
                return _json(400, errors.exception_body(exc))
            write_json(episode_paths(name, episode_no=episode_no).storyboard_path, data)
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        if str(exc).startswith("workspace_not_found:"):
            return _json(404, {"error": f"workspace not found: {name}"})
        raise
    _clear_overview_cache()
    return _json(200, {"saved": True, "storyboard": data, "soft_warnings": data["soft_warnings"]})


def api_drama_storyboard_rewrite_shot(name: str, body: bytes) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    assert payload is not None
    try:
        episode_no = _parse_episode_no(payload.get("episode_no", 1))
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})
    try:
        raw_shot_no = payload.get("shot_no")
        if isinstance(raw_shot_no, bool):
            raise ValueError
        shot_no = int(raw_shot_no)
    except (TypeError, ValueError):
        return _json(400, {"error": "shot_no must be an integer"})
    current_storyboard = payload.get("storyboard")
    if current_storyboard is not None and not isinstance(current_storyboard, dict):
        return _json(400, {"error": "storyboard must be a JSON object"})

    from .. import storyboard_builder
    from ..drama_schemas import episode_paths
    from ..utils import write_json

    try:
        with _workspace_write_guard(name, "web-manual-drama-storyboard-rewrite"):
            prereq = _drama_storyboard_prereq_error(name, episode_no=episode_no)
            if prereq:
                return prereq
            try:
                result = storyboard_builder.rewrite_shot(
                    name,
                    shot_no,
                    mock=True,
                    episode_no=episode_no,
                    storyboard=current_storyboard,
                )
            except FileNotFoundError as exc:
                return _json(400, errors.exception_body(exc))
            except ValueError as exc:
                return _json(400, errors.exception_body(exc))
            except RuntimeError as exc:
                return _drama_storyboard_runtime_error(exc)
            hard_error = _storyboard_hard_error(result)
            if hard_error:
                return hard_error
            write_json(episode_paths(name, episode_no=episode_no).storyboard_path, result)
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        if str(exc).startswith("workspace_not_found:"):
            return _json(404, {"error": f"workspace not found: {name}"})
        raise
    _clear_overview_cache()
    return _storyboard_payload_response(result)


_CHARACTER_ID_RE = re.compile(r"^c\d{3}$")
_REF_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
_CHARACTER_REF_CONTENT_TYPES = {
    ".png": "image/png",
}


def _character_sheet_response(
    sheet: Dict[str, Any],
    *,
    exists: bool = True,
    skipped: bool = False,
) -> Tuple[int, str, bytes]:
    from ..drama_schemas import CharacterSheet
    from ..schemas import model_to_dict

    data = model_to_dict(CharacterSheet(**sheet))
    return _json(200, {"exists": exists, "sheet": data, "skipped": skipped})


def _drama_characters_prereq_error(name: str, *, episode_no: int = 1) -> Optional[Tuple[int, str, bytes]]:
    from ..drama_schemas import DramaStoryboard, episode_paths, validate_storyboard_hard

    data = read_json_optional(episode_paths(name, episode_no=episode_no).storyboard_path, None)
    if not isinstance(data, dict):
        return _json(400, {"error": "station 3 must complete before station 4"})
    try:
        board = DramaStoryboard(**data)
    except Exception as exc:
        return _json(400, errors.exception_body(exc))
    hard_errors = validate_storyboard_hard(board)
    if hard_errors:
        return _json(400, {"error": "station 3 storyboard is invalid: " + ", ".join(hard_errors)})
    return None


def _drama_episode_introduces_new_characters(name: str, *, episode_no: int) -> bool:
    from ..drama_schemas import episode_paths

    setup = read_json_optional(episode_paths(name, episode_no=episode_no).setup_path, None)
    return bool(isinstance(setup, dict) and setup.get("introduces_new_characters") is True)


def api_drama_characters_get(name: str, raw_episode_no: Any = 1) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    try:
        episode_no = _parse_episode_no(raw_episode_no)
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})
    prereq = _drama_characters_prereq_error(name, episode_no=episode_no)
    if prereq:
        return prereq
    from .. import character_designer
    from ..drama_schemas import CharacterSheet, character_paths

    data = read_json_optional(character_paths(name).sheet_path, None)
    if data is None:
        return _json(200, {"exists": False, "sheet": None})
    if not isinstance(data, dict):
        return _json(500, {"error": "character sheet file must be a JSON object"})
    try:
        sheet = CharacterSheet(**data)
        introduces_new = _drama_episode_introduces_new_characters(name, episode_no=episode_no)
        if introduces_new and not character_designer.character_sheet_generated_for_episode(
            sheet, episode_no=episode_no
        ):
            return _json(
                200,
                {
                    "exists": False,
                    "sheet": None,
                    "skipped": False,
                    "needs_generation": True,
                },
            )
        skipped = episode_no > 1 and not introduces_new
        return _character_sheet_response(data, skipped=skipped)
    except Exception as exc:
        return _json(500, errors.exception_body(exc))


def api_drama_characters_generate(name: str, body: bytes) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    assert payload is not None
    try:
        episode_no = _parse_episode_no(payload.get("episode_no", 1))
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})
    return _enqueue_drama_job(name, "drama-characters", episode_no, payload)


def api_drama_characters_save(name: str, body: bytes) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    assert payload is not None
    try:
        episode_no = _parse_episode_no(payload.get("episode_no", 1))
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})
    raw = payload.get("sheet") if isinstance(payload.get("sheet"), dict) else payload
    if not isinstance(raw, dict):
        return _json(400, {"error": "character sheet must be a JSON object"})

    from .. import drama_store
    from ..drama_schemas import CharacterSheet, character_paths
    from ..schemas import model_to_dict
    from ..utils import write_json

    try:
        with _workspace_write_guard(name, "web-manual-drama-characters-save"):
            prereq = _drama_characters_prereq_error(name, episode_no=episode_no)
            if prereq:
                return prereq
            try:
                data = model_to_dict(CharacterSheet(**raw))
            except Exception as exc:
                return _json(400, errors.exception_body(exc))
            sheet_path = character_paths(name).sheet_path
            if sheet_path.is_file():
                drama_store.migrate_fresh_episode_fingerprints_v2(name)
            write_json(sheet_path, data)
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        if str(exc).startswith("workspace_not_found:"):
            return _json(404, {"error": f"workspace not found: {name}"})
        raise
    _clear_overview_cache()
    return _json(200, {"saved": True, "sheet": data})


def api_drama_character_redraw(
    name: str,
    cid: str,
    body: bytes,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    if not _CHARACTER_ID_RE.fullmatch(cid):
        return _json(400, {"error": "invalid character id"})
    content_type = str((headers or {}).get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _json(415, {"error": "Content-Type must be application/json"})
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    assert payload is not None
    try:
        episode_no = _parse_episode_no(payload.get("episode_no", 1))
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})

    from .. import ai_draw_client, drama_store
    from ..drama_schemas import CharacterSheet, character_paths
    from ..schemas import model_to_dict
    from ..utils import write_json

    try:
        with _workspace_write_guard(name, "web-manual-drama-character-redraw"):
            prereq = _drama_characters_prereq_error(name, episode_no=episode_no)
            if prereq:
                return prereq
            sheet_path = character_paths(name).sheet_path
            raw = read_json_optional(sheet_path, None)
            if not isinstance(raw, dict):
                return _json(400, {"error": "character sheet must exist before redraw"})
            try:
                sheet = CharacterSheet(**raw)
            except Exception as exc:
                return _json(400, errors.exception_body(exc))
            characters = [model_to_dict(character) for character in sheet.characters]
            target = next((character for character in characters if character.get("id") == cid), None)
            if target is None:
                return _json(404, {"error": "character not found"})
            from .. import drama_multimodal_smoke
            try:
                paid_state = drama_multimodal_smoke.load_state(name)
            except ValueError:
                return _json(409, {"error": "paid_image_state_requires_repair"})
            paid_phase = (paid_state or {}).get("phases", {}).get("all_character_images", {})
            paid_attempts = (paid_state or {}).get("image_attempts", {}).get(cid, [])
            if paid_phase.get("real") is True and any(
                row.get("status") in {"artifact_received", "succeeded"}
                for row in paid_attempts
                if isinstance(row, dict)
            ):
                return _json(409, {"error": "real_image_would_be_overwritten"})
            local_generators = {"placeholder_png", "mock-multimodal-smoke"}
            for ref in target.get("reference_images", []):
                if (
                    str(ref.get("path") or "").rsplit("/", 1)[-1] == "portrait_neutral.png"
                    and str(ref.get("generated_by") or "") not in local_generators
                ):
                    return _json(409, {"error": "real_image_would_be_overwritten"})
            try:
                image = ai_draw_client.redraw_character_reference(name, target, mock=True)
            except Exception as exc:
                _log_degraded("drama_character_redraw", exc)
                return _json(500, errors.error_body(errors.build_card("server_error")))
            refs = [
                ref
                for ref in target.get("reference_images", [])
                if not str(ref.get("path") or "").rsplit("/", 1)[-1].startswith("portrait_neutral.")
            ]
            refs.insert(0, image)
            target["reference_images"] = refs
            data = model_to_dict(CharacterSheet(**{**model_to_dict(sheet), "characters": characters}))
            drama_store.migrate_fresh_episode_fingerprints_v2(name)
            write_json(sheet_path, data)
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        if str(exc).startswith("workspace_not_found:"):
            return _json(404, {"error": f"workspace not found: {name}"})
        raise
    _clear_overview_cache()
    return _json(200, {"image": image, "sheet": data})


def api_character_ref(name: str, cid: str, filename: str) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    if not _CHARACTER_ID_RE.fullmatch(cid) or not _REF_FILENAME_RE.fullmatch(filename):
        return _json(400, {"error": "invalid character reference path"})
    from ..ai_draw_client import MAX_RESPONSE_BYTES
    suffix = Path(filename).suffix.lower()
    content_type = _CHARACTER_REF_CONTENT_TYPES.get(suffix)
    if not content_type:
        return _json(400, {"error": "unsupported character reference type"})
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        directory = getattr(os, "O_DIRECTORY", None)
        if nofollow is None or directory is None:
            raise OSError("strict no-follow access unavailable")
        workspace_parent_fd = os.open(
            str(paths.WORKSPACE_DIR), os.O_RDONLY | directory | nofollow
        )
        try:
            directory_fd = os.open(
                name,
                os.O_RDONLY | directory | nofollow,
                dir_fd=workspace_parent_fd,
            )
        finally:
            os.close(workspace_parent_fd)
        for part in ("data", "character_refs", cid):
            next_fd = os.open(
                part,
                os.O_RDONLY | directory | nofollow,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            filename,
            os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory_fd,
        )
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            raise OSError("character reference is not a regular file")
        if before.st_size > MAX_RESPONSE_BYTES:
            return _json(413, {"error": "character reference exceeds size limit"})
        chunks: List[bytes] = []
        remaining = MAX_RESPONSE_BYTES + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(file_fd)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
        if len(data) != before.st_size or identity(before) != identity(after):
            raise OSError("character reference changed while reading")
    except FileNotFoundError:
        return _json(404, {"error": "character reference not found"})
    except OSError:
        return _json(400, {"error": "invalid character reference path"})
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)
    if len(data) > MAX_RESPONSE_BYTES:
        return _json(413, {"error": "character reference exceeds size limit"})
    from ..ai_draw_client import _detect_image_type
    try:
        detected_type, _detected_suffix = _detect_image_type(data)
    except ValueError:
        return _json(400, {"error": "character reference bytes are not a supported image"})
    if detected_type != content_type:
        return _json(400, {"error": "character reference type does not match its bytes"})
    return 200, content_type, data


def _parse_episode_no(raw: Any = 1) -> int:
    from ..drama_schemas import normalize_episode_no

    return normalize_episode_no(raw)


def _drama_review_prereq_error(name: str, *, episode_no: int = 1) -> Optional[Tuple[int, str, bytes]]:
    from .. import character_designer
    from ..drama_schemas import CharacterSheet, character_paths

    prereq = _drama_characters_prereq_error(name, episode_no=episode_no)
    if prereq:
        return prereq
    data = read_json_optional(character_paths(name).sheet_path, None)
    if not isinstance(data, dict):
        return _json(400, {"error": "station 4 must complete before drama review"})
    try:
        sheet = CharacterSheet(**data)
    except Exception as exc:
        return _json(400, errors.exception_body(exc))
    if (
        _drama_episode_introduces_new_characters(name, episode_no=episode_no)
        and not character_designer.character_sheet_generated_for_episode(
            sheet, episode_no=episode_no
        )
    ):
        return _json(400, {"error": "station 4 must generate episode characters before drama review"})
    return None


def api_drama_review(name: str, body: bytes) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    assert payload is not None
    try:
        episode_no = _parse_episode_no(payload.get("episode_no", 1))
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be a positive integer"})
    return _enqueue_drama_job(name, "drama-review-assemble", episode_no, payload)


def api_drama_assemble(name: str, body: bytes) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    assert payload is not None
    try:
        episode_no = _parse_episode_no(payload.get("episode_no", 1))
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be a positive integer"})
    from .. import drama_store

    try:
        with _workspace_write_guard(name, "web-manual-drama-assemble"):
            prereq = _drama_review_prereq_error(name, episode_no=episode_no)
            if prereq:
                return prereq
            try:
                result = drama_store.assemble_episode(name, episode_no=episode_no)
            except FileNotFoundError as exc:
                return _json(400, errors.exception_body(exc))
            except ValueError as exc:
                return _json(400, errors.exception_body(exc))
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        if str(exc).startswith("workspace_not_found:"):
            return _json(404, {"error": f"workspace not found: {name}"})
        raise
    _clear_overview_cache()
    return _json(200, result)


_DRAMA_EPISODE_ARTIFACT_ATTRS = (
    "setup_path",
    "hook_candidates_path",
    "storyboard_path",
    "review_path",
    "episode_path",
    "meta_path",
)
_DRAMA_DERIVED_EXPORT_SUFFIXES = (
    ".storyboard.md",
    ".storyboard.csv",
    ".comfy.json",
)


def _valid_inherited_drama_setup(raw: Any, *, episode_no: int) -> bool:
    """Validate the intentionally partial setup used to resume episode N+1."""

    from ..drama_planner import TRACK_PINYIN
    from ..drama_schemas import DramaCoreSetup, DramaHookCandidate

    if not isinstance(raw, dict):
        return False
    identity = raw.get("episode_no")
    season = raw.get("season_no", 1)
    duration = raw.get("target_duration_seconds")
    if (
        not isinstance(identity, int)
        or isinstance(identity, bool)
        or identity != episode_no
        or not isinstance(season, int)
        or isinstance(season, bool)
        or season != 1
        or not isinstance(duration, int)
        or isinstance(duration, bool)
        or not 10 <= duration <= 600
        or not isinstance(raw.get("track"), str)
        or raw.get("track") not in TRACK_PINYIN
    ):
        return False
    for field, limit in (("title", 120), ("logline", 1200), ("episode_mainline", 2000)):
        value = raw.get(field, "")
        if not isinstance(value, str) or len(value) > limit:
            return False
    if not isinstance(raw.get("introduces_new_characters", False), bool):
        return False
    if episode_no > 1:
        if raw.get("parent_episode_no") != episode_no - 1:
            return False
        parent_revision = raw.get("parent_episode_revision")
        if (
            not isinstance(parent_revision, str)
            or re.fullmatch(r"[0-9a-f]{64}", parent_revision) is None
        ):
            return False
    try:
        core = DramaCoreSetup(**raw.get("core_setup"))
        if not core.protagonist:
            return False
        if "hook" in raw:
            DramaHookCandidate(**raw["hook"])
    except Exception:
        return False
    return True


def _drama_next_episode_state(name: str) -> Dict[str, Any]:
    """Return the single route-level continuation decision used by GET/POST."""

    from .. import drama_store
    from ..drama_schemas import DramaEpisode, DramaEpisodeMeta, episode_paths
    from ..schemas import model_to_dict
    from ..utils import sha256_data

    wizard_input = read_json_optional(
        paths.WORKSPACE_DIR / name / "data" / "wizard_input.json", None
    )
    try:
        raw_planned = wizard_input.get("episode_count") if isinstance(wizard_input, dict) else None
        if not isinstance(raw_planned, int) or isinstance(raw_planned, bool):
            raise ValueError("wizard episode_count is invalid")
        planned = _parse_episode_no(raw_planned)
    except (TypeError, ValueError) as exc:
        raise ValueError("wizard episode_count is invalid") from exc

    artifacts: Dict[int, set[str]] = {}
    for episode_no in range(1, 101):
        ep = episode_paths(name, episode_no=episode_no)
        present = {
            attr
            for attr in _DRAMA_EPISODE_ARTIFACT_ATTRS
            if getattr(ep, attr).is_file()
        }
        stem = f"episode_{episode_no:02d}"
        if any(
            (ep.episodes_dir / f"{stem}{suffix}").is_file()
            for suffix in _DRAMA_DERIVED_EXPORT_SUFFIXES
        ):
            present.add("derived_export")
        if present:
            artifacts[episode_no] = present

    episodes = drama_store.list_episodes(name)
    rows_by_no = {int(row["episode_no"]): row for row in episodes}
    contiguous_rows: List[Dict[str, Any]] = []
    blocked_reason: Optional[str] = None
    blocked_message = ""
    repair_episode_no: Optional[int] = None
    latest_is_fresh = False

    assembled_nos = sorted(
        episode_no
        for episode_no, names in artifacts.items()
        if "episode_path" in names or "meta_path" in names
    )
    expected = 1
    for episode_no in assembled_nos:
        names = artifacts[episode_no]
        if episode_no != expected:
            blocked_reason = "episode_sequence_gap"
            blocked_message = "assembled episodes must form a continuous sequence from episode 1"
            repair_episode_no = expected
            break
        if not {"episode_path", "meta_path"} <= names:
            blocked_reason = "previous_episode_incomplete"
            blocked_message = "previous episode must be fully assembled before starting the next episode"
            repair_episode_no = episode_no
            break
        ep = episode_paths(name, episode_no=episode_no)
        raw_episode = read_json_optional(ep.episode_path, None)
        raw_meta = read_json_optional(ep.meta_path, None)
        try:
            if not isinstance(raw_episode, dict) or not isinstance(raw_meta, dict):
                raise ValueError("episode and meta must be JSON objects")
            episode_model = DramaEpisode(**raw_episode)
            meta_model = DramaEpisodeMeta(**raw_meta)
        except Exception:
            blocked_reason = "previous_episode_incomplete"
            blocked_message = "previous episode artifacts are incomplete or invalid"
            repair_episode_no = episode_no
            break
        if episode_model.episode_no != episode_no or meta_model.episode_no != episode_no:
            blocked_reason = "previous_episode_artifact_mismatch"
            blocked_message = "previous episode artifact number does not match"
            repair_episode_no = episode_no
            break
        if not meta_model.input_fingerprint:
            blocked_reason = "previous_episode_fingerprint_missing"
            blocked_message = "previous episode fingerprint is missing"
            repair_episode_no = episode_no
            break
        if meta_model.episode_sha256 != sha256_data(model_to_dict(episode_model)):
            blocked_reason = "previous_episode_sha_mismatch"
            blocked_message = "previous episode content hash does not match its meta"
            repair_episode_no = episode_no
            break
        row = rows_by_no.get(episode_no)
        if row is None:
            blocked_reason = "previous_episode_incomplete"
            blocked_message = "previous episode must be fully assembled before starting the next episode"
            repair_episode_no = episode_no
            break
        contiguous_rows.append(row)
        latest_is_fresh = not bool(row.get("stale"))
        expected += 1

    latest_episode_no = len(contiguous_rows)
    candidate_next = latest_episode_no + 1
    next_episode_no: Optional[int] = candidate_next if candidate_next <= 100 else None
    next_setup: Optional[Dict[str, Any]] = None
    next_initialized = False

    if blocked_reason is None:
        later_nos = [episode_no for episode_no in artifacts if episode_no > candidate_next]
        if later_nos:
            has_assembled_gap = any(
                {"episode_path", "meta_path"} <= artifacts[episode_no]
                for episode_no in later_nos
            )
            blocked_reason = (
                "episode_sequence_gap" if has_assembled_gap else "orphan_episode_artifact"
            )
            blocked_message = (
                "episode artifacts contain a sequence gap"
                if has_assembled_gap
                else "orphan episode artifacts exist beyond the next episode"
            )
            repair_episode_no = candidate_next

    current_artifacts = (
        artifacts.get(candidate_next, set()) if candidate_next <= 100 else set()
    )
    if candidate_next <= 100 and "setup_path" in current_artifacts:
        raw_setup = read_json_optional(
            episode_paths(name, episode_no=candidate_next).setup_path, None
        )
        if _valid_inherited_drama_setup(raw_setup, episode_no=candidate_next):
            next_setup = raw_setup
            next_initialized = True
        if not next_initialized and blocked_reason is None:
            blocked_reason = "next_episode_setup_invalid"
            blocked_message = "next episode setup is invalid and cannot be resumed"
            repair_episode_no = candidate_next
        elif (
            next_initialized
            and "derived_export" in current_artifacts
            and "episode_path" not in current_artifacts
            and blocked_reason is None
        ):
            blocked_reason = "orphan_episode_artifact"
            blocked_message = "next episode has a derived export without an assembled episode"
            repair_episode_no = candidate_next
    elif current_artifacts and blocked_reason is None:
        blocked_reason = "orphan_episode_artifact"
        blocked_message = "next episode artifacts exist without a valid setup"

    if blocked_reason is None and latest_episode_no >= planned:
        blocked_reason = "planned_episode_count_reached"
        blocked_message = "planned episode_count has been reached"
    elif blocked_reason is None and latest_episode_no > 0 and not latest_is_fresh:
        blocked_reason = "previous_episode_stale"
        blocked_message = "previous episode is stale; review and assemble it again first"
        repair_episode_no = latest_episode_no

    can_start_next = (
        latest_episode_no > 0
        and candidate_next <= planned
        and candidate_next <= 100
        and blocked_reason is None
    )
    broken_prefix_reasons = {
        "episode_sequence_gap",
        "previous_episode_incomplete",
        "previous_episode_artifact_mismatch",
        "previous_episode_fingerprint_missing",
        "previous_episode_sha_mismatch",
    }
    return {
        "episodes": contiguous_rows if blocked_reason in broken_prefix_reasons else episodes,
        "planned_episode_count": planned,
        "next_episode_no": next_episode_no,
        "next_episode_initialized": next_initialized,
        "next_episode_blocked_reason": blocked_reason,
        "next_episode_blocked_message": blocked_message,
        "next_episode_repair_no": repair_episode_no,
        "can_start_next": can_start_next,
        "_next_setup": next_setup,
        "_latest_episode_no": latest_episode_no,
    }


def api_drama_episodes(name: str) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    from .. import drama_season_export

    try:
        state = _drama_next_episode_state(name)
        season_export = drama_season_export.public_season_export_readiness(
            name, season_no=1
        )
    except ValueError as exc:
        return _json(400, errors.exception_body(exc))
    public_state = {
        key: value for key, value in state.items() if not key.startswith("_")
    }
    return _json(
        200,
        {
            **public_state,
            "season_export": season_export,
        },
    )


def api_drama_next_episode(name: str, body: bytes) -> Tuple[int, str, bytes]:
    """Initialize episode N+1 by inheriting the previous setup, with no LLM."""

    error = _drama_endpoint_error(name)
    if error:
        return error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    assert payload is not None
    try:
        after_episode_no = _parse_episode_no(payload.get("after_episode_no", 1))
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})
    from .. import drama_planner
    from ..drama_schemas import episode_paths
    from ..utils import write_json

    try:
        with _workspace_write_guard(name, "web-manual-drama-next-episode"):
            try:
                state = _drama_next_episode_state(name)
            except (FileNotFoundError, ValueError) as exc:
                return _json(400, errors.exception_body(exc))
            blocked_reason = state.get("next_episode_blocked_reason")
            if blocked_reason:
                status = 400 if blocked_reason in {
                    "previous_episode_incomplete",
                    "planned_episode_count_reached",
                } else 409
                return _json(
                    status,
                    {
                        "error": state.get("next_episode_blocked_message")
                        or "next episode is blocked",
                        "code": blocked_reason,
                    },
                )
            if state.get("_latest_episode_no") != after_episode_no:
                return _json(
                    409,
                    {
                        "error": "after_episode_no must reference the latest continuous episode",
                        "code": "after_episode_mismatch",
                    },
                )
            try:
                episode_no = _parse_episode_no(state.get("next_episode_no"))
            except (TypeError, ValueError):
                return _json(
                    400,
                    {
                        "error": "episode limit has been reached",
                        "code": "episode_limit_reached",
                    },
                )
            if not state.get("can_start_next"):
                return _json(
                    409,
                    {
                        "error": "next episode cannot be initialized",
                        "code": "next_episode_blocked",
                    },
                )
            current = episode_paths(name, episode_no=episode_no)
            setup = state.get("_next_setup")
            if isinstance(setup, dict):
                created = False
            else:
                setup = drama_planner.run(name, mock=True, episode_no=episode_no)
                setup["introduces_new_characters"] = False
                setup.setdefault("episode_mainline", "")
                write_json(current.setup_path, setup)
                created = True
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        if str(exc).startswith("workspace_not_found:"):
            return _json(404, {"error": f"workspace not found: {name}"})
        raise
    _clear_overview_cache()
    return _json(
        200,
        {
            "episode_no": episode_no,
            "created": created,
            "setup": setup,
            "write_url": f"/w/{name}/write?episode={episode_no}",
        },
    )


def api_drama_episode_detail(name: str, episode: str) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    try:
        episode_no = _parse_episode_no(episode)
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be a positive integer"})
    from .. import drama_store

    try:
        return _json(200, drama_store.episode_detail(name, episode_no=episode_no))
    except FileNotFoundError as exc:
        return _json(404, errors.exception_body(exc))
    except ValueError as exc:
        return _json(400, errors.exception_body(exc))


def _validated_drama_video_params(payload: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    from .. import drama_video

    unknown = set(payload) - {
        "episode_no", "confirm_real_video", "resume_submitted",
        "budget_cny", "timeout_minutes",
    }
    if unknown:
        return f"unknown drama video params: {', '.join(sorted(unknown))}", {}
    try:
        episode_no = _parse_episode_no(payload.get("episode_no", 1))
    except (TypeError, ValueError):
        return "episode_no must be 1 for the video MVP", {}
    if episode_no != 1:
        return "episode_no must be 1 for the video MVP", {}
    if "confirm_real_video" in payload and not isinstance(payload.get("confirm_real_video"), bool):
        return "confirm_real_video must be boolean", {}
    if "resume_submitted" in payload and not isinstance(payload.get("resume_submitted"), bool):
        return "resume_submitted must be boolean", {}
    out: Dict[str, Any] = {"episode_no": 1}
    if payload.get("resume_submitted") is True and not drama_video.real_video_enabled():
        return "restore real video provider configuration before resuming the submitted task", {}
    if drama_video.real_video_enabled():
        if payload.get("resume_submitted") is True:
            out["resume_submitted"] = True
            return None, out
        if payload.get("confirm_real_video") is not True:
            return "confirm_real_video=true is required for real video generation", {}
        for key, maximum in (("budget_cny", 1_000_000.0), ("timeout_minutes", 60.0)):
            error, value = _float_param(payload, key, 0.0, minimum=0.0, maximum=maximum)
            if error:
                return error, {}
            if value <= 0:
                return f"{key} must be finite and positive for real video generation", {}
            out[key] = value
        out["confirm_real_video"] = True
        # Independent last-hop estimate gate, still before job/network.
        try:
            drama_video.validate_real_video_gate(out)
        except (PermissionError, ValueError) as exc:
            return str(exc), {}
    return None, out


def api_drama_video_generate(name: str, body: bytes) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    assert payload is not None
    params_error, params = _validated_drama_video_params(payload)
    if params_error:
        return _json(400, {"error": params_error})
    try:
        from .. import drama_video

        drama_video.load_video_inputs(name, episode_no=1)
        if params.get("resume_submitted") is True:
            submission = drama_video.read_video_submission(name)
            if submission is None or submission.get("status") != "submitted":
                return _json(409, {"error": "no submitted video task is available to resume"})
        job = jobs.start_job(name, "drama-video", params)
    except (FileNotFoundError, ValueError) as exc:
        return _json(400, errors.exception_body(exc))
    except RuntimeError as exc:
        msg = str(exc)
        if msg.startswith("workspace_busy:"):
            return _json(409, {"error": "workspace already has a running job", "running_job_id": msg.split(":", 1)[1]})
        raise
    return _json(202, {"job_id": job["job_id"], "status": job["status"], "step": "drama-video"})


def api_drama_video_status(name: str) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    from .. import drama_video

    status = drama_video.video_status(name, episode_no=1)
    status["real_mode"] = drama_video.real_video_enabled()
    status["fixed_spec"] = {"duration_seconds": 5, "ratio": "9:16", "resolution": "720p"}
    if status["real_mode"]:
        try:
            estimate = float(str(os.getenv("SD_VIDEO_ESTIMATED_COST_CNY") or ""))
        except (TypeError, ValueError):
            estimate = 0.0
        status["estimated_cost_cny"] = estimate if math.isfinite(estimate) and estimate > 0 else None
    active = next((job for job in jobs.active_jobs(name) if job.get("step") == "drama-video"), None)
    if active is not None:
        status["state"] = str(active.get("current_step") or active.get("status") or "pending")
        status["job"] = jobs.public_job_detail_view(active)
    else:
        recent = next((job for job in jobs.recent_jobs(name, limit=20) if job.get("step") == "drama-video"), None)
        if recent is not None and recent.get("status") not in {"succeeded"}:
            recent_state = str(recent.get("status") or "failed")
            if recent_state == "aborted":
                recent_state = "timeout" if recent.get("current_step") == "timeout" else "cancelled"
            if status.get("state") not in {
                "succeeded", "budget_exceeded", "submitted", "submission_unknown",
            }:
                status["state"] = recent_state
            status["latest_attempt_state"] = recent_state
            status["job"] = jobs.public_job_detail_view(recent)
    return _json(200, status)


def api_drama_multimodal_status(name: str) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    from ..drama_multimodal_smoke import public_status
    return _json(200, public_status(name))


def api_drama_video_file(name: str) -> WebResponse:
    error = _drama_endpoint_error(name)
    if error:
        return error
    from .. import drama_video

    try:
        data, _meta = drama_video.read_video(name, episode_no=1)
    except FileNotFoundError as exc:
        return _json(404, errors.exception_body(exc))
    except ValueError as exc:
        return _json(409, errors.exception_body(exc))
    return (
        200,
        "video/mp4",
        data,
        {
            "Content-Disposition": 'inline; filename="episode_01.video.mp4"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


def api_drama_video_public_asset(token: str) -> WebResponse:
    """Tokenized media path intentionally outside bearer-gated /api."""
    from .. import drama_video

    try:
        data, content_type = drama_video.read_public_asset(token)
    except (FileNotFoundError, ValueError):
        return _json(404, {"error": "media not found"})
    return (
        200,
        content_type,
        data,
        {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


_DOWNLOAD_FILENAME_RE = re.compile(
    r"^episode_\d{2,3}(?:\.json|\.storyboard\.(?:md|csv)|\.comfy\.json)$"
)


def api_drama_episode_export(name: str, episode: str, export_format: Any) -> WebResponse:
    error = _drama_endpoint_error(name)
    if error:
        return error
    try:
        episode_no = _parse_episode_no(episode)
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be an integer between 1 and 100"})
    if not isinstance(export_format, str) or export_format not in {"json", "md", "csv", "comfy"}:
        return _json(400, {"error": "format must be one of: json, md, csv, comfy"})
    from .. import drama_store

    try:
        with _workspace_write_guard(name, "web-manual-drama-export"):
            artifact = drama_store.export_episode(name, episode_no=episode_no, format=export_format)
    except FileNotFoundError as exc:
        return _json(404, errors.exception_body(exc))
    except ValueError as exc:
        return _json(400, errors.exception_body(exc))
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        if str(exc).startswith("workspace_not_found:"):
            return _json(404, {"error": f"workspace not found: {name}"})
        raise
    filename = str(artifact.filename)
    if not _DOWNLOAD_FILENAME_RE.fullmatch(filename):
        _log_degraded("drama_export_filename", ValueError("unsafe generated export filename"))
        return _json(500, errors.error_body(errors.build_card("server_error")))
    return (
        200,
        str(artifact.content_type),
        bytes(artifact.body),
        {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


def api_drama_season_export(name: str, season: str, mode: Any) -> WebResponse:
    error = _drama_endpoint_error(name)
    if error:
        return error
    if season != "1":
        return _json(400, {"error": "season_no must be 1"})
    if not isinstance(mode, str) or mode not in {"master", "snapshot"}:
        return _json(400, {"error": "mode must be one of: master, snapshot"})

    from .. import drama_season_export

    try:
        with _workspace_write_guard(name, "web-manual-drama-season-export"):
            artifact = drama_season_export.export_season(
                name, season_no=1, mode=mode
            )
    except drama_season_export.SeasonExportConflict as exc:
        return _json(409, {"error": str(exc), "code": exc.code})
    except (FileNotFoundError, ValueError) as exc:
        return _json(400, errors.exception_body(exc))
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        if str(exc).startswith("workspace_not_found:"):
            return _json(404, {"error": f"workspace not found: {name}"})
        raise

    filename = str(artifact.filename)
    if not re.fullmatch(r"season_01_(?:master|snapshot)\.zip", filename):
        _log_degraded(
            "drama_season_export_filename",
            ValueError("unsafe generated season export filename"),
        )
        return _json(500, errors.error_body(errors.build_card("server_error")))
    return (
        200,
        "application/zip",
        bytes(artifact.body),
        {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


def api_drama_apply_suggestion(name: str, body: bytes) -> Tuple[int, str, bytes]:
    error = _drama_endpoint_error(name)
    if error:
        return error
    payload, parse_error = _parse_json_object_body(body)
    if parse_error:
        return parse_error
    assert payload is not None
    suggestion = payload.get("suggestion") if isinstance(payload.get("suggestion"), dict) else payload
    if not isinstance(suggestion, dict):
        return _json(400, {"error": "suggestion must be a JSON object"})
    try:
        episode_no = _parse_episode_no(payload.get("episode_no", 1))
    except (TypeError, ValueError):
        return _json(400, {"error": "episode_no must be a positive integer"})

    from ..drama_schemas import AdvisorSuggestion

    try:
        item = AdvisorSuggestion(**suggestion)
    except Exception as exc:
        return _json(400, errors.exception_body(exc))
    try:
        with _workspace_write_guard(name, "web-manual-drama-apply-suggestion"):
            result = _apply_drama_suggestion(name, item.model_dump() if hasattr(item, "model_dump") else item.dict(), episode_no=episode_no)
    except RuntimeError as exc:
        conflict = _write_conflict_response(exc)
        if conflict:
            return conflict
        if str(exc).startswith("workspace_not_found:"):
            return _json(404, {"error": f"workspace not found: {name}"})
        raise
    except (FileNotFoundError, ValueError) as exc:
        return _json(400, errors.exception_body(exc))
    _clear_overview_cache()
    return _json(200, {"applied": True, **result})


def _apply_drama_suggestion(name: str, suggestion: Dict[str, Any], *, episode_no: int = 1) -> Dict[str, Any]:
    from .. import drama_store
    from ..drama_schemas import CharacterSheet, DramaStoryboard, episode_paths, character_paths, normalize_storyboard_payload
    from ..schemas import model_to_dict
    from ..utils import write_json

    station = suggestion.get("station")
    field = str(suggestion.get("field") or "")
    new_value = str(suggestion.get("new_value") or "")
    if not field and station != "storyboard":
        raise ValueError("suggestion.field is required")
    if station in ("setup", "hook"):
        path = episode_paths(name, episode_no=episode_no).setup_path
        data = read_json_optional(path, None)
        if not isinstance(data, dict):
            raise FileNotFoundError("station 1/2 setup file is missing")
        if station == "hook":
            hook = data.setdefault("hook", {})
            if not isinstance(hook, dict):
                hook = {}
                data["hook"] = hook
            hook[field or "content"] = new_value
        else:
            if field == "logline":
                data["logline"] = new_value
            else:
                core = data.setdefault("core_setup", {})
                if not isinstance(core, dict):
                    core = {}
                    data["core_setup"] = core
                core[field] = new_value
        write_json(path, data)
        return {"station": station, "target": field}
    if station == "storyboard":
        path = episode_paths(name, episode_no=episode_no).storyboard_path
        data = read_json_optional(path, None)
        if not isinstance(data, dict):
            raise FileNotFoundError("station 3 storyboard file is missing")
        raw_shot_no = suggestion.get("shot_no")
        if isinstance(raw_shot_no, bool):
            raise ValueError("shot_no must be a positive integer")
        shot_no = int(raw_shot_no or 0)
        if shot_no < 1:
            raise ValueError("shot_no must be a positive integer")
        shots = data.get("shots")
        if not isinstance(shots, list) or shot_no > len(shots) or not isinstance(shots[shot_no - 1], dict):
            raise ValueError("shot_no out of range")
        target_field = field or "visual"
        if target_field not in {"beat", "visual", "narration", "dialogue", "ai_draw_prompt"}:
            raise ValueError("unsupported storyboard suggestion field")
        shots[shot_no - 1][target_field] = new_value
        board = DramaStoryboard(**normalize_storyboard_payload(data))
        result = model_to_dict(board)
        write_json(path, result)
        return {"station": station, "target": f"shot:{shot_no}:{target_field}"}
    if station == "characters":
        path = character_paths(name).sheet_path
        data = read_json_optional(path, None)
        if not isinstance(data, dict):
            raise FileNotFoundError("station 4 character sheet is missing")
        cid = str(suggestion.get("character_id") or "c001")
        rows = data.get("characters")
        if not isinstance(rows, list):
            raise ValueError("character sheet must contain characters")
        target = next((row for row in rows if isinstance(row, dict) and row.get("id") == cid), None)
        if target is None:
            raise ValueError("character_id not found")
        if field not in {"name", "role", "wardrobe_default", "visual_signature", "prompt_template_sd"}:
            raise ValueError("unsupported character suggestion field")
        target[field] = new_value
        result = model_to_dict(CharacterSheet(**data))
        drama_store.migrate_fresh_episode_fingerprints_v2(name)
        write_json(path, result)
        return {"station": station, "target": f"{cid}:{field}"}
    raise ValueError("unsupported suggestion station")


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
    with use_workspace(name):
        result = _safe_readiness(chapters=chapters, resume_from=resume_from, replan_every=replan_every)
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
    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
    n = max(1, min(n, 1000))
    with use_workspace(name):
        log_path = paths.llm_calls_log_path()
        # This endpoint feeds the ordinary desktop task page.  Keep raw
        # provider errors and request fingerprints in the local audit log,
        # but never project them into the browser: provider messages may
        # contain upstream URLs or other operational details that are neither
        # useful nor appropriate in the normal user interface.
        lines = [_public_llm_call_view(row) for row in _tail_jsonl(log_path, n)]
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
    error = _workspace_error(name)
    if error:
        return error
    with use_workspace(name):
        drafts = [_draft_summary(path) for path in sorted(paths.drafts_dir().glob("chapter_*.md"))]
    return _json(200, {"drafts": [item for item in drafts if item]})


def api_workspace_draft(name: str, chapter: str, variant: str = "") -> Tuple[int, str, bytes]:
    error = _workspace_error(name)
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
    with use_workspace(name):
        filename = f"chapter_{chapter_no:02d}.partial.md" if variant == "partial" else f"chapter_{chapter_no:02d}.md"
        md_path = paths.drafts_dir() / filename
        if not md_path.exists():
            return _json(404, {"error": f"draft not found: {filename}"})
        text = md_path.read_text(encoding="utf-8", errors="replace")
        if variant == "partial":
            meta = read_json_optional(paths.drafts_dir() / f"chapter_{chapter_no:02d}.failure.json", {})
            review = {}
        else:
            meta = read_json_optional(paths.drafts_dir() / f"chapter_{chapter_no:02d}.meta.json", {})
            review = read_json_optional(paths.reviews_dir() / f"chapter_{chapter_no:02d}.review.json", {})
        # iter076（codex 审查低风险项 + 审查 B L1）：path 类字段相对化投影——meta
        # 只浅拷贝改投影字段，磁盘上的 meta.json 原样不动。必须在 use_workspace
        # 块**内**做：_ws_relative 依赖线程上下文的 workspace_root()，出块后对
        # 非当前 workspace 的书会 relative_to 失败而原样返回绝对路径（泄露复活）。
        meta_out = dict(meta) if isinstance(meta, dict) else {}
        for key in ("snapshot_path", "failure_path"):
            if meta_out.get(key):
                meta_out[key] = _ws_relative(meta_out[key])
        payload = {
            "chapter": chapter_no,
            "variant": variant or "final",
            "path": _ws_relative(str(md_path)),
            "content": text,
            "meta": meta_out,
            "review": review if isinstance(review, dict) else {},
        }
    return _json(200, payload)


def api_workspace_chapter_versions(name: str, chapter: str) -> Tuple[int, str, bytes]:
    """GET /api/workspace/<name>/chapter/<n>/versions — list a chapter's
    on-disk versions (current draft + retry snapshots) for the diff picker
    (iter 074)."""
    error = _workspace_error(name)
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
    error = _workspace_error(name)
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
    error = _workspace_error(name)
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


def _draft_summary(path: Path) -> Optional[Dict[str, Any]]:
    match = re.match(r"chapter_(\d+)(\.partial)?\.md$", path.name)
    if not match:
        return None
    chapter_no = int(match.group(1))
    is_partial = bool(match.group(2))
    if is_partial:
        failure = read_json_optional(path.parent / f"chapter_{chapter_no:02d}.failure.json", {})
        return {
            "chapter": chapter_no,
            "variant": "partial",
            "path": _ws_relative(str(path)),
            "chars": len(path.read_text(encoding="utf-8", errors="replace")),
            "verdict": "failure",
            "needs_human_review": True,
            "rewrite_count": None,
            "review_verdict": None,
            "failure_stage": failure.get("stage") if isinstance(failure, dict) else None,
            "failure_error": failure.get("last_error") if isinstance(failure, dict) else None,
        }
    meta = read_json_optional(path.with_suffix(".meta.json"), {})
    review = read_json_optional(path.parent.parent / "reviews" / f"chapter_{chapter_no:02d}.review.json", {})
    return {
        "chapter": chapter_no,
        "variant": "final",
        "path": _ws_relative(str(path)),
        "chars": len(path.read_text(encoding="utf-8", errors="replace")),
        "verdict": meta.get("verdict") if isinstance(meta, dict) else None,
        "needs_human_review": bool(meta.get("needs_human_review")) if isinstance(meta, dict) else False,
        "rewrite_count": meta.get("rewrite_count") if isinstance(meta, dict) else None,
        "review_verdict": review.get("verdict") if isinstance(review, dict) else None,
        "snapshot_path": _ws_relative(meta.get("snapshot_path")) if isinstance(meta, dict) else None,
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


def api_wizard_drama_start(body: bytes, headers: Dict[str, str]) -> Tuple[int, str, bytes]:
    """POST /api/wizard/drama-start — create an empty drama workspace."""

    content_type = headers.get("content-type", "")
    return wizard.start_drama_workspace(body, content_type)


def api_wizard_premise_start(body: bytes, headers: Dict[str, str]) -> Tuple[int, str, bytes]:
    """POST /api/wizard/premise-start — create a novel workspace from a
    one-sentence premise (iter 048a). Starts no job; the four-stage
    workbench drives prepare-greenfield / debate / plan / write."""

    content_type = headers.get("content-type", "")
    return wizard.start_premise_workspace(body, content_type)


def api_diag_models() -> Tuple[int, str, bytes]:
    """GET /api/diag/models — model-key connectivity matrix (iter 048a).

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

    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    if not _workspace_exists(name):
        return _json(404, {"error": f"workspace not found: {name}"})
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
    if step == "drama-compose":
        return _json(400, {
            "error": "use the dedicated local compose endpoint",
        })
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return _json(400, {"error": "'params' must be an object"})
    workspace_type = _meta_read(name).get("type")
    is_drama_step = step in _DRAMA_JOB_STEPS
    if is_drama_step:
        return _json(400, {
            "error": "use the dedicated drama endpoint",
            "hint": "短剧任务必须从对应创作站或生产页发起",
        })
    if workspace_type == "drama" and not is_drama_step:
        return _json(400, {
            "error": "drama workspace only accepts drama job steps",
            "hint": "drama 模块已可用，请使用短剧写作页的站点操作",
        })
    if workspace_type != "drama" and is_drama_step:
        return _json(400, {"error": "drama job step requires a drama workspace"})
    params_error, params = _validated_run_params(step, params)
    if params_error:
        return _json(400, {"error": params_error})
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
        raise
    return _json(202, {"job_id": job["job_id"], "status": job["status"], "step": step})


def _validated_run_params(step: str, params: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    if step == "drama-compose":
        return _validated_drama_compose_params(params)
    if step in _DRAMA_STEP_TASKS:
        return _validated_drama_params(step, params)
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
        return error, out
    if step == "plan-chapters":
        error, out = _validate_plan_chapters_params(params)
        return error, out
    if step in ("prepare-greenfield", "rebuild-for-start"):
        error, out = _validate_prepare_params(step, params)
        return error, out
    return None, params


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

    if not _validate_workspace_name(name):
        return _json(400, {"error": "invalid workspace name"})
    job = jobs.get_job(job_id)
    if job is None:
        return _json(404, {"error": "job not found"})
    if job.get("workspace") != name:
        # Don't leak existence of a job belonging to another workspace.
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
    job = jobs.get_job(job_id)
    if job is None or job.get("workspace") != name:
        return _json(404, {"error": "job not found"})
    status = str(job.get("status") or "")
    if status not in {"pending", "running"}:
        return _json(409, {"error": "job is not cancellable", "status": status})
    snapshot = jobs.request_cancel(job_id)
    if snapshot is None:
        latest = jobs.get_job(job_id)
        return _json(
            409,
            {
                "error": "job is not cancellable",
                "status": (latest or job).get("status"),
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


# (method, compiled regex, handler). Named groups in the regex become
# kwargs passed to the handler.
_ROUTES: List[Tuple[str, "re.Pattern[str]", Handler]] = [
    ("GET", re.compile(r"^/$"), lambda **_: render_landing()),
    ("GET", re.compile(r"^/library/?$"), lambda **_: render_index()),
    ("GET", re.compile(r"^/trash/?$"), lambda **_: render_trash_page()),
    ("GET", re.compile(r"^/static/app\.css$"), lambda **_: render_static_css()),
    ("GET", re.compile(r"^/static/app\.js$"), lambda **_: render_static_js()),
    ("GET", re.compile(r"^/static/wizard\.js$"), lambda **_: render_static_wizard_js()),
    (
        "GET",
        re.compile(r"^/media/drama-assets/(?P<token>[A-Za-z0-9_-]{32,64})$"),
        lambda token, **_: api_drama_video_public_asset(token),
    ),
    # Legacy /workspace/<name> → 301 to /w/<name>/
    ("GET", re.compile(r"^/workspace/(?P<name>[^/]+)/?$"), lambda name, **_: render_workspace_redirect(name)),
    # Workspace-scoped IA
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/?$"), lambda name, **_: render_workspace_overview(name)),
    (
        "GET",
        re.compile(r"^/w/(?P<name>[^/]+)/write/?$"),
        lambda name, _query=None, **_: render_workspace_write_page(
            name,
            ((_query or {}).get("episode", ["1"])[0]),
        ),
    ),
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/characters/?$"), lambda name, **_: render_workspace_characters_page(name)),
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/production/?$"), lambda name, **_: render_workspace_production_page(name)),
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/assets/?$"), lambda name, **_: render_workspace_assets_page(name)),
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/shot-images/?$"), lambda name, **_: render_workspace_shot_images_page(name)),
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/shot-videos/?$"), lambda name, **_: render_workspace_shot_videos_page(name)),
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/compose/?$"), lambda name, **_: render_workspace_compose_page(name)),
    ("GET", re.compile(r"^/w/(?P<name>[^/]+)/episodes/?$"), lambda name, **_: render_workspace_episodes_page(name)),
    (
        "GET",
        re.compile(r"^/w/(?P<name>[^/]+)/episode/(?P<episode>[^/]+)/?$"),
        lambda name, episode, **_: render_workspace_episode_detail_page(name, episode),
    ),
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
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/delete/?$"),
        lambda name, _body=b"", **_: api_workspace_delete(name, _body),
    ),
    ("GET", re.compile(r"^/api/trash/?$"), lambda **_: api_trash_list()),
    (
        "POST",
        re.compile(r"^/api/trash/(?P<entry>[^/]+)/restore/?$"),
        lambda entry, **_: api_trash_restore(entry),
    ),
    (
        "POST",
        re.compile(r"^/api/trash/(?P<entry>[^/]+)/purge/?$"),
        lambda entry, _body=b"", **_: api_trash_purge(entry, _body),
    ),
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
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/plan/?$"), lambda name, **_: api_workspace_plan(name)),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/workbench/?$"), lambda name, **_: api_workbench_status(name)),
    (
        "PUT",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/outline/?$"),
        lambda name, _body=b"", **_: api_workspace_outline_save(name, _body),
    ),
    # iter 050: structured per-chapter plan edit (workbench stage ③)
    (
        "PUT",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/chapter-plan/(?P<chapter>\d+)/?$"),
        lambda name, chapter, _body=b"", **_: api_workspace_chapter_plan_save(name, chapter, _body),
    ),
    # iter 050 (B1/B3): draft + KB + entity_graph edit surfaces
    (
        "PUT",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/draft/(?P<chapter>\d+)/?$"),
        lambda name, chapter, _body=b"", **_: api_workspace_draft_save(name, chapter, _body),
    ),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/kb/?$"), lambda name, **_: api_workspace_kb_get(name)),
    (
        "PUT",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/kb/?$"),
        lambda name, _body=b"", **_: api_workspace_kb_save(name, _body),
    ),
    # iter 051a: premise expansion view + edit (workbench stage ①)
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/premise-expansion/?$"),
        lambda name, **_: api_workspace_premise_expansion_get(name),
    ),
    (
        "PUT",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/premise-expansion/?$"),
        lambda name, _body=b"", **_: api_workspace_premise_expansion_save(name, _body),
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
    (
        "PUT",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/writer-style/?$"),
        lambda name, _body=b"", **_: api_workspace_writer_style_save(name, _body),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/writer-style/activate/?$"),
        lambda name, _body=b"", **_: api_workspace_writer_style_activate(name, _body),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/writer-style/extract/?$"),
        lambda name, _body=b"", _headers=None, **_: api_workspace_writer_style_extract(name, _body, _headers or {}),
    ),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/entity-graph/?$"), lambda name, **_: api_workspace_entity_graph(name)),
    (
        "PUT",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/entity/(?P<entity_id>[^/]+)/?$"),
        lambda name, entity_id, _body=b"", **_: api_workspace_entity_save(name, entity_id, _body),
    ),
    (
        "PUT",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/relationship/(?P<index>\d+)/?$"),
        lambda name, index, _body=b"", **_: api_workspace_relationship_save(name, index, _body),
    ),
    ("GET", re.compile(r"^/api/workspace/(?P<name>[^/]+)/insights/?$"), lambda name, **_: api_workspace_insights(name)),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/progress/?$"),
        lambda name, _query=None, **_: api_drama_progress(
            name,
            ((_query or {}).get("episode_no", ["1"])[0]),
        ),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/plan/?$"),
        lambda name, _body=b"", **_: api_drama_plan(name, _body),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/hooks/?$"),
        lambda name, _body=b"", **_: api_drama_hooks(name, _body),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/hook-candidates/?$"),
        lambda name, _query=None, **_: api_drama_hook_candidates(
            name, ((_query or {}).get("episode_no", ["1"])[0])
        ),
    ),
    (
        "PUT",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/setup/?$"),
        lambda name, _body=b"", **_: api_drama_setup_save(name, _body),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/storyboard/?$"),
        lambda name, _query=None, **_: api_drama_storyboard_get(
            name,
            ((_query or {}).get("episode_no", ["1"])[0]),
        ),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/storyboard/?$"),
        lambda name, _body=b"", **_: api_drama_storyboard_generate(name, _body),
    ),
    (
        "PUT",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/storyboard/?$"),
        lambda name, _body=b"", **_: api_drama_storyboard_save(name, _body),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/storyboard/rewrite-shot/?$"),
        lambda name, _body=b"", **_: api_drama_storyboard_rewrite_shot(name, _body),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/characters/?$"),
        lambda name, _query=None, **_: api_drama_characters_get(
            name,
            ((_query or {}).get("episode_no", ["1"])[0]),
        ),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/characters/?$"),
        lambda name, _body=b"", **_: api_drama_characters_generate(name, _body),
    ),
    (
        "PUT",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/characters/?$"),
        lambda name, _body=b"", **_: api_drama_characters_save(name, _body),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/characters/(?P<cid>[^/]+)/redraw/?$"),
        lambda name, cid, _body=b"", _headers=None, **_: api_drama_character_redraw(
            name, cid, _body, _headers or {}
        ),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/production/?$"),
        lambda name, _query=None, **_: api_drama_production_get(
            name,
            ((_query or {}).get("episode_no", ["1"])[0]),
        ),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/production/local-demo/?$"),
        lambda name, _body=b"", **_: api_drama_production_local_demo(name, _body),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/assets/?$"),
        lambda name, _query=None, **_: api_drama_assets_get(
            name,
            ((_query or {}).get("season_no", ["1"])[0]),
            ((_query or {}).get("episode_no", ["1"])[0]),
        ),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/assets/select/?$"),
        lambda name, _body=b"", _headers=None, **_: api_drama_assets_select(
            name,
            _body,
            _headers or {},
        ),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/assets/status/?$"),
        lambda name, _body=b"", _headers=None, **_: api_drama_assets_status(
            name,
            _body,
            _headers or {},
        ),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/assets/art-direction-scope/?$"),
        lambda name, _body=b"", _headers=None, **_: api_drama_art_direction_scope(
            name,
            _body,
            _headers or {},
        ),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/shot-images/?$"),
        lambda name, _query=None, **_: api_drama_shot_images_get(
            name,
            ((_query or {}).get("episode_no", ["1"])[0]),
        ),
    ),
    (
        "GET",
        re.compile(
            r"^/api/workspace/(?P<name>[^/]+)/drama/shot-images/"
            r"(?P<raw_episode_no>[0-9]{1,3})/"
            r"(?P<shot_id>shot_[0-9a-f]{24})/"
            r"(?P<candidate_id>sic_[0-9a-f]{24})\.png$"
        ),
        lambda name, raw_episode_no, shot_id, candidate_id, **_: (
            api_drama_shot_image_candidate_png(
                name,
                raw_episode_no,
                shot_id,
                candidate_id,
            )
        ),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/shot-images/select/?$"),
        lambda name, _body=b"", _headers=None, **_: api_drama_shot_images_select(
            name,
            _body,
            _headers or {},
        ),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/shot-videos/?$"),
        lambda name, _query=None, **_: api_drama_shot_videos_get(
            name,
            ((_query or {}).get("episode_no", ["1"])[0]),
        ),
    ),
    (
        "GET",
        re.compile(
            r"^/api/workspace/(?P<name>[^/]+)/drama/shot-videos/"
            r"(?P<raw_episode_no>[0-9]{1,3})/"
            r"(?P<shot_id>shot_[0-9a-f]{24})/"
            r"(?P<candidate_id>svc_[0-9a-f]{24})\.mp4$"
        ),
        lambda name, raw_episode_no, shot_id, candidate_id, _headers=None, **_: (
            api_drama_shot_video_candidate_mp4(
                name,
                raw_episode_no,
                shot_id,
                candidate_id,
                _headers or {},
            )
        ),
    ),
    (
        "HEAD",
        re.compile(
            r"^/api/workspace/(?P<name>[^/]+)/drama/shot-videos/"
            r"(?P<raw_episode_no>[0-9]{1,3})/"
            r"(?P<shot_id>shot_[0-9a-f]{24})/"
            r"(?P<candidate_id>svc_[0-9a-f]{24})\.mp4$"
        ),
        lambda name, raw_episode_no, shot_id, candidate_id, _headers=None, **_: (
            api_drama_shot_video_candidate_mp4(
                name,
                raw_episode_no,
                shot_id,
                candidate_id,
                _headers or {},
                head_only=True,
            )
        ),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/shot-videos/select/?$"),
        lambda name, _body=b"", _headers=None, **_: api_drama_shot_videos_select(
            name,
            _body,
            _headers or {},
        ),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/compose/?$"),
        lambda name, _query=None, **_: api_drama_compose_overview(
            name,
            ((_query or {}).get("episode_no", ["1"])[0]),
        ),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/compose/?$"),
        lambda name, _body=b"", _headers=None, **_: api_drama_compose_start(
            name, _body, _headers or {}
        ),
    ),
    (
        "GET",
        re.compile(
            r"^/api/workspace/(?P<name>[^/]+)/drama/compose/"
            r"(?P<raw_episode_no>[0-9]{1,3})/"
            r"(?P<timeline_fingerprint>[0-9a-f]{64})/"
            r"(?P<kind>mp4|srt|ass|edit)$"
        ),
        lambda name, raw_episode_no, timeline_fingerprint, kind,
        _headers=None, **_: api_drama_compose_deliverable(
            name,
            raw_episode_no,
            timeline_fingerprint,
            kind,
            _headers or {},
        ),
    ),
    (
        "HEAD",
        re.compile(
            r"^/api/workspace/(?P<name>[^/]+)/drama/compose/"
            r"(?P<raw_episode_no>[0-9]{1,3})/"
            r"(?P<timeline_fingerprint>[0-9a-f]{64})/"
            r"(?P<kind>mp4|srt|ass|edit)$"
        ),
        lambda name, raw_episode_no, timeline_fingerprint, kind,
        _headers=None, **_: api_drama_compose_deliverable(
            name,
            raw_episode_no,
            timeline_fingerprint,
            kind,
            _headers or {},
            head_only=True,
        ),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/review/?$"),
        lambda name, _body=b"", **_: api_drama_review(name, _body),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/assemble/?$"),
        lambda name, _body=b"", **_: api_drama_assemble(name, _body),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/apply-suggestion/?$"),
        lambda name, _body=b"", **_: api_drama_apply_suggestion(name, _body),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/episodes/?$"),
        lambda name, **_: api_drama_episodes(name),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/next-episode/?$"),
        lambda name, _body=b"", **_: api_drama_next_episode(name, _body),
    ),
    (
        "GET",
        re.compile(
            r"^/api/workspace/(?P<name>[^/]+)/drama/season/(?P<season>[^/]+)/export/?$"
        ),
        lambda name, season, _query=None, **_: api_drama_season_export(
            name,
            season,
            ((_query or {}).get("mode", [""])[0]),
        ),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/episode/(?P<episode>[^/]+)/export/?$"),
        lambda name, episode, _query=None, **_: api_drama_episode_export(
            name,
            episode,
            ((_query or {}).get("format", [""])[0]),
        ),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/episode/(?P<episode>[^/]+)/?$"),
        lambda name, episode, **_: api_drama_episode_detail(name, episode),
    ),
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/video/?$"),
        lambda name, _body=b"", **_: api_drama_video_generate(name, _body),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/video/?$"),
        lambda name, **_: api_drama_video_status(name),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/video/file/?$"),
        lambda name, **_: api_drama_video_file(name),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/drama/multimodal-smoke/?$"),
        lambda name, **_: api_drama_multimodal_status(name),
    ),
    (
        "GET",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/character-ref/(?P<cid>[^/]+)/(?P<filename>[^/]+)$"),
        lambda name, cid, filename, **_: api_character_ref(name, cid, filename),
    ),
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
    (
        "POST",
        re.compile(r"^/api/workspace/(?P<name>[^/]+)/job/(?P<job_id>[a-f0-9]{32})/cancel/?$"),
        lambda name, job_id, **_: api_job_cancel(name, job_id),
    ),
    # iter 026: onboarding wizard — single multipart POST that starts an
    # auto-pipeline job; client then polls the job_id from above.
    ("GET", re.compile(r"^/wizard/?$"), lambda **_: render_wizard_page()),
    ("GET", re.compile(r"^/api/preflight/?$"), lambda **_: api_preflight()),
    (
        "POST",
        re.compile(r"^/api/wizard/start/?$"),
        lambda _body=b"", _headers=None, **_: api_wizard_start(_body, _headers or {}),
    ),
    (
        "POST",
        re.compile(r"^/api/wizard/drama-start/?$"),
        lambda _body=b"", _headers=None, **_: api_wizard_drama_start(_body, _headers or {}),
    ),
    (
        "POST",
        re.compile(r"^/api/wizard/premise-start/?$"),
        lambda _body=b"", _headers=None, **_: api_wizard_premise_start(_body, _headers or {}),
    ),
    # iter 048a: workbench "test key" — model-key connectivity matrix
    ("GET", re.compile(r"^/api/diag/models/?$"), lambda **_: api_diag_models()),
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
    if (
        headers is not None
        and method in {"POST", "PUT"}
        and _DRAMA_MUTATION_PATH_RE.fullmatch(decoded_path)
    ):
        request_error = _drama_mutation_request_error(body, headers)
        if request_error:
            return request_error
    # iter 049: opt-in bearer-token gate (no-op unless NOVEL_API_TOKEN is set).
    # Only /api/* is gated; pages + /w/ deep links stay open for the browser.
    _token = auth.required_token()
    if _token is not None and not auth.is_authorized(decoded_path, headers or {}, _token):
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
        kwargs["_headers"] = headers or {}
        try:
            return handler(**kwargs)
        except FileNotFoundError as exc:
            return _json(404, errors.exception_body(exc))
        except ValueError as exc:
            return _json(400, errors.exception_body(exc))
        except Exception:
            # Iter 026 code-review #7 hardening: don't leak ``str(exc)``
            # to the client. Log the full exception server-side with a
            # trace_id the user can quote when reporting bugs.
            # iter062: also hand the client a friendly ``card`` (title +
            # next step + the same trace_id) — the ``error`` string stays
            # "internal server error" for backward compatibility.
            import sys
            import traceback as _tb
            import uuid as _uuid

            trace_id = _uuid.uuid4().hex
            sys.stderr.write(f"[web] dispatch trace_id={trace_id}\n")
            _tb.print_exc(file=sys.stderr)
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
