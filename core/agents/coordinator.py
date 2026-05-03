"""Phase 44 Coordinator entry point.

handle_coordinator_input is the Python-callable Coordinator path:
pre-classify → delegate to Idea → delegate to Strategy → return result.

NO Coordinator-level retry. Subordinate failure propagates up (CONTEXT § Failure Handling).

See CONTEXT § Coordinator Role + Behavior for the full design.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional, Tuple

from core.contracts.schemas import StrategySpec
from core.agents.invocation import is_substantive, run_idea, run_strategy

log = logging.getLogger(__name__)

TRIVIAL_RESPONSE = (
    "Hi — I'm the FinGPT Coordinator. I route substantive trading-strategy work "
    "to specialist agents. Try a request like 'design a strategy for...' or 'I have a hypothesis that...'."
)


def handle_coordinator_input(
    input_text: str,
    *,
    db=None,
    task_id: Optional[str] = None,
) -> Tuple[Optional[StrategySpec], dict]:
    """Phase 44 Coordinator path.

    Pre-classify input → if substantive, delegate to Idea Agent then Strategy Agent.
    Returns (StrategySpec, meta) on substantive input that completes the full pipeline.
    Returns (None, {"trivial": True, "message": str}) on non-substantive input.

    NO Coordinator-level retry. Subordinate failures (IdeaAgentDegradedError,
    StrategyAgentDegradedError, InvalidInputError) propagate up immediately.
    The calling layer (scheduler or HTTP handler) decides retry/abandon policy
    (CONTEXT.md § Failure Handling — fail-fast, Coordinator does NOT retry).

    Args:
        input_text: User input text to classify and route.
        db: MongoDB database handle. If None, envelope persistence is skipped.
        task_id: Optional task identifier. Auto-generated if not provided.

    Returns:
        (StrategySpec, meta) tuple on substantive input.
        (None, {"trivial": True, "message": str, "task_id": str}) on trivial input.

    Raises:
        IdeaAgentDegradedError: Idea Agent degraded twice (NOT caught here).
        StrategyAgentDegradedError: Strategy Agent degraded twice (NOT caught here).
        InvalidInputError: Strategy Agent received non-Hypothesis input (programmer error).
    """
    task_id = task_id or f"coord-{uuid.uuid4().hex}"

    if not is_substantive(input_text):
        log.info(
            "coordinator: non-substantive input — direct response (task_id=%s)", task_id
        )
        return None, {"trivial": True, "message": TRIVIAL_RESPONSE, "task_id": task_id}

    log.info(
        "coordinator: substantive input — delegating to Idea Agent (task_id=%s)", task_id
    )

    # Sequential delegation. NO try/except around the inner calls — fail-fast policy:
    # the scheduler / HTTP caller decides retry. Coordinator-level retry is explicitly
    # forbidden per CONTEXT.md § Failure Handling.
    hypothesis = run_idea(input_text, db=db, task_id=task_id)
    strategy_spec = run_strategy(hypothesis, db=db, task_id=task_id)

    meta = {
        "task_id": task_id,
        "agent_path": ["agent_zero", "idea_agent", "strategy_agent"],
        # source_envelope_id populated by run_idea when db is provided;
        # passes through to strategy envelope via hypothesis.source_envelope_id.
        "idea_envelope_id": hypothesis.source_envelope_id,
        "strategy_envelope_id": None,  # Strategy envelope_id not surfaced here;
        # callers needing it should query agent_envelopes by task_id.
    }
    return strategy_spec, meta
