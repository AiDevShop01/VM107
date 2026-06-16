"""Phase 87 Wave 4b — VM101 typed economic_event API client.

Pulls the last N hours of releases from VM101's
``/api/v2/economic-event/list`` endpoint. Per the Phase 47.2 cross-VM
filesystem lock: no parquet, no /cold-data, no shared filesystem reads.

Env-driven fail-fast per CLAUDE.md ``env-driven-no-fallbacks`` lock —
``VM101_INTERNAL_BASE_URL`` MUST be set or construction raises
``RuntimeError`` at the call site (NOT a silent localhost fallback).
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)


class ReleasePoller:
    """Thin HTTPX client around VM101's typed economic_event endpoint.

    The hourly tick of ``MacroStoryTracker`` calls ``poll_recent_releases``
    once. The retirement sweep at the end of the tick calls it again with
    ``hours = 12 * 7 * 24`` to gather the per-indicator history needed by
    ``check_retirement``.
    """

    def __init__(self, vm101_internal_base_url: str | None = None) -> None:
        url = vm101_internal_base_url or os.environ.get("VM101_INTERNAL_BASE_URL")
        if not url:
            raise RuntimeError(
                "VM101_INTERNAL_BASE_URL required — env-driven, no default "
                "(CLAUDE.md env-driven-no-fallbacks lock)"
            )
        self._base = url.rstrip("/")
        self._client = httpx.Client(timeout=10.0)

    def poll_recent_releases(self, hours: int = 6) -> list[dict]:
        """GET ``/api/v2/economic-event/list?hours=N`` and return the rows.

        Returns the ``releases`` list from the JSON body, or an empty list
        when the response omits it. Raises ``httpx.HTTPStatusError`` on
        non-2xx so the agent's outer try/except can log + skip the tick.
        """
        resp = self._client.get(
            f"{self._base}/api/v2/economic-event/list",
            params={"hours": hours},
        )
        resp.raise_for_status()
        body = resp.json()
        return body.get("releases", [])

    def close(self) -> None:
        self._client.close()
