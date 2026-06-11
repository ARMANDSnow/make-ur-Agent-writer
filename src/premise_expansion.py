"""Iter 051a: premise → structured expansion agent + artifact accessors.

The 048a "一句话开书" path wraps a few-dozen-char premise into seed.txt and
runs prepare-greenfield on it; the resulting KB / entity graph are too thin
for debate / plan-chapters to produce a meaningful multi-chapter plan. This
module inserts an explicit, user-editable expansion between the premise and
prepare-greenfield:

* ``expand_premise`` calls the ``premise_expand`` LLM task (deterministic
  stub under mock, 铁律③) and persists ``data/premise_expansion.json``.
* ``load_expansion`` / ``save_expansion_fields`` are the artifact accessors
  used by the web GET/PUT endpoints (050 edit-loop pattern: Pydantic
  validation → atomic ``write_json``; staleness is the workbench mtime
  chain's job, not ours).
* ``expansion_prompt_block`` is the single consumption point for prompt
  chains (compress / bootstrap / debate). It returns ``""`` when the
  artifact is missing or unreadable, so every consumer degrades to the
  pre-051 bare-seed behavior byte-for-byte (铁律④).

The artifact never overwrites seed.txt: seed is what the user said, the
expansion is what the model inferred. One-way consumption, no second
source of truth.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from . import paths
from .llm_client import LLMClient
from .schemas import PremiseExpansion, model_to_dict
from .state import log_event
from .utils import read_json_optional, write_json

SCHEMA_VERSION = 1

# Ordered (field, label) pairs shared by the markdown render and the UI.
FIELD_LABELS = (
    ("genre_tone", "题材基调"),
    ("protagonist", "主角"),
    ("world_notes", "世界观要点"),
    ("central_conflict", "主冲突"),
    ("ending_anchor", "结局锚点"),
    ("arc_hints", "前期弧线提示"),
)


def expand_premise(premise: str, *, force: bool = False) -> Dict[str, Any]:
    """Expand a one-sentence premise into the structured artifact.

    Idempotent by default: an existing artifact is returned as-is unless
    ``force`` is set (the「重新扩写」button), so a re-run never silently
    clobbers user edits.
    """

    premise = (premise or "").strip()
    if not premise:
        raise ValueError("premise must not be empty")
    path = paths.premise_expansion_path()
    if path.exists() and not force:
        existing = load_expansion()
        if existing is not None:
            log_event("premise_expand", "skipped_existing", path=str(path))
            return existing

    client = LLMClient("premise_expand")
    expansion = client.complete_json(
        [
            {
                "role": "system",
                "content": (
                    "你是长篇小说的开发编辑。把用户的一句话立意扩写为结构化设定稿，"
                    "供后续知识库抽取、多 Agent 辩论与分章规划消费。"
                    "只补全立意中可合理推断的内容，不要凭空引入与立意矛盾的设定。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请把下面的一句话立意扩写为结构化设定稿（题材基调 / 主角卡 / "
                    "世界观要点 / 主冲突 / 结局锚点 / 前期弧线提示）。\n\n"
                    f"立意：{premise}"
                ),
            },
        ],
        response_model=PremiseExpansion,
    )
    record = {
        "schema_version": SCHEMA_VERSION,
        "premise": premise,
        "fields": model_to_dict(expansion),
        "generated_by": "premise_expand_v1_mock" if client.is_mock else "premise_expand_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "edited": False,
        "edited_at": "",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    log_event("premise_expand", "done", path=str(path), forced=force)
    return record


def load_expansion() -> Optional[Dict[str, Any]]:
    """Return the artifact dict, or ``None`` when missing/unreadable.

    Graceful degrade (铁律④): a corrupt or schema-invalid artifact logs and
    reads as absent — downstream falls back to the bare-seed path instead
    of failing the pipeline.
    """

    path = paths.premise_expansion_path()
    if not path.exists():
        return None
    record = read_json_optional(path, None)
    if not isinstance(record, dict) or not isinstance(record.get("fields"), dict):
        log_event("premise_expand", "artifact_invalid", path=str(path))
        return None
    try:
        PremiseExpansion(**record["fields"])
    except Exception as exc:
        log_event("premise_expand", "artifact_invalid", path=str(path), error=str(exc))
        return None
    return record


def save_expansion_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a user edit of the expansion fields (050 edit-loop pattern).

    Validates through ``PremiseExpansion`` (which carries the per-field
    length gates), then atomically rewrites the artifact. Creating from
    scratch is allowed — a user may hand-write the expansion without ever
    running the agent. Raises ``ValueError`` on validation failure.
    """

    try:
        validated = PremiseExpansion(**fields)
    except ValueError:
        raise
    except Exception as exc:  # pydantic ValidationError subclasses vary by version
        raise ValueError(str(exc)) from exc
    existing = load_expansion() or {
        "schema_version": SCHEMA_VERSION,
        "premise": "",
        "generated_by": "manual",
        "generated_at": "",
    }
    record = dict(existing)
    record["schema_version"] = SCHEMA_VERSION
    # iter 051c (review L-2): a hand-tampered artifact may lack the premise
    # key entirely — keep the record shape stable for the GET surface.
    record.setdefault("premise", "")
    record["fields"] = model_to_dict(validated)
    record["edited"] = True
    record["edited_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path = paths.premise_expansion_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    log_event("premise_expand", "edited", path=str(path))
    return record


def _one_line(value: Any) -> str:
    """iter 051c (review L-1): collapse embedded newlines to spaces.

    Each rendered field rides on a single markdown list line — a raw
    newline inside a field would break the list structure AND let edited
    text masquerade as a new prompt section header (e.g. a fake
    「人工全局事实:」line). C3c deliberately allows \\n in edit payloads
    (multi-line textareas are legitimate), so the flattening belongs here
    at the render boundary, not in the input gate."""

    return " ".join(str(value or "").split())


def render_expansion_markdown(fields: Dict[str, Any]) -> str:
    """Markdown render shared by prompt injection and the KB section."""

    lines = []
    for key, label in FIELD_LABELS:
        value = fields.get(key)
        if isinstance(value, list):
            items = [_one_line(v) for v in value if _one_line(v)]
            if not items:
                continue
            lines.append(f"- {label}：")
            lines.extend(f"  - {item}" for item in items)
        else:
            text = _one_line(value)
            if not text:
                continue
            lines.append(f"- {label}：{text}")
    return "\n".join(lines)


def expansion_prompt_block() -> str:
    """The single graceful-degrade point for all prompt-chain consumers.

    Returns a ready-to-embed block, or ``""`` when no (valid) artifact
    exists — consumers concatenate it unconditionally and stay
    byte-identical to pre-051 behavior in the missing case.
    """

    record = load_expansion()
    if record is None:
        return ""
    body = render_expansion_markdown(record.get("fields") or {})
    if not body:
        return ""
    return f"premise 扩写稿（用户确认的设定基础）：\n{body}\n\n"
