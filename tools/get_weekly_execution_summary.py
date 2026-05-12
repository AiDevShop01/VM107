"""get_weekly_execution_summary — TOOL GAP #3 CLOSURE.

Batch-read all executions + analytics_snapshot rows closed within a canonical
week window for an account, via VM100 typed internal endpoint.
Phase 39 typed-API lock: VM107 NEVER queries Postgres directly.

Only weekly_review_agent._reader and weekly_review_agent._analyzer are allowed
to invoke (registry-enforced via registry/tool/get_weekly_execution_summary.yaml
allowed_agent_profiles).

BLOCKER #4 doctrine: env-var fetch lives in __init__(), NOT at module scope.
Module-level `raise RuntimeError` breaks pytest collection in any environment
that hasn't set the env var (CI test discovery, local dev). Class-level fail-fast
at instantiation still honors Directive #4 (no silent default) while keeping
imports clean.

FAST_FAIL retry profile:
  - 4xx responses: raise immediately (no retry — client error, retrying won't help)
  - 5xx / network errors: up to 2 retries (3 total attempts), then raise
  - On success: returns GetWeeklyExecutionSummaryResponse

URL pattern:
  GET {VM100_INTERNAL_BASE_URL}/api/journal/internal/executions/week-summary
      ?account_id=X&week_start=YYYY-MM-DD&week_end=YYYY-MM-DD&timezone=UTC

Critical constraint (CONTEXT.md §10 LOCKED):
  week_start/week_end are CANONICAL ANCHORED DATES, not relative offsets.
  This is what enables replay reproducibility — the same anchored dates
  always query the same Postgres data.

X-Agent-Scope header is injected by the caller (ScopeDispatcher.attach_header,
60-05 orchestrator) before invoking this tool. The tool propagates the header
to the HTTP GET request.
"""
from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from fingpt_core.contracts.narrative.scope import ScopeContext

logger = logging.getLogger("fingpt.tools.get_weekly_execution_summary")

# FAST_FAIL retry profile: 4xx → no retry; 5xx → 2 retries (3 total attempts)
_FAST_FAIL_MAX_5XX_RETRIES = 2


class WeeklyExecutionItem(BaseModel):
    """Single execution record from a canonical week window.

    frozen=True + extra='forbid' per Phase 60 contract discipline.
    All timestamp fields are ISO-format strings (from Postgres DateTimeField).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str
    instrument: str
    opened_at: str | None = None
    closed_at: str | None = None
    result_r: float | None = None
    snapshot_id: str | None = None


class GetWeeklyExecutionSummaryRequest(BaseModel):
    """Request contract for get_weekly_execution_summary tool.

    frozen=True + extra='forbid' per Phase 60 contract discipline.

    Critical constraint (CONTEXT.md §10 LOCKED):
        week_start/week_end are `date` objects — canonical ANCHORED dates,
        NOT timedelta or relative 'last 7 days' offsets.
        Anchored dates enable replay reproducibility.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: str
    week_start: date   # canonical anchored date — CONTEXT.md §10 LOCKED
    week_end: date     # canonical anchored date — NOT timedelta or relative
    timezone: str = "UTC"
    scope_context: ScopeContext


class GetWeeklyExecutionSummaryResponse(BaseModel):
    """Response contract for get_weekly_execution_summary tool.

    frozen=True + extra='forbid' per Phase 60 contract discipline.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: str
    week_start: date
    week_end: date
    executions: list[WeeklyExecutionItem]


class GetWeeklyExecutionSummaryTool:
    """Reader/Analyzer-tier tool that batch-reads executions for a canonical week window.

    Queries VM100 GET /api/journal/internal/executions/week-summary which joins
    Postgres Execution + TradeAnalyticsSnapshot + TradeOutcomeRecord.

    This is a standalone class (not inheriting ContractTool / Agent Zero Tool base)
    for the same reason as GetBehavioralEdgesTool and GetCrossTradeBehavioralPatternsTool
    (60-09b / 60-10b deviation): the ContractTool base requires 6 Agent Zero runtime
    positional args not available outside an agent loop. Standalone class preserves
    all CRITICAL pieces:
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

    name = "get_weekly_execution_summary"

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

    def endpoint(self, request: GetWeeklyExecutionSummaryRequest) -> str:
        """Build the VM100 internal endpoint URL for this week-summary request.

        URL shape:
          GET {base}/api/journal/internal/executions/week-summary
        """
        return f"{self._base_url}/api/journal/internal/executions/week-summary"

    def http_method(self) -> str:
        """HTTP method — GET (read-only batch query, no side effects)."""
        return "GET"

    async def call(
        self,
        request: GetWeeklyExecutionSummaryRequest,
        headers: dict | None = None,
    ) -> GetWeeklyExecutionSummaryResponse:
        """Execute the HTTP GET to VM100 internal endpoint.

        Implements FAST_FAIL retry profile:
          - 4xx: raise immediately (no retry)
          - 5xx / transport errors: up to 2 retries (3 total attempts), then raise
          - 200: return GetWeeklyExecutionSummaryResponse

        Critical constraint (CONTEXT.md §10 LOCKED):
            week_start/week_end are sent as ISO date strings (YYYY-MM-DD) in query params —
            canonical anchored dates, not timedelta or relative offsets.

        Args:
            request: Validated GetWeeklyExecutionSummaryRequest
            headers: Optional headers dict (caller should inject X-Agent-Scope
                     via ScopeDispatcher.attach_header before calling)

        Returns:
            GetWeeklyExecutionSummaryResponse with .executions list

        Raises:
            httpx.HTTPStatusError: On 4xx (immediately) or 5xx (after retries exhausted)
            httpx.TransportError: On network failure after retries exhausted
        """
        url = self.endpoint(request)
        outbound_headers = {**(headers or {})}

        # Query params — week_start/week_end as ISO strings (canonical anchored dates)
        params = {
            "account_id": request.account_id,
            "week_start": request.week_start.isoformat(),  # YYYY-MM-DD (CONTEXT.md §10 LOCKED)
            "week_end": request.week_end.isoformat(),      # YYYY-MM-DD (CONTEXT.md §10 LOCKED)
            "timezone": request.timezone,
        }

        last_exc: Exception | None = None
        for attempt in range(_FAST_FAIL_MAX_5XX_RETRIES + 1):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, headers=outbound_headers, params=params)
                    response.raise_for_status()
                    data = response.json()
                    return GetWeeklyExecutionSummaryResponse(
                        account_id=data["account_id"],
                        week_start=date.fromisoformat(data["week_start"]),
                        week_end=date.fromisoformat(data["week_end"]),
                        executions=[
                            WeeklyExecutionItem(**item)
                            for item in data.get("executions", [])
                        ],
                    )

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if 400 <= status < 500:
                    # 4xx: FAST_FAIL — no retry
                    logger.error(
                        "get_weekly_execution_summary: 4xx from VM100 (%s) — no retry: %s",
                        status,
                        exc,
                    )
                    raise
                # 5xx: retry
                last_exc = exc
                logger.warning(
                    "get_weekly_execution_summary: 5xx from VM100 (%s) — attempt %d/%d: %s",
                    status,
                    attempt + 1,
                    _FAST_FAIL_MAX_5XX_RETRIES + 1,
                    exc,
                )
            except (httpx.TransportError, httpx.NetworkError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning(
                    "get_weekly_execution_summary: transport error — attempt %d/%d: %s",
                    attempt + 1,
                    _FAST_FAIL_MAX_5XX_RETRIES + 1,
                    exc,
                )

        # All retries exhausted
        logger.error(
            "get_weekly_execution_summary: all %d attempts failed",
            _FAST_FAIL_MAX_5XX_RETRIES + 1,
        )
        raise last_exc  # type: ignore[misc]


# ──────────────────────────────────────────────────────────────────────────────
# Phase 60.1 (G5) — Tool subclass wrapper for agent.get_tool discoverability.
# The standalone GetWeeklyExecutionSummaryTool class above is used directly by
# the reader/analyzer sub-profiles. This wrapper enables Agent Zero's
# agent.get_tool('get_weekly_execution_summary') discovery path, which filters
# for Tool subclasses only (agent.py:1033 / extract_tools.load_classes_from_file).
#
# Filename invariant (LOCKED): agent.get_tool('get_weekly_execution_summary')
# resolves to this file via load_classes_from_file. The canonical Tool subclass
# MUST remain in this file.
# ──────────────────────────────────────────────────────────────────────────────

from helpers.tool import Tool, Response  # noqa: E402  (intentional bottom-of-file)


class GetWeeklyExecutionSummary(Tool):
    """Reader/Analyzer-tier Tool wrapper around GetWeeklyExecutionSummaryTool.

    Routes agent tool invocations through to the standalone
    GetWeeklyExecutionSummaryTool's .call() method. Preserves:
        - FAST_FAIL retry profile (delegated)
        - VM100_INTERNAL_BASE_URL fail-fast at __init__ (delegated)
        - Pydantic request/response contracts (delegated)
        - X-Agent-Scope header propagation (delegated)
        - CONTEXT.md §10 LOCKED: week_start/week_end are canonical anchored dates
    """

    name = "get_weekly_execution_summary"

    async def execute(self, **kwargs) -> Response:
        """Delegate to the standalone GetWeeklyExecutionSummaryTool.

        kwargs expected from the LLM's structured tool call:
            account_id: str
            week_start: str  ISO date (YYYY-MM-DD) — CONTEXT.md §10 LOCKED canonical anchor
            week_end: str    ISO date (YYYY-MM-DD) — CONTEXT.md §10 LOCKED canonical anchor
            timezone: str    (optional, default 'UTC')
            scope_context: dict (will be model_validated as ScopeContext)
            headers: optional dict — scope headers injected by orchestrator

        Critical constraint: week_start/week_end MUST be canonical anchored dates
        (not relative offsets). The standalone class enforces this via date type.
        """
        inner = GetWeeklyExecutionSummaryTool()

        account_id = kwargs.get("account_id")
        week_start = kwargs.get("week_start")
        week_end = kwargs.get("week_end")
        scope_context_raw = kwargs.get("scope_context")

        if not all([account_id, week_start, week_end, scope_context_raw]):
            return Response(
                message=(
                    "get_weekly_execution_summary: missing required args "
                    "'account_id', 'week_start', 'week_end', or 'scope_context'"
                ),
                break_loop=False,
            )

        headers = kwargs.get("headers") or self.agent.get_data("_outbound_headers") or None

        try:
            from datetime import date as _date
            scope_context = (
                ScopeContext.model_validate(scope_context_raw)
                if isinstance(scope_context_raw, dict)
                else scope_context_raw
            )
            # Convert ISO strings to date objects (CONTEXT.md §10 LOCKED)
            week_start_date = (
                _date.fromisoformat(week_start)
                if isinstance(week_start, str)
                else week_start
            )
            week_end_date = (
                _date.fromisoformat(week_end)
                if isinstance(week_end, str)
                else week_end
            )
            request = GetWeeklyExecutionSummaryRequest(
                account_id=account_id,
                week_start=week_start_date,
                week_end=week_end_date,
                timezone=kwargs.get("timezone", "UTC"),
                scope_context=scope_context,
            )
            response = await inner.call(request, headers=headers)
        except Exception as exc:
            return Response(
                message=f"get_weekly_execution_summary failed: {exc}",
                break_loop=False,
            )

        return Response(
            message=response.model_dump_json(),
            break_loop=False,
        )
