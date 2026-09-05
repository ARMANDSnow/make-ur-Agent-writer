"""Preserve failed draft evidence before an explicitly submitted writing run."""
from __future__ import annotations
import hashlib
import json
import os
import secrets
from typing import Any
from . import paths, workspace_files

DRAFT_LIMIT = 2 * 1024 * 1024
FAILURE_LIMIT = 128 * 1024
COMPLETE_STAGES = frozenset({'budget_check_write', 'lint', 'shadow_review', 'review', 'budget_check_review'})


def _assert_no_canonical(workspace: str, chapter: int) -> None:
    parent, leaf = workspace_files._open_parent(workspace, f'outputs/drafts/chapter_{chapter:02d}.md')
    try:
        try:
            os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise workspace_files.WorkspaceFileError('canonical draft appeared during partial recovery')
    finally:
        os.close(parent)


def _read_evidence(workspace: str, chapter: int) -> dict[str, bytes]:
    result = {}
    for suffix, limit in [('partial.md', DRAFT_LIMIT), ('failure.json', FAILURE_LIMIT)]:
        name = f'chapter_{chapter:02d}.{suffix}'
        try:
            result[name] = workspace_files.read_bytes(workspace, 'outputs/drafts/' + name, max_bytes=limit)
        except FileNotFoundError:
            pass
    return result


def _snapshot(workspace: str, chapter: int, evidence: dict[str, bytes]) -> None:
    parent = workspace_files._open_dir(workspace, ('outputs', 'drafts', 'snapshots'), create=True)
    folder = f'partial_{chapter:02d}_{secrets.token_hex(12)}'
    directory = -1
    try:
        os.mkdir(folder, mode=0o700, dir_fd=parent)
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        for name, payload in evidence.items():
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                view = memoryview(payload)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError('short partial snapshot write')
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
        os.fsync(directory)
        os.fsync(parent)
        info, current = os.fstat(directory), os.stat(folder, dir_fd=parent, follow_symlinks=False)
        if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
            raise workspace_files.WorkspaceFileError('partial snapshot changed')
    finally:
        if directory >= 0:
            os.close(directory)
        os.close(parent)


def prepare_partial_resume(chapter: int, run_context: dict[str, Any], *, allow_resume: bool) -> str:
    """Copy old evidence first; only a matching complete draft may skip writing.

    Legacy writer paths have no verified workspace identity and retain their
    previous behavior. Caller owns the existing workspace writing lock.
    """
    workspace = paths.workspace_name()
    if not workspace:
        return ''
    _assert_no_canonical(workspace, chapter)
    evidence = _read_evidence(workspace, chapter)
    if not evidence:
        return ''
    draft = ''
    raw = evidence.get(f'chapter_{chapter:02d}.partial.md')
    failure_raw = evidence.get(f'chapter_{chapter:02d}.failure.json')
    if allow_resume and raw and failure_raw:
        try:
            failure = json.loads(failure_raw.decode('utf-8'))
            text = raw.decode('utf-8')
            if (isinstance(failure, dict) and type(failure.get('schema_version')) is int
                    and failure['schema_version'] == 2 and type(failure.get('chapter')) is int
                    and failure['chapter'] == chapter and failure.get('run_context') == run_context
                    and failure.get('resume_from_stage') == 'lint' and failure.get('stage') in COMPLETE_STAGES
                    and failure.get('draft_sha256') == hashlib.sha256(raw).hexdigest()
                    and text.strip() and (text.strip() + '\n').encode('utf-8') == raw):
                draft = text.strip()
        except (ValueError, TypeError, UnicodeDecodeError):
            pass
    _snapshot(workspace, chapter, evidence)
    _assert_no_canonical(workspace, chapter)
    if _read_evidence(workspace, chapter) != evidence:
        raise workspace_files.WorkspaceFileError('partial evidence changed before resume')
    return draft
