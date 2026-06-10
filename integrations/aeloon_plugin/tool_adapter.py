"""Adapt the shared MCP ``TOOL_SPECS`` into Aeloon agent ``Tool`` objects
(iter 049).

One spec list drives both the MCP server and Aeloon's LLM tools, so the two
hosts never drift. The Aeloon SDK is imported lazily inside :func:`build_tools`
so this module stays importable for inspection without Aeloon installed.
"""

from __future__ import annotations

from typing import Any, List

from ..mcp_server.tools import TOOL_SPECS, dispatch
from ..novel_ops import NovelOpsConfig

# Tools that only read server state (no workspace mutation) — lets Aeloon's
# task graph parallelise them safely.
_READ_ONLY = frozenset({"novel_status", "novel_open_workbench", "novel_list_books"})


def build_tools(client: Any, cfg: NovelOpsConfig) -> List[Any]:
    """Return one Aeloon ``Tool`` instance per shared spec, each bound to the
    given client + config. Imports ``aeloon`` lazily — only call inside a
    running Aeloon process."""
    from aeloon.core.agent.tools.base import Tool

    return [_make_tool(Tool, spec, client, cfg) for spec in TOOL_SPECS]


def _make_tool(tool_base: type, spec: dict, client: Any, cfg: NovelOpsConfig) -> Any:
    spec_name = spec["name"]
    spec_desc = spec["description"]
    spec_params = spec["inputSchema"]
    mode = "read_only" if spec_name in _READ_ONLY else "mutating"

    class _NovelTool(tool_base):  # type: ignore[misc, valid-type]
        @property
        def name(self) -> str:
            return spec_name

        @property
        def description(self) -> str:
            return spec_desc

        @property
        def parameters(self) -> dict:
            return spec_params

        @property
        def concurrency_mode(self) -> str:
            return mode

        async def execute(self, **kwargs: Any) -> str:
            try:
                return await dispatch(spec_name, kwargs, client, cfg)
            except Exception as exc:  # noqa: BLE001 - tool result must be a string, never a raise
                return f"❌ {spec_name} 执行出错：{type(exc).__name__}: {exc}"

    _NovelTool.__name__ = f"NovelTool_{spec_name}"
    return _NovelTool()
