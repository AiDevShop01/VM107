"""Tests for ScopeDispatcher — CTX-§5.

ScopeDispatcher signs ScopeContext envelopes as JWT-shaped tokens (HS256)
and attaches them as X-Agent-Scope headers on outbound HTTP calls.

Agents NEVER self-authorize. The dispatcher is the cognition gateway.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from datetime import datetime, timezone, timedelta
from uuid import UUID

import pytest


@pytest.fixture()
def scope_ctx():
    """Build a minimal valid ScopeContext for testing."""
    from fingpt_core.contracts.narrative.scope import (
        ScopeContext,
        TruthMode,
    )
    now = datetime.now(timezone.utc)
    return ScopeContext(
        profile_id="trade_auditor_agent._reader",
        account_id="acc-test-001",
        execution_id=UUID("12345678-1234-5678-1234-567812345678"),
        truth_mode=TruthMode.HISTORICAL,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )


@pytest.fixture()
def dispatcher(monkeypatch):
    """Create a ScopeDispatcher with a test secret via env var."""
    monkeypatch.setenv("SCOPE_DISPATCHER_SECRET_KEY", "test-secret-do-not-use-in-prod")
    from helpers.scope_dispatcher import ScopeDispatcher
    return ScopeDispatcher()


def test_jwt_signing(dispatcher, scope_ctx):
    """CTX-§5 — ScopeDispatcher.sign_scope_context produces a JWT-shaped a.b.c token."""
    token = dispatcher.sign_scope_context(scope_ctx)
    parts = token.split(".")
    assert len(parts) == 3, f"Expected 3 dot-separated segments, got {len(parts)}: {token!r}"
    # Each segment must be non-empty base64url
    for part in parts:
        assert part, "Empty segment in JWT token"
        # Base64url chars only
        import re
        assert re.match(r'^[A-Za-z0-9_-]+$', part), f"Segment not base64url: {part!r}"


def test_roundtrip_sign_verify(dispatcher, scope_ctx):
    """sign then verify returns a ScopeContext equal to the original."""
    token = dispatcher.sign_scope_context(scope_ctx)
    recovered = dispatcher.verify(token)
    # Compare by model_dump for Pydantic equality
    assert recovered.model_dump() == scope_ctx.model_dump()


def test_attach_header(dispatcher, scope_ctx):
    """attach_header mutates headers dict in-place with X-Agent-Scope."""
    headers = {}
    result = dispatcher.attach_header(headers, scope_ctx)
    assert "X-Agent-Scope" in result
    expected_token = dispatcher.sign_scope_context(scope_ctx)
    # Tokens should decode to the same payload (sign is deterministic for same input at same time)
    # Verify the attached token is itself valid
    recovered = dispatcher.verify(result["X-Agent-Scope"])
    assert recovered.model_dump() == scope_ctx.model_dump()
    # Also verify attach_header returns the same dict object (mutates in-place)
    assert result is headers


def test_signature_mismatch_different_secret(monkeypatch, scope_ctx):
    """Token signed with secret A, verified with secret B → ScopeSignatureError."""
    monkeypatch.setenv("SCOPE_DISPATCHER_SECRET_KEY", "secret-A")
    from helpers.scope_dispatcher import ScopeDispatcher, ScopeSignatureError
    dispatcher_a = ScopeDispatcher()
    token = dispatcher_a.sign_scope_context(scope_ctx)

    monkeypatch.setenv("SCOPE_DISPATCHER_SECRET_KEY", "secret-B")
    # Re-import or construct with explicit key
    dispatcher_b = ScopeDispatcher(secret_key="secret-B")
    with pytest.raises(ScopeSignatureError):
        dispatcher_b.verify(token)


def test_payload_tampered_after_signing(dispatcher, scope_ctx):
    """Tamper with payload segment but keep old signature → ScopeSignatureError."""
    import base64
    import json
    from helpers.scope_dispatcher import ScopeSignatureError

    token = dispatcher.sign_scope_context(scope_ctx)
    header_b64, payload_b64, sig_b64 = token.split(".")

    # Tamper: decode payload, change profile_id, re-encode
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    payload_dict = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    payload_dict["profile_id"] = "evil_agent"
    tampered_payload = base64.urlsafe_b64encode(
        json.dumps(payload_dict, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()

    tampered_token = f"{header_b64}.{tampered_payload}.{sig_b64}"
    with pytest.raises(ScopeSignatureError):
        dispatcher.verify(tampered_token)


def test_expired_token_rejected(monkeypatch, scope_ctx):
    """ScopeContext with expires_at in the past → ScopeExpiredError on verify."""
    monkeypatch.setenv("SCOPE_DISPATCHER_SECRET_KEY", "test-secret-do-not-use-in-prod")
    from fingpt_core.contracts.narrative.scope import ScopeContext, TruthMode
    from helpers.scope_dispatcher import ScopeDispatcher, ScopeExpiredError

    now = datetime.now(timezone.utc)
    expired_ctx = ScopeContext(
        profile_id="trade_auditor_agent._reader",
        account_id="acc-test-001",
        execution_id=UUID("12345678-1234-5678-1234-567812345678"),
        truth_mode=TruthMode.HISTORICAL,
        issued_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),  # expired 1 hour ago
    )
    disp = ScopeDispatcher()
    token = disp.sign_scope_context(expired_ctx)
    with pytest.raises(ScopeExpiredError):
        disp.verify(token)


def test_construct_without_env_var_raises(monkeypatch):
    """Missing SCOPE_DISPATCHER_SECRET_KEY → RuntimeError at construction (fail-fast, Directive #4)."""
    monkeypatch.delenv("SCOPE_DISPATCHER_SECRET_KEY", raising=False)
    from helpers.scope_dispatcher import ScopeDispatcher
    with pytest.raises(RuntimeError) as exc_info:
        ScopeDispatcher()
    # Should mention Directive #4 or fail-fast
    assert "SCOPE_DISPATCHER_SECRET_KEY" in str(exc_info.value)
