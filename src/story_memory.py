"""Versioned, recoverable memory for manually edited chapters (no LLM calls)."""
from __future__ import annotations
import json
import os
import stat
from pathlib import Path
from . import paths, workspace_files
from .utils import sha256_text, write_json

LIMIT = 4 * 1024 * 1024


def _read(path: Path, default=None):
    if paths.workspace_name():
        root = paths.drafts_dir().parent.parent
        try:
            raw = workspace_files.read_text(paths.workspace_name(), path.relative_to(root).as_posix(), max_bytes=LIMIT, errors="strict")
        except FileNotFoundError:
            return default
        return json.loads(raw)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as handle:
            st = os.fstat(handle.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_size > LIMIT:
                raise ValueError('story_memory_unsafe')
            return json.loads(handle.read(LIMIT + 1))
    except FileNotFoundError:
        return default


def _write(path: Path, value):
    if paths.workspace_name():
        root = paths.drafts_dir().parent.parent
        workspace_files.write_json_atomic(paths.workspace_name(), path.relative_to(root).as_posix(), value, max_bytes=LIMIT)
    else:
        if path.is_symlink():
            raise ValueError('story_memory_unsafe')
        write_json(path, value)


def invalidate_from(drafts: Path, chapter: int, *, include_target: bool = True) -> None:
    """Called under the workspace write lock BEFORE replacing the draft.

    Mark descendants too: reviewing the edited chapter must not silently make
    chapters written against its old content current again.
    """
    metas = sorted(drafts.glob('chapter_*.meta.json'))
    if len(metas) > 10000:
        raise ValueError('story_memory_limit')
    target = drafts / f'chapter_{chapter:02d}.meta.json'
    if include_target and target not in metas:
        metas.append(target)
    for path in metas:
        try:
            no = int(path.name.split('_')[1].split('.')[0])
        except ValueError:
            continue
        if no < chapter or (no == chapter and not include_target):
            continue
        meta = _read(path, {})
        if not isinstance(meta, dict):
            raise ValueError('story_memory_meta_invalid')
        meta['story_memory_invalidated'] = True
        meta['needs_human_review'] = True
        _write(path, meta)


def stale_before(drafts: Path, chapter: int) -> list[int]:
    result = []
    for path in sorted(drafts.glob('chapter_*.meta.json')):
        no = int(path.name.split('_')[1].split('.')[0])
        if no >= chapter:
            continue
        meta = _read(path, {})
        if not isinstance(meta, dict):
            raise ValueError('story_memory_meta_invalid')
        # edited=True is the legacy marker; older saved drafts did not carry
        # a source hash and must be refreshed once, never trusted silently.
        if meta.get('story_memory_invalidated') or (meta.get('edited') and meta.get('story_memory_draft_sha256') != meta.get('draft_sha256')):
            result.append(no)
    return result


def require_current(drafts: Path, chapter: int) -> None:
    stale = stale_before(drafts, chapter)
    if stale:
        raise ValueError('story_memory_stale:' + ','.join(map(str, stale)) + '; 请从最早修改章开始保存并重新检查，更新故事记忆')


def refresh_after_review(drafts: Path, chapter: int) -> bool:
    """After exact approved review, replace stale derived facts by excerpts.

    Old automatic entity states are retained as inactive history, never
    guessed back into an active state. No new model request is submitted.
    """
    from .chapter_summary import _compact_older
    from .entity_advance import parse_chapter_anchor
    meta_path = drafts / f'chapter_{chapter:02d}.meta.json'
    meta = _read(meta_path, {})
    if not isinstance(meta, dict) or not (meta.get('edited') or meta.get('story_memory_invalidated')):
        return False
    if not meta.get('story_memory_invalidated') and meta.get('story_memory_draft_sha256') == meta.get('draft_sha256'):
        return False
    require_current(drafts, chapter)
    if paths.workspace_name():
        draft = workspace_files.read_text(paths.workspace_name(), f'outputs/drafts/chapter_{chapter:02d}.md', max_bytes=LIMIT)
    else:
        draft = (drafts / f'chapter_{chapter:02d}.md').read_text(encoding='utf-8')
    digest = sha256_text(draft)
    review = _read(drafts.parent / 'reviews' / f'chapter_{chapter:02d}.review.json', {})
    if not isinstance(review, dict) or not (review.get('verdict') == meta.get('verdict') == 'Approve'
        and not review.get('needs_human_review') and not meta.get('needs_human_review')
        and review.get('draft_sha256') == meta.get('draft_sha256') == digest
        and isinstance(meta.get('run_context'), dict) and review.get('run_context') == meta.get('run_context')):
        return False
    # Leave a durable marker throughout every recovery write, including a
    # repeated review of an already-recovered manually edited chapter.
    meta['story_memory_invalidated'] = True
    _write(meta_path, meta)
    invalidate_derived_from(drafts, chapter)
    rolling_path = drafts/'rolling_chapter_summary.json'
    rolling = _read(rolling_path, {'chapters':[], 'compressed_older':[]})
    if not isinstance(rolling,dict) or not isinstance(rolling.get('chapters'),list) or not isinstance(rolling.get('compressed_older'),list):
        raise ValueError('story_memory_rolling_invalid')
    rolling['chapters'] = [entry for entry in rolling['chapters'] if isinstance(entry,dict) and entry.get('chapter_no') != chapter]
    rolling['compressed_older'] = [entry for entry in rolling['compressed_older'] if isinstance(entry,dict) and entry.get('chapter_no') != chapter]
    rolling['chapters'].append({'chapter_no':chapter, 'summary':'当前正文摘录（非语义摘要）：'+draft[:1200],
        'key_events':[], 'ending_state':'当前正文末段：'+draft[-1200:],
        'text_snippet':draft[:600]+'\n…\n'+draft[-600:], 'source_draft_sha256':digest})
    rolling['chapters'].sort(key=lambda entry: int(entry['chapter_no']))
    _compact_older(rolling)
    _write(rolling_path,rolling)
    meta['story_memory_draft_sha256'] = digest
    meta['story_memory_invalidated'] = False
    meta['story_memory_kind'] = 'reviewed_excerpt'
    _write(meta_path, meta)
    return True


def invalidate_derived_from(drafts: Path, chapter: int) -> None:
    """Retain old entity history but prevent replay before any rewrite."""
    from .entity_advance import parse_chapter_anchor
    graph_path = drafts.parent.parent / 'data/entity_graph.json'
    graph = _read(graph_path, None)
    if graph is not None:
        if not isinstance(graph, dict):
            raise ValueError('story_memory_graph_invalid')
        for rel in graph.get('relationships', []) or []:
            if not isinstance(rel, dict):
                continue
            for entry in rel.get('timeline', []) or []:
                if not isinstance(entry, dict):
                    continue
                no = parse_chapter_anchor(str(entry.get('anchor_chapter') or ''))
                if no is not None and no >= chapter:
                    entry['active'] = False
                    entry['invalidated_by_edit'] = chapter
        _write(graph_path, graph)
    # An existing sidecar is deliberately preserved: deleting it would enable
    # resume compensation of the pre-edit proposal. Invalidate the proposal
    # itself as well, including the sidecar-missing case.
    for proposal in sorted(drafts.glob('chapter_*.entity_advance_proposals.json')):
        no = int(proposal.name.split('_')[1].split('.')[0])
        if no >= chapter:
            previous = _read(proposal, {})
            _write(proposal, {'chapter_no':no, 'proposed_advances':[], 'invalidated_by_edit':chapter,
                              'previous_proposals':(previous.get('proposed_advances') or previous.get('previous_proposals', [])) if isinstance(previous,dict) else []})
