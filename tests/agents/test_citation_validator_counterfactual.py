"""Phase 61-01 Wave 0 scaffold — test_citation_validator_counterfactual.py

Tests for CitationValidator counterfactual namespace extension.
RG-3 coverage (citation golden tests).

Bodies land in Task 5.
"""

import pytest


@pytest.mark.xfail(strict=True, reason="Phase 61-01 Wave 0 scaffold — body lands in Task 5")
def test_counterfactual_artifact_citation_form_parses():
    """[ref:counterfactual:cf_<uuid>] parses syntactically (artifact-level citation)."""
    assert False, "TBD-61-01"


@pytest.mark.xfail(strict=True, reason="Phase 61-01 Wave 0 scaffold — body lands in Task 5")
def test_counterfactual_scenario_citation_resolves():
    """[ref:counterfactual:counterfactual.stop.atr_1_0:hypothetical_r] parses + validates."""
    assert False, "TBD-61-01"


@pytest.mark.xfail(strict=True, reason="Phase 61-01 Wave 0 scaffold — body lands in Task 5")
def test_unknown_scenario_citation_hard_fails():
    """[ref:counterfactual:counterfactual.stop.nonexistent:hypothetical_r] raises CitationViolation."""
    assert False, "TBD-61-01"


@pytest.mark.xfail(strict=True, reason="Phase 61-01 Wave 0 scaffold — body lands in Task 5")
def test_existing_phase_60_citations_still_work():
    """Backward-compat: existing Phase 60 citation forms still validate after extension (RG-3)."""
    assert False, "TBD-61-01"
