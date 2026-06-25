"""Phase 91 Plan 3 Task 2 — alert_emit_hook tests.

Wraps existing macro_regime_monitor and macro_relationship_discovery
emit points; asserts envelope shape includes event_id stability.

Hook contract:
  * emit_regime_change_alert(transition: dict) — sidecar called from
    MacroRegimeMonitor's run_once after regime_transition_detected emit.
    Envelope: alert_type='regime', subject_id=transition['regime_dimension'],
    severity='RegimeChange' / b13='blocking',
    payload={new_regime, prev_regime, confidence, top_3_indicators}.
  * emit_discovery_alert(proposal: dict) — sidecar called from
    MacroRelationshipDiscovery after EdgeProposer.propose acceptance.
    Envelope: alert_type='discovery', subject_id=proposal['proposal_id'],
    severity='Info' / b13='info' (LD-91-8 always-emit-info pattern),
    payload={discovery_text, agent_confidence, source_indicators, source_assets,
    edge_proposal_id}.
  * Additionally emit_correlation_break_alert for the correlation breakdown
    stub case (Phase 86 dedicated agent absent — interim emit point inside
    macro_relationship_discovery's correlation analysis path).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


@pytest.fixture
def regime_transition():
    return {
        "regime_dimension": "inflation",
        "new_regime": "accelerating",
        "prev_regime": "disinflation",
        "confidence": 0.82,
        "top_3_indicators": ["CPIAUCSL", "PAYEMS", "PPIACO"],
        "belief_store_ref": "vm107://belief_store/regime_transition/abc123",
        "transition_timestamp": "2026-06-25T14:30:00+00:00",
    }


@pytest.fixture
def edge_proposal():
    return {
        "proposal_id": "edge_proposal_id_abc",
        "discovery_text": "Silver decoupling from Gold (r=-0.12 vs 3yr avg 0.78)",
        "agent_confidence": 0.71,
        "source_indicators": [],
        "source_assets": ["XAGUSD", "XAUUSD"],
        "from_node": "XAGUSD",
        "to_node": "XAUUSD",
    }


@pytest.fixture
def correlation_breakdown():
    return {
        "asset_pair": "DXY-Gold",
        "correlation_30d": -0.20,
        "prev_correlation_30d": -0.80,
        "n_observations": 60,
        "delta_abs": 0.60,
        "explanation": "DXY-Gold correlation breakdown",
    }


# ── emit_regime_change_alert ─────────────────────────────────────────────────


class TestEmitRegimeChangeAlert:

    def test_envelope_has_alert_type_regime_and_blocking_b13(self, regime_transition):
        from agents.macro_regime_monitor.alert_emit_hook import emit_regime_change_alert

        captured = []

        def _fake(**kwargs):
            captured.append(kwargs)

        with patch(
            "agents.macro_regime_monitor.alert_emit_hook.emit_alert_candidate",
            side_effect=_fake,
        ):
            emit_regime_change_alert(regime_transition)

        assert len(captured) == 1
        env = captured[0]
        assert env["alert_type"] == "regime"
        assert env["subject_id"] == "inflation"
        assert env["subject_type"] == "regime"
        assert env["b13_internal_severity"] == "blocking"
        assert env["producer_agent_id"] == "vm107.macro_regime_monitor"
        # payload through extra_payload
        payload = env["extra_payload"]
        assert payload["new_regime"] == "accelerating"
        assert payload["prev_regime"] == "disinflation"
        assert payload["confidence"] == pytest.approx(0.82)

    def test_event_id_stable_across_replays(self, regime_transition):
        from agents.macro_regime_monitor.alert_emit_hook import emit_regime_change_alert

        captured = []

        def _fake(**kwargs):
            captured.append(kwargs)

        with patch(
            "agents.macro_regime_monitor.alert_emit_hook.emit_alert_candidate",
            side_effect=_fake,
        ):
            emit_regime_change_alert(regime_transition)
            emit_regime_change_alert(regime_transition)

        assert captured[0]["event_id"] == captured[1]["event_id"], (
            "Same transition → same event_id (sha256 of producer|subject|new|ts)"
        )
        assert len(captured[0]["event_id"]) >= 16


# ── emit_discovery_alert ─────────────────────────────────────────────────────


class TestEmitDiscoveryAlert:

    def test_envelope_has_alert_type_discovery_and_info_severity(self, edge_proposal):
        from agents.macro_relationship_discovery.alert_emit_hook import (
            emit_discovery_alert,
        )

        captured = []

        def _fake(**kwargs):
            captured.append(kwargs)

        with patch(
            "agents.macro_relationship_discovery.alert_emit_hook.emit_alert_candidate",
            side_effect=_fake,
        ):
            emit_discovery_alert(edge_proposal)

        env = captured[0]
        assert env["alert_type"] == "discovery"
        assert env["subject_id"] == "edge_proposal_id_abc"
        assert env["b13_internal_severity"] == "info"
        assert env["producer_agent_id"] == "vm107.macro_relationship_discovery"
        payload = env["extra_payload"]
        assert payload["discovery_text"].startswith("Silver decoupling")
        assert payload["agent_confidence"] == pytest.approx(0.71)
        assert payload["edge_proposal_id"] == "edge_proposal_id_abc"


# ── emit_correlation_break_alert (stub for Phase 86) ─────────────────────────


class TestEmitCorrelationBreakAlert:

    def test_envelope_has_alert_type_correlation_and_warning(self, correlation_breakdown):
        from agents.macro_relationship_discovery.alert_emit_hook import (
            emit_correlation_break_alert,
        )

        captured = []

        def _fake(**kwargs):
            captured.append(kwargs)

        with patch(
            "agents.macro_relationship_discovery.alert_emit_hook.emit_alert_candidate",
            side_effect=_fake,
        ):
            emit_correlation_break_alert(correlation_breakdown)

        env = captured[0]
        assert env["alert_type"] == "correlation"
        assert env["subject_id"] == "DXY-Gold"
        assert env["b13_internal_severity"] == "warning"
        payload = env["extra_payload"]
        assert payload["correlation_30d"] == pytest.approx(-0.20)
        assert payload["prev_correlation_30d"] == pytest.approx(-0.80)
        assert payload["n_observations"] == 60
