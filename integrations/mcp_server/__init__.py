"""MCP server exposing the continuer's operations (iter 049).

``tools.py`` holds the tool specs + dispatch as pure data/logic (no ``mcp``
import, so it is unit-testable); ``server.py`` binds them to the MCP SDK's
stdio transport. Run with ``python -m integrations.mcp_server.server`` after
``pip install mcp`` (see integrations/requirements.txt).
"""
