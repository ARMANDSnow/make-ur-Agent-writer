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


def _empty_fields(fields: Dict[str, Any]) -> list:
    """iter 053（052 实测缺口）：空字符串 / 空列表（或全空白项）都算空。

    052 真模型段二实录：shudian052 的扩写稿 genre_tone / world_notes /
    central_conflict（盘面复核 arc_hints 同）为空落盘，风格定调全靠
    personas 的 style_short_descriptor 兜底——schema 只有长度上限、没有
    非空校验。"""

    empty = []
    for key, _label in FIELD_LABELS:
        value = fields.get(key)
        if isinstance(value, list):
            if not [v for v in value if str(v or "").strip()]:
                empty.append(key)
        elif not str(value or "").strip():
            empty.append(key)
    return empty


def expand_premise(premise: str, *, force: bool = False) -> Dict[str, Any]:
    """Expand a one-sentence premise into the structured artifact.

    Idempotent by default: an existing artifact is returned as-is unless
    ``force`` is set (the「重新扩写」button), so a re-run never silently
    clobbers user edits.

    iter 053: 落盘前做 6 字段非空校验——发现空字段带"必须补全"提示自动重试
    一次；仍空则照常落盘但在 **record 层**记 ``_incomplete_fields`` 标记
    （fields 层会被 ``load_expansion`` 的 ``PremiseExpansion(**fields)`` 反
    序列化拒掉；标记也绝不进 ``expansion_prompt_block`` 的渲染面）。
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
    system_message = {
        "role": "system",
        "content": (
            "你是长篇小说的开发编辑。把用户的一句话立意扩写为结构化设定稿，"
            "供后续知识库抽取、多 Agent 辩论与分章规划消费。"
            "只补全立意中可合理推断的内容，不要凭空引入与立意矛盾的设定。"
        ),
    }
    user_content = (
        "请把下面的一句话立意扩写为结构化设定稿（题材基调 / 主角卡 / "
        "世界观要点 / 主冲突 / 结局锚点 / 前期弧线提示）。\n\n"
        f"立意：{premise}"
    )
    expansion = client.complete_json(
        [system_message, {"role": "user", "content": user_content}],
        response_model=PremiseExpansion,
    )
    fields = model_to_dict(expansion)
    empty = _empty_fields(fields)
    if empty:
        labels = {key: label for key, label in FIELD_LABELS}
        log_event("premise_expand", "empty_fields_retry", fields=empty)
        retry_user = (
            f"{user_content}\n\n"
            "上一稿中以下字段缺失，本次必须全部补全、不得留空："
            + "、".join(labels.get(key, key) for key in empty)
        )
        try:
            retry_expansion = client.complete_json(
                [system_message, {"role": "user", "content": retry_user}],
                response_model=PremiseExpansion,
            )
            retry_fields = model_to_dict(retry_expansion)
            if len(_empty_fields(retry_fields)) < len(empty):
                fields = retry_fields
                empty = _empty_fields(fields)
        except Exception as exc:
            # 重试失败不影响主路径：带着第一稿照常落盘 + 标记。
            log_event("premise_expand", "empty_fields_retry_error", error=str(exc))
    record = {
        "schema_version": SCHEMA_VERSION,
        "premise": premise,
        "fields": fields,
        "generated_by": "premise_expand_v1_mock" if client.is_mock else "premise_expand_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "edited": False,
        "edited_at": "",
    }
    if empty:
        record["_incomplete_fields"] = empty
        log_event("premise_expand", "incomplete_fields", fields=empty)
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
    # iter 053: 手工编辑后重算未完成标记——补全即摘牌，仍空则保留。
    remaining = _empty_fields(record["fields"])
    if remaining:
        record["_incomplete_fields"] = remaining
    else:
        record.pop("_incomplete_fields", None)
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
