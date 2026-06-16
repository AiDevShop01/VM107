"""Phase 53 lifecycle transitions emit governance_action.

Phase 87 Wave 5 — Task 1.
"""
import pytest

from VM107.core.belief.phase53_lifecycle import (
    approve_to_active,
    promote_to_proposed,
    retire_belief,
)

pytestmark = pytest.mark.phase_87


def _shadow():
    return {"belief_id": "b1", "lifecycle_state": "shadow"}


def _proposed():
    return {"belief_id": "b1", "lifecycle_state": "proposed"}


def test_shadow_to_proposed_at_5_reinforcements():
    action = promote_to_proposed(_shadow(), reinforcement_count=5)
    assert action is not None
    assert action.from_state == "shadow"
    assert action.to_state == "proposed"


def test_under_5_reinforcements_does_not_promote():
    assert promote_to_proposed(_shadow(), reinforcement_count=4) is None


def test_proposed_to_active_emits_governance():
    action = approve_to_active(_proposed(), approver_id="admin-1")
    assert action.from_state == "proposed"
    assert action.to_state == "active"
    assert action.approver_id == "admin-1"


def test_cannot_approve_from_shadow():
    with pytest.raises(ValueError, match="cannot approve from state shadow"):
        approve_to_active(_shadow(), approver_id="admin-1")


def test_retire_belief():
    action = retire_belief(_proposed(), reason="user override", approver_id="admin-1")
    assert action.to_state == "retired"
    assert action.reason == "user override"
