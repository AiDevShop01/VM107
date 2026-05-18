"""Phase 48 Plan 48-05 Task 5.2 — convergence ignores severity drift.

REQ-48-D7. CONTEXT § Decision 7:
  "Severity drift tolerated (HIGH vs MEDIUM with same target+issue_type
   counts as same)."

A REFINE -> REFINE iteration where the Critic raised severity from MEDIUM to
HIGH on the SAME (scope, canonical_issue_id, issue_type) tuple still counts
as a stall — the underlying concern hasn't been resolved, only re-weighted.
"""
from __future__ import annotations

import pytest

from core.contracts.schemas import CanonicalIssueId, RefinementTarget


def _target(
    *,
    scope: str = "STRATEGY_SPEC",
    canonical_issue_id: CanonicalIssueId = CanonicalIssueId.WIN_RATE_BELOW_FLOOR,
    issue_type: str = "threshold",
    severity: str = "HIGH",
) -> RefinementTarget:
    return RefinementTarget(
        scope=scope,  # type: ignore[arg-type]
        canonical_issue_id=canonical_issue_id,
        target_field="rules",
        issue="probe",
        issue_type=issue_type,
        severity=severity,  # type: ignore[arg-type]
        suggested_change="probe",
        source_critic_verdict_id="cv_t1",
    )


@pytest.mark.parametrize(
    "prev_sev,curr_sev",
    [
        ("MEDIUM", "HIGH"),  # severity escalation
        ("HIGH", "MEDIUM"),  # severity de-escalation
        ("LOW", "HIGH"),
        ("HIGH", "LOW"),
        ("MEDIUM", "MEDIUM"),  # baseline -- same severity
    ],
)
def test_severity_drift_does_not_affect_match(prev_sev, curr_sev):
    """Same (scope, canonical_issue_id, issue_type) but different severity
    still counts as a match."""
    from core.agents.refinement_orchestrator.convergence_detector import detect_convergence_stall

    prev = [_target(severity=prev_sev)]
    curr = [_target(severity=curr_sev)]

    stalled, repeated = detect_convergence_stall(curr, prev)

    assert stalled is True
    assert len(repeated) == 1


def test_severity_drift_combined_with_multi_target_set_equality():
    """3 targets in prev, 3 in curr, all with severity differences -> stalled."""
    from core.agents.refinement_orchestrator.convergence_detector import detect_convergence_stall

    prev = [
        _target(canonical_issue_id=CanonicalIssueId.WIN_RATE_BELOW_FLOOR, severity="MEDIUM"),
        _target(canonical_issue_id=CanonicalIssueId.REGIME_CONCENTRATION_HIGH, issue_type="diversity", severity="HIGH"),
        _target(canonical_issue_id=CanonicalIssueId.OVERFIT_SIGNATURE, issue_type="signature", severity="LOW"),
    ]
    curr = [
        _target(canonical_issue_id=CanonicalIssueId.WIN_RATE_BELOW_FLOOR, severity="HIGH"),
        _target(canonical_issue_id=CanonicalIssueId.REGIME_CONCENTRATION_HIGH, issue_type="diversity", severity="LOW"),
        _target(canonical_issue_id=CanonicalIssueId.OVERFIT_SIGNATURE, issue_type="signature", severity="MEDIUM"),
    ]

    stalled, repeated = detect_convergence_stall(curr, prev)

    assert stalled is True
    assert len(repeated) == 3


def test_severity_drift_with_partial_overlap_not_stalled():
    """Severity drift on 1 tuple but curr also drops a tuple -> set inequality -> not stalled."""
    from core.agents.refinement_orchestrator.convergence_detector import detect_convergence_stall

    prev = [
        _target(canonical_issue_id=CanonicalIssueId.WIN_RATE_BELOW_FLOOR, severity="MEDIUM"),
        _target(canonical_issue_id=CanonicalIssueId.REGIME_CONCENTRATION_HIGH, issue_type="diversity"),
    ]
    curr = [
        _target(canonical_issue_id=CanonicalIssueId.WIN_RATE_BELOW_FLOOR, severity="HIGH"),
    ]

    stalled, _ = detect_convergence_stall(curr, prev)

    assert stalled is False
