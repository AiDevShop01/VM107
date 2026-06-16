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


def test_deterministic_proposer_set_contains_only_regime_analyst():
    assert DETERMINISTIC_PROPOSERS == {"macro_regime_analyst"}
