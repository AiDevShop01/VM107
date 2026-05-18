"""
Phase 44 + Phase 48 contract exceptions.

Phase 44: SchemaVersionMismatchError — strict fail-fast on version skew.
Phase 48 (Plan 48-01): 6 new typed exceptions per CONTEXT.md § Decisions
5 / 6 / 7 / 10 / 14 and RESEARCH.md § Code Examples lines 1008-1072.
"""
from __future__ import annotations


class SchemaVersionMismatchError(ValueError):
    """Raised when a typed payload's schema_version does not match expected.

    Phase 44: strict fail-fast — NO implicit migration. See CONTEXT.md § A2A Envelope Structure.
    """

    def __init__(self, expected: int, received: int) -> None:
        self.expected = expected
        self.received = received
        super().__init__(f"Schema version mismatch: expected={expected}, received={received}")


# =============================================================================
# Phase 48 Plan 48-01 — typed exceptions for the refinement-loop orchestrator
# =============================================================================


class RefinementRoutingError(ValueError):
    """Raised when RefinementTarget.scope combination is invalid.

    Examples of invalid combinations (caught at orchestrator validation):
    - CODE_MODULE-scoped target referencing a strategy-logic field
    - STRATEGY_SPEC-scoped target referencing a CodeModule-only field

    Phase 48 § Decision 5 — orchestrator rejects at validation time.
    """

    pass


class IdentityDriftError(RuntimeError):
    """Raised when strategy_identity_similarity_score < tightening floor.

    Phase 48 § Decision 10 — orchestrator FORCES termination regardless of
    Critic verdict. Critic CANNOT override.
    """

    def __init__(self, iteration: int, score: float, threshold: float) -> None:
        self.iteration = iteration
        self.score = score
        self.threshold = threshold
        super().__init__(
            f"Identity drift at iteration {iteration}: score={score:.3f} < "
            f"threshold={threshold:.3f} (anchored to iteration 0)"
        )


class ConvergenceStallError(RuntimeError):
    """Raised when repeated (scope, canonical_issue_id, issue_type) detected.

    Phase 48 § Decision 7 — orchestrator terminates BEFORE max-iterations
    when the same refinement target tuple recurs across iterations.
    """

    pass


class BudgetExceededError(RuntimeError):
    """Raised when a refinement-loop budget cap is exceeded.

    Phase 48 § Decision 14 — distinct from Phase 38's
    BoundaryStatus.*_EXCEEDED (per-agent boundary enforcement). This is the
    refinement-loop-level budget exception used by the orchestrator's
    preflight/postflight checks.
    """

    pass


class OrphanStrategyError(ValueError):
    """Raised when StrategySpec / CodeModule lacks Hypothesis lineage.

    Phase 48 § Decision 6 — no orphan-strategy refinement allowed.
    Every artifact must trace back to a root_hypothesis_id.
    """

    pass


class LoopBudgetExceeded(RuntimeError):
    """Raised when per-loop OR per-iteration budget cap is hit.

    Phase 48 § Decision 14 — distinct from Phase 38's
    BoundaryStatus.*_EXCEEDED (which raises a different exception type).
    Two flavors via the ``scope`` attribute: ITERATION | LOOP.
    """

    def __init__(self, scope: str, consumed_usd: float, cap_usd: float) -> None:
        self.scope = scope  # ITERATION | LOOP
        self.consumed_usd = consumed_usd
        self.cap_usd = cap_usd
        super().__init__(
            f"Budget exceeded at scope={scope}: "
            f"consumed={consumed_usd:.4f} USD > cap={cap_usd:.4f} USD"
        )
