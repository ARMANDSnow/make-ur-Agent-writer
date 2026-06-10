"""Aeloon-Pro plugin package (iter 049).

Only the SDK-free command surface is re-exported here so tests and tooling can
``import integrations.aeloon_plugin`` without the Aeloon SDK present. The
SDK-coupled :class:`~integrations.aeloon_plugin.plugin.NovelPlugin` is imported
by Aeloon via the manifest ``entry`` (``...plugin:NovelPlugin``) only.
"""

from .commands import HELP_TEXT, parse_novel_command, run_novel_command

__all__ = ["parse_novel_command", "run_novel_command", "HELP_TEXT"]
