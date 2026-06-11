"""HTTP client for the continuer WebUI job API (iter 049)."""

from .client import NovelClient, TERMINAL_STATUSES
from .errors import NovelApiError

__all__ = ["NovelClient", "NovelApiError", "TERMINAL_STATUSES"]
