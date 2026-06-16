"""REQ-87-7d — LLM-direct propose blocked at API level.

Phase 87 Wave 5 — Task 1.
"""
import pytest

from VM107.core.belief.proposal_authorization import (
    DETERMINISTIC_PROPOSERS,
    authorize_proposer,
)

pytestmark = pytest.mark.phase_87


def test_macro_regime_analyst_allowed():
    authorize_proposer("macro_regime_analyst")  # does not raise
    authorize_proposer("vm107.macro_regime_analyst")


def test_llm_keyword_in_proposer_id_blocked():
    with pytest.raises(PermissionError, match="LLM-direct"):
        authorize_proposer("vm107.macro_release_llm_narrator")
    with pytest.raises(PermissionError, match="LLM-direct"):
        authorize_proposer("LLM_chain")


def test_unknown_proposer_blocked():
    with pytest.raises(PermissionError, match="unknown proposer"):
        authorize_proposer("vm107.macro_random_unknown_agent")


def test_deterministic_proposer_set_contains_both_phase87_proposers():
    """Plan 87-09 shipped with {macro_regime_analyst} only.

    Plan 87-10 (Wave 5b) added macro_regime_monitor as the second
    authorized deterministic proposer — the 6-hourly background agent
    that re-runs Bayesian updates across all 7 regimes. Both proposers
    MUST be present; nothing else may sneak in without a sibling decimal
    phase update + this test bump.
    """
    assert DETERMINISTIC_PROPOSERS == {
        "macro_regime_analyst",
        "macro_regime_monitor",
    }


def test_macro_regime_monitor_allowed():
    """Plan 87-10 — macro_regime_monitor must be an allowed proposer
    (used by the every-6h background agent for Bayesian updates)."""
    authorize_proposer("macro_regime_monitor")          # does not raise
    authorize_proposer("vm107.macro_regime_monitor")    # bare-id strip
