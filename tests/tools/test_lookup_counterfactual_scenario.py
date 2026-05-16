"""Phase 61-01 Task 5 — test_lookup_counterfactual_scenario.py

Tests for lookup_counterfactual_scenario VM107 tool.
RG-8 coverage (scope visibility).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# VM107 root setup
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from helpers.counterfactual_reader import lookup_counterfactual_scenario


def test_lookup_returns_empty_when_registry_empty():
    """lookup_counterfactual_scenario returns None when no scenarios registered (61-01 state).

    In Phase 61-01 V1 — zero production scenarios shipped — the endpoint returns 404.
    """
    # Mock httpx.get to return 404 (no scenarios registered)
    class _MockResponse:
        status_code = 404
        def raise_for_status(self): pass
        def json(self): return {"detail": "not found"}

    with patch.dict("os.environ", {"VM100_INTERNAL_API_URL": "http://vm100-mock:8000"}):
        with patch("httpx.get", return_value=_MockResponse()):
            result = lookup_counterfactual_scenario("counterfactual.stop.atr_1_0")
            assert result is None, f"Expected None for 404 response, got {result!r}"


def test_canonical_tier_scenarios_visible_to_canonical_only_scope():
    """Canonical-tier scenarios visible when counterfactual_visibility=CANONICAL_ONLY.

    Tests _apply_visibility_filter logic directly (unit test without network).
    """
    from helpers.counterfactual_reader import _apply_visibility_filter

    artifacts = [
        {"scenario_id": "counterfactual.stop.atr_1_0", "scenario_tier": "canonical", "truth_mode": "COUNTERFACTUAL"},
        {"scenario_id": "counterfactual.entry.alt_zone", "scenario_tier": "experimental", "truth_mode": "COUNTERFACTUAL"},
    ]

    # CANONICAL_ONLY filter: only canonical tier returned
    result = _apply_visibility_filter(artifacts, "CANONICAL_ONLY", "canonical")
    assert len(result) == 1, f"Expected 1 canonical artifact, got {len(result)}"
    assert result[0]["scenario_tier"] == "canonical"

    # NONE filter: returns []
    result = _apply_visibility_filter(artifacts, "NONE", "canonical")
    assert result == []

    # ALL filter with tier='all': returns both
    result = _apply_visibility_filter(artifacts, "ALL", "all")
    assert len(result) == 2
