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
from .llm_client import LLMClient
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


# ---- 轨 B: 上传样本提取 + 反污染护栏 ----------------------------------------

EXTRACT_SAMPLE_MAX_CHARS = 60000
_SCRUB_NGRAM = 8  # 连续 ≥8 字与样本重合视作 verbatim 泄露


def _empty_fields(fields: Dict[str, Any]) -> List[str]:
    """空字符串 / 空列表（或全空白项）都算空——9 维特征里哪些缺失。"""

    empty: List[str] = []
    for key, _label in FIELD_LABELS:
        value = fields.get(key)
        if isinstance(value, list):
            if not [v for v in value if str(v or "").strip()]:
                empty.append(key)
        elif not str(value or "").strip():
            empty.append(key)
    return empty


def _norm(text: Any) -> str:
    return "".join(str(text or "").split())


def _sample_grams(sample: str) -> set:
    norm = _norm(sample)
    if len(norm) < _SCRUB_NGRAM:
        return set()
    return {norm[i : i + _SCRUB_NGRAM] for i in range(len(norm) - _SCRUB_NGRAM + 1)}


def _has_overlap(text: Any, grams: set) -> bool:
    t = _norm(text)
    if len(t) < _SCRUB_NGRAM or not grams:
        return False
    return any(t[i : i + _SCRUB_NGRAM] in grams for i in range(len(t) - _SCRUB_NGRAM + 1))


def _scrub_sample_overlap(fields: Dict[str, Any], sample: str) -> tuple[Dict[str, Any], List[str]]:
    """反污染二次扫描（P0-A 护栏，不靠 LLM 自律）：任一字段若与上传样本连续重合
    ≥``_SCRUB_NGRAM`` 字，视作 verbatim 泄露并剥离——标量整字段清空、list 剥该条。
    返回 (cleaned_fields, 被剥离的字段名列表)。"""

    grams = _sample_grams(sample)
    if not grams:
        return fields, []
    cleaned = dict(fields)
    scrubbed: List[str] = []
    for key in ("rhythm", "sentence", "diction", "imagery", "dialogue", "subtext", "narration"):
        if isinstance(cleaned.get(key), str) and _has_overlap(cleaned[key], grams):
            cleaned[key] = ""
            scrubbed.append(key)
    for key in ("signatures", "taboo"):
        value = cleaned.get(key)
        if isinstance(value, list):
            kept = [it for it in value if not _has_overlap(it, grams)]
            if len(kept) != len(value):
                cleaned[key] = kept
                scrubbed.append(key)
    return cleaned, scrubbed


def extract_style_card(sample: str, *, force: bool = False) -> Dict[str, Any]:
    """上传样本 → ``style_extract`` LLM task → ``WriterStyleCard`` → 落盘
    （source="extract"）。仿 ``expand_premise``：mock 下确定性 stub（铁律③）、
    幂等（存在不覆盖除非 force）、空字段重试一次、反污染二次扫描兜底。"""

    sample = (sample or "").strip()
    if not sample:
        raise ValueError("sample must not be empty")
    path = paths.writer_style_path()
    if path.exists() and not force:
        existing = load_card()
        if existing is not None:
            log_event("writer_style", "extract_skipped_existing")
            return existing

    client = LLMClient("style_extract")
    system_message = {
        "role": "system",
        "content": (
            "你是研究作家文体的文学编辑。从给定写作样本中提炼【可复用的风格特征】，"
            "输出结构化风格卡（节奏/句式/用词/意象/对话/含蓄度/视角 + 标志性笔法 + 规避笔法）。"
            "只描述笔法手法，不要摘录或复述样本中的具体情节、人名、地名或句子原文；"
            "signatures 描述手法而非给字面例句，以免污染后续写作输出。"
        ),
    }
    # complete_json 不注入 schema（llm_client.py:416 仅传 messages），故必须在
    # prompt 里显式给出 JSON 字段——否则 LLM 自拟 key、解析后全回退默认值（空）。
    # 真模型 V1 实测教训：缺这段格式说明 → 9 维全空 + 空字段重试也救不回。
    user_content = (
        "分析下面这段写作样本的文体，提炼可复用的风格特征。"
        "仅输出一个 JSON 对象（不要 markdown 代码块、不要额外解释），"
        "必须使用以下英文 key、值用中文填写、不得留空：\n"
        '{"name": "风格卡名称，如『冷峻硬汉』", "category": "流派/定位，如『悬疑』", '
        '"rhythm": "叙事节奏：快慢、张弛、场景切换密度", "sentence": "句式特征：长短句配比、语序、标点", '
        '"diction": "用词偏好：书面/口语、雅俗", "imagery": "意象与比喻：取材、密度、感官通道", '
        '"dialogue": "对话风格：信息密度、潜台词、腔调", "subtext": "含蓄度：直白抒情还是留白克制", '
        '"narration": "叙述视角与心理距离", '
        '"signatures": ["标志性笔法，每条一句，描述手法不给原句"], "taboo": ["要避免的笔法，每条一句"]}\n'
        "只描述笔法，不复述样本的情节/人名/原句。\n\n"
        "写作样本：\n" + sample[:EXTRACT_SAMPLE_MAX_CHARS]
    )
    card = client.complete_json(
        [system_message, {"role": "user", "content": user_content}],
        response_model=WriterStyleCard,
    )
    fields = model_to_dict(card)
    empty = _empty_fields(fields)
    if empty:
        log_event("writer_style", "extract_empty_retry", fields=empty)
        retry_content = (
            f"{user_content}\n\n上一稿以下风格维度缺失，本次必须补全、不得留空："
            + "、".join(empty)
        )
        try:
            retry_card = client.complete_json(
                [system_message, {"role": "user", "content": retry_content}],
                response_model=WriterStyleCard,
            )
            retry_fields = model_to_dict(retry_card)
            if len(_empty_fields(retry_fields)) < len(empty):
                fields = retry_fields
                empty = _empty_fields(fields)
        except Exception as exc:
            log_event("writer_style", "extract_empty_retry_error", error=str(exc))

    fields, scrubbed = _scrub_sample_overlap(fields, sample)
    record: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source": "extract",
        "preset_id": "",
        "preset_version": 0,
        "scope": "book",
        "fields": fields,
        "generated_by": "style_extract_v1_mock" if client.is_mock else "style_extract_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "edited": False,
        "edited_at": "",
    }
    if empty:
        record["_incomplete_fields"] = empty
    if scrubbed:
        record["_scrubbed_fields"] = scrubbed
        log_event("writer_style", "extract_scrubbed", fields=scrubbed)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)
    log_event("writer_style", "extract_done", scrubbed=scrubbed)
    return record
