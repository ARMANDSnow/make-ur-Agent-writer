"""User-facing error catalog for the WebUI (iter062).

Turns raw exceptions and readiness blocker codes into a single friendly
card shape so the frontend only has to render, never to interpret::

    {code, title, cause, actions: [{label, href|action}], trace_id, technical}

Design rules:

* ``technical`` is **withheld from the client by default**
  (``expose_technical=False``). Raw exception strings keep going to stderr
  logs only — we preserve the existing "never leak tracebacks to the
  client" guarantee (``server.py`` top-level handler) while still handing
  the user a human-readable title + cause + next step.
* Readiness cards are **derived** from ``src/readiness_catalog`` (iter063
  Part C). That core module is the single source of truth shared by
  ``book_runner._primary_blocker`` and the injected frontend catalog
  (``window.READINESS_CATALOG``), so the three former copies can no longer
  drift. ``readiness_catalog`` imports only ``typing`` — pulling it in keeps
  this module importable without spinning up the server or touching data.

Pure data + pure functions: only ``json`` / ``typing`` / ``readiness_catalog``
imports so tests can import it without spinning up the server.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from .. import readiness_catalog

# ---------------------------------------------------------------------------
# Catalogs
# ---------------------------------------------------------------------------

# General / exception-derived codes. ``action`` strings must match the
# frontend ``bindCtaActions`` dispatch table.
_CATALOG: Dict[str, Dict[str, Any]] = {
    "bad_json": {
        "title": "请求格式有误",
        "cause": "提交的数据不是合法 JSON，可能是请求被中断或客户端版本过旧。",
        "actions": [{"label": "刷新页面重试", "action": "reload"}],
    },
    "file_missing": {
        "title": "所需文件缺失",
        "cause": "需要的产物还没生成或已被移动，按工作台步骤生成后即可继续。",
        "actions": [{"label": "回到工作台", "action": "go_workbench"}],
    },
    "invalid_value": {
        "title": "输入不被接受",
        "cause": "{detail}",
        "actions": [],
    },
    "io_error": {
        "title": "读写文件失败",
        "cause": "磁盘读写出错，可能是文件损坏或权限问题。",
        "actions": [{"label": "查看诊断", "action": "show_diagnostics"}],
    },
    "encoding_error": {
        "title": "文件编码异常",
        "cause": "文件不是 UTF-8 编码，无法读取。请改存为 UTF-8 再试。",
        "actions": [{"label": "查看诊断", "action": "show_diagnostics"}],
    },
    "workspace_busy": {
        "title": "工作区忙",
        "cause": "另一个任务正在占用该作品，等它结束或去任务页查看。",
        "actions": [{"label": "去任务页", "action": "go_jobs"}],
    },
    "server_error": {
        "title": "服务器内部错误",
        "cause": "出了点意外，已经记录下来。把下方编号告诉维护者便于排查。",
        "actions": [{"label": "刷新重试", "action": "reload"}],
    },
    # iter063 A3: onboarding-upload validation. The wizard's simplified
    # renderErrorCard only shows title + cause (no action buttons), so these
    # carry the actionable next step inside ``cause`` instead of ``actions``.
    "upload_no_chapters": {
        "title": "没找到章节标题",
        "cause": "文件里没有「第1章」「Chapter 1」这类章节标题，整本会被切成 0 章。请确认原文带章节标题，或换一个文件再上传。",
        "actions": [],
    },
    "upload_not_utf8": {
        "title": "文件不是 UTF-8 编码",
        "cause": "无法按 UTF-8 读取该文件。请用编辑器把它另存为 UTF-8 编码后再上传。",
        "actions": [],
    },
    "invalid_workspace_name": {
        "title": "作品名不合法",
        "cause": "作品名只能用中文 / 字母 / 数字 / 下划线，中间可含连字符，长度不超过 32 个字符，请换个名字。",
        "actions": [],
    },
    # iter063 A2: draft md saved but meta.json sync failed. The body is on disk,
    # so "保存失败" would be a lie; the chapter sits at draft_hash_mismatch
    # (fail-safe) until a re-save lands the meta. Raw exc goes to stderr only.
    "draft_meta_unsynced": {
        "title": "正文已保存，元数据待同步",
        "cause": "正文已写入磁盘，但元数据同步失败；该章会暂时显示「草稿校验未通过」，再保存一次即可修复，已写好的正文不会丢。",
        "actions": [{"label": "重试保存", "action": "reload"}],
    },
}

# Readiness blocker kind -> friendly card. iter063 Part C: derived from the
# shared src/readiness_catalog (label/cause/cta_*) so card text can't drift
# from book_runner._primary_blocker or the frontend's injected catalog.
_READINESS: Dict[str, Dict[str, Any]] = {
    kind: {
        "title": spec["label"],
        "cause": spec["cause"],
        "actions": [{"label": spec["cta_label"], "action": spec["cta_action"]}],
    }
    for kind, spec in readiness_catalog.KINDS.items()
}

DEFAULT_CODE = "server_error"
_GENERIC_INVALID = "输入有误，请检查后重试。"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def code_for_exception(exc: BaseException) -> str:
    """Map a raw exception to a catalog code.

    Order matters: JSONDecodeError and UnicodeDecodeError subclass
    ValueError, and FileNotFoundError subclasses OSError — check the
    specific types first.
    """
    if isinstance(exc, json.JSONDecodeError):
        return "bad_json"
    if isinstance(exc, FileNotFoundError):
        return "file_missing"
    if isinstance(exc, UnicodeDecodeError):
        return "encoding_error"
    if isinstance(exc, ValueError):
        return "invalid_value"
    if isinstance(exc, OSError):
        return "io_error"
    return "server_error"


def _spec_for(code: str) -> Dict[str, Any]:
    return _CATALOG.get(code) or _READINESS.get(code) or _CATALOG[DEFAULT_CODE]


def build_card(
    code: str,
    *,
    detail: str = "",
    trace_id: str = "",
    technical: str = "",
) -> Dict[str, Any]:
    """Build a card dict from a known code. Unknown codes degrade to server_error."""
    spec = _spec_for(code)
    resolved_code = code if (code in _CATALOG or code in _READINESS) else DEFAULT_CODE
    cause = spec["cause"]
    if "{detail}" in cause:
        cause = cause.format(detail=detail) if detail.strip() else _GENERIC_INVALID
    return {
        "code": resolved_code,
        "title": spec["title"],
        "cause": cause,
        "actions": [dict(a) for a in spec.get("actions", [])],
        "trace_id": trace_id,
        "technical": technical,
    }


def card_for_exception(
    exc: BaseException,
    *,
    trace_id: str = "",
    expose_technical: bool = False,
) -> Dict[str, Any]:
    """Build a friendly card from a raw exception.

    ``technical`` stays empty unless ``expose_technical`` is explicitly set —
    raw exception text is for stderr logs, not the client.
    """
    code = code_for_exception(exc)
    technical = f"{type(exc).__name__}: {exc}" if expose_technical else ""
    return build_card(code, detail=str(exc), trace_id=trace_id, technical=technical)


def readiness_kind(blocker: str) -> str:
    """Classify a raw readiness blocker string into a known kind.

    iter063 Part C: delegates to the shared ``readiness_catalog.classify`` —
    the same function ``book_runner._blocker_kind`` now uses, so the diagnostic
    list and the primary-blocker path can never classify differently.
    """
    return readiness_catalog.classify(blocker)


def readiness_card(blocker: str) -> Dict[str, Any]:
    """Friendly card for a readiness blocker (raw string or kind)."""
    return build_card(readiness_kind(blocker))


def error_body(card: Dict[str, Any]) -> Dict[str, Any]:
    """JSON body for an error response: keep ``error`` (title) for backward
    compatibility, add ``card`` for the new frontend component."""
    return {"error": card.get("title", "出错了"), "card": card}
