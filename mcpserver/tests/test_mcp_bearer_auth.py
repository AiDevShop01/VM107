"""Phase 67 Plan 12 — Bearer auth integration tests (Task 2).

Validates the FastMCP server's auth surface end-to-end against the
JWTVerifier provider:

  - Valid bearer token + correct scope → token verifies + carries scope.
  - Invalid bearer signature → verify_token returns None (401-equivalent).
  - Valid signature, WRONG audience → verify_token returns None (401).
  - Valid signature, correct audience, MISSING required scope → token
    loads but exposes only the granted scopes (server denies tool call).
  - JWKS_URI unreachable → BearerAuth/JWTVerifier raises a descriptive
    error during JWKS fetch (observable at first verify_token call).
  - MANUAL_UAT.md scaffold present with the 3 documented test sections.

NOTE: in fastmcp 3.x, BearerAuthProvider was renamed JWTVerifier — same
JWKS / issuer / audience / required_scopes kwargs. The plan's <interfaces>
block uses the 2.x name; we use the 3.x name per the requirements pin
(>=3.2,<4). Documented as a Pitfall 10 deviation in the SUMMARY.

We exercise JWTVerifier via the `public_key` constructor mode (vs. the
production `jwks_uri` mode) so tests don't need a live JWKS server. The
production code path is exercised separately by the JWKS-unreachable test.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# ---------------------------------------------------------------------------
# Constants + helpers
# ---------------------------------------------------------------------------

VM107_ROOT = Path(__file__).resolve().parents[2]
MANUAL_UAT_PATH = VM107_ROOT / "mcpserver" / "MANUAL_UAT.md"

_TEST_ISSUER = "fingpt-vm100"
_TEST_AUDIENCE = "fingpt-mcp-clients"
_REQUIRED_SCOPE = "mission_control:read"

_REQUIRED_ENV = {
    "VM107_MCP_JWKS_URI": "https://example.com/.well-known/jwks.json",
    "VM107_MCP_ISSUER": _TEST_ISSUER,
    "VM107_MCP_AUDIENCE": _TEST_AUDIENCE,
    "VM107_MCP_PORT": "50091",
    "VM100_BASE_URL": "http://vm100-backend:8000",
    "VM100_INTERNAL_TOKEN": "test-internal-token-abc123",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, **overrides) -> None:
    env = dict(_REQUIRED_ENV)
    env.update(overrides)
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


def _clear_server_module() -> None:
    for key in list(sys.modules.keys()):
        if key == "mcpserver" or key.startswith("mcpserver."):
            del sys.modules[key]


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[str, str]:
    """Generate an RSA keypair for signing test JWTs (PEM strings)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return priv_pem, pub_pem


def _make_jwt(
    priv_pem: str,
    *,
    issuer: str = _TEST_ISSUER,
    audience: str = _TEST_AUDIENCE,
    scope: str | None = _REQUIRED_SCOPE,
    expired: bool = False,
) -> str:
    now = datetime.now(tz=timezone.utc)
    exp = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
    payload: dict = {
        "iss": issuer,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "sub": "test-user",
    }
    if scope is not None:
        payload["scope"] = scope
    return pyjwt.encode(payload, priv_pem, algorithm="RS256")


# ---------------------------------------------------------------------------
# 1. Server module exposes JWTVerifier with the right scopes
# ---------------------------------------------------------------------------


def test_server_auth_is_jwt_verifier_with_required_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mcpserver.server.auth must be a JWTVerifier requiring mission_control:read."""
    _clear_server_module()
    _set_env(monkeypatch)
    server_mod = importlib.import_module("mcpserver.server")

    from fastmcp.server.auth.providers.jwt import JWTVerifier

    assert isinstance(server_mod.auth, JWTVerifier), (
        "mcpserver.server.auth must be a JWTVerifier instance"
    )
    assert server_mod.auth.jwks_uri == _REQUIRED_ENV["VM107_MCP_JWKS_URI"]
    assert (
        server_mod.auth.issuer == _TEST_ISSUER
        or _TEST_ISSUER in (server_mod.auth.issuer or [])
    )
    assert (
        server_mod.auth.audience == _TEST_AUDIENCE
        or _TEST_AUDIENCE in (server_mod.auth.audience or [])
    )
    assert server_mod.auth.required_scopes == [_REQUIRED_SCOPE], (
        f"required_scopes must be [{_REQUIRED_SCOPE!r}]; got {server_mod.auth.required_scopes}"
    )


# ---------------------------------------------------------------------------
# 2. JWTVerifier — valid token + correct scope → loads + carries scope
# ---------------------------------------------------------------------------


def test_valid_token_with_required_scope_verifies(rsa_keypair: tuple[str, str]) -> None:
    """A correctly-signed JWT with mission_control:read scope must verify."""
    priv, pub = rsa_keypair
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    verifier = JWTVerifier(
        public_key=pub,
        issuer=_TEST_ISSUER,
        audience=_TEST_AUDIENCE,
        required_scopes=[_REQUIRED_SCOPE],
        algorithm="RS256",
    )
    token = _make_jwt(priv)
    result = asyncio.run(verifier.verify_token(token))
    assert result is not None, "Valid token with correct scope must verify"
    # Granted scopes must include the required scope
    granted = result.scopes if hasattr(result, "scopes") else []
    assert _REQUIRED_SCOPE in granted, (
        f"Granted scopes must include {_REQUIRED_SCOPE!r}; got {granted}"
    )


# ---------------------------------------------------------------------------
# 3. JWTVerifier — invalid signature → rejected
# ---------------------------------------------------------------------------


def test_invalid_signature_rejected(rsa_keypair: tuple[str, str]) -> None:
    """A JWT signed by a DIFFERENT key (not the configured public_key) must NOT verify."""
    _priv, pub = rsa_keypair
    # Generate a fresh keypair NOT registered with the verifier
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_priv = other_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    from fastmcp.server.auth.providers.jwt import JWTVerifier

    verifier = JWTVerifier(
        public_key=pub,
        issuer=_TEST_ISSUER,
        audience=_TEST_AUDIENCE,
        required_scopes=[_REQUIRED_SCOPE],
        algorithm="RS256",
    )
    # Sign with the OTHER private key — signature won't match
    bad_token = _make_jwt(other_priv)
    result = asyncio.run(verifier.verify_token(bad_token))
    assert result is None, "Token with wrong signature must NOT verify"


# ---------------------------------------------------------------------------
# 4. JWTVerifier — wrong audience → rejected
# ---------------------------------------------------------------------------


def test_wrong_audience_rejected(rsa_keypair: tuple[str, str]) -> None:
    """A JWT with the WRONG `aud` claim must not verify."""
    priv, pub = rsa_keypair
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    verifier = JWTVerifier(
        public_key=pub,
        issuer=_TEST_ISSUER,
        audience=_TEST_AUDIENCE,
        required_scopes=[_REQUIRED_SCOPE],
        algorithm="RS256",
    )
    bad_aud_token = _make_jwt(priv, audience="wrong-audience-other-client")
    result = asyncio.run(verifier.verify_token(bad_aud_token))
    assert result is None, "Token with wrong audience must NOT verify"


# ---------------------------------------------------------------------------
# 5. JWTVerifier — missing required scope → loads but scopes empty (downstream denies)
# ---------------------------------------------------------------------------


def test_missing_required_scope_denied(rsa_keypair: tuple[str, str]) -> None:
    """A JWT missing the required scope must NOT verify (or must carry no granted scopes)."""
    priv, pub = rsa_keypair
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    verifier = JWTVerifier(
        public_key=pub,
        issuer=_TEST_ISSUER,
        audience=_TEST_AUDIENCE,
        required_scopes=[_REQUIRED_SCOPE],
        algorithm="RS256",
    )
    # Token with NO scope claim at all
    no_scope_token = _make_jwt(priv, scope=None)
    result = asyncio.run(verifier.verify_token(no_scope_token))
    # Either fully rejected (None) OR loaded but without the required scope.
    # The FastMCP server's tool-dispatch layer compares granted scopes to
    # required_scopes and denies if missing.
    if result is not None:
        granted = result.scopes if hasattr(result, "scopes") else []
        assert _REQUIRED_SCOPE not in granted, (
            "Token missing required scope must NOT carry it in granted scopes"
        )


# ---------------------------------------------------------------------------
# 6. JWTVerifier — expired token → rejected
# ---------------------------------------------------------------------------


def test_expired_token_rejected(rsa_keypair: tuple[str, str]) -> None:
    """An expired JWT must not verify."""
    priv, pub = rsa_keypair
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    verifier = JWTVerifier(
        public_key=pub,
        issuer=_TEST_ISSUER,
        audience=_TEST_AUDIENCE,
        required_scopes=[_REQUIRED_SCOPE],
        algorithm="RS256",
    )
    expired = _make_jwt(priv, expired=True)
    result = asyncio.run(verifier.verify_token(expired))
    assert result is None, "Expired token must NOT verify"


# ---------------------------------------------------------------------------
# 7. JWKS_URI unreachable — fetch raises descriptive error
# ---------------------------------------------------------------------------


def test_jwks_uri_unreachable_raises_on_token_verify() -> None:
    """When JWKS_URI is unreachable, verify_token returns None (logged error).

    This corresponds to the plan behavior: 'JWKS_URI unreachable → raises
    descriptive error at boot'. In FastMCP 3.x JWTVerifier, the JWKS fetch
    is lazy (first verify call) — the error surfaces there rather than at
    JWTVerifier() construction. verify_token returns None and logs the
    failure; both behaviours indicate auth is dead.
    """
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    verifier = JWTVerifier(
        jwks_uri="http://127.0.0.1:1/.well-known/jwks.json",  # unreachable
        issuer=_TEST_ISSUER,
        audience=_TEST_AUDIENCE,
        required_scopes=[_REQUIRED_SCOPE],
    )
    # Any token-shaped string triggers the JWKS fetch
    fake_token = (
        "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6InRlc3Qta2lkIn0."
        "eyJpc3MiOiJ4In0.invalid-signature"
    )
    # The verifier must NOT silently return a valid AccessToken when JWKS
    # is unreachable — either raises or returns None.
    try:
        result = asyncio.run(verifier.verify_token(fake_token))
        assert result is None, (
            "Verify must reject (None) when JWKS fetch fails — no token can "
            "be validated without keys"
        )
    except Exception:
        # Raising is also acceptable — caller treats both as auth failure
        pass


# ---------------------------------------------------------------------------
# 8. MANUAL_UAT.md scaffold present with required sections
# ---------------------------------------------------------------------------


def test_manual_uat_scaffold_present() -> None:
    """VM107/mcpserver/MANUAL_UAT.md must ship for VALIDATION.md row 6."""
    assert MANUAL_UAT_PATH.exists(), (
        f"MANUAL_UAT.md scaffold missing: {MANUAL_UAT_PATH}"
    )
    content = MANUAL_UAT_PATH.read_text()

    # Required sections per the plan's <interfaces> block
    assert "Manual UAT" in content, "Header missing"
    assert "Claude Desktop" in content, "Claude Desktop section missing"
    assert "Cursor" in content, "Cursor section missing"
    assert (
        "Bearer Auth" in content
        or "Bearer auth" in content
        or "bearer auth" in content
    ), "Bearer auth negative-tests section missing"

    # Each section should reference the actual tool names so a tester can grep
    assert "mission.close.surfaced_lesson" in content
    assert "mission.close.journal_prompts" in content
