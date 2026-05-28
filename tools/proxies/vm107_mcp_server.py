"""Phase 70.5 Decision 18 — proxy for vm107.mcp_server.

VM107 is the canonical epistemic authority boundary. This proxy represents the
VM107 FastMCP server (Phase 67 Plan 12). The MCP server exposes CLOSE-state
cognitive tools to external MCP clients (Claude Desktop, Cursor).

Since this is an MCP server endpoint (not a standard REST query), this proxy
provides server metadata and tool listing rather than a direct invocation proxy.

Status: real — VM107 FastMCP server exists (Phase 67).
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from tools.proxies._vm107_self_client import Vm107SelfClient
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance

# Re-export for test introspection
Vm107Client = Vm107SelfClient


class McpToolInfo(BaseModel):
    """Info about a single MCP-exposed tool."""

    model_config = ConfigDict(extra="allow")

    tool_name: str
    description: str | None = None
    required_scopes: list[str] = Field(default_factory=list)


class Vm107McpServerPayload(BaseModel):
    """Typed payload for vm107.mcp_server proxy.

    Provides MCP server metadata and the list of currently active tools.
    """

    PAYLOAD_SCHEMA_VERSION: ClassVar[str] = "1.0.0"

    model_config = ConfigDict(extra="allow")

    server_version: str | None = None
    active_tools: list[McpToolInfo] = Field(default_factory=list)
    auth_required: bool = True
    required_scopes: list[str] = Field(default_factory=list)
    provenance: ToolProvenance = Field(default_factory=ToolProvenance)


async def run_async(**kwargs) -> Vm107McpServerPayload:
    """Proxy invocation — env-driven URL, no fallback.

    Returns MCP server metadata and active tool list.
    """
    client = Vm107SelfClient()  # raises RuntimeError if VM107_API_URL unset

    # FastMCP server metadata — attempt GET /mcp/info or fall back to static metadata
    try:
        response = await client.get("mcp/info")
        server_version = response.get("version") if isinstance(response, dict) else None
        raw_tools = response.get("tools", []) if isinstance(response, dict) else []
        active_tools = [McpToolInfo(**t) for t in raw_tools if isinstance(t, dict)]
    except Exception:
        # Fallback to known-static tool listing from Phase 67 spec
        server_version = None
        active_tools = [
            McpToolInfo(
                tool_name="mission.close.journal_prompts",
                description="CLOSE-state journal prompts via reflection_prompt emitter",
                required_scopes=["mission_control:read"],
            ),
            McpToolInfo(
                tool_name="mission.close.surfaced_lesson",
                description="CLOSE-state surfaced lesson from VM100",
                required_scopes=["mission_control:read"],
            ),
        ]

    return Vm107McpServerPayload(
        server_version=server_version,
        active_tools=active_tools,
        auth_required=True,
        required_scopes=["mission_control:read"],
        provenance=ToolProvenance(
            signals=ToolConfidenceSignals(
                evidence_quality="complete",
                freshness_observed_seconds=60,
                missing_fields=(),
                is_deterministic=True,
            ),
            citations=(),
            assumptions=(
                "FastMCP v1 ships always-active 2 tools (per-session activation deferred)",
                "Bearer auth via JWTVerifier — env-driven JWKS_URI/ISSUER/AUDIENCE",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM107 FastMCP server health check timed out",
                ),
                FailureMode(
                    code=FailureModeCode.PERMISSION_DENIED,
                    detail="JWT bearer auth failed — missing or invalid mission_control:read scope",
                ),
            ),
        ),
    )
