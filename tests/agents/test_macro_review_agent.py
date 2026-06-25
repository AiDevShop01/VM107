"""Phase 91 Plan 6 Task 2 — MacroReviewAgent tests.

Verifies the synchronous review entry point:
  - Findings synthesis combines payload + regime + correlations
  - Follow-up emits land as 'discovery' (NEVER 'liquidity'/'regime' — self-loop ban)
  - Degraded mode safe when Phase 87/89 clients unavailable
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any
from unittest.mock import patch

import pytest

_VM107_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


pytestmark = pytest.mark.phase91


# ── Findings synthesis ───────────────────────────────────────────────────────


def test_review_liquidity_critical_with_regime_accelerating_includes_pivot_signal():
    """Findings include 'potential macro pivot' when all three signals align."""
    from agents.macro_review_agent.agent import review_alert

    with patch(
        "agents.macro_review_agent.agent._cross_check_regime",
        return_value={"available": True, "regime": "accelerating_inflation", "accelerating": True},
    ), patch(
        "agents.macro_review_agent.agent._cross_check_correlations",
        return_value={"available": True, "correlation_breaks": ["DXY-Gold", "Oil-EURUSD"]},
    ), patch(
        "agents.macro_review_agent.agent.emit_alert_candidate",
        create=True,
    ) as mock_emit:
        result = review_alert(
            alert_trigger_id=42,
            alert_type="liquidity",
            severity="critical",
            subject_id="global_liquidity_score",
            payload={
                "liquidity_score": 22,
                "prev_liquidity_score": 65,
                "citations": ["https://fred.stlouisfed.org/series/BAMLH0A0HYM2"],
            },
            agent_chain_depth=1,
        )

    assert result["status"] == "ok"
    assert "potential macro pivot" in result["findings"].lower()
    assert result["follow_up_count"] == 1
    assert result["follow_up_alert_types"] == ["discovery"]


def test_review_liquidity_critical_with_regime_unavailable_degraded_mode():
    """Findings still synthesized when Phase 87 client unavailable."""
    from agents.macro_review_agent.agent import review_alert

    with patch(
        "agents.macro_review_agent.agent._cross_check_regime",
        return_value={"available": False, "regime": None, "accelerating": False},
    ), patch(
        "agents.macro_review_agent.agent._cross_check_correlations",
        return_value={"available": False, "correlation_breaks": []},
    ):
        result = review_alert(
            alert_trigger_id=43,
            alert_type="liquidity",
            severity="critical",
            subject_id="global_liquidity_score",
            payload={"liquidity_score": 25},
            agent_chain_depth=1,
        )

    assert result["status"] == "ok"
    assert "global_liquidity_score" in result["findings"]
    # No follow-up emitted — pivot signal requires regime+correlations
    assert result["follow_up_count"] == 0


def test_review_never_emits_self_loop_alert_type():
    """Even if findings claim pivot, follow-up alert_type MUST be 'discovery'.

    Self-loop ban enforced by the agent code's assertion + the
    _BANNED_FOLLOW_UP_ALERT_TYPES_FOR_SELF_LOOP constant.
    """
    from agents.macro_review_agent.agent import (
        _BANNED_FOLLOW_UP_ALERT_TYPES_FOR_SELF_LOOP,
    )

    assert "liquidity" in _BANNED_FOLLOW_UP_ALERT_TYPES_FOR_SELF_LOOP
    assert "regime" in _BANNED_FOLLOW_UP_ALERT_TYPES_FOR_SELF_LOOP
    # 'discovery' must NOT be in the banned set (it's the canonical follow-up).
    assert "discovery" not in _BANNED_FOLLOW_UP_ALERT_TYPES_FOR_SELF_LOOP


def test_review_returns_error_status_on_internal_failure():
    """Exceptions in review_alert are caught at the OUTER level — never propagate."""
    from agents.macro_review_agent.agent import review_alert

    # Patch synthesize to raise — _cross_check_* both have their own
    # try/except so we use synthesize to trigger the outer review_alert except.
    with patch(
        "agents.macro_review_agent.agent._synthesize_findings",
        side_effect=RuntimeError("synthesize boom"),
    ):
        result = review_alert(
            alert_trigger_id=44,
            alert_type="liquidity",
            severity="critical",
            subject_id="global_liquidity_score",
            payload={},
            agent_chain_depth=1,
        )

    assert result["status"] == "error"
    assert "synthesize boom" in result["error"]
    assert result["follow_up_count"] == 0


# ── Class facade ─────────────────────────────────────────────────────────────


def test_macro_review_agent_class_delegates_to_module_function():
    from agents.macro_review_agent.agent import MacroReviewAgent

    agent = MacroReviewAgent()
    assert agent.agent_id == "vm107.macro_review_agent"

    with patch(
        "agents.macro_review_agent.agent._cross_check_regime",
        return_value={"available": False, "regime": None, "accelerating": False},
    ), patch(
        "agents.macro_review_agent.agent._cross_check_correlations",
        return_value={"available": False, "correlation_breaks": []},
    ):
        result = agent.review_alert(
            alert_trigger_id=50,
            alert_type="regime",
            severity="regime_change",
            subject_id="cpi",
            payload={},
            agent_chain_depth=1,
        )

    assert result["status"] == "ok"
    assert result["agent_id"] == "vm107.macro_review_agent"
