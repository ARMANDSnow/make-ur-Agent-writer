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

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any, List, Optional

from pydantic import BaseModel, Field

from aeloon.plugins._sdk import CommandContext, Plugin

# stdlib-only, SDK-free helper —— 只拉标准库，不触发续写重依赖（见其模块 docstring）。
from src.web.background import (
    BackendHandle,
    ensure_backend_running,
    parse_base_url,
    stop_backend,
)

from ..novel_client import NovelClient
from ..novel_ops import NovelOpsConfig
from . import tool_adapter
from .commands import parse_novel_command, run_novel_command

if TYPE_CHECKING:  # PluginAPI is a type-only import (matches Aeloon's Wiki plugin)
    from aeloon.plugins._sdk.api import PluginAPI

logger = logging.getLogger(__name__)


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
    auto_start_backend: bool = Field(
        default=True, description="loopback base_url 时随 aeloon 自动拉起续写后端 web 服务"
    )
    backend_ready_timeout_s: float = Field(
        default=20.0, description="自动启动后等待后端就绪的上限（秒）"
    )


class NovelPlugin(Plugin):
    """`/novel` command + LLM tools that drive the continuer WebUI over HTTP."""

    def __init__(self) -> None:
        self._client: Optional[NovelClient] = None
        self._ops_cfg = NovelOpsConfig()
        self._tools: List[Any] = []
        self._conf: Optional[NovelPluginConfig] = None
        self._base_url: str = ""
        self._backend: Optional[BackendHandle] = None

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
        """随 aeloon 启动幂等拉起续写后端，使 /novel 的网页工作台 deep-link 直接可达。

        best-effort：仅当 ``auto_start_backend`` 开启且 base_url 是 loopback 时才起
        *本地* 后端；远程 base_url 视作那边已有服务、跳过。一切失败都降级（记
        warning），绝不让 activate 抛异常拖垮 aeloon 的插件 boot —— 即便如此，
        ``register()`` 已注册的 ``/novel`` 命令仍在，只是首用时需手动起后端。
        """
        conf = self._conf
        if conf is None or not conf.auto_start_backend:
            return
        host, port, is_loopback = parse_base_url(self._base_url)
        if not is_loopback:
            logger.info("base_url=%s 非 loopback，跳过自动启动续写后端", self._base_url)
            return
        try:
            # ensure_backend_running 是同步阻塞（socket/subprocess/轮询），放线程池
            # 避免卡住 aeloon 的事件循环（同 NovelClient 处理阻塞 IO 的做法）。
            self._backend = await asyncio.to_thread(
                ensure_backend_running,
                host,
                port,
                token=(conf.api_token or os.environ.get("NOVEL_API_TOKEN") or None),
                wait_s=conf.backend_ready_timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 - 双保险：helper 不该抛，但绝不让 activate 失败
            logger.warning("自动启动续写后端被跳过：%r", exc)
            return
        if self._backend.reason:
            logger.warning("续写后端未自动就绪：%s", self._backend.reason)
        elif self._backend.started_by_us:
            logger.info("已随 aeloon 自动启动续写后端 http://%s:%d", host, port)
        else:
            logger.info("续写后端已在 http://%s:%d 运行，复用之", host, port)

    async def deactivate(self) -> None:
        """aeloon 退出时清理：只终止我们自己起的后端子进程（复用的/未起的不动）。"""
        if self._backend is not None:
            await asyncio.to_thread(stop_backend, self._backend)
            self._backend = None

    # -- internals ----------------------------------------------------------

    def _build(self, api: PluginAPI) -> None:
        raw = dict(getattr(api, "config", None) or {})
        known = {k: raw[k] for k in raw if k in NovelPluginConfig.model_fields}
        conf = NovelPluginConfig(**known)
        base_url = conf.base_url or os.environ.get("NOVEL_BASE_URL", "http://127.0.0.1:8765")
        token = conf.api_token or os.environ.get("NOVEL_API_TOKEN", "")
        # 存给 activate/deactivate 复用，避免重复解析 host 配置。
        self._conf = conf
        self._base_url = base_url
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
