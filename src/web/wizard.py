"""iter 026: onboarding wizard.

A user uploads an ``.epub`` or ``.txt`` of a novel; the wizard creates a
fresh workspace, drops the file into ``workspaces/<name>/小说txt/``, then
fires a single ``auto-pipeline`` job whose worker (in ``src/web/jobs.py``)
runs the 9-step SOP. The browser polls the job's status.

Why a single job (not 7 POSTs from the front-end): the orchestration is
in ``src/auto_pipeline.py``; reproducing it in JS would create a second
source of truth for step ordering. The wizard front-end stays at two
states — uploading and polling.

Multipart parser: ``cgi.FieldStorage`` is deprecated in Python 3.13. We
parse ``multipart/form-data`` by hand because the wizard only ever sends
two fields (workspace name + file blob); a 60-line bytes splitter is
easier to audit than pulling in ``python-multipart``.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple  # noqa: F401

from .. import paths
from ..cli_workspace import init_workspace
from ..epub_to_txt import extract_epub
from . import jobs

# 50 MB hard cap on upload payload. server.py imposes a wider 64 MB
# safety cap; this is the wizard-specific cap that returns a friendly
# 413 with a JSON body the front-end can show to the user.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

ALLOWED_MIME = frozenset(
    {
        "application/epub+zip",
        "application/octet-stream",  # browsers sometimes send this for .epub
        "text/plain",
        "text/plain; charset=utf-8",
    }
)


def start_upload(body: bytes, content_type: str) -> Tuple[int, str, bytes]:
    """POST /api/wizard/start handler.

    Parses the multipart body, creates the workspace, drops the file
    into ``小说txt/``, and starts the ``auto-pipeline`` job. Returns
    ``202 {"name", "job_id"}`` on success.
    """

    if not content_type or "multipart/form-data" not in content_type:
        return _json(415, {"error": "Content-Type must be multipart/form-data"})
    if len(body) > MAX_UPLOAD_BYTES:
        return _json(413, {"error": f"upload exceeds {MAX_UPLOAD_BYTES} bytes"})
    try:
        fields = _parse_multipart(body, content_type)
    except ValueError as exc:
        return _json(400, {"error": f"multipart parse failed: {exc}"})

    name_field = fields.get("workspace")
    file_field = fields.get("upload")
    if not isinstance(name_field, str) or not name_field.strip():
        return _json(400, {"error": "missing 'workspace' field"})
    if file_field is None or not isinstance(file_field, dict):
        return _json(400, {"error": "missing 'upload' file"})

    name = name_field.strip()
    if not _validate_name(name):
        return _json(400, {"error": "invalid workspace name"})

    file_bytes: bytes = file_field["content"]
    filename: str = (file_field.get("filename") or "").strip()
    file_mime: str = (file_field.get("content_type") or "application/octet-stream").strip()
    if file_mime not in ALLOWED_MIME:
        return _json(415, {"error": f"unsupported MIME: {file_mime}"})
    if not file_bytes:
        return _json(400, {"error": "uploaded file is empty"})

    # Workspace creation: fail loudly if one already exists by that
    # name (don't silently overwrite).
    target_root = paths.WORKSPACE_DIR / name
    if target_root.exists():
        return _json(409, {"error": f"workspace already exists: {name}"})
    try:
        init_workspace(name)
    except (ValueError, FileExistsError) as exc:
        return _json(400, {"error": str(exc)})

    # Defense-in-depth: ensure the final destination really is under
    # workspaces/<name>/ after path resolution.
    raw_dir = target_root / "小说txt"
    try:
        raw_dir.resolve().relative_to(paths.WORKSPACE_DIR.resolve())
    except (OSError, ValueError):
        return _json(400, {"error": "resolved path escapes workspaces/"})

    suffix = ".epub" if (filename.lower().endswith(".epub") or "epub" in file_mime) else ".txt"

    # Iter 026 code-review #2: extract_epub / write_bytes can raise
    # BadZipFile, KeyError (spine missing in malformed epub), or OSError
    # (disk full, encoding). Without a rollback the half-created
    # workspace lingers and the next same-name upload hits the
    # ``target_root.exists()`` 409 forever. Wrap the IO segment in a
    # try/except whose failure path rmtree's the workspace and returns
    # a friendly 400 (not a 500 trace_id, since this is user-input
    # failure, not an internal crash).
    # iter 026 P5b regression-review MED: capture ``tmp_path`` BEFORE
    # the write so a write failure (disk full) still lets the outer
    # except cleanup the (already created on __enter__) NamedTemporaryFile.
    # ``delete=False`` is required so ``extract_epub`` can re-open the
    # path, but means we own cleanup ourselves.
    tmp_path: Optional[Path] = None
    try:
        if suffix == ".epub":
            with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(file_bytes)
            extract_epub(tmp_path, raw_dir / "upload.txt")
        else:
            (raw_dir / "upload.txt").write_bytes(file_bytes)
    except Exception as exc:
        # Log full traceback server-side; tell the user the file looked
        # bad without leaking internal paths or stack frames.
        import sys
        import traceback as _tb

        sys.stderr.write(
            f"[wizard] upload processing failed for workspace={name!r}: "
            f"{type(exc).__name__}: {exc}\n"
        )
        _tb.print_exc(file=sys.stderr)
        shutil.rmtree(target_root, ignore_errors=True)
        # Don't leak the staging temp file even when the failure is in
        # the write itself.
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return _json(
            400,
            {"error": "failed to process upload (file may be corrupt or unreadable)"},
        )
    finally:
        # Happy-path cleanup of the staging temp file.
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    # Now start the 9-step job. We pass ``chapters=1`` so the wizard
    # always produces a single ch1 — the user grows the corpus from
    # ``write_book.sh`` afterward.
    try:
        job = jobs.start_job(
            name,
            "auto-pipeline",
            {"chapters": 1, "extract_limit": 5, "force": True},
        )
    except (ValueError, RuntimeError) as exc:
        # Roll back the half-created workspace so the user can retry
        # with the same name; otherwise they'd hit "already exists"
        # forever.
        shutil.rmtree(target_root, ignore_errors=True)
        return _json(500, {"error": f"failed to start pipeline: {exc}"})

    return _json(202, {"name": name, "job_id": job["job_id"]})


# ---- helpers ---------------------------------------------------------------


_VALID_NAME_RE = re.compile(
    r"^[a-zA-Z0-9_一-鿿]"
    r"(?:[a-zA-Z0-9_一-鿿-]{0,30}[a-zA-Z0-9_一-鿿])?$"
)
_RESERVED_NAMES = frozenset({"legacy"})


def _validate_name(name: str) -> bool:
    if name in _RESERVED_NAMES:
        return False
    return bool(_VALID_NAME_RE.match(name))


def _json(status: int, payload: Dict[str, Any]) -> Tuple[int, str, bytes]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return status, "application/json; charset=utf-8", body


_BOUNDARY_RE = re.compile(r"boundary=([^\s;]+)", re.IGNORECASE)


def _parse_multipart(body: bytes, content_type: str) -> Dict[str, Any]:
    """Return a dict of field-name → value, where text fields are str
    and file fields are dict ``{filename, content_type, content}``.

    Only handles what the wizard sends: small number of fields, no
    nested multipart, no transfer encoding. Raises ``ValueError`` on
    structural problems.
    """

    match = _BOUNDARY_RE.search(content_type)
    if match is None:
        raise ValueError("Content-Type missing boundary")
    boundary = match.group(1).strip('"')
    delim = b"--" + boundary.encode("ascii")
    parts = body.split(delim)
    # Drop the preamble (parts[0]) and the trailing close (parts[-1],
    # which is just "--\r\n").
    if len(parts) < 3:
        raise ValueError("no parts found")
    result: Dict[str, Any] = {}
    for raw in parts[1:-1]:
        # Each part starts with \r\n after the delimiter and ends with
        # \r\n before the next delimiter.
        raw = raw.strip(b"\r\n")
        if not raw:
            continue
        header_block, _, content = raw.partition(b"\r\n\r\n")
        headers = _parse_headers(header_block)
        disposition = headers.get("content-disposition", "")
        name = _extract_dispo_param(disposition, "name")
        filename = _extract_dispo_param(disposition, "filename")
        if name is None:
            continue
        if filename is not None:
            result[name] = {
                "filename": filename,
                "content_type": headers.get("content-type", "application/octet-stream"),
                "content": content,
            }
        else:
            # Text field — decode as UTF-8.
            try:
                result[name] = content.decode("utf-8")
            except UnicodeDecodeError:
                result[name] = content.decode("utf-8", errors="replace")
    return result


def _parse_headers(block: bytes) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for line in block.split(b"\r\n"):
        if b":" not in line:
            continue
        key, _, val = line.partition(b":")
        headers[key.decode("ascii", errors="replace").strip().lower()] = (
            val.decode("ascii", errors="replace").strip()
        )
    return headers


def _extract_dispo_param(disposition: str, key: str) -> Optional[str]:
    # ``form-data; name="workspace"; filename="book.epub"``
    pattern = rf'{key}="([^"]*)"'
    m = re.search(pattern, disposition)
    return m.group(1) if m else None
