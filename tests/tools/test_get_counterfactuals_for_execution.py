"""Phase 61-01 Wave 0 scaffold — test_get_counterfactuals_for_execution.py

Tests for get_counterfactuals_for_execution VM107 tool.
RG-8 coverage (scope visibility).

Bodies land in Task 5.
"""

import pytest


@pytest.mark.xfail(strict=True, reason="Phase 61-01 Wave 0 scaffold — body lands in Task 5")
def test_canonical_only_filter():
    """Experimental-tier scenarios NOT returned when scope=CANONICAL_ONLY."""
    assert False, "TBD-61-01"


@pytest.mark.xfail(strict=True, reason="Phase 61-01 Wave 0 scaffold — body lands in Task 5")
def test_none_scope_returns_empty():
    """Returns [] when counterfactual_visibility=NONE."""
    assert False, "TBD-61-01"


@pytest.mark.xfail(strict=True, reason="Phase 61-01 Wave 0 scaffold — body lands in Task 5")
def test_tier_canonical_default():
    """Default tier='canonical' returns only canonical-tier artifacts."""
    assert False, "TBD-61-01"
