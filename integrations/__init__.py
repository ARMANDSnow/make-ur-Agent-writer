"""Outbound integrations for the Dragon Raja continuer (iter 049).

This package adapts the continuer's local WebUI (``python3 main.py web``,
default ``http://127.0.0.1:8765``) to third-party agent hosts:

* ``novel_client`` — a dependency-free async HTTP client for the WebUI's
  job API (stdlib urllib offloaded to a thread, so it never blocks an
  asyncio event loop).
* ``novel_ops`` — host-agnostic operations + markdown formatting shared by
  both adapters; fully unit-testable under ``OPENAI_MODEL=mock`` with no
  host SDK installed.
* ``aeloon_plugin`` — an Aeloon-Pro plugin (commands + LLM tools) that wires
  Aeloon's ``CommandContext`` to ``novel_ops``.
* ``mcp_server`` — an MCP stdio server exposing the same operations so any
  MCP host (Aeloon, Claude Code, …) can drive the continuer.

The adapters talk HTTP to a separately-running WebUI process rather than
importing ``src`` inline: the pipeline is synchronous and minutes-long, so
running it inside a host's event loop would stall it, and the "jump to the
workbench" deep-link requires the HTTP server to be up anyway.
"""
