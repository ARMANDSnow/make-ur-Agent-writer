"""Iter 056: 作家风格卡——预置库 + 激活卡快照 + prompt 注入消费点。

复刻 iter051a ``premise_expansion`` 的「可编辑卡片 artifact」范式：

* ``load_presets`` 读全局只读预置库 ``config/style_presets.json``（graceful：
  缺失→[]、单条坏卡跳过、不整库失效）。
* ``activate_preset`` 把预置卡 **快照** fields 落到 ``data/writer_style.json``
  ——存的是 fields 而非 preset_id 引用，预置库日后升级不会让已激活卡漂移
  （写到一半风格突变是灾难）。``preset_id``/``preset_version`` 仅作审计，
  注入与渲染绝不回查预置库。
* ``load_card`` / ``save_card_fields`` 是 GET/PUT 端点的 artifact accessors
  （050 edit-loop：Pydantic 校验 → 原子 ``write_json``）。
* ``writer_style_prompt_block`` 是 prompt 链的**单一消费点**，镜像
  ``writer._canon_anchor_block``：**有起点（续写书）/ 无卡 / 卡损坏 → 返回 ""**，
  上游无条件拼接、缺失时逐字节回到注入前行为（铁律④）。仅 premise 自创书
  注入，续写书靠原著 style_examples + 起点前原文。

extract（上传样本→卡）在轨 B 追加；本模块本身不依赖 LLMClient。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from . import paths, start_point
from .config import load_config
from .schemas import WriterStyleCard, model_to_dict
from .state import log_event
from .utils import read_json_optional, write_json

SCHEMA_VERSION = 1

PRESETS_CONFIG_NAME = "style_presets.json"

# 进 prompt 正文的字段（field, 中文 label），供渲染与 UI 共享。
# name/category 是身份元字段，不进正文列表——单独渲染为卡头。
FIELD_LABELS = (
    ("rhythm", "叙事节奏"),
    ("sentence", "句式特征"),
    ("diction", "用词偏好"),
    ("imagery", "意象比喻"),
    ("dialogue", "对话风格"),
    ("subtext", "含蓄度"),
    ("narration", "叙述视角"),
    ("signatures", "标志性笔法"),
    ("taboo", "规避笔法"),
)


def _presets_raw() -> Dict[str, Any]:
    raw = load_config(PRESETS_CONFIG_NAME)
    return raw if isinstance(raw, dict) else {}


def _presets_version() -> int:
    """预置库的 schema_version——激活时快照进 record，UI 可据此提示升级。"""
    try:
        return int(_presets_raw().get("schema_version", 0))
    except (TypeError, ValueError):
        return 0


def load_presets() -> List[Dict[str, Any]]:
    """全局只读预置库。每条 card 过 ``WriterStyleCard`` 校验后规整返回；
    缺失/格式错→[]，单条坏卡或重复 id 跳过（不整库失效）。"""

    presets = _presets_raw().get("presets")
    if not isinstance(presets, list):
        return []
    out: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in presets:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("id")
        card = entry.get("card")
        if not isinstance(pid, str) or not pid or pid in seen_ids or not isinstance(card, dict):
            continue
        try:
            validated = WriterStyleCard(**card)
        except Exception:
            log_event("writer_style", "preset_invalid", preset_id=pid)
            continue
        seen_ids.add(pid)
        out.append({"id": pid, "card": model_to_dict(validated)})
    return out


def activate_preset(preset_id: str) -> Dict[str, Any]:
    """选中预置卡：**快照** fields 入 workspace（非引用 id），落
    ``data/writer_style.json``。未知 id → ``ValueError``。"""

    match = next((p for p in load_presets() if p.get("id") == preset_id), None)
    if match is None:
        raise ValueError(f"unknown preset_id: {preset_id}")
    fields = model_to_dict(WriterStyleCard(**(match.get("card") or {})))
    record = {
        "schema_version": SCHEMA_VERSION,
        "source": "preset",
        "preset_id": preset_id,
        "preset_version": _presets_version(),
        "scope": "book",
        "fields": fields,
        "generated_by": "preset_snapshot",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "edited": False,
        "edited_at": "",
    }
    path = paths.writer_style_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    log_event("writer_style", "activated_preset", preset_id=preset_id)
    return record


def load_card() -> Optional[Dict[str, Any]]:
    """读激活卡 record，或缺失/不可读时返回 ``None``（铁律④ graceful degrade：
    坏卡 / schema 不符当作不存在，下游回到无卡路径而非崩流水线）。"""

    path = paths.writer_style_path()
    if not path.exists():
        return None
    record = read_json_optional(path, None)
    if not isinstance(record, dict) or not isinstance(record.get("fields"), dict):
        log_event("writer_style", "artifact_invalid", path=str(path))
        return None
    try:
        WriterStyleCard(**record["fields"])
    except Exception as exc:
        log_event("writer_style", "artifact_invalid", path=str(path), error=str(exc))
        return None
    return record


def save_card_fields(
    fields: Dict[str, Any],
    *,
    source: Optional[str] = None,
    preset_id: Optional[str] = None,
    preset_version: Optional[int] = None,
) -> Dict[str, Any]:
    """持久化用户编辑（050 edit-loop）。Pydantic 校验（携 per-field 长度门）
    → 原子重写。允许从零手写（未跑预置/提取也能直接建卡）。来源元字段：
    调用方显式传则更新，否则保留既有（从零创建默认 ``manual``）。校验失败抛
    ``ValueError``。"""

    try:
        validated = WriterStyleCard(**fields)
    except ValueError:
        raise
    except Exception as exc:  # pydantic ValidationError 跨版本子类不一
        raise ValueError(str(exc)) from exc
    existing = load_card() or {
        "schema_version": SCHEMA_VERSION,
        "source": "manual",
        "preset_id": "",
        "preset_version": 0,
        "generated_by": "manual",
        "generated_at": "",
    }
    record = dict(existing)
    record["schema_version"] = SCHEMA_VERSION
    record.setdefault("scope", "book")
    record["source"] = source if source is not None else record.get("source", "manual")
    record["preset_id"] = preset_id if preset_id is not None else record.get("preset_id", "")
    record["preset_version"] = (
        preset_version if preset_version is not None else record.get("preset_version", 0)
    )
    record["fields"] = model_to_dict(validated)
    record["edited"] = True
    record["edited_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path = paths.writer_style_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    log_event("writer_style", "edited", path=str(path))
    return record


def _one_line(value: Any) -> str:
    """折叠内嵌换行为空格（防注入到可缓存段时破坏段结构 / 伪造段头，
    iter051c review L-1 同款防御）。"""

    return " ".join(str(value or "").split())


def render_card_markdown(fields: Dict[str, Any]) -> str:
    """Markdown 渲染，供 prompt 注入与 UI 预览共享（name/category 不在此，
    它们由 prompt block 的卡头单独承载）。"""

    lines: List[str] = []
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


def writer_style_prompt_block() -> str:
    """风格卡注入的单一 graceful-degrade 点，镜像 ``_canon_anchor_block``。

    条件注入（铁律④回退契约）：
      * 有起点（续写书）→ ""（续写靠原著 style_examples + 起点前原文，
        不注入风格卡，避免与原著风格打架）；
      * 无卡 / 卡损坏 / 渲染为空 → ""；
    返回串**自带尾部 ``\\n\\n`` 分隔**，上游裸拼即可；空时返回 "" 使上游
    逐字节回到注入前。
    """

    if start_point.get_start_chapter_id():  # 有起点=续写书 → 不注入
        return ""
    record = load_card()
    if record is None:
        return ""
    fields = record.get("fields") or {}
    body = render_card_markdown(fields)
    if not body:
        return ""
    name = _one_line(fields.get("name"))
    head = "# 作家风格卡" + (f"·{name}" if name else "") + "（本书统一笔法，匹配下述风格特征写作）\n\n"
    tail = (
        "\n\n写作时匹配上述风格特征的节奏、句式、用词与含蓄度；"
        "不得违反上方关键风格戒律，与原著风格样例冲突时以系统戒律为准。\n\n"
    )
    return f"{head}{body}{tail}"
