"""POST /api/v1/agents/pipeline/mentor — synchronous mentor pipeline runner.

BUG-10 fix: gives Dagster a clean HTTP boundary to invoke MentorPipelineOrchestrator
instead of importing VM107 helpers in-process. The orchestrator + Agent Zero
subordinate runtime live HERE (VM107); Dagster just POSTs the request and waits.

Request shape:
    {
        "profile": "trade_auditor_agent" | "behavioral_mentor_agent" | "weekly_review_agent",
        "execution_id": "<uuid>",            # required for per-trade profiles; null for weekly
        "account_id": "<str>",                # routing only
        "source_snapshot_id": "<uuid>",
        "ruleset_version": "v1.0",
        "analysis_version": 1,
        "template_version": "1.0.0",
        "replay_artifact_id": "<uuid>" | null,
        "regime_snapshot_age_hours": <float|null>,
        "scope_origin": "<str>"               # forwarded into ScopeContext
    }

Response:
    200 + {"status": "success", "execution_id": "...", "profile": "...",
           "unsourced_claim_count": N}
    4xx — invalid input
    5xx — pipeline raised (orchestrator error path)

Sync execution is acceptable for V1 because per-trade audit completes within
a couple of minutes. Dagster's HTTP client sets a long timeout; if mentor
pipelines grow longer we'd revisit with a 202 + task_id + poll pattern
matching refine.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from flask import Response

from helpers.api import ApiHandler, Input, Output, Request

log = logging.getLogger("vm107.api.v1.agents.pipeline.mentor")

_ALLOWED_PROFILES = {
    "trade_auditor_agent",
    "behavioral_mentor_agent",
    "weekly_review_agent",
}


def _json_response(body: dict[str, Any], status: int) -> Response:
    return Response(
        response=json.dumps(body),
        status=status,
        mimetype="application/json",
    )


def _maybe_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


class PipelineMentor(ApiHandler):
    """Synchronous mentor pipeline runner."""

    @classmethod
    def requires_api_key(cls) -> bool:
        # Internal service-to-service endpoint (Dagster → VM107). Matches the
        # Phase 39 lock used by VM100's /api/journal/internal/* routes:
        # auth is via the X-Agent-Scope HMAC header (verified inside the
        # orchestrator's scope_dispatcher.attach_header), not via X-API-KEY.
        return False

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: Input, request: Request) -> Output:
        if not isinstance(input, dict):
            return _json_response(
                {"error": "InvalidBody", "detail": "Request body must be a JSON object."},
                422,
            )

        profile = input.get("profile")
        if profile not in _ALLOWED_PROFILES:
            return _json_response(
                {
                    "error": "InvalidProfile",
                    "detail": f"profile must be one of {sorted(_ALLOWED_PROFILES)}; got {profile!r}",
                },
                422,
            )

        source_snapshot_id = _maybe_uuid(input.get("source_snapshot_id"))
        if source_snapshot_id is None:
            return _json_response(
                {"error": "InvalidBody", "detail": "source_snapshot_id must be a UUID string"},
                422,
            )

        execution_id = _maybe_uuid(input.get("execution_id"))
        if profile != "weekly_review_agent" and execution_id is None:
            return _json_response(
                {
                    "error": "InvalidBody",
                    "detail": "execution_id is required for per-trade profiles",
                },
                422,
            )

        ruleset_version = str(input.get("ruleset_version") or "v1.0")
        analysis_version = int(input.get("analysis_version") or 1)
        template_version = str(input.get("template_version") or "1.0.0")
        replay_artifact_id = _maybe_uuid(input.get("replay_artifact_id"))
        regime_age = input.get("regime_snapshot_age_hours")
        regime_snapshot_age_hours = float(regime_age) if regime_age is not None else 999.0
        account_id = str(input.get("account_id") or "")
        scope_origin = str(input.get("scope_origin") or "")

        log.info(
            "mentor_pipeline.request profile=%s execution_id=%s account_id=%s",
            profile,
            execution_id,
            account_id,
        )

        try:
            orchestrator, scope_context = _build_orchestrator_and_scope(
                profile=profile,
                account_id=account_id,
                execution_id=execution_id,
                scope_origin=scope_origin,
            )
        except Exception as exc:
            log.exception("mentor_pipeline.builder_failed: %s", exc)
            return _json_response(
                {"error": "BuilderError", "detail": str(exc)[:500]},
                500,
            )

        try:
            envelope = await orchestrator.run(
                execution_id=execution_id,
                scope_context=scope_context,
                replay_artifact_id=replay_artifact_id,
                ruleset_version=ruleset_version,
                analysis_version=analysis_version,
                template_version=template_version,
                source_snapshot_id=source_snapshot_id,
                truth_mode=_truth_mode_historical(),
                replay_metadata={},
                regime_snapshot_age_hours=regime_snapshot_age_hours,
            )
        except Exception as exc:
            log.exception(
                "mentor_pipeline.run_failed profile=%s execution_id=%s: %s",
                profile,
                execution_id,
                exc,
            )
            return _json_response(
                {
                    "error": type(exc).__name__,
                    "detail": str(exc)[:1000],
                    "profile": profile,
                    "execution_id": str(execution_id) if execution_id else None,
                },
                500,
            )

        return _json_response(
            {
                "status": "success",
                "profile": profile,
                "execution_id": str(execution_id) if execution_id else None,
                "unsourced_claim_count": getattr(envelope, "unsourced_claim_count", 0),
            },
            200,
        )


def _truth_mode_historical():
    from fingpt_core.contracts.narrative.scope import TruthMode
    return TruthMode.HISTORICAL


def _build_orchestrator_and_scope(
    *,
    profile: str,
    account_id: str,
    execution_id: UUID | None,
    scope_origin: str,
):
    """Construct a MentorPipelineOrchestrator + matching ScopeContext.

    Mirrors the structure of the existing Dagster-side builder, but everything
    runs in-process here (VM107 has all helpers locally). The orchestrator
    invokes Agent Zero subordinates that share this process's runtime.
    """
    from datetime import datetime, timedelta, timezone

    from fingpt_core.contracts.narrative.scope import (
        NarrativeVisibility,
        ScopeContext,
        TruthMode,
    )
    from helpers.citation_validator import CitationValidator
    from helpers.confidence_vector_calculator import ConfidenceVectorCalculator
    from helpers.mentor_pipeline_orchestrator import MentorPipelineOrchestrator
    from helpers.mentor_subordinate_invoker import invoke_mentor_subordinate
    from helpers.scope_dispatcher import ScopeDispatcher
    from tools.persist_narrative import PersistNarrativeTool

    registry_path = Path(os.environ.get("VM107_REGISTRY_PATH", "/a0/registry"))
    citation_validator = CitationValidator(registry_path)
    confidence_calculator = ConfidenceVectorCalculator()
    scope_dispatcher = ScopeDispatcher()
    narrative_persister = PersistNarrativeTool()

    now = datetime.now(timezone.utc)
    scope_context = ScopeContext(
        profile_id=profile,
        account_id=account_id or None,
        execution_id=execution_id,
        truth_mode=TruthMode.HISTORICAL,
        narrative_visibility=NarrativeVisibility.NONE,
        issued_at=now,
        expires_at=now + timedelta(hours=2),
    )

    class _LoggingEventEmitter:
        """Lightweight emitter that logs locally. The pipeline persists the
        narrative directly via VM100 HTTP; we don't need a Phase 56 client here
        since refine-style endpoints already drive their own event chain."""

        def __init__(self) -> None:
            self._correlation_id = str(uuid4())

        def emit(self, event_type, **kwargs):
            log.info("[mentor_event] %s %s", event_type, kwargs)

        def new_correlation_id(self):
            self._correlation_id = str(uuid4())
            return self._correlation_id

    orchestrator = MentorPipelineOrchestrator(
        profile=profile,
        scope_dispatcher=scope_dispatcher,
        citation_validator=citation_validator,
        confidence_calculator=confidence_calculator,
        event_emitter=_LoggingEventEmitter(),
        subordinate_invoker=invoke_mentor_subordinate,
        narrative_persister_client=narrative_persister,
    )
    return orchestrator, scope_context
