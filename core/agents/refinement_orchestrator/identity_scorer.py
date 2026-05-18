"""Phase 48 Plan 48-05 — identity drift detector.

REQ-48-D10. CONTEXT § Decision 10 LOCKED:
  Deterministic structured-diff Python score over StrategySpec fields.
  NEVER vector/semantic similarity (47.6 rejects probabilistic discovery
  in cognition paths).

Pure function: ``compute_score(spec_new, spec_iter0) -> (float, list[dict])``.

Anchoring contract: ``spec_iter0`` is the ORIGIN spec (iteration 0).
Identity ALWAYS compares against iter 0, NEVER iter N-1, so creeping drift
is impossible by construction. Anchoring is enforced by the orchestrator
(Plan 08b reads ``RefinementLoopState.spec_iter0_id`` and passes the
hydrated spec).

Field-mutability weights (planner-locked, Plan 48-05 Task 5.1):
  IMMUTABLE_CORE  -> 0.5   (severity HIGH)
  REFINABLE       -> 0.2   (severity MEDIUM)
  MINOR_TUNING    -> 0.0   (severity LOW, no score contribution)

The score is ``1.0 - sum(weights_of_divergent_fields)``, clamped to
``[0.0, 1.0]``. Iteration thresholds live in ``policy_constants`` (single
source of truth):

  iter 1 vs iter 0: >= 0.70
  iter 2 vs iter 0: >= 0.80
  iter 3 vs iter 0: >= 0.90

Purity: no I/O. No Mongo. No LLM. No registry. The orchestrator calls
``compute_score`` then stamps the result via ``append_iteration_artifact``;
THIS module returns inputs->decision only.
"""
from __future__ import annotations

from typing import Any

from core.agents.refinement_orchestrator.policy_constants import IDENTITY_THRESHOLDS
from core.contracts.schemas import FieldMutability, StrategySpec

# ---------------------------------------------------------------------------
# Field-mutability -> (weight, severity) lookup. Single source of truth for
# the structured-diff calculus. Pinned at module import time; never mutated.
# ---------------------------------------------------------------------------

_MUTABILITY_WEIGHT: dict[str, float] = {
    FieldMutability.IMMUTABLE_CORE.value: 0.5,
    FieldMutability.REFINABLE.value: 0.2,
    FieldMutability.MINOR_TUNING.value: 0.0,
}

_MUTABILITY_SEVERITY: dict[str, str] = {
    FieldMutability.IMMUTABLE_CORE.value: "HIGH",
    FieldMutability.REFINABLE.value: "MEDIUM",
    FieldMutability.MINOR_TUNING.value: "LOW",
}

# Fields without explicit mutability metadata (e.g., schema_version) default
# to MINOR_TUNING (zero weight) so the score is robust to schema additions.
_DEFAULT_MUTABILITY: str = FieldMutability.MINOR_TUNING.value


def _resolve_mutability(spec_cls: type[StrategySpec], field_name: str) -> str:
    """Return the FieldMutability string for a StrategySpec field.

    Pydantic ``Field(json_schema_extra={"mutability": ...})`` is the canonical
    surface — see ``core.contracts.schemas.StrategySpec``. Missing metadata
    falls back to MINOR_TUNING (zero weight, LOW severity).
    """
    field = spec_cls.model_fields.get(field_name)
    if field is None:
        return _DEFAULT_MUTABILITY
    extra = field.json_schema_extra
    if isinstance(extra, dict):
        mutability = extra.get("mutability")
        if isinstance(mutability, str):
            return mutability
    return _DEFAULT_MUTABILITY


def compute_score(
    spec_new: StrategySpec,
    spec_iter0: StrategySpec,
) -> tuple[float, list[dict[str, Any]]]:
    """Compute identity-similarity score + per-field diff breakdown.

    Args:
        spec_new: The candidate StrategySpec (iteration N).
        spec_iter0: The anchor StrategySpec (iteration 0). NEVER iter N-1.

    Returns:
        (score, diff_breakdown).
          score: float in [0.0, 1.0]. 1.0 == bit-identical or only MINOR_TUNING drift.
          diff_breakdown: list of dicts, one per differing field. Each entry
            carries: field, severity, was, now, weight.

    Determinism: pure function over Pydantic introspection — no randomness,
    no I/O, no module-level mutable state. Same inputs -> same outputs across
    arbitrarily many calls.

    Anchored-to-origin: this function does NOT enforce anchoring; the caller
    (orchestrator's main loop, Plan 08b) is responsible for passing iter 0.
    Tests confirm the orchestrator wires this correctly.
    """
    diff_breakdown: list[dict[str, Any]] = []
    weight_sum: float = 0.0

    # Walk the union of field names in canonical (model-declaration) order so
    # the diff output is stable across runs.
    new_dump = spec_new.model_dump()
    origin_dump = spec_iter0.model_dump()

    for field_name in StrategySpec.model_fields:
        was = origin_dump.get(field_name)
        now = new_dump.get(field_name)
        if was == now:
            continue

        mutability = _resolve_mutability(StrategySpec, field_name)
        weight = _MUTABILITY_WEIGHT.get(mutability, 0.0)
        severity = _MUTABILITY_SEVERITY.get(mutability, "LOW")

        diff_breakdown.append(
            {
                "field": field_name,
                "severity": severity,
                "was": was,
                "now": now,
                "weight": weight,
            }
        )
        weight_sum += weight

    raw_score = 1.0 - weight_sum
    score = max(0.0, min(1.0, raw_score))
    return score, diff_breakdown


def should_terminate_for_drift(score: float, iteration: int) -> bool:
    """Return True iff this iteration's score is below the tightening threshold.

    Args:
        score: identity-similarity score from ``compute_score``.
        iteration: 1-indexed iteration number (the refinement iteration
            being judged; iteration 0 is the origin and never drifts).

    Returns:
        True if orchestrator MUST terminate with TerminationReason.IDENTITY_DRIFT.

    Thresholds come EXCLUSIVELY from ``policy_constants.IDENTITY_THRESHOLDS``
    (Plan 04 single source of truth). Iteration numbers outside the locked
    set {1, 2, 3} are treated conservatively: anything beyond iter 3 inherits
    the iter-3 threshold (0.90).
    """
    threshold = IDENTITY_THRESHOLDS.get(iteration)
    if threshold is None:
        # Defensive: iteration > MAX_ITERATIONS should never reach here, but
        # if it does, apply the tightest known floor.
        threshold = max(IDENTITY_THRESHOLDS.values())
    return score < threshold


__all__ = ["compute_score", "should_terminate_for_drift"]
