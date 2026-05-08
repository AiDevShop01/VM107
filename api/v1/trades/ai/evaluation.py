"""TradeAiEvaluation — Mode B formal evaluation ApiHandler.

POST /api/v1/trades/<journal_id>/ai/evaluation

Calls run_pre_trade_evaluation. On EvaluationContractViolation → 502.
On missing required fields → 422. On success → 200 with evaluation payload.

Mode A (chat.py) and Mode B (this file) MUST NOT share prompts or output paths.
Mode A uses chat_evaluator.md + stateless litellm.acompletion (free text).
Mode B uses pre_trade_evaluation.md + structured-output runner → PreTradeEvaluation.
"""
from __future__ import annotations

import json
import logging
import uuid

from flask import Response, request

from helpers.api import ApiHandler, Input, Output
from helpers.mongo import get_mongo_db
from core.agents.evaluation_runner import run_pre_trade_evaluation
from core.agents.invocation_exceptions import EvaluationContractViolation

log = logging.getLogger(__name__)


class TradeAiEvaluation(ApiHandler):
    """Mode B formal pre-trade evaluation endpoint.

    Registered via webapp.add_url_rule() in helpers/ui_server.py.
    journal_id is read from request.view_args (Flask parametric URL).
    X-API-KEY authentication required.

    On success → 200 with {evaluation, envelope_id, evaluation_id}.
    On EvaluationContractViolation → 502 with {error, detail, envelope_id}.
    On missing required fields → 422.
    """

    @classmethod
    def requires_api_key(cls) -> bool:
        return True

    @classmethod
    def requires_auth(cls) -> bool:
        return False

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: Input, request) -> Output:  # type: ignore[override]
        # Extract journal_id from parametric URL segment.
        journal_id = (getattr(request, "view_args", None) or {}).get("journal_id", "").strip()
        if not journal_id:
            return Response(
                json.dumps({"error": "Missing journal_id in URL"}),
                422,
                mimetype="application/json",
            )

        # Validate required fields — conversation_id is required.
        conversation_id = (input.get("conversation_id") or "").strip()
        if not conversation_id:
            return Response(
                json.dumps({"error": "conversation_id required"}),
                422,
                mimetype="application/json",
            )

        user_id = (input.get("user_id") or "").strip()
        if not user_id:
            return Response(
                json.dumps({"error": "user_id required"}),
                422,
                mimetype="application/json",
            )

        # strategy_id is nullable per CONTEXT § Endpoint Contracts.
        strategy_id = input.get("strategy_id") or None
        context_block: dict = input.get("context") or {}

        db = get_mongo_db()
        task_id = f"eval-{uuid.uuid4().hex}"

        try:
            # Phase 47.3: runner now returns PreTradeEvaluation directly.
            # context_block is no longer passed in — the runner builds its
            # own EvaluationContext from Tier-1 (VM100 internal) + Tier-2
            # (VM102) + Tier-3 stubs. envelope_id is read off the success
            # envelope persisted inside the runner via the source_envelope_id
            # round-trip; for the API response we surface the same value
            # via the runner's input_payload tracing.
            evaluation = await run_pre_trade_evaluation(
                journal_id=journal_id,
                conversation_id=conversation_id,
                strategy_id=strategy_id,
                user_id=user_id,
                db=db,
                task_id=task_id,
            )
            envelope_id = evaluation.source_envelope_id or ""
        except EvaluationContractViolation as exc:
            # Failure envelope already persisted inside runner; envelope_id stashed on exception.
            log.warning(
                "EvaluationContractViolation journal_id=%s envelope_id=%s",
                journal_id,
                getattr(exc, "envelope_id", None),
            )
            return Response(
                json.dumps({
                    "error": "EvaluationContractViolation",
                    "detail": str(exc),
                    "envelope_id": getattr(exc, "envelope_id", None),
                }),
                502,
                mimetype="application/json",
            )
        except Exception as exc:
            log.warning(
                "evaluation hard failure journal_id=%s: %s", journal_id, exc
            )
            return Response(
                json.dumps({"error": "AI service error", "detail": str(exc)}),
                502,
                mimetype="application/json",
            )

        evaluation_id = str(evaluation.evaluation_id)
        return Response(
            json.dumps({
                "evaluation": evaluation.model_dump(mode="json"),
                "envelope_id": envelope_id,
                "evaluation_id": evaluation_id,
            }),
            200,
            mimetype="application/json",
        )
