"""Error type for :mod:`integrations.novel_client`."""

from __future__ import annotations

from typing import Any, Optional


class NovelApiError(Exception):
    """Raised when the WebUI returns a non-2xx response or is unreachable.

    ``status_code`` is the HTTP status (``0`` for a transport/connection
    error, where no response was received). ``payload`` is the decoded JSON
    body when available — callers inspect e.g. ``payload.get("running_job_id")``
    on a 409 or ``status_code == 404`` to branch on the failure shape.
    """

    def __init__(
        self,
        status_code: int,
        payload: Optional[Any],
        message: Optional[str] = None,
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self.message = message or f"HTTP {status_code}"
        super().__init__(f"[{status_code}] {self.message}")

    @property
    def running_job_id(self) -> Optional[str]:
        """The conflicting job id surfaced by a 409 busy response, if any."""
        if isinstance(self.payload, dict):
            value = self.payload.get("running_job_id")
            if isinstance(value, str):
                return value
        return None
