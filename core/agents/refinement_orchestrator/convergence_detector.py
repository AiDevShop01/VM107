"""Phase 48 Plan 48-05 — convergence-stall detector.

REQ-48-D7. CONTEXT § Decision 7 LOCKED:
  "After iteration N, orchestrator compares iteration N's
   ``refinement_targets`` against iteration N-1's, by **structured tuple
   equality on (scope, canonical_issue_id, issue_type)**.
   Severity drift tolerated (HIGH vs MEDIUM with same target+issue_type
   counts as same).
   NEVER compare raw LLM prose (LLM wording varies; structured intent
   stable)."

Pure function: ``detect_convergence_stall(targets_curr, targets_prev)``
returns ``(stalled, repeated_targets)``. No I/O, no Mongo, no LLM, no
registry. The orchestrator (Plan 08b) stamps the decision via
``append_iteration_artifact``.

Match key = ``(scope, canonical_issue_id, issue_type)``. Match semantics:
  set(curr_keys) == set(prev_keys) AND at least one shared key  -> stalled.

Edge cases:
  * ``targets_prev == []``  -> ``(False, [])``  (no prior to compare)
  * ``targets_curr == []``  -> ``(False, [])``  (no current concerns)
  * curr super-set / sub-set / disjoint -> ``(False, [])``

Critic NEVER emits ``is_stalling`` (CONTEXT § Anti-Patterns) — convergence
detection is orchestration policy, not Critic cognition.
"""
from __future__ import annotations

from core.contracts.schemas import RefinementTarget


def _key(target: RefinementTarget) -> tuple[str, str, str]:
    """Convergence-detection key tuple: (scope, canonical_issue_id, issue_type).

    severity, target_field, issue, suggested_change, source_critic_verdict_id
    are DELIBERATELY excluded — they vary with Critic prose drift across
    iterations even when the structured intent is unchanged.

    ``canonical_issue_id`` is a CanonicalIssueId StrEnum -> ``.value``
    yields the stable string. ``scope`` is a ``Literal`` of two strings.
    ``issue_type`` is a controlled-vocabulary string.
    """
    return (target.scope, target.canonical_issue_id.value, target.issue_type)


def detect_convergence_stall(
    targets_curr: list[RefinementTarget],
    targets_prev: list[RefinementTarget],
) -> tuple[bool, list[RefinementTarget]]:
    """Decide whether iteration N's refinement_targets stall iteration N-1's.

    Args:
        targets_curr: RefinementTargets emitted by Critic at iteration N.
        targets_prev: RefinementTargets emitted at iteration N-1.

    Returns:
        (stalled, repeated_targets).
          stalled: True iff set(curr_keys) == set(prev_keys) and at least
            one tuple is shared.
          repeated_targets: list of RefinementTarget objects from
            ``targets_curr`` whose key tuple appears in BOTH lists.
            Empty when not stalled.
    """
    # Defensive: no prior or no current -> never stalled.
    if not targets_prev or not targets_curr:
        return False, []

    curr_keys = {_key(t) for t in targets_curr}
    prev_keys = {_key(t) for t in targets_prev}

    shared = curr_keys & prev_keys
    stalled = (curr_keys == prev_keys) and len(shared) > 0

    if not stalled:
        return False, []

    # Preserve order from targets_curr; return the SAME RefinementTarget
    # objects (identity-preserving — tests assert ``repeated[0] is curr_t``).
    repeated_targets = [t for t in targets_curr if _key(t) in shared]
    return True, repeated_targets


__all__ = ["detect_convergence_stall"]
