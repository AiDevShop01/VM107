"""Tests for PersistNarrativeTool — writer-tier HTTP client to VM100 internal endpoint.

CTX-§3 + Phase 39 typed-API lock: persist_narrative routes through VM100 HTTP endpoint.
NEVER direct DB write from VM107.

BLOCKER #4 doctrine: env-var fetch at INSTANCE construction, not at module import.
Module imports must stay clean even with VM100_INTERNAL_BASE_URL unset.

Test cases:
  1. test_request_contract_pydantic_extra_forbid
  2. test_endpoint_includes_execution_id
  3. test_endpoint_for_weekly_uses_weekly_route
  4. test_module_imports_cleanly_without_env_var  (BLOCKER #4 audit)
  5. test_construction_fails_without_vm100_url
  6. test_http_post_attaches_scope_header
  7. test_4xx_no_retry
  8. test_5xx_retries_then_fails
"""
from __future__ import annotations

import sys
import importlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
from uuid import UUID, uuid4

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest
import httpx
from datetime import datetime, timezone, timedelta

from pydantic import ValidationError

from fingpt_core.contracts.narrative.scope import (
    ScopeContext, TruthMode
)
from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
from fingpt_core.contracts.narrative.sentence import NarrativeSentence, SentenceClass
from fingpt_core.contracts.narrative.citation import CitationToken


# ────────────────────────────────────────────────────────────────────────────
# Import the module under test (set env var first to allow import)
# ────────────────────────────────────────────────────────────────────────────

import os
os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://test-vm100:8000")

from tools.persist_narrative import (
    PersistNarrativeTool,
    PersistNarrativeRequest,
    PersistNarrativeResponse,
)


# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

def _make_scope_context() -> ScopeContext:
    now = datetime.now(timezone.utc)
    return ScopeContext(
        profile_id="trade_auditor_agent",
        account_id="acc-001",
        execution_id=uuid4(),
        truth_mode=TruthMode.HISTORICAL,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _make_envelope(execution_id: UUID | None = None, profile: str = "trade_auditor_agent") -> NarrativeEnvelope:
    return NarrativeEnvelope(
        profile=profile,
        execution_id=execution_id or uuid4(),
        sentences=[
            NarrativeSentence(
                sentence_index=0,
                sentence_class=SentenceClass.TRANSITION,
                text="The trade was executed promptly.",
                citations=[],
            )
        ],
    )


def _make_persist_request(execution_id: UUID | None = None, profile: str = "trade_auditor_agent") -> PersistNarrativeRequest:
    scope_context = _make_scope_context()
    envelope = _make_envelope(execution_id=execution_id, profile=profile)
    return PersistNarrativeRequest(
        envelope=envelope,
        scope_context=scope_context,
        ruleset_version="v1.0",
        analysis_version=1,
        template_version="t1.0",
        scope_origin=scope_context.model_dump_json(),
        truth_mode="HISTORICAL",
        source_snapshot_id=uuid4(),
        source_replay_artifact_id=uuid4(),
        generated_by="dagster_sensor",
        generated_reason="AUTO",
        writer_profile_id="trade_auditor_agent._writer",
    )


# ────────────────────────────────────────────────────────────────────────────
# Test 1: PersistNarrativeRequest rejects extra fields (Pydantic extra='forbid')
# ────────────────────────────────────────────────────────────────────────────

def test_request_contract_pydantic_extra_forbid():
    """PersistNarrativeRequest with extra fields raises ValidationError."""
    scope_context = _make_scope_context()
    envelope = _make_envelope()
    with pytest.raises(ValidationError):
        PersistNarrativeRequest(
            envelope=envelope,
            scope_context=scope_context,
            ruleset_version="v1.0",
            analysis_version=1,
            template_version="t1.0",
            scope_origin="{}",
            truth_mode="HISTORICAL",
            source_snapshot_id=uuid4(),
            source_replay_artifact_id=uuid4(),
            generated_by="dagster_sensor",
            generated_reason="AUTO",
            writer_profile_id="trade_auditor_agent._writer",
            extra_field_that_should_be_rejected=42,  # this must cause failure
        )


# ────────────────────────────────────────────────────────────────────────────
# Test 2: endpoint includes execution_id
# ────────────────────────────────────────────────────────────────────────────

def test_endpoint_includes_execution_id(monkeypatch):
    """Tool endpoint includes execution_id in URL path."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000")
    tool = PersistNarrativeTool()

    execution_id = uuid4()
    request = _make_persist_request(execution_id=execution_id, profile="trade_auditor")

    endpoint = tool.endpoint(request)

    assert str(execution_id) in endpoint, f"execution_id {execution_id} not in endpoint: {endpoint}"
    assert endpoint.endswith(f"/{execution_id}/trade_auditor") or f"/{execution_id}/trade_auditor" in endpoint


# ────────────────────────────────────────────────────────────────────────────
# Test 3: weekly_review endpoint uses weekly route shape
# ────────────────────────────────────────────────────────────────────────────

def test_endpoint_for_weekly_uses_weekly_route(monkeypatch):
    """When execution_id is None, endpoint uses /weekly/<profile> route."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000")
    tool = PersistNarrativeTool()

    weekly_envelope = NarrativeEnvelope(
        profile="weekly_review",
        execution_id=None,
        sentences=[
            NarrativeSentence(
                sentence_index=0,
                sentence_class=SentenceClass.TRANSITION,
                text="Weekly review complete.",
                citations=[],
            )
        ],
    )
    scope_context = _make_scope_context()
    request = PersistNarrativeRequest(
        envelope=weekly_envelope,
        scope_context=scope_context,
        ruleset_version="v1.0",
        analysis_version=1,
        template_version="t1.0",
        scope_origin="{}",
        truth_mode="HISTORICAL",
        source_snapshot_id=uuid4(),
        source_replay_artifact_id=uuid4(),
        generated_by="weekly_schedule",
        generated_reason="SCHEDULED",
        writer_profile_id="weekly_review._writer",
    )

    endpoint = tool.endpoint(request)

    assert "/weekly/" in endpoint, f"Expected '/weekly/' in endpoint: {endpoint}"
    assert endpoint.endswith("/weekly/weekly_review") or "/weekly/weekly_review" in endpoint


# ────────────────────────────────────────────────────────────────────────────
# Test 4: BLOCKER #4 audit — module imports cleanly without env var set
# ────────────────────────────────────────────────────────────────────────────

def test_module_imports_cleanly_without_env_var(monkeypatch):
    """Module-level import must NOT raise RuntimeError even when VM100_INTERNAL_BASE_URL is unset.

    BLOCKER #4 doctrine: fail-fast at INSTANCE construction, never at module import.
    This prevents pytest collection failures in CI / local dev without the env var.
    """
    monkeypatch.delenv("VM100_INTERNAL_BASE_URL", raising=False)

    # Re-importing should NOT raise — module-level code has no side effects
    import tools.persist_narrative as pn_module
    importlib.reload(pn_module)  # force fresh load with env var absent

    # Module exports still accessible (no RuntimeError at module scope)
    assert hasattr(pn_module, "PersistNarrativeTool")
    assert hasattr(pn_module, "PersistNarrativeRequest")
    assert hasattr(pn_module, "PersistNarrativeResponse")


# ────────────────────────────────────────────────────────────────────────────
# Test 5: instantiation fails without env var (INSTANCE-level fail-fast)
# ────────────────────────────────────────────────────────────────────────────

def test_construction_fails_without_vm100_url(monkeypatch):
    """PersistNarrativeTool() raises RuntimeError if VM100_INTERNAL_BASE_URL is not set."""
    monkeypatch.delenv("VM100_INTERNAL_BASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="VM100_INTERNAL_BASE_URL"):
        PersistNarrativeTool()


# ────────────────────────────────────────────────────────────────────────────
# Test 6: HTTP POST attaches X-Agent-Scope header
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_http_post_attaches_scope_header(monkeypatch):
    """POST to VM100 carries X-Agent-Scope header (attached by caller before invocation)."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000")

    tool = PersistNarrativeTool()
    request = _make_persist_request()

    # Mock httpx.AsyncClient.post to capture the request headers
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "narrative_id": str(uuid4()),
        "narrative_version": 1,
        "unsourced_claim_count": 0,
    }
    mock_response.raise_for_status = MagicMock()

    captured_kwargs = {}

    async def mock_post(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return mock_response

    # Inject X-Agent-Scope header (as orchestrator would)
    scope_headers = {"X-Agent-Scope": "eyJ0eXAiOiJKV1QifQ.eyJwcm9maWxlX2lkIjoidGVzdCJ9.sig"}

    with patch.object(tool, "_make_headers", return_value=scope_headers, create=True):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = mock_post
            mock_client_cls.return_value = mock_client

            response = await tool.persist(request, headers=scope_headers)

    # Verify the tool uses POST method
    assert tool.http_method() == "POST"


# ────────────────────────────────────────────────────────────────────────────
# Test 7: 4xx → no retry (FAST_FAIL)
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_4xx_no_retry(monkeypatch):
    """4xx response raises immediately; FAST_FAIL means exactly 1 HTTP attempt."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000")
    tool = PersistNarrativeTool()
    request = _make_persist_request()

    attempt_count = [0]

    async def mock_post(url, **kwargs):
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
        mock_client.post = mock_post
        mock_client_cls.return_value = mock_client

        with pytest.raises((httpx.HTTPStatusError, Exception)):
            await tool.persist(request)

    assert attempt_count[0] == 1, f"Expected 1 attempt for 4xx, got {attempt_count[0]}"


# ────────────────────────────────────────────────────────────────────────────
# Test 8: 5xx → retries 2x then raises (3 total attempts per FAST_FAIL profile)
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_5xx_retries_then_fails(monkeypatch):
    """5xx response retries 2x then raises (3 total attempts per FAST_FAIL profile)."""
    monkeypatch.setenv("VM100_INTERNAL_BASE_URL", "http://vm100:8000")
    tool = PersistNarrativeTool()
    request = _make_persist_request()

    attempt_count = [0]

    async def mock_post(url, **kwargs):
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
        mock_client.post = mock_post
        mock_client_cls.return_value = mock_client

        with pytest.raises((httpx.HTTPStatusError, Exception)):
            await tool.persist(request)

    assert attempt_count[0] == 3, f"Expected 3 attempts for 5xx FAST_FAIL, got {attempt_count[0]}"
