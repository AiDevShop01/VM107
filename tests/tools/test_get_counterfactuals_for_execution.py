"""Phase 61-01 Task 5 — test_get_counterfactuals_for_execution.py

Tests for get_counterfactuals_for_execution VM107 tool.
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

from helpers.counterfactual_reader import _apply_visibility_filter, get_counterfactuals_for_execution


def test_canonical_only_filter():
    """Experimental-tier scenarios NOT returned when scope=CANONICAL_ONLY."""
    artifacts = [
        {"scenario_id": "counterfactual.stop.atr_1_0", "scenario_tier": "canonical", "truth_mode": "COUNTERFACTUAL"},
        {"scenario_id": "counterfactual.entry.vwap_cross", "scenario_tier": "experimental", "truth_mode": "COUNTERFACTUAL"},
    ]

    result = _apply_visibility_filter(artifacts, "CANONICAL_ONLY", "all")
    # Experimental scenarios must NOT appear in CANONICAL_ONLY regardless of tier param
    assert all(a["scenario_tier"] == "canonical" for a in result), (
        f"Experimental scenario leaked through CANONICAL_ONLY filter: {result}"
    )
    assert len(result) == 1


def test_none_scope_returns_empty():
    """Returns [] when counterfactual_visibility=NONE."""
    # Fast-path: no network call, returns [] immediately
    with patch.dict("os.environ", {"VM100_INTERNAL_API_URL": "http://vm100-mock:8000"}):
        result = get_counterfactuals_for_execution(
            "00000000-0000-0000-0000-000000000001",
            counterfactual_visibility="NONE",
        )
        assert result == [], f"Expected [] for NONE visibility, got {result!r}"


def test_tier_canonical_default():
    """Default tier='canonical' returns only canonical-tier artifacts."""
    artifacts = [
        {"scenario_id": "counterfactual.stop.atr_1_0", "scenario_tier": "canonical", "truth_mode": "COUNTERFACTUAL"},
        {"scenario_id": "counterfactual.stop.atr_1_5", "scenario_tier": "canonical", "truth_mode": "COUNTERFACTUAL"},
        {"scenario_id": "counterfactual.entry.alt_zone", "scenario_tier": "experimental", "truth_mode": "COUNTERFACTUAL"},
    ]

    # Default tier='canonical' in ALL visibility
    result = _apply_visibility_filter(artifacts, "ALL", "canonical")
    assert len(result) == 2, f"Expected 2 canonical artifacts, got {len(result)}"
    assert all(a["scenario_tier"] == "canonical" for a in result)
