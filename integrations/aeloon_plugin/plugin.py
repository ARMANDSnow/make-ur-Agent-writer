"""Aeloon-Pro plugin entry (iter 049).

Thin glue: the ONLY module that imports the Aeloon SDK. It builds the shared
:class:`~integrations.novel_client.NovelClient` from plugin config, registers
the ``/novel`` command + LLM tools, and forwards each invocation to the
host-agnostic :mod:`integrations.aeloon_plugin.commands` layer. All real logic
lives there and in :mod:`integrations.novel_ops`, so it is unit-tested without
this SDK present.

Install: see ``README.md`` — a ``.pth`` puts this repo on Aeloon's import path
and a manifest under ``~/.aeloon/plugins/`` makes the plugin discoverable
(Aeloon's loader uses plain ``importlib`` and never extends ``sys.path``).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, List, Optional

from pydantic import BaseModel, Field

from aeloon.plugins._sdk import CommandContext, Plugin

from ..novel_client import NovelClient
from ..novel_ops import NovelOpsConfig
from . import tool_adapter
from .commands import parse_novel_command, run_novel_command

if TYPE_CHECKING:  # PluginAPI is a type-only import (matches Aeloon's Wiki plugin)
    from aeloon.plugins._sdk.api import PluginAPI


class NovelPluginConfig(BaseModel):
    """Plugin config. Aeloon merges ``~/.aeloon/config.json`` →
    ``api.config``; env vars are the fallback for headless runs."""

    base_url: str = Field(default="http://127.0.0.1:8765", description="续写服务地址")
    api_token: str = Field(default="", description="可选 bearer token（对应服务端 NOVEL_API_TOKEN）")
    default_book: str = Field(default="", description="默认作品名；省略则用唯一的那本")
    write_tier: str = Field(default="mid", description="写作档位 high/mid/low")
    write_budget_cny: float = Field(default=5.0, description="单次写作预算（元）")
    outline_chapters: int = Field(default=3, description="细纲默认章数")
    write_chapters: int = Field(default=1, description="正文默认章数")
    request_timeout_s: float = Field(default=30.0, description="单请求超时（秒）")
    job_timeout_s: float = Field(default=3600.0, description="单任务轮询超时（秒）")


class NovelPlugin(Plugin):
    """`/novel` command + LLM tools that drive the continuer WebUI over HTTP."""

    def __init__(self) -> None:
        self._client: Optional[NovelClient] = None
        self._ops_cfg = NovelOpsConfig()
        self._tools: List[Any] = []

    # -- lifecycle ----------------------------------------------------------

    def register(self, api: PluginAPI) -> None:
        api.register_config_schema(NovelPluginConfig)
        api.register_command(
            "novel",
            self._handle_novel,
            description="一句话开书并多 agent 续写中文小说（/novel help 看用法）",
        )
        self._build(api)
        for tool in self._tools:
            api.register_tool(tool)

    async def activate(self, api: PluginAPI) -> None:
        # Build happens once in register() — the config is already available
        # there and the registered tools must reference the same client the
        # command handler uses. Nothing to warm up; kept for lifecycle clarity.
        return None

    # -- internals ----------------------------------------------------------

    def _build(self, api: PluginAPI) -> None:
        raw = dict(getattr(api, "config", None) or {})
        known = {k: raw[k] for k in raw if k in NovelPluginConfig.model_fields}
        conf = NovelPluginConfig(**known)
        base_url = conf.base_url or os.environ.get("NOVEL_BASE_URL", "http://127.0.0.1:8765")
        token = conf.api_token or os.environ.get("NOVEL_API_TOKEN", "")
        self._client = NovelClient(
            base_url=base_url,
            api_token=token or None,
            request_timeout_s=conf.request_timeout_s,
            job_timeout_s=conf.job_timeout_s,
        )
        self._ops_cfg = NovelOpsConfig(
            default_book=conf.default_book or None,
            write_tier=conf.write_tier,
            write_budget_cny=conf.write_budget_cny,
            outline_chapters=conf.outline_chapters,
            write_chapters=conf.write_chapters,
        )
        self._tools = tool_adapter.build_tools(self._client, self._ops_cfg)

    async def _handle_novel(self, ctx: CommandContext, args: str) -> Optional[str]:
        verb, kwargs = parse_novel_command(args)

        async def _emit(text: str) -> None:
            try:
                await ctx.send_progress(text)
            except Exception:  # progress is best-effort (e.g. wechat channel)
                pass

        result = await run_novel_command(
            verb, kwargs, self._client, self._ops_cfg, emit=_emit
        )
        await ctx.reply(result)
        return None
