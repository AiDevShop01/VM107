"""get_cross_trade_behavioral_patterns — TOOL GAP #2 CLOSURE.

Query Neo4j :EXHIBITS BehavioralPattern edges across an account's executions
via VM100 typed internal endpoint.
Phase 39 typed-API lock: VM107 NEVER queries Neo4j directly.

Only behavioral_mentor_agent._analyzer is allowed to invoke (registry-enforced via
registry/tool/get_cross_trade_behavioral_patterns.yaml allowed_agent_profiles).

BLOCKER #4 doctrine: env-var fetch lives in __init__(), NOT at module scope.
Module-level `raise RuntimeError` breaks pytest collection in any environment
that hasn't set the env var (CI test discovery, local dev). Class-level fail-fast
at instantiation still honors Directive #4 (no silent default) while keeping
imports clean.

FAST_FAIL retry profile:
  - 4xx responses: raise immediately (no retry — client error, retrying won't help)
  - 5xx / network errors: up to 2 retries (3 total attempts), then raise
  - On success: returns GetCrossTradeBehavioralPatternsResponse

URL pattern:
  GET {VM100_INTERNAL_BASE_URL}/api/journal/internal/cross-trade-patterns?account_id=X&window_days=Y

X-Agent-Scope header is injected by the caller (ScopeDispatcher.attach_header,
60-05 orchestrator) before invoking this tool. The tool propagates the header
to the HTTP GET request.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from fingpt_core.contracts.narrative.scope import ScopeContext

logger = logging.getLogger("fingpt.tools.get_cross_trade_behavioral_patterns")

# FAST_FAIL retry profile: 4xx → no retry; 5xx → 2 retries (3 total attempts)
_FAST_FAIL_MAX_5XX_RETRIES = 2


class GetCrossTradeBehavioralPatternsRequest(BaseModel):
    """Request contract for get_cross_trade_behavioral_patterns tool.

    frozen=True + extra='forbid' per Phase 60 contract discipline.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: str
    window_days: int = 30
    scope_context: ScopeContext


class CrossTradePatternItem(BaseModel):
    """Single BehavioralPattern frequency record across an account's executions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern_name: str
    frequency: int
    recent_executions: list[str]


class GetCrossTradeBehavioralPatternsResponse(BaseModel):
    """Response contract for get_cross_trade_behavioral_patterns tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    patterns: list[CrossTradePatternItem]


class GetCrossTradeBehavioralPatternsTool:
    """Analyzer-tier tool that reads :EXHIBITS BehavioralPattern cross-trade edges via VM100.

    This is a standalone class (not inheriting ContractTool / Agent Zero Tool base)
    for the same reason as PersistNarrativeTool (60-06 deviation) and GetBehavioralEdgesTool
    (60-09b deviation): the ContractTool base requires 6 Agent Zero runtime positional
    args not available outside an agent loop. Standalone class preserves all CRITICAL pieces:
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

    name = "get_cross_trade_behavioral_patterns"

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

    def endpoint(self, request: GetCrossTradeBehavioralPatternsRequest) -> str:
        """Build the VM100 internal endpoint URL for this cross-trade-patterns request.

        URL shape:
          GET {base}/api/journal/internal/cross-trade-patterns
          (query-string params account_id + window_days attached by HTTP layer)
        """
        return f"{self._base_url}/api/journal/internal/cross-trade-patterns"

    def http_method(self) -> str:
        """HTTP method — GET (read-only query, no side effects)."""
        return "GET"

    async def call(
        self,
        request: GetCrossTradeBehavioralPatternsRequest,
        headers: dict | None = None,
    ) -> GetCrossTradeBehavioralPatternsResponse:
        """Execute the HTTP GET to VM100 internal endpoint.

        Implements FAST_FAIL retry profile:
          - 4xx: raise immediately (no retry)
          - 5xx / transport errors: up to 2 retries (3 total attempts), then raise
          - 200: return GetCrossTradeBehavioralPatternsResponse

        Args:
            request: Validated GetCrossTradeBehavioralPatternsRequest
            headers: Optional headers dict (caller should inject X-Agent-Scope
                     via ScopeDispatcher.attach_header before calling)

        Returns:
            GetCrossTradeBehavioralPatternsResponse with .patterns list

        Raises:
            httpx.HTTPStatusError: On 4xx (immediately) or 5xx (after retries exhausted)
            httpx.TransportError: On network failure after retries exhausted
        """
        url = self.endpoint(request)
        params = {
            "account_id": request.account_id,
            "window_days": request.window_days,
        }
        outbound_headers = {**(headers or {})}

        last_exc: Exception | None = None
        for attempt in range(_FAST_FAIL_MAX_5XX_RETRIES + 1):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, params=params, headers=outbound_headers)
                    response.raise_for_status()
                    data = response.json()
                    # VM100 returns a raw JSON list; wrap into response contract
                    if isinstance(data, list):
                        return GetCrossTradeBehavioralPatternsResponse(
                            patterns=[CrossTradePatternItem(**item) for item in data]
                        )
                    # Already wrapped shape
                    return GetCrossTradeBehavioralPatternsResponse.model_validate(data)

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if 400 <= status < 500:
                    # 4xx: FAST_FAIL — no retry
                    logger.error(
                        "get_cross_trade_behavioral_patterns: 4xx from VM100 (%s) — no retry: %s",
                        status,
                        exc,
                    )
                    raise
                # 5xx: retry
                last_exc = exc
                logger.warning(
                    "get_cross_trade_behavioral_patterns: 5xx from VM100 (%s) — attempt %d/%d: %s",
                    status,
                    attempt + 1,
                    _FAST_FAIL_MAX_5XX_RETRIES + 1,
                    exc,
                )
            except (httpx.TransportError, httpx.NetworkError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning(
                    "get_cross_trade_behavioral_patterns: transport error — attempt %d/%d: %s",
                    attempt + 1,
                    _FAST_FAIL_MAX_5XX_RETRIES + 1,
                    exc,
                )

        # All retries exhausted
        logger.error(
            "get_cross_trade_behavioral_patterns: all %d attempts failed",
            _FAST_FAIL_MAX_5XX_RETRIES + 1,
        )
        raise last_exc  # type: ignore[misc]


# ──────────────────────────────────────────────────────────────────────────────
# Phase 60.1 (G4) — Tool subclass wrapper for agent.get_tool discoverability.
# The standalone GetCrossTradeBehavioralPatternsTool class above is used directly
# by the analyzer sub-profile. This wrapper enables Agent Zero's
# agent.get_tool('get_cross_trade_behavioral_patterns') discovery path, which
# filters for Tool subclasses only (agent.py:1033 / extract_tools.load_classes_from_file).
#
# Filename invariant (LOCKED): agent.get_tool('get_cross_trade_behavioral_patterns')
# resolves to this file via load_classes_from_file. The canonical Tool subclass
# MUST remain in this file.
# ──────────────────────────────────────────────────────────────────────────────

from helpers.tool import Tool, Response  # noqa: E402  (intentional bottom-of-file)


class GetCrossTradeBehavioralPatterns(Tool):
    """Analyzer-tier Tool wrapper around GetCrossTradeBehavioralPatternsTool.

    Routes agent tool invocations through to the standalone
    GetCrossTradeBehavioralPatternsTool's .call() method. Preserves:
        - FAST_FAIL retry profile (delegated)
        - VM100_INTERNAL_BASE_URL fail-fast at __init__ (delegated)
        - Pydantic request/response contracts (delegated)
        - X-Agent-Scope header propagation (delegated)
    """

    name = "get_cross_trade_behavioral_patterns"

    async def execute(self, **kwargs) -> Response:
        """Delegate to the standalone GetCrossTradeBehavioralPatternsTool.

        kwargs expected from the LLM's structured tool call:
            account_id: str
            window_days: int (optional, default 30)
            scope_context: dict (will be model_validated as ScopeContext)
            headers: optional dict — scope headers injected by orchestrator
        """
        inner = GetCrossTradeBehavioralPatternsTool()

        account_id = kwargs.get("account_id")
        scope_context_raw = kwargs.get("scope_context")
        if account_id is None or scope_context_raw is None:
            return Response(
                message="get_cross_trade_behavioral_patterns: missing required args 'account_id' or 'scope_context'",
                break_loop=False,
            )

        headers = kwargs.get("headers") or self.agent.get_data("_outbound_headers") or None

        try:
            scope_context = (
                ScopeContext.model_validate(scope_context_raw)
                if isinstance(scope_context_raw, dict)
                else scope_context_raw
            )
            request = GetCrossTradeBehavioralPatternsRequest(
                account_id=account_id,
                window_days=kwargs.get("window_days", 30),
                scope_context=scope_context,
            )
            response = await inner.call(request, headers=headers)
        except Exception as exc:
            return Response(
                message=f"get_cross_trade_behavioral_patterns failed: {exc}",
                break_loop=False,
            )

        return Response(
            message=response.model_dump_json(),
            break_loop=False,
        )
