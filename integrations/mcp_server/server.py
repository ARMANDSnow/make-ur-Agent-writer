"""MCP stdio server for the Dragon Raja continuer (iter 049).

Thin binding layer: it imports the MCP SDK and forwards every tool call to
:func:`integrations.mcp_server.tools.dispatch`. All routing/logic lives in
``tools.py`` (no ``mcp`` import there) so it stays unit-testable.

Run::

    pip install mcp                       # see integrations/requirements.txt
    NOVEL_BASE_URL=http://127.0.0.1:8765 \
        python -m integrations.mcp_server.server

Then register it in Aeloon's ``~/.aeloon/config.json`` ``mcpServers`` (type
``stdio``) or any MCP host's config (Claude Code ``.mcp.json``). The continuer
WebUI (``python3 main.py web``) must be running for tools to do anything.
"""

from __future__ import annotations

import asyncio
import os

from ..novel_client import NovelClient
from ..novel_ops import NovelOpsConfig
from . import tools as toolmod


def _env_float(name: str, default: float) -> float:
    # iter 051b (F8): a typo'd numeric env used to crash the whole MCP server
    # at startup (bare float()). Same semantics as src/config._env_float, but
    # local: integrations/ deliberately does not import the engine package.
    value = os.environ.get(name)
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _client_from_env() -> NovelClient:
    return NovelClient(
        os.environ.get("NOVEL_BASE_URL", "http://127.0.0.1:8765"),
        api_token=os.environ.get("NOVEL_API_TOKEN") or None,
        request_timeout_s=_env_float("NOVEL_REQUEST_TIMEOUT_S", 30.0),
        poll_interval_s=_env_float("NOVEL_POLL_INTERVAL_S", 2.0),
        job_timeout_s=_env_float("NOVEL_JOB_TIMEOUT_S", 3600.0),
    )


def _cfg_from_env() -> NovelOpsConfig:
    return NovelOpsConfig(
        default_book=os.environ.get("NOVEL_DEFAULT_BOOK") or None,
        write_tier=os.environ.get("NOVEL_WRITE_TIER", "mid"),
        write_budget_cny=_env_float("NOVEL_WRITE_BUDGET_CNY", 5.0),
    )


async def _amain() -> None:
    # Imported lazily so the module can be imported (and the rest of the
    # package tested) even when the optional ``mcp`` dependency is absent.
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    client = _client_from_env()
    cfg = _cfg_from_env()
    server = Server("dragon-raja-continuer")

    @server.list_tools()
    async def list_tools():  # noqa: ANN202 - SDK callback
        return [
            Tool(
                name=spec["name"],
                description=spec["description"],
                inputSchema=spec["inputSchema"],
            )
            for spec in toolmod.TOOL_SPECS
        ]

    @server.call_tool()
    async def call_tool(name, arguments):  # noqa: ANN001,ANN202 - SDK callback
        try:
            text = await toolmod.dispatch(name, arguments, client, cfg)
        except ValueError as exc:  # unknown tool
            text = f"❌ {exc}"
        except Exception as exc:  # noqa: BLE001 - degrade gracefully, don't crash the stdio loop
            text = f"❌ {name} 执行出错：{type(exc).__name__}: {exc}"
        return [TextContent(type="text", text=text)]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
