"""fetch_replay_frame — Phase 59 CONTEXT §18.

Given (execution_id, occurred_at, sequence_number), returns a single ReplayFrame
with the full ReplayState snapshot at that point in time.

CONTEXT §18 LOCKED rule: ReplayFrame.state is non-None — the state snapshot is
included in every frame return so the caller has full temporal context without
an additional round-trip.

Phase 39 typed-API discipline:
  - NO filesystem reads
  - NO direct DB access
  - Only HTTP via VM100 internal endpoint (no-auth, internal router)
  - timeout=30 (Pitfall 11)
  - 404 → ToolError(code='not_found')
  - 503/504 → ToolError(code='vm100_degraded')   NOT raise
  - transport → ToolError(code='vm100_unavailable') NOT raise

Phase 47.6 capability_type: replay_frame
Endpoint: GET /api/journal/internal/replay-artifacts/{execution_id}/frames/{line_index}

line_index mapping: sequence_number - 1 (sequence_number is 1-based per Phase 59
event model; line_index is 0-based in the ReplayLine ORM).

Provenance metadata is automatically carried via the ReplayFrame.metadata field
(execution_id, truth_mode, reconstruction_service_version, reconstructed_at).
"""
from __future__ import annotations

import logging
import os
from typing import Union
from uuid import UUID

import httpx
from pydantic import BaseModel

from fingpt_core.contracts.replay.frame import ReplayFrame
from tools.replay.lookup_replay_artifact import ToolError

logger = logging.getLogger(__name__)

VM100_BASE = os.getenv("VM100_API_URL", "http://192.168.1.100:8000")
_TIMEOUT = 30.0


def fetch_replay_frame(
    execution_id: UUID,
    occurred_at: str,
    sequence_number: int,
    truth_mode: str = "HISTORICAL",
    replay_version: int | None = None,
) -> Union[ReplayFrame, ToolError]:
    """Return a single ReplayFrame at the given sequence point.

    Args:
        execution_id: UUID of the closed execution.
        occurred_at: ISO-format datetime of the frame (used as hint for line lookup).
        sequence_number: 1-based sequence number within the execution event log.
        truth_mode: 'HISTORICAL' (default) or 'COUNTERFACTUAL' (raises on VM100).
        replay_version: specific artifact version; None = latest.

    Returns:
        ReplayFrame on success (state is non-None per CONTEXT §18).
        ToolError on any failure — NEVER raises (Pitfall 11).
    """
    # line_index is 0-based; sequence_number is 1-based per event model
    line_index = max(0, sequence_number - 1)
    url = f"{VM100_BASE}/api/journal/internal/replay-artifacts/{execution_id}/frames/{line_index}"
    params: dict = {}
    if replay_version is not None:
        params["replay_version"] = replay_version
    if truth_mode != "HISTORICAL":
        params["truth_mode"] = truth_mode

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(url, params=params)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning("fetch_replay_frame: VM100 unreachable — %s", exc)
        return ToolError(
            code="vm100_unavailable",
            message=f"VM100 API unreachable: {exc}",
        )

    if resp.status_code == 404:
        return ToolError(
            code="not_found",
            message=(
                f"No replay frame for execution_id={execution_id}, "
                f"sequence_number={sequence_number}"
            ),
        )
    if resp.status_code in (503, 504):
        return ToolError(
            code="vm100_degraded",
            message=f"VM100 returned HTTP {resp.status_code}",
        )

    resp.raise_for_status()
    return ReplayFrame.model_validate(resp.json())
