"""Phase 48 typed emit helpers for refinement lifecycle events.

REGISTER_CAPABILITY: type=service, id=refinement_events_emitter_vm107, path=VM107/core/events/refinement_events.py

CONTEXT § Decision 18: the refinement_orchestrator is the SOLE EMITTER of
the 10 Phase 48 lifecycle event types. This module ships the 10 typed
wrappers around ``core.events.phase56_client.emit_event``. Each helper:

  1. Validates its kwargs against a typed Pydantic payload model.
  2. Calls ``emit_event`` with the hardcoded event_type + category +
     correlation_id=loop_id + causality_scope="IDEA" (planner V1 lock).

Categories (CONTEXT § Decision 18 + Plan 07 frontmatter):
  - "cognition" for: refinement_loop_started, iteration_started,
    critic_verdict_received, hard_veto_triggered, identity_drift_detected,
    convergence_stall_detected, budget_exceeded.
  - "lifecycle" for terminal events: strategy_accepted, strategy_rejected,
    loop_terminated.

This module is imported EXCLUSIVELY by modules under
``core/agents/refinement_orchestrator/``. The
``test_orchestrator_sole_emitter.py`` AST guard enforces this invariant —
no agent profile (``agents/strategy_refinement_critic/...`` etc.) may
import these helpers.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Imported here so monkeypatch.setattr("core.events.refinement_events.emit_event", ...)
# works in tests without touching phase56_client itself.
from core.events.phase56_client import emit_event


# ---------------------------------------------------------------------------
# Per-event Pydantic payload models. extra="forbid" — any unexpected kwarg
# is a contract violation that surfaces immediately at the helper call site.
# ---------------------------------------------------------------------------


class _PayloadBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RefinementLoopStartedPayload(_PayloadBase):
    loop_id: str
    task_id: str
    root_hypothesis_id: str
    strategy_family: str
    registry_snapshot_hash: str


class IterationStartedPayload(_PayloadBase):
    loop_id: str
    iteration_number: int = Field(..., ge=0)
    root_hypothesis_id: str
    registry_snapshot_hash: str


class CriticVerdictReceivedPayload(_PayloadBase):
    loop_id: str
    iteration_number: int = Field(..., ge=0)
    critic_verdict_id: str
    verdict: Literal["ACCEPT", "REFINE", "REJECT"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    refinement_targets_count: int = Field(..., ge=0)


class HardVetoTriggeredPayload(_PayloadBase):
    loop_id: str
    iteration_number: int = Field(..., ge=0)
    vetoes_triggered: list[dict[str, Any]]


class IdentityDriftDetectedPayload(_PayloadBase):
    loop_id: str
    iteration_number: int = Field(..., ge=0)
    identity_score: float = Field(..., ge=0.0, le=1.0)
    threshold: float = Field(..., ge=0.0, le=1.0)
    identity_diff_breakdown: dict[str, Any]


class ConvergenceStallDetectedPayload(_PayloadBase):
    loop_id: str
    iteration_number: int = Field(..., ge=0)
    repeated_targets: list[dict[str, Any]]


class BudgetExceededPayload(_PayloadBase):
    loop_id: str
    iteration_number: int = Field(..., ge=0)
    scope: Literal["ITERATION", "LOOP"]
    consumed_usd: float = Field(..., ge=0.0)
    cap_usd: float = Field(..., ge=0.0)


class StrategyAcceptedPayload(_PayloadBase):
    loop_id: str
    accepted_strategy_id: str
    root_hypothesis_id: str
    final_iteration: int = Field(..., ge=0)
    registry_yaml_path: str


class StrategyRejectedPayload(_PayloadBase):
    loop_id: str
    rejected_strategy_id: str
    root_hypothesis_id: str
    termination_reason: str
    final_iteration: int = Field(..., ge=0)


class LoopTerminatedPayload(_PayloadBase):
    loop_id: str
    termination_reason: str
    final_iteration: int = Field(..., ge=0)
    total_cost_usd: float = Field(..., ge=0.0)


# ---------------------------------------------------------------------------
# 10 typed emit helpers. Each: validates payload, then calls emit_event with
# the hardcoded event_type + correlation_id=loop_id + causality_scope='IDEA'.
# ---------------------------------------------------------------------------


def emit_refinement_loop_started(
    *,
    loop_id: str,
    task_id: str,
    root_hypothesis_id: str,
    strategy_family: str,
    registry_snapshot_hash: str,
) -> None:
    """Emit ``refinement_loop_started`` at the very start of a refinement loop."""
    payload = RefinementLoopStartedPayload(
        loop_id=loop_id,
        task_id=task_id,
        root_hypothesis_id=root_hypothesis_id,
        strategy_family=strategy_family,
        registry_snapshot_hash=registry_snapshot_hash,
    ).model_dump()
    emit_event(
        event_type="refinement_loop_started",
        category="cognition",
        correlation_id=loop_id,
        payload=payload,
        causality_scope="IDEA",
    )


def emit_iteration_started(
    *,
    loop_id: str,
    iteration_number: int,
    root_hypothesis_id: str,
    registry_snapshot_hash: str,
) -> None:
    """Emit ``iteration_started`` at the start of each refinement iteration."""
    payload = IterationStartedPayload(
        loop_id=loop_id,
        iteration_number=iteration_number,
        root_hypothesis_id=root_hypothesis_id,
        registry_snapshot_hash=registry_snapshot_hash,
    ).model_dump()
    emit_event(
        event_type="iteration_started",
        category="cognition",
        correlation_id=loop_id,
        payload=payload,
        causality_scope="IDEA",
    )


def emit_critic_verdict_received(
    *,
    loop_id: str,
    iteration_number: int,
    critic_verdict_id: str,
    verdict: str,
    confidence: float,
    refinement_targets_count: int,
) -> None:
    """Emit ``critic_verdict_received`` after a CriticVerdict is parsed."""
    payload = CriticVerdictReceivedPayload(
        loop_id=loop_id,
        iteration_number=iteration_number,
        critic_verdict_id=critic_verdict_id,
        verdict=verdict,  # type: ignore[arg-type]
        confidence=confidence,
        refinement_targets_count=refinement_targets_count,
    ).model_dump()
    emit_event(
        event_type="critic_verdict_received",
        category="cognition",
        correlation_id=loop_id,
        payload=payload,
        causality_scope="IDEA",
    )


def emit_hard_veto_triggered(
    *,
    loop_id: str,
    iteration_number: int,
    vetoes_triggered: list[dict[str, Any]],
) -> None:
    """Emit ``hard_veto_triggered`` when one or more deterministic vetoes fire."""
    payload = HardVetoTriggeredPayload(
        loop_id=loop_id,
        iteration_number=iteration_number,
        vetoes_triggered=vetoes_triggered,
    ).model_dump()
    emit_event(
        event_type="hard_veto_triggered",
        category="cognition",
        correlation_id=loop_id,
        payload=payload,
        causality_scope="IDEA",
    )


def emit_identity_drift_detected(
    *,
    loop_id: str,
    iteration_number: int,
    identity_score: float,
    threshold: float,
    identity_diff_breakdown: dict[str, Any],
) -> None:
    """Emit ``identity_drift_detected`` when AST identity score falls below threshold."""
    payload = IdentityDriftDetectedPayload(
        loop_id=loop_id,
        iteration_number=iteration_number,
        identity_score=identity_score,
        threshold=threshold,
        identity_diff_breakdown=identity_diff_breakdown,
    ).model_dump()
    emit_event(
        event_type="identity_drift_detected",
        category="cognition",
        correlation_id=loop_id,
        payload=payload,
        causality_scope="IDEA",
    )


def emit_convergence_stall_detected(
    *,
    loop_id: str,
    iteration_number: int,
    repeated_targets: list[dict[str, Any]],
) -> None:
    """Emit ``convergence_stall_detected`` when refinement targets repeat across iterations."""
    payload = ConvergenceStallDetectedPayload(
        loop_id=loop_id,
        iteration_number=iteration_number,
        repeated_targets=repeated_targets,
    ).model_dump()
    emit_event(
        event_type="convergence_stall_detected",
        category="cognition",
        correlation_id=loop_id,
        payload=payload,
        causality_scope="IDEA",
    )


def emit_budget_exceeded(
    *,
    loop_id: str,
    iteration_number: int,
    scope: str,
    consumed_usd: float,
    cap_usd: float,
) -> None:
    """Emit ``budget_exceeded`` when iteration or loop USD cap exhausts.

    Emitted BY THE ORCHESTRATOR, never by the Critic (Critic is budget-blind
    per CONTEXT § Anti-Patterns).
    """
    payload = BudgetExceededPayload(
        loop_id=loop_id,
        iteration_number=iteration_number,
        scope=scope,  # type: ignore[arg-type]
        consumed_usd=consumed_usd,
        cap_usd=cap_usd,
    ).model_dump()
    emit_event(
        event_type="budget_exceeded",
        category="cognition",
        correlation_id=loop_id,
        payload=payload,
        causality_scope="IDEA",
    )


def emit_strategy_accepted(
    *,
    loop_id: str,
    accepted_strategy_id: str,
    root_hypothesis_id: str,
    final_iteration: int,
    registry_yaml_path: str,
) -> None:
    """Emit ``strategy_accepted`` (terminal) when StrategySpec is promoted."""
    payload = StrategyAcceptedPayload(
        loop_id=loop_id,
        accepted_strategy_id=accepted_strategy_id,
        root_hypothesis_id=root_hypothesis_id,
        final_iteration=final_iteration,
        registry_yaml_path=registry_yaml_path,
    ).model_dump()
    emit_event(
        event_type="strategy_accepted",
        category="lifecycle",
        correlation_id=loop_id,
        payload=payload,
        causality_scope="IDEA",
    )


def emit_strategy_rejected(
    *,
    loop_id: str,
    rejected_strategy_id: str,
    root_hypothesis_id: str,
    termination_reason: str,
    final_iteration: int,
) -> None:
    """Emit ``strategy_rejected`` (terminal) when StrategySpec is archived."""
    payload = StrategyRejectedPayload(
        loop_id=loop_id,
        rejected_strategy_id=rejected_strategy_id,
        root_hypothesis_id=root_hypothesis_id,
        termination_reason=termination_reason,
        final_iteration=final_iteration,
    ).model_dump()
    emit_event(
        event_type="strategy_rejected",
        category="lifecycle",
        correlation_id=loop_id,
        payload=payload,
        causality_scope="IDEA",
    )


def emit_loop_terminated(
    *,
    loop_id: str,
    termination_reason: str,
    final_iteration: int,
    total_cost_usd: float,
) -> None:
    """Emit ``loop_terminated`` (terminal) at the very end of every refinement loop."""
    payload = LoopTerminatedPayload(
        loop_id=loop_id,
        termination_reason=termination_reason,
        final_iteration=final_iteration,
        total_cost_usd=total_cost_usd,
    ).model_dump()
    emit_event(
        event_type="loop_terminated",
        category="lifecycle",
        correlation_id=loop_id,
        payload=payload,
        causality_scope="IDEA",
    )


__all__ = [
    # Helpers
    "emit_refinement_loop_started",
    "emit_iteration_started",
    "emit_critic_verdict_received",
    "emit_hard_veto_triggered",
    "emit_identity_drift_detected",
    "emit_convergence_stall_detected",
    "emit_budget_exceeded",
    "emit_strategy_accepted",
    "emit_strategy_rejected",
    "emit_loop_terminated",
    # Payload models (re-exported so callers can type-hint or test against them)
    "RefinementLoopStartedPayload",
    "IterationStartedPayload",
    "CriticVerdictReceivedPayload",
    "HardVetoTriggeredPayload",
    "IdentityDriftDetectedPayload",
    "ConvergenceStallDetectedPayload",
    "BudgetExceededPayload",
    "StrategyAcceptedPayload",
    "StrategyRejectedPayload",
    "LoopTerminatedPayload",
]
