"""get_behavioral_edges — TOOL GAP #1 CLOSURE.

Query Neo4j :FAILED_DUE_TO edges per execution_id via VM100 typed internal endpoint.
Phase 39 typed-API lock: VM107 NEVER queries Neo4j directly.

Only trade_auditor_agent._analyzer is allowed to invoke (registry-enforced via
registry/tool/get_behavioral_edges.yaml allowed_agent_profiles).

BLOCKER #4 doctrine: env-var fetch lives in __init__(), NOT at module scope.
Module-level `raise RuntimeError` breaks pytest collection in any environment
that hasn't set the env var (CI test discovery, local dev). Class-level fail-fast
at instantiation still honors Directive #4 (no silent default) while keeping
imports clean.

FAST_FAIL retry profile:
  - 4xx responses: raise immediately (no retry — client error, retrying won't help)
  - 5xx / network errors: up to 2 retries (3 total attempts), then raise
  - On success: returns GetBehavioralEdgesResponse

URL pattern:
  GET {VM100_INTERNAL_BASE_URL}/api/journal/internal/behavioral-edges/{execution_id}

X-Agent-Scope header is injected by the caller (ScopeDispatcher.attach_header,
60-05 orchestrator) before invoking this tool. The tool propagates the header
to the HTTP GET request.
"""
from __future__ import annotations

import logging
import os
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict

from fingpt_core.contracts.narrative.scope import ScopeContext

logger = logging.getLogger("fingpt.tools.get_behavioral_edges")

# FAST_FAIL retry profile: 4xx → no retry; 5xx → 2 retries (3 total attempts)
_FAST_FAIL_MAX_5XX_RETRIES = 2


class GetBehavioralEdgesRequest(BaseModel):
    """Request contract for get_behavioral_edges tool.

    frozen=True + extra='forbid' per Phase 60 contract discipline.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: UUID
    scope_context: ScopeContext


class BehavioralEdgeItem(BaseModel):
    """Single :FAILED_DUE_TO edge from Phase 58 behavioral graph."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern_name: str
    confidence: float
    timestamp: str


class GetBehavioralEdgesResponse(BaseModel):
    """Response contract for get_behavioral_edges tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    edges: list[BehavioralEdgeItem]


class GetBehavioralEdgesTool:
    """Analyzer-tier tool that reads :FAILED_DUE_TO edges from Phase 58 Neo4j via VM100.

    This is a standalone class (not inheriting ContractTool / Agent Zero Tool base)
    for the same reason as PersistNarrativeTool (60-06 deviation): the ContractTool
    base requires 6 Agent Zero runtime positional args not available outside an agent
    loop. Standalone class preserves all CRITICAL pieces:
      - request/response Pydantic contracts (extra='forbid', frozen)
      - FAST_FAIL retry profile (4xx no-retry; 5xx up to 2 retries)
      - env-driven URL (no fallback default)
      - GET method
      - canonical route shape

    FAST_FAIL retry profile:
      - 4xx: raise immediately (no retry)
      - 5xx / network errors: up to 2 retries (3 total attempts), then raise

    Env-var doctrine (Directive #4):
      VM100_INTERNAL_BASE_URL is read in __init__ — fail-fast at instantiation,
      never at module import. No fallback default.
    """

    name = "get_behavioral_edges"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Read VM100_INTERNAL_BASE_URL at construction time.

        Raises RuntimeError immediately if the env var is not set.
        This is intentional (Directive #4 — fail-fast at startup, no silent defaults).
        Configure via docker-compose.yml environment section.

        Module-level imports remain clean even when the env var is absent.
        """
        base = os.environ.get("VM100_INTERNAL_BASE_URL")
        if not base:
            raise RuntimeError(
                "VM100_INTERNAL_BASE_URL must be set (no fallback per Directive #4 — "
                "env-driven config, no silent default). Configure via docker-compose.yml. "
                "See memory/feedback_env_driven_no_fallbacks.md."
            )
        self._base_url = base.rstrip("/")

    # ── Public interface ──────────────────────────────────────────────────

    def endpoint(self, request: GetBehavioralEdgesRequest) -> str:
        """Build the VM100 internal endpoint URL for this behavioral-edges request.

        URL shape:
          GET {base}/api/journal/internal/behavioral-edges/{execution_id}
        """
        return f"{self._base_url}/api/journal/internal/behavioral-edges/{request.execution_id}"

    def http_method(self) -> str:
        """HTTP method — GET (read-only query, no side effects)."""
        return "GET"

    async def call(
        self,
        request: GetBehavioralEdgesRequest,
        headers: dict | None = None,
    ) -> GetBehavioralEdgesResponse:
        """Execute the HTTP GET to VM100 internal endpoint.

        Implements FAST_FAIL retry profile:
          - 4xx: raise immediately (no retry)
          - 5xx / transport errors: up to 2 retries (3 total attempts), then raise
          - 200: return GetBehavioralEdgesResponse (wraps list as .edges)

        Args:
            request: Validated GetBehavioralEdgesRequest
            headers: Optional headers dict (caller should inject X-Agent-Scope
                     via ScopeDispatcher.attach_header before calling)

        Returns:
            GetBehavioralEdgesResponse with .edges list

        Raises:
            httpx.HTTPStatusError: On 4xx (immediately) or 5xx (after retries exhausted)
            httpx.TransportError: On network failure after retries exhausted
        """
        url = self.endpoint(request)
        outbound_headers = {**(headers or {})}

        last_exc: Exception | None = None
        for attempt in range(_FAST_FAIL_MAX_5XX_RETRIES + 1):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, headers=outbound_headers)
                    response.raise_for_status()
                    data = response.json()
                    # VM100 returns a raw JSON list; wrap into response contract
                    if isinstance(data, list):
                        return GetBehavioralEdgesResponse(
                            edges=[BehavioralEdgeItem(**item) for item in data]
                        )
                    # Already wrapped shape
                    return GetBehavioralEdgesResponse.model_validate(data)

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if 400 <= status < 500:
                    # 4xx: FAST_FAIL — no retry
                    logger.error(
                        "get_behavioral_edges: 4xx from VM100 (%s) — no retry: %s",
                        status,
                        exc,
                    )
                    raise
                # 5xx: retry
                last_exc = exc
                logger.warning(
                    "get_behavioral_edges: 5xx from VM100 (%s) — attempt %d/%d: %s",
                    status,
                    attempt + 1,
                    _FAST_FAIL_MAX_5XX_RETRIES + 1,
                    exc,
                )
            except (httpx.TransportError, httpx.NetworkError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning(
                    "get_behavioral_edges: transport error — attempt %d/%d: %s",
                    attempt + 1,
                    _FAST_FAIL_MAX_5XX_RETRIES + 1,
                    exc,
                )

        # All retries exhausted
        logger.error(
            "get_behavioral_edges: all %d attempts failed",
            _FAST_FAIL_MAX_5XX_RETRIES + 1,
        )
        raise last_exc  # type: ignore[misc]
