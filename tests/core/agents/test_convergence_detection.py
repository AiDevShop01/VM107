"""Phase 48 Plan 48-05 Task 5.2 — convergence_detector structured-tuple match.

REQ-48-D7. CONTEXT § Decision 7:
  "Compares iteration N's refinement_targets against iteration N-1's, by
   structured tuple equality on (scope, canonical_issue_id, issue_type)."

Comparison key = ``(scope, canonical_issue_id, issue_type)``. ignores severity
(see test_convergence_severity_drift), ignores suggested_change prose,
ignores target_field nuance.

Returns ``(stalled: bool, repeated_targets: list[RefinementTarget])``.

Edge cases:
  * targets_prev == []           -> (False, [])   no prior to compare
  * curr is super-set of prev    -> (False, [])   curr introduced new concerns
  * curr is sub-set of prev      -> (False, [])   curr resolved some prior concerns
  * curr == prev (set equality)  -> (True, repeated_targets)

Pure function: no Mongo, no LLM, no I/O.
"""
from __future__ import annotations

import pytest

from core.contracts.schemas import CanonicalIssueId, RefinementTarget


def _target(
    *,
    scope: str = "STRATEGY_SPEC",
    canonical_issue_id: CanonicalIssueId = CanonicalIssueId.WIN_RATE_BELOW_FLOOR,
    target_field: str = "rules",
    issue: str = "win rate too low",
    issue_type: str = "threshold",
    severity: str = "HIGH",
    suggested_change: str = "tighten entry filter",
    source_critic_verdict_id: str = "cv_test_001",
) -> RefinementTarget:
    """Helper to build a RefinementTarget with sensible defaults."""
    return RefinementTarget(
        scope=scope,  # type: ignore[arg-type]
        canonical_issue_id=canonical_issue_id,
        target_field=target_field,
        issue=issue,
        issue_type=issue_type,
        severity=severity,  # type: ignore[arg-type]
        suggested_change=suggested_change,
        source_critic_verdict_id=source_critic_verdict_id,
    )


def test_empty_prev_returns_not_stalled():
    """Iteration 0 has no prior -> no stall possible."""
    from core.agents.refinement_orchestrator.convergence_detector import detect_convergence_stall

    curr = [_target()]
    stalled, repeated = detect_convergence_stall(curr, [])

    assert stalled is False
    assert repeated == []


def test_identical_single_tuple_returns_stalled():
    """prev and curr each have one target with same (scope, issue_id, type) -> stalled."""
    from core.agents.refinement_orchestrator.convergence_detector import detect_convergence_stall

    prev = [_target(canonical_issue_id=CanonicalIssueId.WIN_RATE_BELOW_FLOOR, issue_type="threshold")]
    curr = [_target(canonical_issue_id=CanonicalIssueId.WIN_RATE_BELOW_FLOOR, issue_type="threshold")]

    stalled, repeated = detect_convergence_stall(curr, prev)

    assert stalled is True
    assert len(repeated) == 1


def test_curr_is_superset_returns_not_stalled():
    """curr has NEW concerns vs prev -> not stalled (search is still moving)."""
    from core.agents.refinement_orchestrator.convergence_detector import detect_convergence_stall

    prev = [_target(canonical_issue_id=CanonicalIssueId.WIN_RATE_BELOW_FLOOR)]
    curr = [
        _target(canonical_issue_id=CanonicalIssueId.WIN_RATE_BELOW_FLOOR),
        _target(canonical_issue_id=CanonicalIssueId.REGIME_CONCENTRATION_HIGH, target_field="features"),
    ]

    stalled, repeated = detect_convergence_stall(curr, prev)

    assert stalled is False


def test_curr_is_subset_returns_not_stalled():
    """curr resolved some concerns vs prev -> not stalled (progress)."""
    from core.agents.refinement_orchestrator.convergence_detector import detect_convergence_stall

    prev = [
        _target(canonical_issue_id=CanonicalIssueId.WIN_RATE_BELOW_FLOOR),
        _target(canonical_issue_id=CanonicalIssueId.REGIME_CONCENTRATION_HIGH, target_field="features"),
    ]
    curr = [_target(canonical_issue_id=CanonicalIssueId.WIN_RATE_BELOW_FLOOR)]

    stalled, repeated = detect_convergence_stall(curr, prev)

    assert stalled is False


def test_completely_different_returns_not_stalled():
    """No overlap -> definitely not stalled."""
    from core.agents.refinement_orchestrator.convergence_detector import detect_convergence_stall

    prev = [_target(canonical_issue_id=CanonicalIssueId.WIN_RATE_BELOW_FLOOR)]
    curr = [_target(canonical_issue_id=CanonicalIssueId.OVERFIT_SIGNATURE, target_field="features", issue_type="signature")]

    stalled, repeated = detect_convergence_stall(curr, prev)

    assert stalled is False
    assert repeated == []


def test_empty_curr_returns_not_stalled():
    """No current targets -> no stall (probably an ACCEPT path or first-iter)."""
    from core.agents.refinement_orchestrator.convergence_detector import detect_convergence_stall

    prev = [_target()]
    curr: list[RefinementTarget] = []

    stalled, repeated = detect_convergence_stall(curr, prev)

    assert stalled is False
    assert repeated == []


@pytest.mark.parametrize(
    "scope_prev,scope_curr,expected_stalled",
    [
        ("STRATEGY_SPEC", "STRATEGY_SPEC", True),
        ("CODE_MODULE", "CODE_MODULE", True),
        ("STRATEGY_SPEC", "CODE_MODULE", False),  # scope changed -> not a match
        ("CODE_MODULE", "STRATEGY_SPEC", False),
    ],
)
def test_scope_is_part_of_match_key(scope_prev, scope_curr, expected_stalled):
    from core.agents.refinement_orchestrator.convergence_detector import detect_convergence_stall

    prev = [_target(scope=scope_prev, target_field="rules")]
    curr = [_target(scope=scope_curr, target_field="rules")]

    stalled, _ = detect_convergence_stall(curr, prev)
    assert stalled is expected_stalled


@pytest.mark.parametrize(
    "issue_type_prev,issue_type_curr,expected_stalled",
    [
        ("threshold", "threshold", True),
        ("threshold", "structural", False),
        ("calibration", "calibration", True),
    ],
)
def test_issue_type_is_part_of_match_key(issue_type_prev, issue_type_curr, expected_stalled):
    from core.agents.refinement_orchestrator.convergence_detector import detect_convergence_stall

    prev = [_target(issue_type=issue_type_prev)]
    curr = [_target(issue_type=issue_type_curr)]

    stalled, _ = detect_convergence_stall(curr, prev)
    assert stalled is expected_stalled


def test_target_field_is_NOT_part_of_match_key():
    """target_field nuance is ignored -- only (scope, canonical_issue_id, issue_type) matters."""
    from core.agents.refinement_orchestrator.convergence_detector import detect_convergence_stall

    prev = [_target(target_field="rules")]
    curr = [_target(target_field="features")]  # different target_field, same key tuple

    stalled, _ = detect_convergence_stall(curr, prev)
    assert stalled is True


def test_suggested_change_prose_is_NOT_part_of_match_key():
    """Different rationale prose with same key tuple still counts as stalled."""
    from core.agents.refinement_orchestrator.convergence_detector import detect_convergence_stall

    prev = [_target(suggested_change="raise threshold to 0.7")]
    curr = [_target(suggested_change="recompute window length")]

    stalled, _ = detect_convergence_stall(curr, prev)
    assert stalled is True


def test_repeated_targets_returned_when_stalled():
    """When stalled, the returned RefinementTarget objects come from CURR list."""
    from core.agents.refinement_orchestrator.convergence_detector import detect_convergence_stall

    curr_t = _target(suggested_change="curr-rationale")
    prev_t = _target(suggested_change="prev-rationale")

    stalled, repeated = detect_convergence_stall([curr_t], [prev_t])

    assert stalled is True
    assert len(repeated) == 1
    assert repeated[0] is curr_t  # identity check — repeated comes from CURR
    assert repeated[0].suggested_change == "curr-rationale"


def test_returns_tuple_bool_list():
    from core.agents.refinement_orchestrator.convergence_detector import detect_convergence_stall

    result = detect_convergence_stall([_target()], [_target()])

    assert isinstance(result, tuple)
    assert len(result) == 2
    stalled, repeated = result
    assert isinstance(stalled, bool)
    assert isinstance(repeated, list)
