"""Phase 61-02 Task 5 — test_get_counterfactuals_for_execution_live.py

Tests for get_counterfactuals_for_execution with the 5 canonical stop scenarios
now registered. Graduates from 61-01 stub tests to live response validation.

RG coverage: RG-2 (truth_mode=COUNTERFACTUAL in every response), RG-8 (scope filter).
Law #4: truth_mode='COUNTERFACTUAL' verified on every returned artifact.
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

from helpers.counterfactual_reader import (
    _apply_visibility_filter,
    get_counterfactuals_for_execution,
)


# ---------------------------------------------------------------------------
# Synthetic response fixture — 5 canonical stop artifacts
# ---------------------------------------------------------------------------

_FIVE_CANONICAL_ARTIFACTS = [
    {
        "counterfactual_id": f"cf-000{i}",
        "execution_id": "aaaabbbb-1111-2222-3333-444455556666",
        "scenario_id": scenario_id,
        "scenario_version": "1.0.0",
        "scenario_tier": "canonical",
        "truth_mode": "COUNTERFACTUAL",
        "hypothetical_r": 1.5 + i * 0.1,
        "as_traded_r": 1.75,
        "simulation_integrity": {
            "future_information_used": False,
            "optimization_performed": False,
        },
    }
    for i, scenario_id in enumerate(
        [
            "counterfactual.stop.atr_0_5",
            "counterfactual.stop.atr_1_0",
            "counterfactual.stop.atr_1_5",
            "counterfactual.stop.liquidity_buffer",
            "counterfactual.stop.session_range",
        ]
    )
]


# ---------------------------------------------------------------------------
# Test: returns 5 canonical stop artifacts
# ---------------------------------------------------------------------------


def test_returns_5_canonical_stop_artifacts():
    """With 5 artifacts returned by VM100, tool returns all 5 for CANONICAL_ONLY scope.

    Phase 61-02: all 5 stop scenario artifacts exist for this execution.
    """
    execution_id = "aaaabbbb-1111-2222-3333-444455556666"

    import httpx

    class _MockResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return _FIVE_CANONICAL_ARTIFACTS

    with patch.dict("os.environ", {"VM100_INTERNAL_API_URL": "http://vm100-mock:8000"}):
        with patch("httpx.get", return_value=_MockResponse()):
            result = get_counterfactuals_for_execution(
                execution_id,
                counterfactual_visibility="CANONICAL_ONLY",
                tier="canonical",
            )

    assert len(result) == 5, (
        f"Expected 5 canonical stop artifacts, got {len(result)}. "
        "Phase 61-02: all 5 stop scenarios should be present."
    )


def test_filters_to_canonical_when_scope_is_canonical_only():
    """CANONICAL_ONLY scope never returns experimental artifacts (RG-8)."""
    mixed_artifacts = _FIVE_CANONICAL_ARTIFACTS + [
        {
            "counterfactual_id": "cf-exp-001",
            "execution_id": "aaaabbbb-1111-2222-3333-444455556666",
            "scenario_id": "counterfactual.entry.vwap_cross",
            "scenario_version": "0.1.0",
            "scenario_tier": "experimental",
            "truth_mode": "COUNTERFACTUAL",
            "hypothetical_r": 0.5,
            "as_traded_r": 1.75,
        }
    ]

    class _MockResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return mixed_artifacts

    with patch.dict("os.environ", {"VM100_INTERNAL_API_URL": "http://vm100-mock:8000"}):
        with patch("httpx.get", return_value=_MockResponse()):
            result = get_counterfactuals_for_execution(
                "aaaabbbb-1111-2222-3333-444455556666",
                counterfactual_visibility="CANONICAL_ONLY",
                tier="all",
            )

    # Experimental scenario must never appear with CANONICAL_ONLY (RG-8)
    experimental = [a for a in result if a.get("scenario_tier") == "experimental"]
    assert not experimental, (
        f"CANONICAL_ONLY scope returned experimental artifacts: {experimental}. "
        "RG-8 scope filter must exclude experimental when CANONICAL_ONLY."
    )
    assert len(result) == 5, (
        f"Expected 5 canonical artifacts (1 experimental filtered out), got {len(result)}"
    )


def test_returns_empty_when_scope_is_none():
    """NONE visibility returns [] immediately without network call (fast-path)."""
    call_count = []

    with patch.dict("os.environ", {"VM100_INTERNAL_API_URL": "http://vm100-mock:8000"}):
        with patch("httpx.get", side_effect=lambda *a, **kw: call_count.append(1)):
            result = get_counterfactuals_for_execution(
                "aaaabbbb-1111-2222-3333-444455556666",
                counterfactual_visibility="NONE",
            )

    assert result == [], f"Expected [] for NONE visibility, got {result!r}"
    assert len(call_count) == 0, (
        f"NONE visibility should fast-path without network call. "
        f"httpx.get called {len(call_count)} time(s)."
    )


def test_artifact_response_carries_truth_mode_counterfactual():
    """All returned artifacts have truth_mode='COUNTERFACTUAL' (Law #4, RG-2).

    The reader MUST filter out any artifact lacking truth_mode=COUNTERFACTUAL.
    """
    # Mix: valid + one invalid (missing truth_mode=COUNTERFACTUAL)
    mixed_artifacts = _FIVE_CANONICAL_ARTIFACTS + [
        {
            "counterfactual_id": "cf-invalid-001",
            "execution_id": "aaaabbbb-1111-2222-3333-444455556666",
            "scenario_id": "counterfactual.stop.atr_1_0",
            "scenario_version": "0.9.0",
            "scenario_tier": "canonical",
            "truth_mode": "CANONICAL",  # Law #4 violation — reader must filter this out
            "hypothetical_r": 1.5,
            "as_traded_r": 1.75,
        }
    ]

    class _MockResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return mixed_artifacts

    with patch.dict("os.environ", {"VM100_INTERNAL_API_URL": "http://vm100-mock:8000"}):
        with patch("httpx.get", return_value=_MockResponse()):
            result = get_counterfactuals_for_execution(
                "aaaabbbb-1111-2222-3333-444455556666",
                counterfactual_visibility="CANONICAL_ONLY",
                tier="all",
            )

    # Law #4: ALL returned artifacts must have truth_mode=COUNTERFACTUAL
    for artifact in result:
        assert artifact.get("truth_mode") == "COUNTERFACTUAL", (
            f"Artifact {artifact.get('counterfactual_id')!r} has "
            f"truth_mode={artifact.get('truth_mode')!r}, expected 'COUNTERFACTUAL'. "
            "Law #4: CounterfactualReader must enforce truth_mode filter."
        )

    # The invalid artifact should have been filtered out
    invalid_ids = [
        a.get("counterfactual_id") for a in result if a.get("truth_mode") != "COUNTERFACTUAL"
    ]
    assert not invalid_ids, f"Invalid artifacts leaked through: {invalid_ids}"


def test_returns_empty_on_vm100_unavailable():
    """Returns [] when VM100 is unavailable (ToolError pattern — never raises, Pitfall 11)."""
    import httpx

    with patch.dict("os.environ", {"VM100_INTERNAL_API_URL": "http://vm100-down:8000"}):
        with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
            result = get_counterfactuals_for_execution(
                "aaaabbbb-1111-2222-3333-444455556666",
                counterfactual_visibility="CANONICAL_ONLY",
            )

    assert result == [], (
        f"Expected [] on VM100 unavailable (Pitfall 11 — never raises). Got: {result!r}"
    )


def test_simulation_integrity_no_future_information():
    """All artifacts carry simulation_integrity.future_information_used=False (Law #3)."""

    class _MockResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return _FIVE_CANONICAL_ARTIFACTS

    with patch.dict("os.environ", {"VM100_INTERNAL_API_URL": "http://vm100-mock:8000"}):
        with patch("httpx.get", return_value=_MockResponse()):
            result = get_counterfactuals_for_execution(
                "aaaabbbb-1111-2222-3333-444455556666",
                counterfactual_visibility="CANONICAL_ONLY",
            )

    for artifact in result:
        integrity = artifact.get("simulation_integrity", {})
        assert integrity.get("future_information_used") is False, (
            f"Artifact {artifact.get('scenario_id')!r} has "
            f"future_information_used={integrity.get('future_information_used')!r}, "
            "expected False (Law #3 — no future information)."
        )
