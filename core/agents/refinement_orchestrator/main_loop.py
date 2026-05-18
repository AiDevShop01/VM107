"""Phase 48 Plan 08b — main refinement orchestrator loop.

REGISTER_CAPABILITY: type=service, id=refinement_orchestrator, path=VM107/registry/service/refinement_orchestrator.yaml

CONTEXT § Decision 2 + § Decision 5 + § Decision 6 + § Decision 10 + § Decisions 4/7/9/14/18.

Compose every prior Phase 48 wave into a single deterministic refinement
orchestrator entry. Reads ``hypothesis_id`` from Mongo, runs iteration 0
(Strategy → Code → Build → Backtest), anchors identity at the iter-0
StrategySpec, and runs up to ``MAX_ITERATIONS`` refinement passes until a
terminal state is reached.

The 14 TerminationReason values are the only legal terminal outcomes:
    ACCEPTED, CRITIC_REJECT, HARD_VETO, IDENTITY_DRIFT, CONVERGENCE_STALL,
    BUDGET_EXCEEDED_ITERATION, BUDGET_EXCEEDED_LOOP, MAX_ITERATIONS,
    BUILD_FAILURE, CRITIC_DEGRADED, STRATEGY_DEGRADED, CODE_DEGRADED,
    BUILD_FAILED, BACKTEST_DEGRADED

Architecture invariants this module preserves:
  * Critic-budget-blind (Plan 05) — never threads budget state into run_critic.
  * Sole-emitter (Plan 07) — lives under refinement_orchestrator/ so
    permitted to import core.events.refinement_events.
  * Pattern 51 (Plan 03 + 07) — every emit is paired with persist_atomically.
  * Snapshot frozen at loop start (Plan 03 + § Decision 15) — registry is
    NEVER re-read mid-loop.
  * Identity anchored to iter 0 (§ Decision 10) — compute_score(spec_new,
    spec_iter0) NEVER (spec_new, spec_prev_iter).

Pure assembly — every gate, governor, and emitter is imported and called.
No re-implementation of acceptance, vetoes, identity, convergence, or budget
logic lives here.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Optional

from core.agents.family_skill_map import select_skill
from core.agents.invocation import (
    BacktesterDegradedError,
    CodeAgentDegradedError,
    CriticDegradedError,
    StrategyAgentDegradedError,
    run_backtest,
    run_build,
    run_code,
    run_critic,
    run_strategy,
)
from core.agents.refinement_orchestrator.acceptance_floor import classify_acceptance
from core.agents.refinement_orchestrator.acceptance_path import (
    accept_strategy,
    assert_hypothesis_exists,
)
from core.agents.refinement_orchestrator.budget_governor import BudgetGovernor
from core.agents.refinement_orchestrator.checkpoint import (
    is_terminal,
    load_state,
    resume_or_initialize,
)
from core.agents.refinement_orchestrator.convergence_detector import (
    detect_convergence_stall,
)
from core.agents.refinement_orchestrator.hard_vetoes import check_hard_vetoes
from core.agents.refinement_orchestrator.identity_scorer import (
    compute_score,
    should_terminate_for_drift,
)
from core.agents.refinement_orchestrator.policy_constants import (
    BUDGET_CAPS_USD,
    IDENTITY_THRESHOLDS,
    MAX_ITERATIONS,
)
from core.agents.refinement_orchestrator.refinement_routing import (
    route_refinement,
    validate_scope_combinations,
)
from core.agents.refinement_orchestrator.rejection_path import reject_strategy
from core.agents.refinement_orchestrator.snapshot_freeze import freeze_snapshot_hash
from core.agents.refinement_orchestrator.state import (
    append_iteration_artifact,
    finalize_state,
    update_loop_state,
)
from core.contracts.exceptions import OrphanStrategyError
from core.contracts.schemas import (
    AcceptanceClassification,
    CodeModule,
    CriticVerdict,
    ExecutionCost,
    Hypothesis,
    RefinementContextEnvelope,
    RefinementLoopState,
    RefinementOutcome,
    RefinementTarget,
    StrategySpec,
    TerminationReason,
)
from core.events.refinement_events import (
    emit_budget_exceeded,
    emit_convergence_stall_detected,
    emit_critic_verdict_received,
    emit_hard_veto_triggered,
    emit_identity_drift_detected,
    emit_iteration_started,
    emit_loop_terminated,
    emit_refinement_loop_started,
)

log = logging.getLogger("vm107.refinement_orchestrator.main_loop")

# Mongo collection names used by main_loop. Aligned with Plan 48-02 migrations.
_HYPOTHESES = "hypotheses"
_STRATEGY_SPECS = "strategy_specs"
_CODE_MODULES = "code_modules"
_BUILD_REPORTS = "build_reports"
_BACKTEST_RESULTS = "backtest_results"
_CRITIC_VERDICTS = "critic_verdicts"


# ---------------------------------------------------------------------------
# Internal exception used to short-circuit the iteration when a deterministic
# gate fires (no Python-flow stack-unwinding through every step otherwise).
# ---------------------------------------------------------------------------


class _LoopTermination(Exception):
    """Internal sentinel: a gate decided the loop must stop now.

    Carries the TerminationReason + any per-reason context the rejection
    path needs (identity_diff_breakdown / repeated_targets / verdict).
    """

    def __init__(
        self,
        *,
        reason: TerminationReason,
        verdict: Optional[CriticVerdict] = None,
        identity_diff_breakdown: Optional[list[dict[str, Any]]] = None,
        repeated_targets: Optional[list[RefinementTarget]] = None,
        threshold: Optional[float] = None,
        identity_score: Optional[float] = None,
        vetoes: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        self.reason = reason
        self.verdict = verdict
        self.identity_diff_breakdown = identity_diff_breakdown
        self.repeated_targets = repeated_targets
        self.threshold = threshold
        self.identity_score = identity_score
        self.vetoes = vetoes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_db() -> Any:
    """Resolve the Mongo handle.

    Env-driven (CONTEXT § feedback_env_driven_no_fallbacks). Tests inject the
    DB by monkeypatching this helper before invoking ``run_refinement_loop``;
    production resolves via ``helpers.mongo.get_mongo_db``.
    """
    from helpers.mongo import get_mongo_db

    return get_mongo_db()


def _load_hypothesis(db: Any, hypothesis_id: str) -> Hypothesis:
    """Read + validate the immutable Hypothesis. § Decision 6 fail-fast contract.

    Raises:
        OrphanStrategyError: hypothesis_id does not resolve in Mongo (no
            orphan strategies allowed — every refinement traces back to a
            Hypothesis WORM doc).
    """
    doc = db[_HYPOTHESES].find_one({"_id": hypothesis_id})
    if not doc:
        raise OrphanStrategyError(
            f"hypothesis_id={hypothesis_id!r} not found in {_HYPOTHESES!r}. "
            "Phase 48 entry contract: every refinement loop must trace back to "
            "an immutable Hypothesis (CONTEXT § Decision 6)."
        )
    # Strip Mongo-internal keys before Pydantic validation.
    doc = {k: v for k, v in doc.items() if k != "_id"}
    return Hypothesis.model_validate(doc)


def _load_spec_iter0(state: RefinementLoopState, db: Any) -> StrategySpec:
    """Hydrate the iter-0 StrategySpec from Mongo by ``state.spec_iter0_id``.

    Anchored-identity contract (§ Decision 10): main_loop ALWAYS compares
    iteration N's StrategySpec against iteration 0's. Never iter N-1. This
    helper is the only authorized loader of the iter-0 anchor.

    Raises:
        OrphanStrategyError: ``spec_iter0_id`` is None (iter 0 not yet
            persisted) OR the StrategySpec doc is missing from Mongo.
    """
    if not state.spec_iter0_id:
        raise OrphanStrategyError(
            f"spec_iter0_id is None for loop_id={state.loop_id!r}; iteration 0 "
            "has not been persisted yet. Identity gate cannot run without an "
            "anchor (CONTEXT § Decision 10)."
        )
    doc = db[_STRATEGY_SPECS].find_one({"_id": state.spec_iter0_id})
    if not doc:
        raise OrphanStrategyError(
            f"spec_iter0_id={state.spec_iter0_id!r} not found in "
            f"{_STRATEGY_SPECS!r}. Anchored-identity contract violated."
        )
    doc = {k: v for k, v in doc.items() if k != "_id"}
    return StrategySpec.model_validate(doc)


def _persist_artifact(
    db: Any, collection: str, payload: dict[str, Any], artifact_id: str
) -> None:
    """Append-only insert with explicit ``_id``. Used by every iteration's
    Strategy/Code/Build/Backtest/Critic-verdict persistence step.
    """
    doc = dict(payload)
    doc["_id"] = artifact_id
    db[collection].insert_one(doc)


def _total_loop_usd(governor: BudgetGovernor) -> float:
    return float(governor.budget_snapshot.get("loop_total_usd", 0.0))


def _build_outcome(
    *,
    loop_id: str,
    termination_reason: TerminationReason,
    accepted_strategy_id: Optional[str],
    rejected_strategy_id: Optional[str],
    final_iteration: int,
    governor: BudgetGovernor,
) -> RefinementOutcome:
    total_cost = ExecutionCost(
        tokens_in=int(governor.budget_snapshot.get("loop_total_tokens", 0)),
        tokens_out=0,
        usd_cost=_total_loop_usd(governor),
        wall_time_ms=int(governor.budget_snapshot.get("loop_total_wall_ms", 0)),
        category="LLM",
    )
    return RefinementOutcome(
        loop_id=loop_id,
        termination_reason=termination_reason,
        accepted_strategy_id=accepted_strategy_id,
        rejected_strategy_id=rejected_strategy_id,
        final_iteration=final_iteration,
        total_cost=total_cost,
    )


def _emit_loop_terminated_safely(
    *,
    loop_id: str,
    termination_reason: TerminationReason,
    final_iteration: int,
    total_cost_usd: float,
) -> None:
    """Emit loop_terminated; swallow emit failures (the rejection/acceptance
    path has already emitted strategy_accepted/strategy_rejected, so a
    second emit failure should not mask the terminal outcome we already
    returned to the caller).
    """
    try:
        emit_loop_terminated(
            loop_id=loop_id,
            termination_reason=termination_reason.value,
            final_iteration=final_iteration,
            total_cost_usd=total_cost_usd,
        )
    except Exception:  # noqa: BLE001
        log.exception(
            "main_loop: emit_loop_terminated failed for loop_id=%s reason=%s",
            loop_id,
            termination_reason,
        )


def _terminate_with_rejection(
    db: Any,
    *,
    state: RefinementLoopState,
    governor: BudgetGovernor,
    termination_reason: TerminationReason,
    final_iteration: int,
    iteration_artifact_ids: list[dict[str, Any]],
    verdict: Optional[CriticVerdict] = None,
    identity_diff_breakdown: Optional[list[dict[str, Any]]] = None,
    repeated_targets: Optional[list[RefinementTarget]] = None,
) -> RefinementOutcome:
    """Common terminal-rejection path used by every non-ACCEPT termination.

    1. Calls reject_strategy (Plan 08a) — persists rejected_strategies doc
       + emits strategy_rejected.
    2. Emits loop_terminated.
    3. finalize_state(termination_reason).
    4. Returns RefinementOutcome.

    Pattern 51 ordering preserved: rejection_path emits strategy_rejected
    in-line with its insert (Plan 08a); loop_terminated emits AFTER.
    """
    rejected_strategy_id = reject_strategy(
        db,
        state=state,
        termination_reason=termination_reason.value,
        verdict_or_none=verdict,
        final_iteration=final_iteration,
        iteration_artifact_ids=iteration_artifact_ids,
        identity_diff_breakdown=identity_diff_breakdown,
        repeated_targets=repeated_targets,
    )

    _emit_loop_terminated_safely(
        loop_id=state.loop_id,
        termination_reason=termination_reason,
        final_iteration=final_iteration,
        total_cost_usd=_total_loop_usd(governor),
    )

    finalize_state(db, state.loop_id, termination_reason.value)
    update_loop_state(db, state.loop_id, budget_snapshot=governor.budget_snapshot)

    return _build_outcome(
        loop_id=state.loop_id,
        termination_reason=termination_reason,
        accepted_strategy_id=None,
        rejected_strategy_id=rejected_strategy_id,
        final_iteration=final_iteration,
        governor=governor,
    )


def _terminate_with_acceptance(
    db: Any,
    *,
    state: RefinementLoopState,
    governor: BudgetGovernor,
    verdict: CriticVerdict,
    final_iteration: int,
    final_iteration_ids: dict[str, str],
) -> RefinementOutcome:
    """Terminal-acceptance path: § Decision 11 promote-to-operational-cognition.

    1. assert_hypothesis_exists (defensive orphan check at acceptance time).
    2. accept_strategy (Plan 08a) — accepted_strategies WORM + registry YAML
       + strategy_accepted event.
    3. emit_loop_terminated.
    4. finalize_state(ACCEPTED).
    """
    assert_hypothesis_exists(db, hypothesis_id=state.root_hypothesis_id)

    accepted_strategy_id = accept_strategy(
        db,
        state=state,
        verdict=verdict,
        final_iteration_ids=final_iteration_ids,
        final_iteration=final_iteration,
    )

    _emit_loop_terminated_safely(
        loop_id=state.loop_id,
        termination_reason=TerminationReason.ACCEPTED,
        final_iteration=final_iteration,
        total_cost_usd=_total_loop_usd(governor),
    )

    finalize_state(db, state.loop_id, TerminationReason.ACCEPTED.value)
    update_loop_state(db, state.loop_id, budget_snapshot=governor.budget_snapshot)

    return _build_outcome(
        loop_id=state.loop_id,
        termination_reason=TerminationReason.ACCEPTED,
        accepted_strategy_id=accepted_strategy_id,
        rejected_strategy_id=None,
        final_iteration=final_iteration,
        governor=governor,
    )


def _run_iteration_zero(
    db: Any,
    *,
    state: RefinementLoopState,
    hypothesis: Hypothesis,
    governor: BudgetGovernor,
) -> tuple[StrategySpec, CodeModule, Any, Any, dict[str, str]]:
    """Run the iter-0 pipeline (Strategy → Code → Build → Backtest).

    Persists each artifact with an ``_id`` and records the bundle on
    RefinementLoopState.iteration_artifact_ids. Critically writes
    ``state.spec_iter0_id`` to the iter-0 StrategySpec ID — that's the
    identity anchor every subsequent iteration uses.

    Degraded-agent exceptions propagate up so the caller can map them to the
    correct TerminationReason sub-state.
    """
    # Strategy.
    spec_iter0 = run_strategy(hypothesis, db=db, task_id=state.loop_id)
    spec_iter0_id = f"spec_{state.loop_id}_iter0"
    _persist_artifact(db, _STRATEGY_SPECS, spec_iter0.model_dump(), spec_iter0_id)

    # Critical: record the identity anchor (§ Decision 10).
    update_loop_state(db, state.loop_id, spec_iter0_id=spec_iter0_id)
    state.spec_iter0_id = spec_iter0_id

    # Code.
    code_iter0 = run_code(spec_iter0, db=db, task_id=state.loop_id)
    code_iter0_id = f"code_{state.loop_id}_iter0"
    _persist_artifact(db, _CODE_MODULES, code_iter0.model_dump(), code_iter0_id)

    # Build (pure-Python; never degrades).
    build_iter0 = run_build(code_iter0)
    build_iter0_id = f"build_{state.loop_id}_iter0"
    _persist_artifact(db, _BUILD_REPORTS, build_iter0.model_dump(), build_iter0_id)

    # Backtest.
    backtest_iter0 = run_backtest(code_iter0, db=db, task_id=state.loop_id)
    backtest_iter0_id = f"bt_{state.loop_id}_iter0"
    _persist_artifact(
        db, _BACKTEST_RESULTS, backtest_iter0.model_dump(), backtest_iter0_id
    )

    bundle = {
        "iter": 0,
        "strategy_spec_id": spec_iter0_id,
        "code_module_id": code_iter0_id,
        "build_report_id": build_iter0_id,
        "backtest_result_id": backtest_iter0_id,
    }
    append_iteration_artifact(db, state.loop_id, 0, bundle)

    return spec_iter0, code_iter0, build_iter0, backtest_iter0, bundle


def _route_next_iteration(
    *,
    targets: list[RefinementTarget],
    prior_spec: StrategySpec,
    prior_code: CodeModule,
    hypothesis: Hypothesis,
    envelope: RefinementContextEnvelope,
) -> tuple[StrategySpec, CodeModule]:
    """Validate + dispatch refinement targets via Plan 08a routing module."""
    validate_scope_combinations(targets)
    return route_refinement(
        targets=targets,
        prior_spec=prior_spec,
        prior_code=prior_code,
        hypothesis=hypothesis,
        envelope=envelope,
    )


# ---------------------------------------------------------------------------
# Public entry — run_refinement_loop
# ---------------------------------------------------------------------------


def run_refinement_loop(
    hypothesis_id: str,
    *,
    task_id: Optional[str] = None,
) -> RefinementOutcome:
    """Single public Phase 48 entry. § Decision 2 + Decision 6 + Decision 10.

    Composition layout:
      Plan 03: state lifecycle + snapshot freeze + Pattern 51 persistence.
      Plan 04: acceptance_floor (HARD_REJECT / REFINABLE / CRITIC_ELIGIBLE)
               + hard_vetoes (4 catastrophic family-agnostic rules).
      Plan 05: identity_scorer (anchored to iter 0) + convergence_detector
               (3-tuple set equality) + budget_governor (10-key snapshot,
               iteration + loop caps, no-grace preflight).
      Plan 06: strategy_refinement_critic profile + 5 family overlays +
               family_skill_map dispatcher + HYBRID confidence clamp.
      Plan 07: 10 typed emit helpers (sole-emitter invariant; this module
               lives under refinement_orchestrator/ so it is the authorized
               importer).
      Plan 08a: refinement_routing.route_refinement (Strategy-first cascade
                + scope validation) + acceptance_path.accept_strategy
                (12-field WORM + registry YAML + strategy_accepted event)
                + rejection_path.reject_strategy (12-field WORM +
                strategy_rejected event + failure_surface_summary).

    Args:
        hypothesis_id: Mongo _id of the immutable Hypothesis WORM doc.
        task_id: Optional Phase 42 task id (defaults to an api-uuid).

    Returns:
        RefinementOutcome. The terminal RefinementOutcome's termination_reason
        is one of the 14 TerminationReason enum values. accepted_strategy_id
        is populated iff termination_reason == ACCEPTED.

    Raises:
        OrphanStrategyError: hypothesis_id not found in Mongo (no orphan
            strategies allowed).
    """
    db = _get_db()
    _task_id = task_id or f"api-{uuid.uuid4()}"
    loop_id = f"loop_{uuid.uuid4()}"

    # 1) Resolve + validate the Hypothesis WORM root.
    hypothesis = _load_hypothesis(db, hypothesis_id)

    # 2) Initialize / resume RefinementLoopState. resume_or_initialize is
    #    idempotent: a brand-new loop_id gets a fresh state; an existing
    #    loop_id returns the persisted state (resumability).
    state = resume_or_initialize(
        db, loop_id=loop_id, hypothesis_id=hypothesis_id, task_id=_task_id
    )

    # If we resumed onto a terminal state, return immediately — the previous
    # process already finalized and emitted the terminal events.
    if is_terminal(state):
        return _build_outcome(
            loop_id=state.loop_id,
            termination_reason=TerminationReason(state.termination_reason),
            accepted_strategy_id=None,
            rejected_strategy_id=None,
            final_iteration=state.iteration,
            governor=BudgetGovernor(state),
        )

    # 3) Freeze snapshot (idempotent — § Decision 15).
    freeze_snapshot_hash(db, state.loop_id)

    # 4) Budget governor + initial loop_started emit.
    governor = BudgetGovernor(state)
    emit_refinement_loop_started(
        loop_id=state.loop_id,
        task_id=_task_id,
        root_hypothesis_id=state.root_hypothesis_id,
        strategy_family=state.strategy_family,
        registry_snapshot_hash=state.loop_registry_snapshot_hash,
    )

    # 5) Iteration 0 — generate the origin StrategySpec + downstream artifacts.
    iteration_artifact_ids: list[dict[str, Any]] = []
    try:
        spec_curr, code_curr, build_curr, backtest_curr, iter0_bundle = (
            _run_iteration_zero(
                db,
                state=state,
                hypothesis=hypothesis,
                governor=governor,
            )
        )
        iteration_artifact_ids.append(iter0_bundle)
    except StrategyAgentDegradedError as e:
        log.warning("main_loop: STRATEGY_DEGRADED at iter 0 — %s", e)
        return _terminate_with_rejection(
            db,
            state=state,
            governor=governor,
            termination_reason=TerminationReason.STRATEGY_DEGRADED,
            final_iteration=0,
            iteration_artifact_ids=iteration_artifact_ids,
        )
    except CodeAgentDegradedError as e:
        log.warning("main_loop: CODE_DEGRADED at iter 0 — %s", e)
        return _terminate_with_rejection(
            db,
            state=state,
            governor=governor,
            termination_reason=TerminationReason.CODE_DEGRADED,
            final_iteration=0,
            iteration_artifact_ids=iteration_artifact_ids,
        )
    except BacktesterDegradedError as e:
        log.warning("main_loop: BACKTEST_DEGRADED at iter 0 — %s", e)
        return _terminate_with_rejection(
            db,
            state=state,
            governor=governor,
            termination_reason=TerminationReason.BACKTEST_DEGRADED,
            final_iteration=0,
            iteration_artifact_ids=iteration_artifact_ids,
        )

    # Iter-0 cannot trip MAX_ITERATIONS (only iter > MAX_ITERATIONS can). Iter-0
    # CAN still trip vetoes / acceptance / Critic. We start the gate cycle now.
    prev_targets: list[RefinementTarget] = []
    iteration = 0
    final_iteration_ids = dict(iter0_bundle)

    # 6) Refinement loop: gate cascade + Critic + routing.
    while True:
        # Per-iteration emit.
        emit_iteration_started(
            loop_id=state.loop_id,
            iteration_number=iteration,
            root_hypothesis_id=state.root_hypothesis_id,
            registry_snapshot_hash=state.loop_registry_snapshot_hash,
        )

        # Gate 1: hard vetoes (CONTEXT § Decision 9 — absolute authority).
        vetoes = check_hard_vetoes(backtest_curr)
        if vetoes:
            update_loop_state(db, state.loop_id, veto_history=vetoes)
            state.veto_history = list(vetoes)
            try:
                emit_hard_veto_triggered(
                    loop_id=state.loop_id,
                    iteration_number=iteration,
                    vetoes_triggered=vetoes,
                )
            except Exception:  # noqa: BLE001
                log.exception("main_loop: emit_hard_veto_triggered failed")
            return _terminate_with_rejection(
                db,
                state=state,
                governor=governor,
                termination_reason=TerminationReason.HARD_VETO,
                final_iteration=iteration,
                iteration_artifact_ids=iteration_artifact_ids,
            )

        # Gate 2: acceptance floor (deterministic — pre-Critic per § Decision 8).
        floor = classify_acceptance(backtest_curr)
        if floor.classification == AcceptanceClassification.HARD_REJECT:
            return _terminate_with_rejection(
                db,
                state=state,
                governor=governor,
                termination_reason=TerminationReason.CRITIC_REJECT,
                final_iteration=iteration,
                iteration_artifact_ids=iteration_artifact_ids,
            )

        # Gate 3: budget preflight (§ Decision 14 — no grace iteration).
        if not governor.preflight(
            estimated_iteration_floor_usd=BUDGET_CAPS_USD["per_iteration"]
        ):
            try:
                emit_budget_exceeded(
                    loop_id=state.loop_id,
                    iteration_number=iteration,
                    scope="LOOP",
                    consumed_usd=_total_loop_usd(governor),
                    cap_usd=BUDGET_CAPS_USD["per_loop"],
                )
            except Exception:  # noqa: BLE001
                log.exception("main_loop: emit_budget_exceeded(LOOP) failed")
            return _terminate_with_rejection(
                db,
                state=state,
                governor=governor,
                termination_reason=TerminationReason.BUDGET_EXCEEDED_LOOP,
                final_iteration=iteration,
                iteration_artifact_ids=iteration_artifact_ids,
            )

        # Gate 4: Critic (ONLY LLM call inside the iteration). Critic-budget-blind.
        # family_skill_map[StrategySpec.strategy_family] yields the deterministic
        # skill id — Plan 06 maps it to the loaded SKILL.md overlay.
        _ = select_skill(spec_curr.strategy_family)  # validates family + raises on unknown
        try:
            verdict = run_critic(
                state,
                spec_curr,
                code_curr,
                build_curr,
                backtest_curr,
                db=db,
                task_id=state.loop_id,
            )
        except CriticDegradedError as e:
            log.warning("main_loop: CRITIC_DEGRADED at iter %d — %s", iteration, e)
            return _terminate_with_rejection(
                db,
                state=state,
                governor=governor,
                termination_reason=TerminationReason.CRITIC_DEGRADED,
                final_iteration=iteration,
                iteration_artifact_ids=iteration_artifact_ids,
            )

        verdict_id = f"cv_{state.loop_id}_iter{iteration}"
        verdict_payload = verdict.model_dump()
        verdict_payload["source_critic_verdict_id"] = verdict_id
        _persist_artifact(db, _CRITIC_VERDICTS, verdict_payload, verdict_id)
        iteration_artifact_ids[-1]["critic_verdict_id"] = verdict_id
        final_iteration_ids["critic_verdict_id"] = verdict_id
        state.critic_history = list(state.critic_history) + [verdict_id]
        update_loop_state(
            db, state.loop_id, critic_history=state.critic_history
        )

        try:
            emit_critic_verdict_received(
                loop_id=state.loop_id,
                iteration_number=iteration,
                critic_verdict_id=verdict_id,
                verdict=verdict.verdict,
                confidence=verdict.confidence,
                refinement_targets_count=len(verdict.refinement_targets),
            )
        except Exception:  # noqa: BLE001
            log.exception("main_loop: emit_critic_verdict_received failed")

        # Gate 5: identity drift (only meaningful for iter > 0). § Decision 10
        # ALWAYS anchors to spec_iter0 — NEVER to spec_prev_iter.
        if iteration >= 1:
            spec_iter0 = _load_spec_iter0(state, db)
            identity_score, diff_breakdown = compute_score(spec_curr, spec_iter0)
            state.identity_scores = list(state.identity_scores) + [identity_score]
            update_loop_state(
                db, state.loop_id, identity_scores=state.identity_scores
            )
            if should_terminate_for_drift(identity_score, iteration):
                threshold = IDENTITY_THRESHOLDS.get(iteration, 0.90)
                try:
                    emit_identity_drift_detected(
                        loop_id=state.loop_id,
                        iteration_number=iteration,
                        identity_score=identity_score,
                        threshold=threshold,
                        identity_diff_breakdown={"diffs": diff_breakdown},
                    )
                except Exception:  # noqa: BLE001
                    log.exception("main_loop: emit_identity_drift_detected failed")
                return _terminate_with_rejection(
                    db,
                    state=state,
                    governor=governor,
                    termination_reason=TerminationReason.IDENTITY_DRIFT,
                    final_iteration=iteration,
                    iteration_artifact_ids=iteration_artifact_ids,
                    verdict=verdict,
                    identity_diff_breakdown=diff_breakdown,
                )

        # Gate 6: convergence stall (compares against prev_targets — Plan 05).
        if iteration >= 1:
            stalled, repeated = detect_convergence_stall(
                verdict.refinement_targets, prev_targets
            )
            if stalled:
                try:
                    emit_convergence_stall_detected(
                        loop_id=state.loop_id,
                        iteration_number=iteration,
                        repeated_targets=[t.model_dump() for t in repeated],
                    )
                except Exception:  # noqa: BLE001
                    log.exception("main_loop: emit_convergence_stall_detected failed")
                return _terminate_with_rejection(
                    db,
                    state=state,
                    governor=governor,
                    termination_reason=TerminationReason.CONVERGENCE_STALL,
                    final_iteration=iteration,
                    iteration_artifact_ids=iteration_artifact_ids,
                    verdict=verdict,
                    repeated_targets=repeated,
                )

        # Critic dispatch: ACCEPT / REFINE / REJECT.
        if verdict.verdict == "ACCEPT":
            return _terminate_with_acceptance(
                db,
                state=state,
                governor=governor,
                verdict=verdict,
                final_iteration=iteration,
                final_iteration_ids=final_iteration_ids,
            )

        if verdict.verdict == "REJECT":
            return _terminate_with_rejection(
                db,
                state=state,
                governor=governor,
                termination_reason=TerminationReason.CRITIC_REJECT,
                final_iteration=iteration,
                iteration_artifact_ids=iteration_artifact_ids,
                verdict=verdict,
            )

        # REFINE — check if we have iterations left.
        if iteration + 1 >= MAX_ITERATIONS:
            return _terminate_with_rejection(
                db,
                state=state,
                governor=governor,
                termination_reason=TerminationReason.MAX_ITERATIONS,
                final_iteration=iteration,
                iteration_artifact_ids=iteration_artifact_ids,
                verdict=verdict,
            )

        # Per-iteration budget check (post-Critic).
        try:
            governor.check_iteration_cap()
        except Exception:  # LoopBudgetExceeded
            try:
                emit_budget_exceeded(
                    loop_id=state.loop_id,
                    iteration_number=iteration,
                    scope="ITERATION",
                    consumed_usd=float(
                        governor.budget_snapshot.get("iteration_usd", 0.0)
                    ),
                    cap_usd=BUDGET_CAPS_USD["per_iteration"],
                )
            except Exception:  # noqa: BLE001
                log.exception("main_loop: emit_budget_exceeded(ITERATION) failed")
            return _terminate_with_rejection(
                db,
                state=state,
                governor=governor,
                termination_reason=TerminationReason.BUDGET_EXCEEDED_ITERATION,
                final_iteration=iteration,
                iteration_artifact_ids=iteration_artifact_ids,
                verdict=verdict,
            )
        try:
            governor.check_loop_cap()
        except Exception:
            try:
                emit_budget_exceeded(
                    loop_id=state.loop_id,
                    iteration_number=iteration,
                    scope="LOOP",
                    consumed_usd=_total_loop_usd(governor),
                    cap_usd=BUDGET_CAPS_USD["per_loop"],
                )
            except Exception:  # noqa: BLE001
                log.exception("main_loop: emit_budget_exceeded(LOOP) failed")
            return _terminate_with_rejection(
                db,
                state=state,
                governor=governor,
                termination_reason=TerminationReason.BUDGET_EXCEEDED_LOOP,
                final_iteration=iteration,
                iteration_artifact_ids=iteration_artifact_ids,
                verdict=verdict,
            )

        # Carry refinement_targets forward for next-iteration convergence check.
        prev_targets = list(verdict.refinement_targets)

        # Refinement routing — Strategy/Code regenerate per § Decision 5.
        iteration += 1
        envelope = RefinementContextEnvelope(
            iteration=iteration,
            prior_strategy_spec_id=final_iteration_ids["strategy_spec_id"],
            prior_code_module_id=final_iteration_ids["code_module_id"],
            prior_build_report_id=final_iteration_ids["build_report_id"],
            prior_backtest_result_id=final_iteration_ids["backtest_result_id"],
            critic_verdict_id=verdict_id,
            refinement_targets=list(verdict.refinement_targets),
            identity_score=(
                state.identity_scores[-1] if state.identity_scores else 1.0
            ),
            registry_snapshot_hash=state.loop_registry_snapshot_hash,
        )

        try:
            spec_curr, code_curr = _route_next_iteration(
                targets=list(verdict.refinement_targets),
                prior_spec=spec_curr,
                prior_code=code_curr,
                hypothesis=hypothesis,
                envelope=envelope,
            )
        except StrategyAgentDegradedError as e:
            log.warning("main_loop: STRATEGY_DEGRADED at iter %d — %s", iteration, e)
            return _terminate_with_rejection(
                db,
                state=state,
                governor=governor,
                termination_reason=TerminationReason.STRATEGY_DEGRADED,
                final_iteration=iteration,
                iteration_artifact_ids=iteration_artifact_ids,
            )
        except CodeAgentDegradedError as e:
            log.warning("main_loop: CODE_DEGRADED at iter %d — %s", iteration, e)
            return _terminate_with_rejection(
                db,
                state=state,
                governor=governor,
                termination_reason=TerminationReason.CODE_DEGRADED,
                final_iteration=iteration,
                iteration_artifact_ids=iteration_artifact_ids,
            )

        # Persist regenerated artifacts.
        spec_curr_id = f"spec_{state.loop_id}_iter{iteration}"
        code_curr_id = f"code_{state.loop_id}_iter{iteration}"
        _persist_artifact(db, _STRATEGY_SPECS, spec_curr.model_dump(), spec_curr_id)
        _persist_artifact(db, _CODE_MODULES, code_curr.model_dump(), code_curr_id)

        # Run Build/Backtest for the regenerated module.
        build_curr = run_build(code_curr)
        build_curr_id = f"build_{state.loop_id}_iter{iteration}"
        _persist_artifact(
            db, _BUILD_REPORTS, build_curr.model_dump(), build_curr_id
        )

        # BuildReport status="failure" maps to BUILD_FAILED terminal state.
        if getattr(build_curr, "status", "success") == "failure":
            iteration_artifact_ids.append(
                {
                    "iter": iteration,
                    "strategy_spec_id": spec_curr_id,
                    "code_module_id": code_curr_id,
                    "build_report_id": build_curr_id,
                    "backtest_result_id": None,
                }
            )
            append_iteration_artifact(
                db, state.loop_id, iteration, iteration_artifact_ids[-1]
            )
            return _terminate_with_rejection(
                db,
                state=state,
                governor=governor,
                termination_reason=TerminationReason.BUILD_FAILED,
                final_iteration=iteration,
                iteration_artifact_ids=iteration_artifact_ids,
            )

        try:
            backtest_curr = run_backtest(code_curr, db=db, task_id=state.loop_id)
        except BacktesterDegradedError as e:
            log.warning("main_loop: BACKTEST_DEGRADED at iter %d — %s", iteration, e)
            return _terminate_with_rejection(
                db,
                state=state,
                governor=governor,
                termination_reason=TerminationReason.BACKTEST_DEGRADED,
                final_iteration=iteration,
                iteration_artifact_ids=iteration_artifact_ids,
            )

        backtest_curr_id = f"bt_{state.loop_id}_iter{iteration}"
        _persist_artifact(
            db, _BACKTEST_RESULTS, backtest_curr.model_dump(), backtest_curr_id
        )

        iteration_bundle: dict[str, Any] = {
            "iter": iteration,
            "strategy_spec_id": spec_curr_id,
            "code_module_id": code_curr_id,
            "build_report_id": build_curr_id,
            "backtest_result_id": backtest_curr_id,
        }
        iteration_artifact_ids.append(iteration_bundle)
        append_iteration_artifact(db, state.loop_id, iteration, iteration_bundle)

        final_iteration_ids = dict(iteration_bundle)

        # Reset iteration tally for next pass (loop totals preserved).
        governor.reset_iteration_tally()
        update_loop_state(
            db, state.loop_id, iteration=iteration, budget_snapshot=governor.budget_snapshot
        )
        # Loop continues — next iteration's gate cascade runs.


__all__ = [
    "run_refinement_loop",
    "_load_spec_iter0",
]
