"""Phase 91 Plan 2 Task 2 — MacroIndicatorAlertEmitter tests.

Asserts the emitter:
  - Fires the correct default condition tiers per Tier-1 indicator
  - Sends b13_internal_severity matching the condition tier
  - Generates stable event_ids keyed on (indicator_id, release_date, condition_id)
  - Always emits the info-tier "release_landed" envelope per release
  - Forwards FRED payload sub-dict to VM100 via extra_payload
  - Skips emission when indicator_id is missing
  - Handles emit failures without crashing
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def cpi_release_above_4():
    """CPI release that fires the 'cpi_gt_4' + 'release_landed' tiers."""
    return {
        "indicator_id": "CPIAUCSL",
        "release_date": "2026-06-25",
        "value": 4.2,
        "prev_value": 3.8,
        "consensus": 3.9,
        "history_30y": [
            1.5, 1.8, 2.0, 2.1, 2.2, 2.3, 2.3, 2.4, 2.5, 2.5,
            2.6, 2.6, 2.7, 2.7, 2.8, 2.8, 2.9, 3.0, 3.0, 3.1,
            3.1, 3.2, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.0,
        ],
    }


@pytest.fixture
def cpi_release_critical_above_5():
    """CPI release that fires cpi_gt_4 (warning) + cpi_gt_5 (blocking) + info."""
    return {
        "indicator_id": "CPIAUCSL",
        "release_date": "2026-06-25",
        "value": 5.5,
        "prev_value": 4.8,
        "consensus": 4.5,
        "history_30y": [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
    }


@pytest.fixture
def nfp_release_strong():
    """NFP release that fires nfp_gt_250k + info."""
    return {
        "indicator_id": "PAYEMS",
        "release_date": "2026-06-06",
        "value": 275000,
        "prev_value": 220000,
        "consensus": 250000,
    }


@pytest.fixture
def unrate_crosses_above_4():
    """UNRATE release that fires unrate_crosses_above_4 + info."""
    return {
        "indicator_id": "UNRATE",
        "release_date": "2026-06-06",
        "value": 4.1,
        "prev_value": 3.9,
        "consensus": 4.0,
    }


@pytest.fixture
def quiet_cpi_release():
    """CPI release with no threshold breach — only info-tier should fire."""
    return {
        "indicator_id": "CPIAUCSL",
        "release_date": "2026-06-25",
        "value": 3.2,
        "prev_value": 3.1,
        "consensus": 3.2,
    }


@pytest.fixture
def mock_emit_alert_candidate():
    """Patch emit_alert_candidate where the agent imports it; capture call args."""
    captured: list[dict] = []

    def _fake_emit(**kwargs):
        captured.append(dict(kwargs))

    with patch(
        "agents.macro_indicator_alert_emitter.agent.emit_alert_candidate",
        side_effect=_fake_emit,
    ) as p:
        p.captured = captured  # type: ignore[attr-defined]
        yield p


# ── Tier matching ────────────────────────────────────────────────────────────

class TestTierMatching:

    def test_cpi_above_4_fires_warning_tier_plus_info(
        self, cpi_release_above_4, mock_emit_alert_candidate
    ):
        from agents.macro_indicator_alert_emitter import MacroIndicatorAlertEmitter

        result = MacroIndicatorAlertEmitter().emit_for_release(cpi_release_above_4)

        assert result["indicator_id"] == "CPIAUCSL"
        assert "cpi_gt_4" in result["matched_condition_ids"]
        assert "release_landed" in result["matched_condition_ids"]
        # value 4.2 doesn't cross 5
        assert "cpi_gt_5" not in result["matched_condition_ids"]
        assert result["emitted_count"] == len(result["matched_condition_ids"])

        # Severity tiers respected
        emits = mock_emit_alert_candidate.captured
        cpi_gt_4 = next(e for e in emits if e["explanation"].startswith("CPI 4.20%"))
        assert cpi_gt_4["b13_internal_severity"] == "warning"
        assert cpi_gt_4["alert_type"] == "macro_indicator"
        assert cpi_gt_4["subject_id"] == "CPIAUCSL"

    def test_cpi_above_5_fires_critical_blocking_tier(
        self, cpi_release_critical_above_5, mock_emit_alert_candidate
    ):
        from agents.macro_indicator_alert_emitter import MacroIndicatorAlertEmitter

        result = MacroIndicatorAlertEmitter().emit_for_release(cpi_release_critical_above_5)

        assert "cpi_gt_4" in result["matched_condition_ids"]
        assert "cpi_gt_5" in result["matched_condition_ids"]
        # Also surprise: (5.5 - 4.5) / 4.5 = 0.222 < 0.3 → no surprise tier
        assert "cpi_surprise_0_3" not in result["matched_condition_ids"]

        emits = mock_emit_alert_candidate.captured
        critical = next(e for e in emits if "CRITICAL" in e["explanation"])
        assert critical["b13_internal_severity"] == "blocking"

    def test_nfp_strong_print_fires_nfp_gt_250k(
        self, nfp_release_strong, mock_emit_alert_candidate
    ):
        from agents.macro_indicator_alert_emitter import MacroIndicatorAlertEmitter

        result = MacroIndicatorAlertEmitter().emit_for_release(nfp_release_strong)

        assert result["indicator_id"] == "PAYEMS"
        assert "nfp_gt_250k" in result["matched_condition_ids"]
        # 275000 not below 100000
        assert "nfp_lt_100k" not in result["matched_condition_ids"]
        # surprise = (275000 - 250000) / 250000 = 0.1 < 0.5
        assert "nfp_surprise_0_5" not in result["matched_condition_ids"]

    def test_unrate_crosses_above_4_fires_only_when_prev_below(
        self, unrate_crosses_above_4, mock_emit_alert_candidate
    ):
        from agents.macro_indicator_alert_emitter import MacroIndicatorAlertEmitter

        result = MacroIndicatorAlertEmitter().emit_for_release(unrate_crosses_above_4)

        assert "unrate_crosses_above_4" in result["matched_condition_ids"]
        # 4.1 not > 5
        assert "unrate_gt_5" not in result["matched_condition_ids"]

    def test_quiet_release_emits_only_info_tier(
        self, quiet_cpi_release, mock_emit_alert_candidate
    ):
        from agents.macro_indicator_alert_emitter import MacroIndicatorAlertEmitter

        result = MacroIndicatorAlertEmitter().emit_for_release(quiet_cpi_release)

        # No default tier fires; only info-tier
        assert result["matched_condition_ids"] == ["release_landed"]
        assert result["emitted_count"] == 1
        emits = mock_emit_alert_candidate.captured
        assert len(emits) == 1
        assert emits[0]["b13_internal_severity"] == "info"


# ── Idempotency / event_id stability ─────────────────────────────────────────

class TestEventIdStability:

    def test_event_id_stable_across_replays(
        self, cpi_release_above_4, mock_emit_alert_candidate
    ):
        """Re-emitting the same (indicator, release_date, condition) produces same event_id."""
        from agents.macro_indicator_alert_emitter import MacroIndicatorAlertEmitter

        emitter = MacroIndicatorAlertEmitter()
        emitter.emit_for_release(cpi_release_above_4)
        first_run = list(mock_emit_alert_candidate.captured)
        mock_emit_alert_candidate.captured.clear()
        emitter.emit_for_release(cpi_release_above_4)
        second_run = list(mock_emit_alert_candidate.captured)

        first_ids = {(e["explanation"], e["event_id"]) for e in first_run}
        second_ids = {(e["explanation"], e["event_id"]) for e in second_run}
        assert first_ids == second_ids, (
            "Replays must produce identical event_ids — sha256(indicator|date|condition)[:16]"
        )

    def test_event_id_differs_per_condition_tier(
        self, cpi_release_critical_above_5, mock_emit_alert_candidate
    ):
        from agents.macro_indicator_alert_emitter import MacroIndicatorAlertEmitter

        MacroIndicatorAlertEmitter().emit_for_release(cpi_release_critical_above_5)

        ids = [e["event_id"] for e in mock_emit_alert_candidate.captured]
        # All distinct — one event_id per fired condition
        assert len(set(ids)) == len(ids), (
            f"Expected unique event_ids per tier — got duplicates: {ids}"
        )
        # All 16-char hex (sha256 truncation)
        for ev_id in ids:
            assert len(ev_id) == 16
            int(ev_id, 16)  # Raises ValueError if not hex


# ── Payload propagation ──────────────────────────────────────────────────────

class TestPayloadPropagation:

    def test_extra_payload_includes_fred_release_fields(
        self, cpi_release_above_4, mock_emit_alert_candidate
    ):
        """extra_payload sub-dict carries value / prev_value / consensus / history_30y."""
        from agents.macro_indicator_alert_emitter import MacroIndicatorAlertEmitter

        MacroIndicatorAlertEmitter().emit_for_release(cpi_release_above_4)

        emits = mock_emit_alert_candidate.captured
        assert len(emits) > 0
        for e in emits:
            payload = e["extra_payload"]
            assert payload["indicator_id"] == "CPIAUCSL"
            assert payload["value"] == 4.2
            assert payload["prev_value"] == 3.8
            assert payload["consensus"] == 3.9
            assert isinstance(payload["history_30y"], list)
            assert payload["history_30y"][0] == 1.5
            assert "condition_id" in payload

    def test_citation_uses_fred_grammar(
        self, cpi_release_above_4, mock_emit_alert_candidate
    ):
        from agents.macro_indicator_alert_emitter import MacroIndicatorAlertEmitter

        MacroIndicatorAlertEmitter().emit_for_release(cpi_release_above_4)

        emits = mock_emit_alert_candidate.captured
        for e in emits:
            assert e["citations"] == ["fred://CPIAUCSL/2026-06-25"]


# ── Defensive paths ──────────────────────────────────────────────────────────

class TestDefensivePaths:

    def test_missing_indicator_id_returns_skip(self, mock_emit_alert_candidate):
        from agents.macro_indicator_alert_emitter import MacroIndicatorAlertEmitter

        result = MacroIndicatorAlertEmitter().emit_for_release({"value": 4.2})

        assert result["skipped_no_indicator"] is True
        assert result["emitted_count"] == 0
        assert mock_emit_alert_candidate.captured == []

    def test_unknown_indicator_only_emits_info_tier(self, mock_emit_alert_candidate):
        """Indicator not in INDICATOR_DEFAULT_CONDITIONS still gets info-tier emit."""
        from agents.macro_indicator_alert_emitter import MacroIndicatorAlertEmitter

        result = MacroIndicatorAlertEmitter().emit_for_release({
            "indicator_id": "GS10",
            "release_date": "2026-06-25",
            "value": 4.5,
        })

        assert result["matched_condition_ids"] == ["release_landed"]
        assert mock_emit_alert_candidate.captured[0]["subject_id"] == "GS10"

    def test_emit_failure_does_not_crash_other_tiers(
        self, cpi_release_critical_above_5,
    ):
        """If one emit raises, the loop continues for remaining tiers."""
        from agents.macro_indicator_alert_emitter import MacroIndicatorAlertEmitter

        call_count = {"n": 0}

        def _fake_emit(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated transient emit failure")

        with patch(
            "agents.macro_indicator_alert_emitter.agent.emit_alert_candidate",
            side_effect=_fake_emit,
        ):
            # Should not raise
            result = MacroIndicatorAlertEmitter().emit_for_release(cpi_release_critical_above_5)

        # First tier failed → not in matched, but others continued
        assert call_count["n"] >= 2
        # At least one tier emitted successfully
        assert len(result["matched_condition_ids"]) >= 1


# ── Module-level shim ────────────────────────────────────────────────────────

def test_module_level_emit_for_release_shim(
    cpi_release_above_4, mock_emit_alert_candidate
):
    from agents.macro_indicator_alert_emitter import emit_for_release

    result = emit_for_release(cpi_release_above_4)
    assert result["emitted_count"] >= 1
    assert len(mock_emit_alert_candidate.captured) >= 1


# ── Conditions catalog sanity ────────────────────────────────────────────────

def test_conditions_catalog_covers_all_5_tier1_indicators():
    from agents.macro_indicator_alert_emitter.conditions import INDICATOR_DEFAULT_CONDITIONS

    expected = {"CPIAUCSL", "PAYEMS", "UNRATE", "FEDFUNDS", "PPIACO"}
    assert set(INDICATOR_DEFAULT_CONDITIONS.keys()) == expected, (
        f"Plan 2 must cover all 5 Tier-1 indicators. Got: {sorted(INDICATOR_DEFAULT_CONDITIONS.keys())}"
    )


def test_each_condition_has_unique_id_per_indicator():
    """Per-condition event_id uses condition['id'] — duplicates would collide event_ids."""
    from agents.macro_indicator_alert_emitter.conditions import INDICATOR_DEFAULT_CONDITIONS

    for indicator_id, conditions in INDICATOR_DEFAULT_CONDITIONS.items():
        ids = [c["id"] for c in conditions]
        assert len(set(ids)) == len(ids), (
            f"Duplicate condition id in {indicator_id}: {ids}"
        )


def test_each_condition_has_required_keys():
    from agents.macro_indicator_alert_emitter.conditions import INDICATOR_DEFAULT_CONDITIONS

    required = {"id", "expr", "severity", "template"}
    valid_severities = {"info", "warning", "blocking"}
    for indicator_id, conditions in INDICATOR_DEFAULT_CONDITIONS.items():
        for c in conditions:
            missing = required - set(c.keys())
            assert not missing, f"{indicator_id}/{c.get('id')} missing keys: {missing}"
            assert c["severity"] in valid_severities, (
                f"{indicator_id}/{c['id']} has invalid B13 severity: {c['severity']}"
            )
