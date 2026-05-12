"""Tests for GetBehavioralEdgesTool — TOOL GAP #1 CLOSURE.

Queries Neo4j :FAILED_DUE_TO edges per execution_id via VM100 typed endpoint.
Phase 39 typed-API lock: VM107 NEVER queries Neo4j directly.

BLOCKER #4 doctrine: env-var fetch at INSTANCE construction, not at module import.
Module imports must stay clean even with VM100_INTERNAL_BASE_URL unset.

Test cases:
  1. test_module_imports_cleanly_without_env_var  (BLOCKER #4 audit)
  2. test_construction_fails_without_vm100_url
  3. test_request_contract_extra_forbid
  4. test_endpoint_includes_execution_id
  5. test_http_method_is_get
  6. test_4xx_no_retry
  7. test_5xx_retries_then_fails
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import httpx
from pydantic import ValidationError

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# ────────────────────────────────────────────────────────────────────────────
# Import the module under test (set env var first to allow import)
# ────────────────────────────────────────────────────────────────────────────

os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://test-vm100:8000")

from tools.get_behavioral_edges import (
    GetBehavioralEdgesTool,
    GetBehavioralEdgesRequest,
    GetBehavioralEdgesResponse,
)
from fingpt_core.contracts.narrative.scope import ScopeContext, TruthMode, NarrativeVisibility
from datetime import datetime, timezone, timedelta


# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

def _make_scope_context() -> ScopeContext:
    now = datetime.now(timezone.utc)
    return ScopeContext(
        profile_id="trade_auditor_agent._analyzer",
        account_id="acc-001",
        execution_id=uuid4(),
        truth_mode=TruthMode.HISTORICAL,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _make_request(execution_id: UUID | None = None) -> GetBehavioralEdgesRequest:
    scope = _make_scope_context()
    return GetBehavioralEdgesRequest(
        execution_id=execution_id or uuid4(),
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
    import tools.get_behavioral_edges as gbe_module
    importlib.reload(gbe_module)  # force fresh load with env var absent

    # Module exports still accessible (no RuntimeError at module scope)
    assert hasattr(gbe_module, "GetBehavioralEdgesTool")
    assert hasattr(gbe_module, "GetBehavioralEdgesRequest")
    assert hasattr(gbe_module, "GetBehavioralEdgesResponse")


# ────────────────────────────────────────────────────────────────────────────
# Test 2: instantiation fails without env var (INSTANCE-level fail-fast)
# ────────────────────────────────────────────────────────────────────────────

def test_construction_fails_without_vm100_url(monkeypatch):
    """GetBehavioralEdgesTool() raises RuntimeError if VM100_INTERNAL_BASE_URL is not set."""
    monkeypatch.delenv("VM100_INTERNAL_BASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="VM100_INTERNAL_BASE_URL"):
        GetBehavioralEdgesTool()


# ────────────────────────────────────────────────────────────────────────────
# Test 3: request_contract has extra='forbid'
# ────────────────────────────────────────────────────────────────────────────

def test_request_contract_extra_forbid():
    """GetBehavioralEdgesRequest with extra fields raises ValidationError."""
    scope = _make_scope_context()
    with pytest.raises(ValidationError):
        GetBehavioralEdgesRequest(
            execution_id=uuid4(),
            scope_context=scope,
            extra_field_that_should_be_rejected=42,
        )


# ────────────────────────────────────────────────────────────────────────────
# Test 4: endpoint() includes execution_id in path
# ────────────────────────────────────────────────────────────────────────────

def test_endpoint_includes_execution_id(monkeypatch):
    """endpoint() returns URL with execution_id substituted into the path."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000")
    tool = GetBehavioralEdgesTool()

    execution_id = uuid4()
    request = _make_request(execution_id=execution_id)
    url = tool.endpoint(request)

    assert str(execution_id) in url, f"execution_id {execution_id} not in URL: {url}"
    assert "/behavioral-edges/" in url, f"Expected '/behavioral-edges/' in URL: {url}"
    assert url.endswith(str(execution_id)), f"URL should end with execution_id: {url}"


# ────────────────────────────────────────────────────────────────────────────
# Test 5: http_method() returns "GET"
# ────────────────────────────────────────────────────────────────────────────

def test_http_method_is_get(monkeypatch):
    """GetBehavioralEdgesTool uses HTTP GET method."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000")
    tool = GetBehavioralEdgesTool()

    assert tool.http_method() == "GET"


# ────────────────────────────────────────────────────────────────────────────
# Test 6: 4xx → no retry (FAST_FAIL)
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_4xx_no_retry(monkeypatch):
    """4xx response raises immediately; FAST_FAIL means exactly 1 HTTP attempt."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000")
    tool = GetBehavioralEdgesTool()
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
    tool = GetBehavioralEdgesTool()
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
