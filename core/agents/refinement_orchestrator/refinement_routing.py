"""Phase 48 refinement routing — scope-tagged dispatch + invalid-combo validation.

REQ-48-D5. CONTEXT § Decision 5.

Pure-function dispatcher. NO Mongo, NO LLM directly (delegates to the typed
wrappers ``run_strategy`` / ``run_code`` from ``core.agents.invocation``).
NO Phase 56 emit. NO registry side-effects.

Public surface:
    validate_scope_combinations(targets) -> None
        Raises RefinementRoutingError on invalid scope/field combos.
    route_refinement(targets, prior_spec, prior_code, hypothesis, envelope)
            -> tuple[StrategySpec, CodeModule]
        Dispatches according to the target list's scope mix:
          - any STRATEGY_SPEC target present -> run_strategy(hypothesis, ...)
            cascades into run_code(new_spec, ...).
          - all CODE_MODULE targets -> run_code(prior_spec, ...); StrategySpec
            unchanged (Decision 5 strict rule).

Validation rules:
  (a) CODE_MODULE-scoped target whose target_field exists ONLY on StrategySpec
      -> RefinementRoutingError.
  (b) STRATEGY_SPEC-scoped target whose target_field exists ONLY on CodeModule
      -> RefinementRoutingError.
  (c) Duplicate (target_field, scope) tuples -> RefinementRoutingError.

Field-membership sets are built ONCE at module import from the respective
``model_fields`` dicts on StrategySpec / CodeModule. ``version`` is shared
(legal in either scope). Dotted-prefix fields (e.g. ``metrics.win_rate``)
are accepted in either scope — Critic frequently routes metric-scoped
concerns via STRATEGY_SPEC (parameter tuning) without that being illegal.

Decision 5 ordering guarantee: Strategy-first cascade is acyclic. Even when
the target list is supplied in CODE-first order, this module ALWAYS calls
``run_strategy`` first when at least one STRATEGY_SPEC-scoped target is
present, and passes the resulting NEW StrategySpec to ``run_code``.
"""
from __future__ import annotations

from typing import Iterable

from core.agents.invocation import run_code, run_strategy
from core.contracts.exceptions import RefinementRoutingError
from core.contracts.schemas import (
    CodeModule,
    Hypothesis,
    RefinementContextEnvelope,
    RefinementTarget,
    StrategySpec,
)

# ---------------------------------------------------------------------------
# Field-membership sets (built once at module import).
# ---------------------------------------------------------------------------

_STRATEGY_FIELDS: frozenset[str] = frozenset(StrategySpec.model_fields.keys())
_CODE_FIELDS: frozenset[str] = frozenset(CodeModule.model_fields.keys())

_STRATEGY_ONLY_FIELDS: frozenset[str] = _STRATEGY_FIELDS - _CODE_FIELDS
_CODE_ONLY_FIELDS: frozenset[str] = _CODE_FIELDS - _STRATEGY_FIELDS
_SHARED_FIELDS: frozenset[str] = _STRATEGY_FIELDS & _CODE_FIELDS


def _top_level_field(target_field: str) -> str:
    """Return the top-level field segment (dotted-prefix-aware).

    Dotted-prefix fields (e.g. ``metrics.win_rate``) are forwarded by the
    Critic for nested concerns. Validation operates on the top-level segment.
    """
    return target_field.split(".", 1)[0]


def validate_scope_combinations(targets: Iterable[RefinementTarget]) -> None:
    """Reject invalid scope/field combinations + duplicate (field, scope) tuples.

    Raises:
        RefinementRoutingError: any of the 3 invalid conditions detected.

    Returns:
        None on success (empty target list is treated as a no-op — the loop
        body is responsible for not routing when the Critic has emitted no
        targets).
    """
    seen: set[tuple[str, str]] = set()
    for tgt in targets:
        scope = tgt.scope
        field = tgt.target_field
        top = _top_level_field(field)

        # (a) CODE_MODULE target on StrategySpec-only field
        if scope == "CODE_MODULE" and top in _STRATEGY_ONLY_FIELDS:
            raise RefinementRoutingError(
                f"Invalid scope/field combination: CODE_MODULE target on "
                f"StrategySpec-only field {field!r}. CODE_MODULE-scoped "
                f"targets must point at CodeModule fields or shared fields. "
                f"StrategySpec-only fields: {sorted(_STRATEGY_ONLY_FIELDS)}"
            )

        # (b) STRATEGY_SPEC target on CodeModule-only field
        if scope == "STRATEGY_SPEC" and top in _CODE_ONLY_FIELDS:
            raise RefinementRoutingError(
                f"Invalid scope/field combination: STRATEGY_SPEC target on "
                f"CodeModule-only field {field!r}. STRATEGY_SPEC-scoped "
                f"targets must point at StrategySpec fields, shared fields, "
                f"or dotted-prefix nested fields. "
                f"CodeModule-only fields: {sorted(_CODE_ONLY_FIELDS)}"
            )

        # (c) Duplicate (target_field, scope) tuple
        key = (field, scope)
        if key in seen:
            raise RefinementRoutingError(
                f"Duplicate refinement target: (target_field={field!r}, "
                f"scope={scope!r}) appears more than once in the target list. "
                f"Each (field, scope) pair must be unique per iteration."
            )
        seen.add(key)


def _has_strategy_scope(targets: Iterable[RefinementTarget]) -> bool:
    return any(t.scope == "STRATEGY_SPEC" for t in targets)


def route_refinement(
    *,
    targets: list[RefinementTarget],
    prior_spec: StrategySpec,
    prior_code: CodeModule,
    hypothesis: Hypothesis,
    envelope: RefinementContextEnvelope,
) -> tuple[StrategySpec, CodeModule]:
    """Route a refinement target list back into the typed wrappers.

    Dispatch table (CONTEXT § Decision 5):
      - >=1 STRATEGY_SPEC scoped target  -> run_strategy(hypothesis, env) then
                                            run_code(NEW_spec, env)
      - all CODE_MODULE scoped targets   -> run_code(prior_spec, env);
                                            StrategySpec passed through unchanged

    Validation is invoked FIRST — invalid scope combinations raise
    RefinementRoutingError before any LLM wrapper executes.

    Args:
        targets: Critic-emitted refinement targets for this iteration.
        prior_spec: StrategySpec from the previous iteration.
        prior_code: CodeModule from the previous iteration.
        hypothesis: Immutable root Hypothesis (anchors STRATEGY_SPEC scope).
        envelope: typed RefinementContextEnvelope threaded into both wrappers.

    Returns:
        Tuple of (new_or_prior_strategy_spec, new_code_module).

    Raises:
        RefinementRoutingError: scope/field combination invalid.
        StrategyAgentDegradedError / CodeAgentDegradedError: from the wrappers.
    """
    # Validation runs FIRST — never call a wrapper on an invalid target list.
    validate_scope_combinations(targets)

    if _has_strategy_scope(targets):
        # Strategy regenerates from the SAME immutable Hypothesis + targets.
        new_spec = run_strategy(hypothesis, refinement_context=envelope)
        # Cascade: Code regenerates from the NEW spec (acyclic per Decision 5).
        new_code = run_code(new_spec, refinement_context=envelope)
        return new_spec, new_code

    # All CODE_MODULE scope: StrategySpec unchanged; only Code regenerates.
    new_code = run_code(prior_spec, refinement_context=envelope)
    return prior_spec, new_code


__all__ = [
    "route_refinement",
    "validate_scope_combinations",
]
