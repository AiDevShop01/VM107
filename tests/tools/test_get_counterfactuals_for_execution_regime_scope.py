"""Phase 61-04 Task 3 — test_get_counterfactuals_for_execution_regime_scope.py

Scope-filter verification for regime-gate counterfactual scenarios (RG-8).

Tests:
  - CANONICAL_ONLY scope: regime-gate artifacts visible (they are canonical-tier)
  - NONE scope: regime-gate artifacts blocked
  - Cumulative tier filter: canonical filter returns 12 artifacts (5 stop + 4 exit + 3 regime)
  - Regime artifacts interleaved with stop/exit: filter still canonical-only-preserving
  - Phase 61 backward-compat: stop/exit visibility unaffected by regime tier addition (RG-3)

RG-8 coverage (scope visibility for non-participation regime-gate artifacts).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from helpers.counterfactual_reader import _apply_visibility_filter, get_counterfactuals_for_execution


# ---------------------------------------------------------------------------
# Synthetic artifact factory
# ---------------------------------------------------------------------------


def _regime_artifact(scenario_id: str, outcome_class: str = "non_participation") -> dict:
    """Build a minimal regime-gate counterfactual artifact dict for filter testing."""
    return {
        "scenario_id": scenario_id,
        "scenario_tier": "canonical",
        "truth_mode": "COUNTERFACTUAL",
        "divergence_type": "PRE_ENTRY",
        "hypothetical_r": "0.00",  # non-participation → 0 R
        "explanation_summary": {
            "policy_outcome_class": outcome_class,
            "gate_fired": outcome_class == "non_participation",
        },
    }


def _stop_artifact(scenario_id: str) -> dict:
    """Build a minimal stop counterfactual artifact dict for filter testing."""
    return {
        "scenario_id": scenario_id,
        "scenario_tier": "canonical",
        "truth_mode": "COUNTERFACTUAL",
        "divergence_type": "MID_TRADE",
        "hypothetical_r": "1.20",
    }


def _exit_artifact(scenario_id: str) -> dict:
    """Build a minimal exit counterfactual artifact dict for filter testing."""
    return {
        "scenario_id": scenario_id,
        "scenario_tier": "canonical",
        "truth_mode": "COUNTERFACTUAL",
        "divergence_type": "EXIT_TIME",
        "hypothetical_r": "2.40",
    }


def _experimental_artifact(scenario_id: str) -> dict:
    """Build an experimental-tier artifact (should be blocked by CANONICAL_ONLY)."""
    return {
        "scenario_id": scenario_id,
        "scenario_tier": "experimental",
        "truth_mode": "COUNTERFACTUAL",
        "divergence_type": "PRE_ENTRY",
        "hypothetical_r": "1.00",
    }


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_FIVE_STOP_ARTIFACTS = [
    _stop_artifact("counterfactual.stop.atr_0_5"),
    _stop_artifact("counterfactual.stop.atr_1_0"),
    _stop_artifact("counterfactual.stop.atr_1_5"),
    _stop_artifact("counterfactual.stop.liquidity_buffer"),
    _stop_artifact("counterfactual.stop.session_range"),
]

_FOUR_EXIT_ARTIFACTS = [
    _exit_artifact("counterfactual.exit.partial_1r"),
    _exit_artifact("counterfactual.exit.be_after_1r"),
    _exit_artifact("counterfactual.exit.trailing_atr"),
    _exit_artifact("counterfactual.exit.mfe_aware_trail"),
]

_THREE_REGIME_ARTIFACTS = [
    _regime_artifact("counterfactual.regime.skip_low_vol", "non_participation"),
    _regime_artifact("counterfactual.regime.skip_countertrend", "gate_did_not_fire"),
    _regime_artifact("counterfactual.regime.avoid_news_window", "non_participation"),
]

_ALL_TWELVE_CANONICAL_ARTIFACTS = (
    _FIVE_STOP_ARTIFACTS + _FOUR_EXIT_ARTIFACTS + _THREE_REGIME_ARTIFACTS
)


# ---------------------------------------------------------------------------
# CANONICAL_ONLY scope tests
# ---------------------------------------------------------------------------


def test_canonical_only_scope_sees_regime_artifacts():
    """CANONICAL_ONLY scope: regime-gate artifacts (canonical-tier) ARE visible (RG-8)."""
    result = _apply_visibility_filter(_ALL_TWELVE_CANONICAL_ARTIFACTS, "CANONICAL_ONLY", "all")

    regime_in_result = [a for a in result if a["scenario_id"].startswith("counterfactual.regime.")]
    assert len(regime_in_result) == 3, (
        f"Expected 3 regime artifacts in CANONICAL_ONLY result, got {len(regime_in_result)}: "
        f"{[a['scenario_id'] for a in regime_in_result]}"
    )


def test_canonical_only_scope_returns_all_twelve_canonical():
    """CANONICAL_ONLY scope: all 12 canonical artifacts visible (5 stop + 4 exit + 3 regime)."""
    result = _apply_visibility_filter(_ALL_TWELVE_CANONICAL_ARTIFACTS, "CANONICAL_ONLY", "all")
    assert len(result) == 12, (
        f"Expected 12 canonical artifacts in CANONICAL_ONLY result, got {len(result)}"
    )


def test_canonical_only_blocks_experimental_even_with_regime():
    """CANONICAL_ONLY scope: experimental-tier blocked even when regime artifacts present (RG-8)."""
    mixed_artifacts = _ALL_TWELVE_CANONICAL_ARTIFACTS + [
        _experimental_artifact("counterfactual.regime.experimental_gate_v2"),
    ]
    result = _apply_visibility_filter(mixed_artifacts, "CANONICAL_ONLY", "all")

    experimental_leaked = [a for a in result if a["scenario_tier"] == "experimental"]
    assert len(experimental_leaked) == 0, (
        f"Experimental scenario leaked through CANONICAL_ONLY filter: "
        f"{[a['scenario_id'] for a in experimental_leaked]}"
    )
    # All 12 canonical still present
    assert len(result) == 12, (
        f"Expected 12 canonical artifacts, got {len(result)}"
    )


def test_tier_canonical_filter_returns_3_regime_plus_5_stop_plus_4_exit():
    """tier='canonical' filter in ALL visibility confirms 12 total canonical (cumulative)."""
    result = _apply_visibility_filter(_ALL_TWELVE_CANONICAL_ARTIFACTS, "ALL", "canonical")

    assert len(result) == 12, (
        f"Expected 12 artifacts with tier='canonical', got {len(result)}"
    )
    stop_count = sum(1 for a in result if a["scenario_id"].startswith("counterfactual.stop."))
    exit_count = sum(1 for a in result if a["scenario_id"].startswith("counterfactual.exit."))
    regime_count = sum(1 for a in result if a["scenario_id"].startswith("counterfactual.regime."))

    assert stop_count == 5, f"Expected 5 stop artifacts, got {stop_count}"
    assert exit_count == 4, f"Expected 4 exit artifacts, got {exit_count}"
    assert regime_count == 3, f"Expected 3 regime artifacts, got {regime_count}"


# ---------------------------------------------------------------------------
# NONE scope tests
# ---------------------------------------------------------------------------


def test_none_scope_blocks_regime_artifacts():
    """NONE scope: regime-gate artifacts (canonical) are blocked (RG-8)."""
    with patch.dict("os.environ", {"VM100_INTERNAL_API_URL": "http://vm100-mock:8000"}):
        result = get_counterfactuals_for_execution(
            "00000000-0000-0000-0000-000000000002",
            counterfactual_visibility="NONE",
        )
    assert result == [], (
        f"Expected [] for NONE visibility (all artifacts blocked), got {result!r}"
    )


def test_none_scope_returns_empty_regardless_of_regime_tier():
    """NONE visibility returns [] — regime artifacts do not bypass NONE filter."""
    # The fast-path for NONE does not make an API call and returns [] immediately.
    # This test verifies the fast-path is not bypassed by non-participation semantics.
    with patch.dict("os.environ", {"VM100_INTERNAL_API_URL": "http://vm100-mock:8000"}):
        result = get_counterfactuals_for_execution(
            "00000000-0000-0000-0000-000000000003",
            counterfactual_visibility="NONE",
        )
    assert result == [], f"NONE scope must return [] always, got {result!r}"


# ---------------------------------------------------------------------------
# Backward-compat: stop + exit visibility unaffected by regime addition (RG-3)
# ---------------------------------------------------------------------------


def test_stop_artifacts_visible_in_canonical_only_after_regime_addition():
    """Stop artifacts still visible in CANONICAL_ONLY scope after adding regime artifacts (RG-3)."""
    result = _apply_visibility_filter(_ALL_TWELVE_CANONICAL_ARTIFACTS, "CANONICAL_ONLY", "all")
    stop_in_result = [a for a in result if a["scenario_id"].startswith("counterfactual.stop.")]
    assert len(stop_in_result) == 5, (
        f"Stop artifacts should not be affected by regime additions. "
        f"Expected 5, got {len(stop_in_result)}: {[a['scenario_id'] for a in stop_in_result]}"
    )


def test_exit_artifacts_visible_in_canonical_only_after_regime_addition():
    """Exit artifacts still visible in CANONICAL_ONLY scope after adding regime artifacts (RG-3)."""
    result = _apply_visibility_filter(_ALL_TWELVE_CANONICAL_ARTIFACTS, "CANONICAL_ONLY", "all")
    exit_in_result = [a for a in result if a["scenario_id"].startswith("counterfactual.exit.")]
    assert len(exit_in_result) == 4, (
        f"Exit artifacts should not be affected by regime additions. "
        f"Expected 4, got {len(exit_in_result)}: {[a['scenario_id'] for a in exit_in_result]}"
    )


# ---------------------------------------------------------------------------
# Non-participation semantics: gate_did_not_fire artifacts still visible
# ---------------------------------------------------------------------------


def test_gate_did_not_fire_artifacts_visible_in_canonical_only():
    """Regime artifact with gate_did_not_fire outcome is still canonical-tier → visible (RG-8).

    A gate-did-not-fire artifact does NOT mean "no artifact" — it means the artifact
    records that the regime filter was evaluated but did NOT block entry. This is a
    distinct semantic from non-participation; both are canonical-tier.
    """
    gate_not_fired = _regime_artifact(
        "counterfactual.regime.skip_low_vol", outcome_class="gate_did_not_fire"
    )
    artifacts = [gate_not_fired]
    result = _apply_visibility_filter(artifacts, "CANONICAL_ONLY", "all")
    assert len(result) == 1, (
        f"gate_did_not_fire regime artifact should be visible in CANONICAL_ONLY. "
        f"Got {len(result)} artifacts."
    )
    assert result[0]["scenario_id"] == "counterfactual.regime.skip_low_vol"


def test_non_participation_artifacts_visible_separately_from_gate_did_not_fire():
    """Both non_participation and gate_did_not_fire outcomes appear in CANONICAL_ONLY (RG-8).

    Two regime artifacts for the same scenario (gate fired for one execution, not for another)
    must both pass the visibility filter independently.
    """
    artifacts = [
        _regime_artifact("counterfactual.regime.skip_low_vol", "non_participation"),
        _regime_artifact("counterfactual.regime.skip_low_vol", "gate_did_not_fire"),
    ]
    result = _apply_visibility_filter(artifacts, "CANONICAL_ONLY", "all")
    assert len(result) == 2, (
        f"Both non_participation and gate_did_not_fire should be visible in CANONICAL_ONLY. "
        f"Got {len(result)}: {result}"
    )
