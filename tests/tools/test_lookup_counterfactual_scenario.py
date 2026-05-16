"""Phase 61-01 Wave 0 scaffold — test_lookup_counterfactual_scenario.py

Tests for lookup_counterfactual_scenario VM107 tool.
RG-8 coverage (scope visibility).

Bodies land in Task 5.
"""

import pytest


@pytest.mark.xfail(strict=True, reason="Phase 61-01 Wave 0 scaffold — body lands in Task 5")
def test_lookup_returns_empty_when_registry_empty():
    """lookup_counterfactual_scenario returns None/empty when no scenarios registered (61-01 state)."""
    assert False, "TBD-61-01"


@pytest.mark.xfail(strict=True, reason="Phase 61-01 Wave 0 scaffold — body lands in Task 5")
def test_canonical_tier_scenarios_visible_to_canonical_only_scope():
    """Canonical-tier scenarios visible when counterfactual_visibility=CANONICAL_ONLY."""
    assert False, "TBD-61-01"
