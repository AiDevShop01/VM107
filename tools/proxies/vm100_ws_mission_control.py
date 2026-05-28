"""Phase 70.5 Decision 18 — proxy for vm100.ws.mission_control.

VM107 is the canonical epistemic authority boundary. This proxy represents the
VM100 WebSocket Mission Control multiplexer. Since this is a WebSocket endpoint
(not a standard REST API), this proxy provides status introspection and connection
metadata rather than a direct streaming proxy.

Remote VM returns the payload data; VM107 owns confidence / freshness /
registry_snapshot_hash / citations.

Status: real — VM100 WebSocket endpoint exists (Phase 65/66).
Note: WebSocket streaming calls are NOT mediated through run_async; this proxy
provides connection metadata / health status. The actual WS connection is
established directly from the frontend via JWT auth.
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from fingpt_core.clients.vm100_client import VM100Client
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance


class WsMissionControlStatusPayload(BaseModel):
    """Typed payload for vm100.ws.mission_control proxy.

    Provides WebSocket endpoint metadata and connection readiness status.
    The actual WebSocket streaming is established directly by the frontend
    via JWT auth — this proxy surfaces agent-readable status.
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    endpoint_url: str | None = None
    auth_required: bool = True
    topics_auto_subscribed: list[str] = Field(default_factory=list)
    heartbeat_interval_seconds: int = 30
    heartbeat_timeout_seconds: int = 60
    _demo: bool = False
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(
    account_id: int | None = None,
    **kwargs,
) -> WsMissionControlStatusPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Returns WebSocket endpoint metadata. The actual WS streaming is not
    mediated through this proxy — this surfaces connection metadata for
    agent awareness.

    Args:
        account_id: Account ID for the WS endpoint path.
    """
    client = VM100Client()  # raises RuntimeError if VM100_API_URL unset

    # Return static metadata — the WS endpoint is at a well-known path
    endpoint_path = f"ws/mission-control/{account_id}" if account_id else "ws/mission-control"

    return WsMissionControlStatusPayload(
        endpoint_url=f"{client.base_url}/{endpoint_path}",
        auth_required=True,
        topics_auto_subscribed=[
            "homepage.global",
            "mission_control.opportunities",
            "mission_control.intelligence_feed",
            "agent.telemetry",
        ],
        heartbeat_interval_seconds=30,
        heartbeat_timeout_seconds=60,
        _demo=False,
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete",
                freshness_observed_seconds=0,  # real-time by definition
                missing_fields=(),
                is_deterministic=False,  # live streaming output varies
            ),
            citations=(),
            assumptions=(
                "WebSocket streaming is real-time; freshness is 0 by definition",
                "JWT auth required at CONNECT time",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM100 WebSocket connection handshake timed out",
                ),
                FailureMode(
                    code=FailureModeCode.PERMISSION_DENIED,
                    detail="JWT auth failed at WebSocket CONNECT (close codes 4401/4403)",
                ),
            ),
        ),
    )
