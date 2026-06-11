"""MCP tool specs + dispatch (iter 049) — pure, no ``mcp`` dependency.

``TOOL_SPECS`` is a list of ``{name, description, inputSchema}`` dicts that
``server.py`` turns into MCP ``Tool`` objects. ``dispatch()`` routes a tool
call to the matching ``novel_ops`` coroutine and returns a Markdown string.
Keeping both here means the routing + schemas are testable under
``OPENAI_MODEL=mock`` without importing the MCP SDK.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..novel_ops import (
    NovelOpsConfig,
    op_auto,
    op_list,
    op_new,
    op_open,
    op_outline,
    op_prepare,
    op_status,
    op_write,
)

_BOOK_PROP = {
    "book": {
        "type": "string",
        "description": "工作区/书名；省略则用默认书或唯一的那本书",
    }
}

TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "novel_create",
        "description": "用一句话设定开一本新书，并自动完成设定准备（创建工作区 + 抽取设定）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "premise": {"type": "string", "description": "一句话故事设定"},
                "name": {"type": "string", "description": "可选的工作区名（仅字母数字/下划线/中文）"},
            },
            "required": ["premise"],
        },
    },
    {
        "name": "novel_prepare",
        "description": "（重新）运行设定准备阶段：抽取设定、压缩知识库、引导锚点。",
        "inputSchema": {"type": "object", "properties": dict(_BOOK_PROP)},
    },
    {
        "name": "novel_plan_outline",
        "description": "生成章节细纲（需要时先做故事大纲），完成后返回细纲摘要。",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_BOOK_PROP,
                "chapters": {"type": "integer", "minimum": 1, "maximum": 200, "description": "细纲章数，默认 3"},
            },
        },
    },
    {
        "name": "novel_write_chapters",
        "description": "续写正文若干章（先做就绪检查；带 5+1 评审与重写）。返回写作结果与花费。",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_BOOK_PROP,
                "chapters": {"type": "integer", "minimum": 1, "description": "续写章数，默认 1"},
                "tier": {"type": "string", "description": "模型档位 high/mid/low，默认 mid"},
                "budget_cny": {"type": "number", "minimum": 0, "description": "本次预算（元），0 表示不限"},
            },
        },
    },
    {
        "name": "novel_auto",
        "description": "一键续写：从当前进度自动推进设定→大纲→细纲→正文，直到写出正文。适合“帮我接着写”这类整体请求。",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_BOOK_PROP,
                "chapters": {"type": "integer", "minimum": 1, "description": "最终正文阶段续写的章数，默认 1"},
            },
        },
    },
    {
        "name": "novel_status",
        "description": "查看一本书在四步工作台中的进度（设定/大纲/细纲/正文）。",
        "inputSchema": {"type": "object", "properties": dict(_BOOK_PROP)},
    },
    {
        "name": "novel_open_workbench",
        "description": "返回这本书的工作台网页链接，用于在浏览器里精修大纲/阅读正文。",
        "inputSchema": {"type": "object", "properties": dict(_BOOK_PROP)},
    },
    {
        "name": "novel_list_books",
        "description": "列出当前所有作品（工作区）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

TOOL_NAMES = frozenset(s["name"] for s in TOOL_SPECS)


async def dispatch(
    name: str,
    arguments: Optional[Dict[str, Any]],
    client: Any,
    cfg: Optional[NovelOpsConfig] = None,
) -> str:
    """Route an MCP tool call to the matching op. Raises ``ValueError`` for
    an unknown tool name. MCP has no streaming progress channel here, so no
    ``emit`` is passed — ops block on the job-poll loop and return a summary."""
    cfg = cfg or NovelOpsConfig()
    args = arguments or {}
    if name == "novel_create":
        return await op_new(client, args.get("premise", ""), args.get("name"), cfg=cfg)
    if name == "novel_prepare":
        return await op_prepare(client, args.get("book"), cfg=cfg)
    if name == "novel_plan_outline":
        return await op_outline(client, args.get("book"), args.get("chapters"), cfg=cfg)
    if name == "novel_write_chapters":
        return await op_write(
            client,
            args.get("book"),
            args.get("chapters"),
            tier=args.get("tier"),
            budget_cny=args.get("budget_cny"),
            cfg=cfg,
        )
    if name == "novel_auto":
        return await op_auto(client, args.get("book"), args.get("chapters"), cfg=cfg)
    if name == "novel_status":
        return await op_status(client, args.get("book"), cfg=cfg)
    if name == "novel_open_workbench":
        return await op_open(client, args.get("book"), cfg=cfg)
    if name == "novel_list_books":
        return await op_list(client, cfg=cfg)
    raise ValueError(f"unknown tool: {name}")
