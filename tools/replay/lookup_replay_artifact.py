"""lookup_replay_artifact — Phase 59 CONTEXT §18.

Given an execution_id, returns the latest (or specific version) ReplayArtifactMeta
from VM100's internal replay artifacts endpoint.

Phase 39 typed-API discipline:
  - NO filesystem reads
  - NO direct DB access
  - Only HTTP via VM100 internal endpoint (no-auth, internal router)
  - timeout=30 (Pitfall 11)
  - 404 → ToolError(code='not_found')
  - 503/504 → ToolError(code='vm100_degraded')   NOT raise
  - transport → ToolError(code='vm100_unavailable') NOT raise

Phase 47.6 capability_type: replay_lookup
Endpoint: GET /api/journal/internal/replay-artifacts/{execution_id}
"""
from __future__ import annotations

import logging
import os
from typing import Union
from uuid import UUID

import httpx
from pydantic import BaseModel

from fingpt_core.contracts.replay import ReplayArtifactMeta

logger = logging.getLogger(__name__)

VM100_BASE = os.getenv("VM100_API_URL", "http://192.168.1.100:8000")
_TIMEOUT = 30.0


class ToolError(BaseModel):
    """Typed error return — never raised, always returned (Pitfall 11)."""

    code: str
    message: str


def lookup_replay_artifact(
    execution_id: UUID,
    replay_version: int | None = None,
) -> Union[ReplayArtifactMeta, ToolError]:
    """Return lightweight ReplayArtifactMeta for the given execution_id.

    Args:
        execution_id: UUID of the closed execution.
        replay_version: specific version to fetch; None = latest.

    Returns:
        ReplayArtifactMeta on success, ToolError on any failure.
        NEVER raises — all errors returned as ToolError (Pitfall 11).
    """
    url = f"{VM100_BASE}/api/journal/internal/replay-artifacts/{execution_id}"
    params: dict = {}
    if replay_version is not None:
        params["replay_version"] = replay_version

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(url, params=params)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning("lookup_replay_artifact: VM100 unreachable — %s", exc)
        return ToolError(
            code="vm100_unavailable",
            message=f"VM100 API unreachable: {exc}",
        )

    if resp.status_code == 404:
        return ToolError(
            code="not_found",
            message=f"No replay artifact for execution_id={execution_id}",
        )
    if resp.status_code in (503, 504):
        return ToolError(
            code="vm100_degraded",
            message=f"VM100 returned HTTP {resp.status_code}",
        )

    resp.raise_for_status()
    return ReplayArtifactMeta.model_validate(resp.json())
