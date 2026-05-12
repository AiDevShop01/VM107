"""Tests for GetWeeklyExecutionSummaryTool — Phase 60 Plan 11b TOOL GAP #3 CLOSURE.

Queries Postgres executions + analytics_snapshot for a canonical week window
via VM100 typed endpoint. Phase 39 typed-API lock: VM107 NEVER queries Postgres directly.

BLOCKER #4 doctrine: env-var fetch at INSTANCE construction, not at module import.
Module imports must stay clean even with VM100_INTERNAL_BASE_URL unset.

Critical constraint (CONTEXT.md §10 LOCKED):
  week_start/week_end use `date` type — canonical ANCHORED dates, NOT timedelta
  or relative 'last 7 days' offsets. Anchored dates enable replay reproducibility.

Test cases:
  1. test_module_imports_cleanly_without_env_var   (BLOCKER #4 audit)
  2. test_construction_fails_without_vm100_url     (instance-level fail-fast)
  3. test_request_contract_extra_forbid            (extra='forbid' enforced)
  4. test_request_contract_uses_date_not_timedelta (CONTEXT.md §10 LOCKED)
  5. test_endpoint_uses_week_summary_route         (URL shape)
  6. test_4xx_no_retry                             (FAST_FAIL — 1 attempt)
  7. test_5xx_retries_then_fails                   (FAST_FAIL — 3 total attempts)
"""
from __future__ import annotations

import importlib
import os
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from pydantic import ValidationError

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# ────────────────────────────────────────────────────────────────────────────
# Set env vars before importing (scope contract needs SCOPE_DISPATCHER_SECRET_KEY)
# ────────────────────────────────────────────────────────────────────────────

os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://test-vm100:8000")
os.environ.setdefault("SCOPE_DISPATCHER_SECRET_KEY", "test-secret")

from tools.get_weekly_execution_summary import (
    GetWeeklyExecutionSummaryTool,
    GetWeeklyExecutionSummaryRequest,
    GetWeeklyExecutionSummaryResponse,
    WeeklyExecutionItem,
)
from fingpt_core.contracts.narrative.scope import ScopeContext, TruthMode, NarrativeVisibility


# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

def _make_scope_context() -> ScopeContext:
    now = datetime.now(timezone.utc)
    return ScopeContext(
        profile_id="weekly_review_agent._reader",
        account_id="acc-001",
        execution_id=None,
        truth_mode=TruthMode.HISTORICAL,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _make_request(
    account_id: str = "acc-001",
    week_start: date = date(2026, 1, 6),
    week_end: date = date(2026, 1, 12),
    timezone_str: str = "UTC",
) -> GetWeeklyExecutionSummaryRequest:
    scope = _make_scope_context()
    return GetWeeklyExecutionSummaryRequest(
        account_id=account_id,
        week_start=week_start,
        week_end=week_end,
        timezone=timezone_str,
        scope_context=scope,
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 1: BLOCKER #4 audit — module imports cleanly without env var set
# ────────────────────────────────────────────────────────────────────────────

def test_module_imports_cleanly_without_env_var(monkeypatch):
    """Module-level import must NOT raise RuntimeError even when VM100_INTERNAL_BASE_URL is unset.

    BLOCKER #4 doctrine: fail-fast at INSTANCE construction, never at module import.
    Prevents pytest collection failures in CI / local dev without the env var.
    """
    monkeypatch.delenv("VM100_INTERNAL_BASE_URL", raising=False)

    # Re-importing should NOT raise — module-level code has no side effects
    import tools.get_weekly_execution_summary as wes_module
    importlib.reload(wes_module)  # force fresh load with env var absent

    # Module exports still accessible (no RuntimeError at module scope)
    assert hasattr(wes_module, "GetWeeklyExecutionSummaryTool")
    assert hasattr(wes_module, "GetWeeklyExecutionSummaryRequest")
    assert hasattr(wes_module, "GetWeeklyExecutionSummaryResponse")


# ────────────────────────────────────────────────────────────────────────────
# Test 2: instantiation fails without env var (INSTANCE-level fail-fast)
# ────────────────────────────────────────────────────────────────────────────

def test_construction_fails_without_vm100_url(monkeypatch):
    """GetWeeklyExecutionSummaryTool() raises RuntimeError if VM100_INTERNAL_BASE_URL is not set."""
    monkeypatch.delenv("VM100_INTERNAL_BASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="VM100_INTERNAL_BASE_URL"):
        GetWeeklyExecutionSummaryTool()


# ────────────────────────────────────────────────────────────────────────────
# Test 3: request_contract has extra='forbid'
# ────────────────────────────────────────────────────────────────────────────

def test_request_contract_extra_forbid():
    """GetWeeklyExecutionSummaryRequest with extra fields raises ValidationError."""
    scope = _make_scope_context()
    with pytest.raises(ValidationError):
        GetWeeklyExecutionSummaryRequest(
            account_id="acc-001",
            week_start=date(2026, 1, 6),
            week_end=date(2026, 1, 12),
            timezone="UTC",
            scope_context=scope,
            extra_field_that_should_be_rejected="forbidden",
        )


# ────────────────────────────────────────────────────────────────────────────
# Test 4: CONTEXT.md §10 LOCKED — request uses date type, NOT timedelta
# ────────────────────────────────────────────────────────────────────────────

def test_request_contract_uses_date_not_timedelta():
    """week_start and week_end fields accept date objects (canonical anchored windows).

    CONTEXT.md §10 LOCKED: week_start/week_end are canonical anchored dates,
    NOT timedelta or relative 'last 7 days' offsets. Using `date` type enforces
    this at the type system level. Replay reproducibility requires anchored windows.
    """
    scope = _make_scope_context()
    week_start = date(2026, 1, 6)
    week_end = date(2026, 1, 12)

    # Construct with date objects — must succeed
    req = GetWeeklyExecutionSummaryRequest(
        account_id="acc-001",
        week_start=week_start,
        week_end=week_end,
        timezone="UTC",
        scope_context=scope,
    )

    # Verify the fields are date objects (canonical anchored windows)
    assert isinstance(req.week_start, date), "week_start must be date, not timedelta or str"
    assert isinstance(req.week_end, date), "week_end must be date, not timedelta or str"
    assert req.week_start == week_start
    assert req.week_end == week_end


# ────────────────────────────────────────────────────────────────────────────
# Test 5: endpoint() uses week-summary route
# ────────────────────────────────────────────────────────────────────────────

def test_endpoint_uses_week_summary_route(monkeypatch):
    """endpoint() returns the week-summary route."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000")
    tool = GetWeeklyExecutionSummaryTool()
    request = _make_request()

    url = tool.endpoint(request)

    assert "/executions/week-summary" in url, f"Expected '/executions/week-summary' in URL: {url}"
    assert url.startswith("http://vm100:8000"), f"URL should start with base URL: {url}"


# ────────────────────────────────────────────────────────────────────────────
# Test 6: 4xx → no retry (FAST_FAIL)
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_4xx_no_retry(monkeypatch):
    """4xx response raises immediately; FAST_FAIL means exactly 1 HTTP attempt."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000")
    tool = GetWeeklyExecutionSummaryTool()
    request = _make_request()

    attempt_count = [0]

    async def mock_get(url, **kwargs):
        attempt_count[0] += 1
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403 Forbidden",
            request=MagicMock(),
            response=mock_resp,
        )
        return mock_resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = mock_get
        mock_client_cls.return_value = mock_client

        with pytest.raises((httpx.HTTPStatusError, Exception)):
            await tool.call(request)

    assert attempt_count[0] == 1, f"Expected 1 attempt for 4xx FAST_FAIL, got {attempt_count[0]}"


# ────────────────────────────────────────────────────────────────────────────
# Test 7: 5xx → retries 2x then raises (3 total attempts per FAST_FAIL profile)
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_5xx_retries_then_fails(monkeypatch):
    """5xx response retries 2x then raises (3 total attempts per FAST_FAIL profile)."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000")
    tool = GetWeeklyExecutionSummaryTool()
    request = _make_request()

    attempt_count = [0]

    async def mock_get(url, **kwargs):
        attempt_count[0] += 1
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503 Service Unavailable",
            request=MagicMock(),
            response=mock_resp,
        )
        return mock_resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = mock_get
        mock_client_cls.return_value = mock_client

        with pytest.raises((httpx.HTTPStatusError, Exception)):
            await tool.call(request)

    assert attempt_count[0] == 3, f"Expected 3 attempts for 5xx FAST_FAIL, got {attempt_count[0]}"
