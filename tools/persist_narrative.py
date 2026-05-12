"""persist_narrative — writer-tier tool. Only _writer sub-profiles may invoke this.

Routes through VM100 internal endpoint per Phase 39 typed-API lock.
NEVER reads VM100 DB or filesystem directly.

Phase 39 typed-API lock: all cross-VM persistence routes through typed HTTP endpoints.
Phase 47.6 registry mandate: this tool is registered at VM107/registry/tool/persist_narrative.yaml.
CTX-§5: X-Agent-Scope header is injected by the orchestrator (ScopeDispatcher.attach_header)
  before invoking this tool. This tool propagates the header to the HTTP request.

BLOCKER #4 doctrine: env-var fetch lives in __init__(), NOT at module scope.
Module-level `raise RuntimeError` breaks pytest collection in any environment
that hasn't set the env var (CI test discovery, local dev). Class-level fail-fast
at instantiation still honors Directive #4 (no silent default) while keeping
imports clean.

Tool registration enforces writer-tier restriction via tool_scope.py SENSITIVE_TOOLS
(60-05): only _writer sub-profiles have persist_narrative in their HARD_ALLOWED_TOOLS.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict

from fingpt_core.contracts.narrative.envelope import NarrativeEnvelope
from fingpt_core.contracts.narrative.scope import ScopeContext
from fingpt_core.contracts.errors import ContractValidationError

logger = logging.getLogger("fingpt.tools.persist_narrative")

# FAST_FAIL retry profile: 4xx → no retry; 5xx → 2 retries (3 total attempts)
_FAST_FAIL_MAX_5XX_RETRIES = 2


class PersistNarrativeRequest(BaseModel):
    """Request contract for persist_narrative tool.

    All fields required. frozen=True + extra='forbid' per Phase 60 contract discipline.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    envelope: NarrativeEnvelope
    scope_context: ScopeContext
    ruleset_version: str
    analysis_version: int
    template_version: str
    scope_origin: str
    truth_mode: str
    source_snapshot_id: UUID
    source_replay_artifact_id: UUID | None
    generated_by: str
    generated_reason: str
    writer_profile_id: str
    requested_by: str | None = None
    reason_note: str | None = None


class PersistNarrativeResponse(BaseModel):
    """Response contract for persist_narrative tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    narrative_id: UUID
    narrative_version: int
    unsourced_claim_count: int


class PersistNarrativeTool:
    """Writer-tier tool that persists a NarrativeEnvelope to VM100 internal endpoint.

    This is a standalone class (not inheriting Agent Zero Tool base) used by the
    MentorPipelineOrchestrator directly. The orchestrator passes it as
    `narrative_persister_client` and calls `.persist(request)`.

    FAST_FAIL retry profile:
      - 4xx responses: raise immediately (no retry — client error, retrying won't help)
      - 5xx / network errors: up to 2 retries (3 total attempts), then raise
      - On success: returns PersistNarrativeResponse

    URL pattern:
      - Per-trade: POST {VM100_INTERNAL_BASE_URL}/api/journal/internal/review-narratives/{execution_id}/{profile}
      - Weekly:    POST {VM100_INTERNAL_BASE_URL}/api/journal/internal/review-narratives/weekly/{profile}

    Env-var doctrine (Directive #4):
      VM100_INTERNAL_BASE_URL is read in __init__ — fail-fast at instantiation,
      never at module import. No fallback default.
    """

    name = "persist_narrative"

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

    def endpoint(self, request: PersistNarrativeRequest) -> str:
        """Build the VM100 internal endpoint URL for this persist request.

        URL shape (per plan 60-06 interface spec):
          - Per-trade: .../review-narratives/{execution_id}/{profile}
          - Weekly (execution_id is None): .../review-narratives/weekly/{profile}
        """
        exec_id = request.envelope.execution_id
        profile = request.envelope.profile
        if exec_id is None:
            return f"{self._base_url}/api/journal/internal/review-narratives/weekly/{profile}"
        return f"{self._base_url}/api/journal/internal/review-narratives/{exec_id}/{profile}"

    def http_method(self) -> str:
        """HTTP method for persist operation."""
        return "POST"

    async def persist(
        self,
        request: PersistNarrativeRequest,
        headers: dict | None = None,
    ) -> PersistNarrativeResponse:
        """Execute the HTTP POST to VM100 internal endpoint.

        Implements FAST_FAIL retry profile:
          - 4xx: raise immediately (no retry)
          - 5xx / transport errors: up to 2 retries (3 total attempts), then raise
          - 200: return PersistNarrativeResponse

        Args:
            request: Validated PersistNarrativeRequest
            headers: Optional headers dict (caller should inject X-Agent-Scope
                     via ScopeDispatcher.attach_header before calling persist)

        Returns:
            PersistNarrativeResponse with narrative_id + narrative_version

        Raises:
            httpx.HTTPStatusError: On 4xx (immediately) or 5xx (after retries exhausted)
            httpx.TransportError: On network failure after retries exhausted
            ContractValidationError: On invalid response shape
        """
        url = self.endpoint(request)
        outbound_headers = {**(headers or {})}
        payload = self._build_payload(request)

        last_exc: Exception | None = None
        for attempt in range(_FAST_FAIL_MAX_5XX_RETRIES + 1):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, json=payload, headers=outbound_headers)
                    response.raise_for_status()
                    data = response.json()
                    try:
                        return PersistNarrativeResponse.model_validate(data)
                    except Exception as ve:
                        raise ContractValidationError(
                            message=f"Invalid PersistNarrativeResponse: {ve}",
                            errors=[str(ve)],
                        ) from ve
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if 400 <= status < 500:
                    # 4xx: FAST_FAIL — no retry
                    logger.error(
                        "persist_narrative: 4xx from VM100 (%s) — no retry: %s",
                        status,
                        exc,
                    )
                    raise
                # 5xx: retry
                last_exc = exc
                logger.warning(
                    "persist_narrative: 5xx from VM100 (%s) — attempt %d/%d: %s",
                    status,
                    attempt + 1,
                    _FAST_FAIL_MAX_5XX_RETRIES + 1,
                    exc,
                )
            except (httpx.TransportError, httpx.NetworkError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning(
                    "persist_narrative: transport error — attempt %d/%d: %s",
                    attempt + 1,
                    _FAST_FAIL_MAX_5XX_RETRIES + 1,
                    exc,
                )

        # All retries exhausted
        logger.error("persist_narrative: all %d attempts failed", _FAST_FAIL_MAX_5XX_RETRIES + 1)
        raise last_exc  # type: ignore[misc]

    def _make_headers(self, extra: dict | None = None) -> dict:
        """Build base headers dict. Caller injects X-Agent-Scope separately."""
        headers = {"Content-Type": "application/json"}
        if extra:
            headers.update(extra)
        return headers

    # ── Private helpers ───────────────────────────────────────────────────

    def _build_payload(self, request: PersistNarrativeRequest) -> dict:
        """Serialise PersistNarrativeRequest to a JSON-serialisable dict."""
        return json.loads(request.model_dump_json())


# ──────────────────────────────────────────────────────────────────────────────
# Phase 60.1 (G2) — Tool subclass wrapper for agent.get_tool discoverability.
# The standalone PersistNarrativeTool class above is used directly by the
# MentorPipelineOrchestrator (60-06). This wrapper enables Agent Zero's
# agent.get_tool('persist_narrative') discovery path, which filters for
# Tool subclasses only (agent.py:1033 / extract_tools.load_classes_from_file).
#
# Filename invariant (LOCKED): agent.get_tool('persist_narrative') resolves to
# this file (persist_narrative.py) via load_classes_from_file. The canonical
# Tool subclass MUST remain in this file — do NOT move it to persist_narrative_tool.py.
# ──────────────────────────────────────────────────────────────────────────────

from helpers.tool import Tool, Response  # noqa: E402  (intentional bottom-of-file)


class PersistNarrative(Tool):
    """Agent Zero Tool wrapper around PersistNarrativeTool.

    Routes call_subordinate('writer') tool invocations through to the
    standalone PersistNarrativeTool's .persist() method. Preserves:
        - FAST_FAIL retry profile (delegated)
        - VM100_INTERNAL_BASE_URL fail-fast at __init__ (delegated)
        - Pydantic request/response contracts (delegated)
        - X-Agent-Scope header propagation (delegated; orchestrator/middleware injects)

    Hard scope enforcement (tool_scope.py SENSITIVE_TOOLS check) fires BEFORE
    this class is constructed when agent.get_tool() resolves it — see
    60-05 + 60-09b for the denial-stub pattern.
    """

    name = "persist_narrative"

    async def execute(self, **kwargs) -> Response:
        """Delegate to the standalone PersistNarrativeTool.

        kwargs expected from the LLM's structured tool call:
            All fields of PersistNarrativeRequest (envelope, scope_context,
            ruleset_version, analysis_version, template_version, etc.)
            headers: optional dict — scope headers injected by orchestrator or
                     tool_execute_before extension (60-19 G23)
        """
        # Instantiate the standalone tool (reads VM100_INTERNAL_BASE_URL once).
        # This is cheap; no LLM cost, no network call.
        inner = PersistNarrativeTool()

        # Extract headers before passing remaining kwargs to PersistNarrativeRequest.
        headers = kwargs.pop("headers", None) or self.agent.get_data("_outbound_headers") or None

        if not kwargs:
            return Response(
                message="persist_narrative: missing required args for PersistNarrativeRequest",
                break_loop=False,
            )

        try:
            # Build PersistNarrativeRequest from all remaining kwargs.
            # The LLM call includes all required fields (envelope, scope_context,
            # ruleset_version, analysis_version, template_version, scope_origin,
            # truth_mode, source_snapshot_id, source_replay_artifact_id,
            # generated_by, generated_reason, writer_profile_id, etc.)
            request = PersistNarrativeRequest.model_validate(kwargs)
            response = await inner.persist(request, headers=headers)
        except Exception as exc:
            return Response(
                message=f"persist_narrative failed: {exc}",
                break_loop=False,
            )

        # Return a JSON-serializable message so the LLM can inspect it.
        return Response(
            message=response.model_dump_json(),
            break_loop=False,
            additional={
                "narrative_id": str(response.narrative_id),
                "narrative_version": response.narrative_version,
                "unsourced_claim_count": response.unsourced_claim_count,
            },
        )
