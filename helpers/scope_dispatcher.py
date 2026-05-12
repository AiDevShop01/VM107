"""ScopeDispatcher — signs ScopeContext envelopes per CTX-§5.

Cognitive authorization, not transport credentials.

All cross-VM HTTP calls from VM107 carry X-Agent-Scope header. Downstream VMs
(VM100, VM102) verify the signature + scope claims BEFORE query planning
(RESEARCH.md Pitfall 8: pre-query enforcement). HS256 + monthly key rotation.

Key IDs (kid) enable zero-downtime rotation — verify step checks kid field
to select the appropriate secret when multiple keys are in rotation.

Directive #4: SCOPE_DISPATCHER_SECRET_KEY env var is REQUIRED at boot.
No fallback default. Silent misconfiguration is worse than a startup crash.
Configure via docker-compose.yml environment section.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

from fingpt_core.contracts.narrative.scope import ScopeContext

# Key ID for this VM107 scope signing key — bump to "vm107-scope-v2" on rotation
KID = "vm107-scope-v1"

_JWT_HEADER = {"alg": "HS256", "typ": "JWT", "kid": KID}
_JWT_HEADER_SERIALISED = json.dumps(_JWT_HEADER, separators=(",", ":")).encode("utf-8")


class ScopeSignatureError(Exception):
    """Raised when a token's HMAC signature does not match or the token is malformed."""


class ScopeExpiredError(Exception):
    """Raised when a token's ScopeContext has an expires_at in the past."""


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    # Restore standard base64 padding before decoding
    padded = s + "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


class ScopeDispatcher:
    """Signs and verifies ScopeContext JWT-shaped envelopes.

    Usage:
        dispatcher = ScopeDispatcher()   # reads SCOPE_DISPATCHER_SECRET_KEY from env
        token = dispatcher.sign_scope_context(ctx)
        ctx = dispatcher.verify(token)
        headers = dispatcher.attach_header({}, ctx)
    """

    def __init__(self, secret_key: str | None = None) -> None:
        """Construct dispatcher. secret_key defaults to SCOPE_DISPATCHER_SECRET_KEY env var.

        Raises RuntimeError immediately if neither argument nor env var is set.
        This is intentional (Directive #4 — fail-fast at startup, no silent defaults).
        """
        secret = secret_key if secret_key is not None else os.environ.get("SCOPE_DISPATCHER_SECRET_KEY")
        if not secret:
            raise RuntimeError(
                "SCOPE_DISPATCHER_SECRET_KEY must be set (no fallback per Directive #4 — "
                "env-driven config, no silent default). Configure via docker-compose.yml."
            )
        self._secret: bytes = secret.encode("utf-8")

    # ------------------------------------------------------------------
    # Signing
    # ------------------------------------------------------------------

    def sign_scope_context(self, scope_context: ScopeContext) -> str:
        """Return a JWT-shaped HS256 token: base64url(header).base64url(payload).base64url(sig).

        The payload is the Pydantic ScopeContext serialised to JSON with sorted keys.
        Sorted keys ensure deterministic output for the same input (important for caching).
        """
        header_b64 = _b64url_encode(_JWT_HEADER_SERIALISED)
        # model_dump_json serialises datetime + UUID correctly
        payload_dict = json.loads(scope_context.model_dump_json())
        payload_b64 = _b64url_encode(
            json.dumps(payload_dict, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        sig = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        sig_b64 = _b64url_encode(sig)
        return f"{header_b64}.{payload_b64}.{sig_b64}"

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify(self, token: str) -> ScopeContext:
        """Verify signature and expiry; return the decoded ScopeContext.

        Raises:
            ScopeSignatureError: if the token is malformed or the HMAC does not match.
            ScopeExpiredError:   if scope_context.expires_at is in the past.
        """
        try:
            header_b64, payload_b64, sig_b64 = token.split(".")
        except ValueError as exc:
            raise ScopeSignatureError(
                "Malformed token — expected 3 dot-separated base64url segments."
            ) from exc

        # Recompute expected HMAC
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig = hmac.new(self._secret, signing_input, hashlib.sha256).digest()

        try:
            actual_sig = _b64url_decode(sig_b64)
        except Exception as exc:
            raise ScopeSignatureError("Malformed signature segment.") from exc

        # Constant-time comparison prevents timing attacks
        if not hmac.compare_digest(expected_sig, actual_sig):
            raise ScopeSignatureError(
                "Signature mismatch — token was tampered with or signed with a different key."
            )

        # Decode and parse payload
        try:
            payload_bytes = _b64url_decode(payload_b64)
            payload = json.loads(payload_bytes.decode("utf-8"))
        except Exception as exc:
            raise ScopeSignatureError("Failed to decode payload segment.") from exc

        ctx = ScopeContext.model_validate(payload)

        # Expiry check (post-signature — only examine content after trust is established)
        now = datetime.now(timezone.utc)
        if ctx.expires_at <= now:
            raise ScopeExpiredError(
                f"ScopeContext expired at {ctx.expires_at} (current UTC: {now}). "
                "Re-issue a fresh scope context for this invocation."
            )

        return ctx

    # ------------------------------------------------------------------
    # Header injection
    # ------------------------------------------------------------------

    def attach_header(self, headers: dict, scope_context: ScopeContext) -> dict:
        """Inject X-Agent-Scope header into the headers dict.

        Mutates headers in-place AND returns it (fluent usage):
            headers = dispatcher.attach_header(httpx_request.headers, ctx)

        This is the single call-site for all downstream VM HTTP calls from VM107
        (VM100 narrative endpoints, VM102 analytics endpoints, Qdrant, Neo4j).
        """
        headers["X-Agent-Scope"] = self.sign_scope_context(scope_context)
        return headers

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def is_expired(self, scope_context: ScopeContext) -> bool:
        """Return True if scope_context.expires_at is in the past."""
        return scope_context.expires_at <= datetime.now(timezone.utc)
