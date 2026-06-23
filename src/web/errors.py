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
* Readiness text is kept verbatim in sync with
  ``book_runner._primary_blocker`` labels. This module is the single source
  going forward; we deliberately do **not** merge the three catalogs this
  round (frontend ``CTA_ACTIONS`` / backend ``_primary_blocker`` / here) —
  see iteration_062 Notes. Drift is guarded by tests.

Pure data + pure functions: only ``json`` / ``typing`` imports so tests can
import it without spinning up the server or touching optional data sources.
"""

from __future__ import annotations

import json
from typing import Any, Dict

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
}

# Readiness blocker kind -> friendly card. Titles/actions aligned verbatim
# with book_runner._primary_blocker.labels (src/book_runner.py).
_READINESS: Dict[str, Dict[str, Any]] = {
    "start_point_missing": {
        "title": "未设置续写起点",
        "cause": "先选定从原作哪一章之后开始续写，之后才能生成章节计划。",
        "actions": [{"label": "去设置起点", "action": "scroll_to_start_point"}],
    },
    "outline_missing": {
        "title": "缺少全书大纲",
        "cause": "先生成或检查全书走向，再进入章节续写。",
        "actions": [{"label": "去计划页", "action": "go_plan"}],
    },
    "chapter_plan_missing": {
        "title": "缺少章节计划",
        "cause": "续写需要本章计划，可先用默认目标章数生成。",
        "actions": [{"label": "生成章节计划", "action": "run_plan_chapters"}],
    },
    "chapter_plan_invalid": {
        "title": "章节计划文件损坏",
        "cause": "章节计划文件无法读取，重新生成即可修复，已写好的正文不受影响。",
        "actions": [{"label": "重新生成计划", "action": "run_plan_chapters"}],
    },
    "retry_exhausted": {
        "title": "已有草稿未通过",
        "cause": "本章已有草稿但未达通过门槛，可查看后重试。",
        "actions": [{"label": "查看并重试", "action": "retry_write_book"}],
    },
    "preflight_failed": {
        "title": "工程预检未通过",
        "cause": "上游配置或数据预检没通过，先看诊断再续写。",
        "actions": [{"label": "查看诊断", "action": "show_diagnostics"}],
    },
    "foreshadowing_overdue": {
        "title": "有 must-resolve 伏笔超期未回收",
        "cause": "存在标记为必须回收的伏笔超期未回收。",
        "actions": [{"label": "查看诊断", "action": "show_diagnostics"}],
    },
    "unknown": {
        "title": "续写入口受阻",
        "cause": "续写前置条件未满足，查看诊断了解详情。",
        "actions": [{"label": "查看诊断", "action": "show_diagnostics"}],
    },
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

    Mirrors book_runner._blocker_kind so the diagnostic list can be
    translated independently of the primary-blocker path.
    """
    if blocker in _READINESS:
        return blocker
    # Below: prefixed / substring variants that are not exact catalog keys
    # (exact keys already returned above).
    if blocker.startswith("chapter_plan:") or "plan_item_missing" in blocker:
        return "chapter_plan_missing"
    if blocker.startswith("outline_missing") or "outline_missing" in blocker:
        return "outline_missing"
    if "retry_exhausted" in blocker or "existing_output_not_strict_approved" in blocker:
        return "retry_exhausted"
    if blocker.startswith("preflight:"):
        return "preflight_failed"
    if blocker.startswith("foreshadowing_must_resolve_overdue") or blocker.startswith("foreshadowing_gate_error"):
        return "foreshadowing_overdue"
    return "unknown"


def readiness_card(blocker: str) -> Dict[str, Any]:
    """Friendly card for a readiness blocker (raw string or kind)."""
    return build_card(readiness_kind(blocker))


def error_body(card: Dict[str, Any]) -> Dict[str, Any]:
    """JSON body for an error response: keep ``error`` (title) for backward
    compatibility, add ``card`` for the new frontend component."""
    return {"error": card.get("title", "出错了"), "card": card}
