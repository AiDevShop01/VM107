"""Phase 91 Plan 3 Task 2 — MacroLiquidityMonitor tests.

NEW agent under agents/macro_liquidity_monitor/.

Contract:
  * compute_liquidity_score(substrate) → float 0..100 OR None when Phase 86
    substrate incomplete (status=experimental — no emit).
  * emit_for_score(score, components, prev_score=None) — calls
    emit_alert_candidate when score crosses 30 OR drops > 15 points in 24h.
    severity = 'blocking' (Critical) if score < 20, else 'warning' (Important).
  * Module-level MacroLiquidityMonitor agent_id = 'vm107.macro_liquidity_monitor'.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ── compute_liquidity_score ──────────────────────────────────────────────────


class TestComputeLiquidityScore:

    def test_full_substrate_returns_score_in_range(self):
        from agents.macro_liquidity_monitor.agent import MacroLiquidityMonitor

        substrate = {
            "credit_spreads_widened": False,
            "funding_stress_index": 0.20,
            "dxy_spike_24h": 0.10,
        }
        score = MacroLiquidityMonitor().compute_liquidity_score(substrate)
        assert isinstance(score, (int, float))
        assert 0 <= score <= 100

    def test_stress_substrate_returns_low_score(self):
        from agents.macro_liquidity_monitor.agent import MacroLiquidityMonitor

        substrate = {
            "credit_spreads_widened": True,
            "funding_stress_index": 0.78,
            "dxy_spike_24h": 1.2,
        }
        score = MacroLiquidityMonitor().compute_liquidity_score(substrate)
        assert score is not None
        # Stress conditions → low score
        assert score < 50

    def test_empty_substrate_returns_none(self):
        """status=experimental — incomplete substrate yields no score, no emit."""
        from agents.macro_liquidity_monitor.agent import MacroLiquidityMonitor

        score = MacroLiquidityMonitor().compute_liquidity_score({})
        assert score is None


# ── emit_for_score ───────────────────────────────────────────────────────────


class TestEmitForScore:

    def test_score_below_30_emits_warning(self):
        from agents.macro_liquidity_monitor.agent import MacroLiquidityMonitor

        captured = []

        def _fake(**kwargs):
            captured.append(kwargs)

        with patch(
            "agents.macro_liquidity_monitor.agent.emit_alert_candidate",
            side_effect=_fake,
        ):
            MacroLiquidityMonitor().emit_for_score(
                score=22,
                components={"credit_spreads_widened": True},
                prev_score=45,
            )

        assert len(captured) == 1
        env = captured[0]
        assert env["alert_type"] == "liquidity"
        assert env["subject_id"] == "global_liquidity_score"
        # Score < 20 = blocking; score 22 between 20 and 30 = warning
        assert env["b13_internal_severity"] == "warning"
        assert env["extra_payload"]["liquidity_score"] == 22
        assert env["extra_payload"]["prev_liquidity_score"] == 45

    def test_score_below_20_emits_blocking_critical(self):
        from agents.macro_liquidity_monitor.agent import MacroLiquidityMonitor

        captured = []

        def _fake(**kwargs):
            captured.append(kwargs)

        with patch(
            "agents.macro_liquidity_monitor.agent.emit_alert_candidate",
            side_effect=_fake,
        ):
            MacroLiquidityMonitor().emit_for_score(
                score=15,
                components={"credit_spreads_widened": True, "funding_stress_index": 0.9},
                prev_score=40,
            )

        assert len(captured) == 1
        env = captured[0]
        assert env["b13_internal_severity"] == "blocking"

    def test_score_above_30_does_not_emit_when_no_drop(self):
        """Above threshold + no >15pt drop → no emit (avoid alert spam)."""
        from agents.macro_liquidity_monitor.agent import MacroLiquidityMonitor

        captured = []

        def _fake(**kwargs):
            captured.append(kwargs)

        with patch(
            "agents.macro_liquidity_monitor.agent.emit_alert_candidate",
            side_effect=_fake,
        ):
            MacroLiquidityMonitor().emit_for_score(
                score=80, components={}, prev_score=82,
            )

        assert captured == []

    def test_large_24h_drop_emits_even_when_above_threshold(self):
        """Drop > 15 points in 24h fires even when current score > 30."""
        from agents.macro_liquidity_monitor.agent import MacroLiquidityMonitor

        captured = []

        def _fake(**kwargs):
            captured.append(kwargs)

        with patch(
            "agents.macro_liquidity_monitor.agent.emit_alert_candidate",
            side_effect=_fake,
        ):
            MacroLiquidityMonitor().emit_for_score(
                score=50, components={}, prev_score=70,  # 20pt drop
            )

        assert len(captured) == 1


# ── Compute-then-emit integration ───────────────────────────────────────────


class TestRunOnce:

    def test_run_once_skips_emit_on_incomplete_substrate(self):
        from agents.macro_liquidity_monitor.agent import MacroLiquidityMonitor

        captured = []

        def _fake(**kwargs):
            captured.append(kwargs)

        with patch(
            "agents.macro_liquidity_monitor.agent.emit_alert_candidate",
            side_effect=_fake,
        ):
            result = MacroLiquidityMonitor().run_once(substrate={}, prev_score=40)

        # No emit when score is None
        assert captured == []
        assert result["score"] is None
        assert result["emitted"] is False

    def test_run_once_emits_on_stress(self):
        from agents.macro_liquidity_monitor.agent import MacroLiquidityMonitor

        captured = []

        def _fake(**kwargs):
            captured.append(kwargs)

        with patch(
            "agents.macro_liquidity_monitor.agent.emit_alert_candidate",
            side_effect=_fake,
        ):
            result = MacroLiquidityMonitor().run_once(
                substrate={
                    "credit_spreads_widened": True,
                    "funding_stress_index": 0.8,
                    "dxy_spike_24h": 1.2,
                },
                prev_score=50,
            )

        assert result["emitted"] is True
        assert result["score"] is not None
        assert len(captured) == 1
