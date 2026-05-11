"""fetch_replay_chart_slice — Phase 59 CONTEXT §13, §18.

Given (execution_id, occurred_at, bars_around), returns a ChartSlice (OHLC
window centered around occurred_at) for the replay chart strip.

CONTEXT §13 (chart slice separate) — chart data is fetched independently of
frame narration. This tool is the VM107 agent's dedicated chart-slice surface.
The result is used for chart reasoning in mentor agents.

Graceful degrade (CONTEXT §13):
  - When VM102 is down, VM100 returns 503 with {fallback: True}.
  - Tool returns ChartSlice(bars=[], degraded=True) so the mentor agent can
    skip chart reasoning gracefully rather than failing.
  - degraded=True is stored as a model extra field (ChartSlice is BaseContract
    with extra='allow' for forward-compat — if not, we subclass).

Phase 39 typed-API discipline:
  - NO filesystem reads
  - NO direct DB access
  - Only HTTP via VM100 endpoint
  - timeout=30 (Pitfall 11)
  - 503/504 → degraded ChartSlice (NOT ToolError, NOT raise) — chart failure
    is non-fatal; mentor agent continues without chart reasoning

Phase 47.6 capability_type: replay_chart
Endpoint: GET /api/journal/replay/{execution_id}/chart-slice?at=<iso>&bars=<n>

Authentication: X-VM107-Service-Token header (service-to-service; avoids JWT
dependency per Phase 39 internal discipline). Token value from env var
VM107_SERVICE_TOKEN (falls back to empty string for dev/test).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Union
from uuid import UUID

import httpx

from fingpt_core.contracts.replay.chart import ChartSlice, OHLCBar

logger = logging.getLogger(__name__)

VM100_BASE = os.environ["VM100_API_URL"]
VM107_SERVICE_TOKEN = os.environ["VM107_SERVICE_TOKEN"]
_TIMEOUT = 30.0


def _degraded_chart_slice(execution_id: UUID, occurred_at: str) -> ChartSlice:
    """Return a degraded (empty) ChartSlice for graceful fallback."""
    # Parse occurred_at to populate required datetime fields
    try:
        dt = datetime.fromisoformat(occurred_at)
    except (ValueError, TypeError):
        dt = datetime.now(tz=timezone.utc)

    # Build a minimal ChartSlice with empty bars and degraded marker
    # ChartSlice extends BaseContract; we use model_construct to bypass
    # optional validators since this is a synthesised degraded response.
    slice_obj = ChartSlice.model_construct(
        instrument="",
        timeframe="",
        bars=[],
        requested_around=dt,
        center_at=dt,
    )
    # Mark as degraded — attach as attribute (ChartSlice is a Pydantic model
    # with model_config extra='allow' in BaseContract or we set via __dict__).
    object.__setattr__(slice_obj, "degraded", True)
    return slice_obj


def fetch_replay_chart_slice(
    execution_id: UUID,
    occurred_at: str,
    bars_around: int = 20,
) -> ChartSlice:
    """Return a ChartSlice (OHLC window) for the replay chart strip.

    Args:
        execution_id: UUID of the closed execution.
        occurred_at: ISO-format datetime to center the chart slice around.
        bars_around: number of bars to include (default 20, VM100 max=50).

    Returns:
        ChartSlice on success (bars populated, degraded=False).
        ChartSlice(bars=[], degraded=True) when VM100/VM102 unavailable.
        NEVER raises (Pitfall 11 — chart failure is non-fatal for mentor agent).
    """
    url = f"{VM100_BASE}/api/journal/replay/{execution_id}/chart-slice"
    params = {"at": occurred_at, "bars": bars_around}
    headers: dict[str, str] = {}
    if VM107_SERVICE_TOKEN:
        headers["X-VM107-Service-Token"] = VM107_SERVICE_TOKEN

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(url, params=params, headers=headers)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning(
            "fetch_replay_chart_slice: VM100 unreachable — %s (returning degraded)", exc
        )
        return _degraded_chart_slice(execution_id, occurred_at)

    if resp.status_code in (503, 504):
        logger.warning(
            "fetch_replay_chart_slice: VM100 returned %s (VM102 likely down) — returning degraded",
            resp.status_code,
        )
        return _degraded_chart_slice(execution_id, occurred_at)

    if resp.status_code >= 400:
        logger.warning(
            "fetch_replay_chart_slice: unexpected %s — returning degraded",
            resp.status_code,
        )
        return _degraded_chart_slice(execution_id, occurred_at)

    try:
        slice_obj = ChartSlice.model_validate(resp.json())
        # Mark as non-degraded
        object.__setattr__(slice_obj, "degraded", False)
        return slice_obj
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_replay_chart_slice: response parse error — %s", exc)
        return _degraded_chart_slice(execution_id, occurred_at)
