"""Host-agnostic ``/novel`` command parsing + routing (iter 049).

Deliberately free of the Aeloon SDK so the whole command surface is unit
testable under ``OPENAI_MODEL=mock`` with a fake client. ``plugin.py`` is the
only module that imports the SDK; it unwraps the host ``CommandContext`` and
delegates here. All real work lives in :mod:`integrations.novel_ops`.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, Union

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

Emit = Callable[[str], Union[None, Awaitable[None]]]

# subcommand aliases → canonical verb (English + 常用中文)
_ALIASES = {
    "new": "new", "开书": "new", "n": "new",
    "prepare": "prepare", "准备": "prepare",
    "outline": "outline", "细纲": "outline", "大纲": "outline",
    "write": "write", "写": "write", "续写": "write",
    "auto": "auto", "一键": "auto",
    "status": "status", "状态": "status", "s": "status",
    "open": "open", "打开": "open",
    "list": "list", "列表": "list", "ls": "list",
    "help": "help", "帮助": "help", "?": "help",
}

HELP_TEXT = (
    "**小说续写工作台** — 在聊天里开书、出细纲、写正文；精修点链接跳网页工作台。\n\n"
    "- `/novel new <一句话设定>` —— 开新书并自动准备设定（可 `… as 书名` 指定名字）\n"
    "- `/novel outline [章数]` —— 生成章节细纲（默认 3 章）\n"
    "- `/novel write [章数]` —— 续写正文（默认 1 章，带 5+1 评审）\n"
    "- `/novel auto [章数]` —— 一键从当前进度跑到正文\n"
    "- `/novel status [书名]` —— 查看四步进度\n"
    "- `/novel open [书名]` —— 返回网页工作台链接\n"
    "- `/novel list` —— 列出所有作品\n"
    "- `/novel prepare [书名]` —— 重新准备设定\n"
)


def _count_and_book(rest: str) -> Dict[str, Any]:
    """Parse the ``[book] [chapters]`` / ``[chapters]`` tail shared by
    write / outline / auto. A leading number is章数; otherwise the first token
    is the book name and a trailing number is章数."""
    out: Dict[str, Any] = {}
    tokens = rest.split()
    if not tokens:
        return out
    if tokens[0].isdigit():
        out["chapters"] = int(tokens[0])
        return out
    out["book"] = tokens[0]
    if len(tokens) > 1 and tokens[1].isdigit():
        out["chapters"] = int(tokens[1])
    return out


def parse_novel_command(args: str) -> Tuple[str, Dict[str, Any]]:
    """Split ``/novel`` arguments into ``(verb, kwargs)``. Unknown / empty →
    ``("help", {})``. Pure and deterministic — the unit-test seam."""
    text = (args or "").strip()
    if not text:
        return "help", {}
    head, _, rest = text.partition(" ")
    rest = rest.strip()
    verb = _ALIASES.get(head.lower())
    if verb is None:
        return "help", {}
    if verb == "new":
        premise, sep, name = rest.rpartition(" as ")
        if sep:  # explicit "<premise> as <name>"
            return "new", {"premise": premise.strip(), "name": (name.strip() or None)}
        return "new", {"premise": rest, "name": None}
    if verb in ("write", "outline", "auto"):
        return verb, _count_and_book(rest)
    if verb in ("status", "open", "prepare"):
        return verb, {"book": (rest or None)}
    if verb == "list":
        return "list", {}
    return "help", {}


async def run_novel_command(
    verb: str,
    kwargs: Dict[str, Any],
    client: Any,
    cfg: NovelOpsConfig,
    *,
    emit: Optional[Emit] = None,
) -> str:
    """Route a parsed command to the matching ``novel_ops`` coroutine and
    return its Markdown reply. ``emit`` streams progress for long jobs.

    Ops already convert :class:`NovelApiError` (transport/HTTP) into friendly
    Markdown; this wrapper additionally catches the *unexpected* (KeyError /
    TypeError / …) so a chat message degrades gracefully instead of crashing
    the host's command handler."""
    try:
        return await _route_novel_command(verb, kwargs, client, cfg, emit)
    except Exception as exc:  # noqa: BLE001 - last-resort friendly degrade
        return f"❌ 处理 `/novel {verb}` 时出错：{type(exc).__name__}: {exc}"


async def _route_novel_command(
    verb: str,
    kwargs: Dict[str, Any],
    client: Any,
    cfg: NovelOpsConfig,
    emit: Optional[Emit],
) -> str:
    book = kwargs.get("book")
    chapters = kwargs.get("chapters")
    if verb == "new":
        return await op_new(client, kwargs.get("premise", ""), kwargs.get("name"), emit=emit, cfg=cfg)
    if verb == "prepare":
        return await op_prepare(client, book, emit=emit, cfg=cfg)
    if verb == "outline":
        return await op_outline(client, book, chapters, emit=emit, cfg=cfg)
    if verb == "write":
        return await op_write(client, book, chapters, emit=emit, cfg=cfg)
    if verb == "auto":
        return await op_auto(client, book, chapters, emit=emit, cfg=cfg)
    if verb == "status":
        return await op_status(client, book, cfg=cfg)
    if verb == "open":
        return await op_open(client, book, cfg=cfg)
    if verb == "list":
        return await op_list(client, cfg=cfg)
    return HELP_TEXT
