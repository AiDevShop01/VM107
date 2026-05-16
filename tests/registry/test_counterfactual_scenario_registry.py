"""Phase 61-01 Wave 0 scaffold — test_counterfactual_scenario_registry.py

Tests for VM107 counterfactual_scenario registry category.
RG-10 coverage.

Bodies land in Task 5.
"""

import pytest


@pytest.mark.xfail(strict=True, reason="Phase 61-01 Wave 0 scaffold — body lands in Task 5")
def test_registry_subdirs_includes_counterfactual_scenario():
    """REGISTRY_SUBDIRS in citation_validator.py includes 'counterfactual_scenario'."""
    assert False, "TBD-61-01"


@pytest.mark.xfail(strict=True, reason="Phase 61-01 Wave 0 scaffold — body lands in Task 5")
def test_load_known_registry_ids_does_not_crash_on_empty_counterfactual_dir():
    """load_known_registry_ids() with empty counterfactual_scenario/ dir does not crash."""
    assert False, "TBD-61-01"
