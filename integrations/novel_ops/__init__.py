"""Host-agnostic operations + formatting shared by the Aeloon plugin and the
MCP server (iter 049).

Every ``op_*`` coroutine takes a :class:`~integrations.novel_client.NovelClient`,
an optional :class:`NovelOpsConfig`, and an optional ``emit`` progress callback
(sync or async), and returns a Markdown string suitable for a chat reply. All
logic lives here so it is unit-testable with a fake client and no host SDK.
"""

from .config import NovelOpsConfig
from .ops import (
    op_auto,
    op_new,
    op_open,
    op_outline,
    op_prepare,
    op_status,
    op_list,
    op_write,
)

__all__ = [
    "NovelOpsConfig",
    "op_new",
    "op_prepare",
    "op_outline",
    "op_write",
    "op_auto",
    "op_status",
    "op_list",
    "op_open",
]
