"""Phase 83 Plan 09 — VM107 → VM100 calendar client (Decision D1 consumer side).

Sync httpx (Open Question 1 — consistency with existing 8 VM107 clients).
Returns [] on transient failure so composer can fall through to tiered
degradation (Decision H1).

Env-driven config (CLAUDE.md lock — no fallback defaults for required vars):
  MACRO_EMITTER_CALENDAR_URL  — required: base URL of VM100 (e.g. http://vm100-backend:8000)
  VM107_SERVICE_JWT            — required: HS256 bearer token for JWTAuth gate
  MACRO_EMITTER_CALENDAR_TIMEOUT_SEC — optional: default 5 seconds
"""
from __future__ import annotations

import logging
import os
from typing import List

import httpx

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fail-fast module-level env validation (CLAUDE.md env-driven-config lock)
# No os.getenv("X", "default") — fail at import if required vars missing.
# ---------------------------------------------------------------------------
_BASE_URL: str = os.environ["MACRO_EMITTER_CALENDAR_URL"]
_JWT: str = os.environ["VM107_SERVICE_JWT"]
_TIMEOUT: float = float(os.environ.get("MACRO_EMITTER_CALENDAR_TIMEOUT_SEC", "5"))


class MacroCalendarHTTPClient:
    """VM107 → VM100 calendar HTTP client (Decision D1).

    Calls GET /api/v1/mission-control/calendar/upcoming on the VM100 backend.
    Returns the items list directly ([]  on any transient failure).

    Constructor accepts explicit overrides so tests can bypass the module-level
    env constants without needing to reload the module.
    """

    def __init__(
        self,
        base_url: str = _BASE_URL,
        jwt: str = _JWT,
        timeout_sec: float = _TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._jwt = jwt
        self._timeout = timeout_sec

    def fetch_upcoming(self, hours: int = 24) -> List[dict]:
        """Fetch upcoming calendar events from VM100.

        Args:
            hours: Lookahead window in hours (passed as ?hours= query param).

        Returns:
            List of UpcomingCalendarItem dicts per Plan 07 schema.
            Returns [] on any transient failure (HTTP error, network error, parse error).
            Composer handles the empty-list Tier-1/Tier-3 degradation path.
        """
        url = f"{self._base_url}/api/v1/mission-control/calendar/upcoming"
        try:
            response = httpx.get(
                url,
                params={"hours": hours},
                headers={"Authorization": f"Bearer {self._jwt}"},
                timeout=self._timeout,
            )
            response.raise_for_status()
            return response.json().get("items", [])
        except (httpx.HTTPStatusError, httpx.HTTPError, httpx.RequestError) as exc:
            log.warning(
                "MacroCalendarHTTPClient.fetch_upcoming degraded (returning []): %s: %r",
                type(exc).__name__,
                exc,
            )
            return []
        except Exception as exc:
            # Broad catch for JSON parse errors, KeyError, etc.
            log.warning(
                "MacroCalendarHTTPClient.fetch_upcoming unexpected error (returning []): %s: %r",
                type(exc).__name__,
                exc,
            )
            return []
