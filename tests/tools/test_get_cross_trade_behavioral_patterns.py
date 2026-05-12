"""Tests for GetCrossTradeBehavioralPatternsTool — TOOL GAP #2 CLOSURE.

Queries Neo4j :EXHIBITS BehavioralPattern edges across an account's executions
via VM100 typed endpoint. Phase 39 typed-API lock: VM107 NEVER queries Neo4j directly.

BLOCKER #4 doctrine: env-var fetch at INSTANCE construction, not at module import.
Module imports must stay clean even with VM100_INTERNAL_BASE_URL unset.

Test cases:
  1. test_module_imports_cleanly_without_env_var  (BLOCKER #4 audit)
  2. test_construction_fails_without_vm100_url
  3. test_request_contract_extra_forbid
  4. test_endpoint_uses_cross_trade_route
  5. test_http_method_is_get
  6. test_4xx_no_retry
  7. test_5xx_retries_then_fails
"""
from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import httpx
from pydantic import ValidationError

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# ────────────────────────────────────────────────────────────────────────────
# Import the module under test (set env var first to allow scope import)
# ────────────────────────────────────────────────────────────────────────────

os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://test-vm100:8000")
os.environ.setdefault("SCOPE_DISPATCHER_SECRET_KEY", "test-secret")

from tools.get_cross_trade_behavioral_patterns import (
    GetCrossTradeBehavioralPatternsTool,
    GetCrossTradeBehavioralPatternsRequest,
    GetCrossTradeBehavioralPatternsResponse,
    CrossTradePatternItem,
)
from fingpt_core.contracts.narrative.scope import ScopeContext, TruthMode, NarrativeVisibility


# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

def _make_scope_context() -> ScopeContext:
    now = datetime.now(timezone.utc)
    return ScopeContext(
        profile_id="behavioral_mentor_agent._analyzer",
        account_id="acc-001",
        execution_id=None,
        truth_mode=TruthMode.HISTORICAL,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _make_request(
    account_id: str = "acc-001",
    window_days: int = 30,
) -> GetCrossTradeBehavioralPatternsRequest:
    scope = _make_scope_context()
    return GetCrossTradeBehavioralPatternsRequest(
        account_id=account_id,
        window_days=window_days,
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
    import tools.get_cross_trade_behavioral_patterns as ctbp_module
    importlib.reload(ctbp_module)  # force fresh load with env var absent

    # Module exports still accessible (no RuntimeError at module scope)
    assert hasattr(ctbp_module, "GetCrossTradeBehavioralPatternsTool")
    assert hasattr(ctbp_module, "GetCrossTradeBehavioralPatternsRequest")
    assert hasattr(ctbp_module, "GetCrossTradeBehavioralPatternsResponse")


# ────────────────────────────────────────────────────────────────────────────
# Test 2: instantiation fails without env var (INSTANCE-level fail-fast)
# ────────────────────────────────────────────────────────────────────────────

def test_construction_fails_without_vm100_url(monkeypatch):
    """GetCrossTradeBehavioralPatternsTool() raises RuntimeError if VM100_INTERNAL_BASE_URL is not set."""
    monkeypatch.delenv("VM100_INTERNAL_BASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="VM100_INTERNAL_BASE_URL"):
        GetCrossTradeBehavioralPatternsTool()


# ────────────────────────────────────────────────────────────────────────────
# Test 3: request_contract has extra='forbid'
# ────────────────────────────────────────────────────────────────────────────

def test_request_contract_extra_forbid():
    """GetCrossTradeBehavioralPatternsRequest with extra fields raises ValidationError."""
    scope = _make_scope_context()
    with pytest.raises(ValidationError):
        GetCrossTradeBehavioralPatternsRequest(
            account_id="acc-001",
            window_days=30,
            scope_context=scope,
            extra_field_that_should_be_rejected="forbidden",
        )


# ────────────────────────────────────────────────────────────────────────────
# Test 4: endpoint() uses cross-trade-patterns route
# ────────────────────────────────────────────────────────────────────────────

def test_endpoint_uses_cross_trade_route(monkeypatch):
    """endpoint() returns the cross-trade-patterns route (not behavioral-edges)."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000")
    tool = GetCrossTradeBehavioralPatternsTool()
    request = _make_request()

    url = tool.endpoint(request)

    assert "/cross-trade-patterns" in url, f"Expected '/cross-trade-patterns' in URL: {url}"
    assert url.startswith("http://vm100:8000"), f"URL should start with base URL: {url}"
    # Should NOT contain execution_id path segment (query-string API, not path param)
    assert "/behavioral-edges/" not in url, "Should not use behavioral-edges route"


# ────────────────────────────────────────────────────────────────────────────
# Test 5: http_method() returns "GET"
# ────────────────────────────────────────────────────────────────────────────

def test_http_method_is_get(monkeypatch):
    """GetCrossTradeBehavioralPatternsTool uses HTTP GET method."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000")
    tool = GetCrossTradeBehavioralPatternsTool()

    assert tool.http_method() == "GET"


# ────────────────────────────────────────────────────────────────────────────
# Test 6: 4xx → no retry (FAST_FAIL)
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_4xx_no_retry(monkeypatch):
    """4xx response raises immediately; FAST_FAIL means exactly 1 HTTP attempt."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000")
    tool = GetCrossTradeBehavioralPatternsTool()
    request = _make_request()

    attempt_count = [0]

    async def mock_get(url, **kwargs):
        attempt_count[0] += 1
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "422 Unprocessable Entity",
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
    tool = GetCrossTradeBehavioralPatternsTool()
    request = _make_request()

    attempt_count = [0]

    async def mock_get(url, **kwargs):
        attempt_count[0] += 1
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Internal Server Error",
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
