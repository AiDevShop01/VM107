"""Phase 67 Plan 07 — ReflectionPrompt assemblers tests (Task 1).

Covers the 4 progressive enrichment assemblers + Pitfall 3 fix
(CrossTradePatternsService.get_session_patterns).

Each assembler is pure (no side effects beyond service calls) and accepts a
``vm100_client`` injection for the chokepoint pattern. The intermediate
types (TradeObservation, BehavioralInterpretation, PatternContext,
LongitudinalContext) are frozen dataclasses — NOT Pydantic (these are
internal pipeline types, not wire contracts).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from emitters.reflection.assemblers.trade_observation import (
    TradeObservation,
    TradeObservationAssembler,
)
from emitters.reflection.assemblers.behavioral_interpretation import (
    BehavioralInterpretation,
    BehavioralInterpretationAssembler,
)
from emitters.reflection.assemblers.pattern_context import (
    PatternContext,
    PatternContextAssembler,
)
from emitters.reflection.assemblers.longitudinal_context import (
    LongitudinalContext,
    LongitudinalContextAssembler,
)


pytestmark = pytest.mark.phase_67


# ── 1. TradeObservationAssembler ────────────────────────────────────────────


def test_trade_observation_assembler_returns_list_of_dataclasses():
    """assemble() returns list[TradeObservation] from VM100 trade outcomes."""
    fake_vm100 = MagicMock()
    fake_vm100.get_trade_outcomes_for_session = MagicMock(
        return_value=[
            {
                "trade_id": "t-1",
                "symbol": "EURUSD",
                "entry_at": "2026-05-25T09:15:00Z",
                "exit_at": "2026-05-25T10:30:00Z",
                "pnl_r": 1.5,
                "regime": "TREND",
                "behavioral_tags": ["premature_entry"],
            },
            {
                "trade_id": "t-2",
                "symbol": "GBPUSD",
                "entry_at": "2026-05-25T11:00:00Z",
                "exit_at": "2026-05-25T12:00:00Z",
                "pnl_r": -0.8,
                "regime": "RANGE",
                "behavioral_tags": [],
            },
        ]
    )
    assembler = TradeObservationAssembler(vm100_client=fake_vm100)
    out = assembler.assemble(account_id=42, session_date=date(2026, 5, 25))
    assert isinstance(out, list)
    assert len(out) == 2
    assert all(isinstance(o, TradeObservation) for o in out)
    assert out[0].trade_id == "t-1"
    assert out[0].pnl_r == 1.5
    assert out[0].regime == "TREND"
    assert out[1].pnl_r == -0.8


def test_trade_observation_assembler_empty_returns_empty_list():
    """No trades in session → empty list (no error)."""
    fake_vm100 = MagicMock()
    fake_vm100.get_trade_outcomes_for_session = MagicMock(return_value=[])
    assembler = TradeObservationAssembler(vm100_client=fake_vm100)
    out = assembler.assemble(account_id=42, session_date=date(2026, 5, 25))
    assert out == []


def test_trade_observation_assembler_handles_missing_upstream():
    """vm100_client raises → returns empty list, sets missing_sources flag."""
    fake_vm100 = MagicMock()
    fake_vm100.get_trade_outcomes_for_session = MagicMock(
        side_effect=RuntimeError("VM100 down")
    )
    assembler = TradeObservationAssembler(vm100_client=fake_vm100)
    out = assembler.assemble(account_id=42, session_date=date(2026, 5, 25))
    assert out == []
    assert "vm100" in assembler.missing_sources


def test_trade_observation_assembler_dataclass_is_frozen():
    """TradeObservation is a frozen dataclass — mutation raises."""
    obs = TradeObservation(
        trade_id="t-1",
        symbol="EURUSD",
        entry_at=datetime(2026, 5, 25, 9, 15, tzinfo=timezone.utc),
        exit_at=datetime(2026, 5, 25, 10, 30, tzinfo=timezone.utc),
        pnl_r=1.5,
        regime="TREND",
        behavioral_tags=("premature_entry",),
    )
    with pytest.raises(Exception):
        obs.pnl_r = 99.0  # type: ignore[misc]


# ── 2. BehavioralInterpretationAssembler ────────────────────────────────────


def test_behavioral_interpretation_attaches_discipline_flags():
    """Attaches discipline_flags + mentor_narrative_summary to each trade."""
    observations = [
        TradeObservation(
            trade_id="t-1",
            symbol="EURUSD",
            entry_at=datetime(2026, 5, 25, 9, 15, tzinfo=timezone.utc),
            exit_at=datetime(2026, 5, 25, 10, 30, tzinfo=timezone.utc),
            pnl_r=1.5,
            regime="TREND",
            behavioral_tags=("premature_entry",),
        ),
    ]
    fake_vm100 = MagicMock()
    # NarrativeEnvelope shape (Phase 60 mentor_pipeline_writer output)
    fake_vm100.get_mentor_narrative_for_trade = MagicMock(
        return_value={
            "discipline_flags": ["premature_entry", "size_violation"],
            "narrative_summary": "Entered before M5 BOS during high compression.",
            "confidence": 0.78,
        }
    )

    assembler = BehavioralInterpretationAssembler(vm100_client=fake_vm100)
    out = assembler.assemble(
        account_id=42, session_date=date(2026, 5, 25), observations=observations
    )
    assert len(out) == 1
    assert isinstance(out[0], BehavioralInterpretation)
    assert "premature_entry" in out[0].discipline_flags
    assert out[0].mentor_narrative_summary.startswith("Entered before")
    assert out[0].confidence == 0.78


def test_behavioral_interpretation_handles_missing_narrative_gracefully():
    """vm100_client returns None / raises → partial interpretation."""
    observations = [
        TradeObservation(
            trade_id="t-1",
            symbol="EURUSD",
            entry_at=datetime(2026, 5, 25, 9, 15, tzinfo=timezone.utc),
            exit_at=datetime(2026, 5, 25, 10, 30, tzinfo=timezone.utc),
            pnl_r=1.5,
            regime="TREND",
            behavioral_tags=(),
        ),
    ]
    fake_vm100 = MagicMock()
    fake_vm100.get_mentor_narrative_for_trade = MagicMock(
        side_effect=RuntimeError("mentor down")
    )

    assembler = BehavioralInterpretationAssembler(vm100_client=fake_vm100)
    out = assembler.assemble(
        account_id=42, session_date=date(2026, 5, 25), observations=observations
    )
    # Still returns one interpretation per observation; degraded fields.
    assert len(out) == 1
    assert out[0].discipline_flags == ()
    assert "mentor_narrative" in assembler.missing_sources


# ── 3. PatternContextAssembler ─────────────────────────────────────────────


def test_pattern_context_calls_session_patterns_not_30d():
    """Pitfall 3 fix verification — uses get_session_patterns, NOT get_patterns."""
    fake_vm100 = MagicMock()
    fake_vm100.get_session_patterns = MagicMock(
        return_value=[
            {
                "pattern_id": "p-1",
                "pattern_name": "premature_entry_cluster",
                "supporting_trade_ids": ["t-1", "t-3"],
                "severity": 0.7,
            }
        ]
    )
    # Ensure get_patterns (30d) is NOT called
    fake_vm100.get_patterns = MagicMock(return_value=[])

    assembler = PatternContextAssembler(vm100_client=fake_vm100)
    interpretations: list[BehavioralInterpretation] = []
    out = assembler.assemble(
        account_id=42,
        session_date=date(2026, 5, 25),
        interpretations=interpretations,
    )
    assert fake_vm100.get_session_patterns.called
    assert not fake_vm100.get_patterns.called
    assert len(out) == 1
    assert isinstance(out[0], PatternContext)
    assert out[0].pattern_name == "premature_entry_cluster"


def test_pattern_context_handles_missing_patterns_service():
    """Missing patterns service → returns empty list + missing_sources updated."""
    fake_vm100 = MagicMock()
    fake_vm100.get_session_patterns = MagicMock(
        side_effect=RuntimeError("neo4j down")
    )

    assembler = PatternContextAssembler(vm100_client=fake_vm100)
    out = assembler.assemble(
        account_id=42, session_date=date(2026, 5, 25), interpretations=[]
    )
    assert out == []
    assert "cross_trade_patterns" in assembler.missing_sources


# ── 4. LongitudinalContextAssembler ────────────────────────────────────────


def test_longitudinal_context_pulls_phase_62_evolution_and_adaptive():
    """Pulls BehavioralEvolution + AdaptiveRecommendation via VM100 chokepoint."""
    fake_vm100 = MagicMock()
    fake_vm100.get_behavioral_evolution = MagicMock(
        return_value={
            "evolution_trend": "improving",
            "behavioral_trajectory": "stabilizing after spike",
        }
    )
    fake_vm100.get_adaptive_recommendation = MagicMock(
        return_value={
            "recommendation": "Reduce session size by 25% on Mondays",
            "target_surface": "category_point_weight",
        }
    )

    assembler = LongitudinalContextAssembler(vm100_client=fake_vm100)
    out = assembler.assemble(
        account_id=42,
        session_date=date(2026, 5, 25),
        patterns=[],
    )
    assert isinstance(out, list)
    assert len(out) == 1
    assert isinstance(out[0], LongitudinalContext)
    assert out[0].evolution_trend == "improving"
    assert "Reduce session size" in out[0].adaptive_recommendation


def test_longitudinal_context_handles_missing_phase_62_data():
    """Missing Phase 62 data → empty list + missing_sources updated."""
    fake_vm100 = MagicMock()
    fake_vm100.get_behavioral_evolution = MagicMock(
        side_effect=RuntimeError("phase 62 service down")
    )
    fake_vm100.get_adaptive_recommendation = MagicMock(
        side_effect=RuntimeError("phase 62 service down")
    )

    assembler = LongitudinalContextAssembler(vm100_client=fake_vm100)
    out = assembler.assemble(
        account_id=42, session_date=date(2026, 5, 25), patterns=[]
    )
    assert out == []
    assert (
        "behavioral_evolution" in assembler.missing_sources
        or "adaptive_recommendation" in assembler.missing_sources
    )


# ── 5. Pitfall 3 Fix: CrossTradePatternsService.get_session_patterns ────────
#
# The actual unit tests for the VM100 CrossTradePatternsService.get_session_patterns
# method live in VM100/backend/journal/tests/test_cross_trade_patterns_service.py
# (Django app context required to import the service module — VM100 tests
# bootstrap Django via tests/conftest.py). The PatternContextAssembler test
# above ("test_pattern_context_calls_session_patterns_not_30d") verifies the
# CONSUMER side of the contract (this assembler calls .get_session_patterns,
# not .get_patterns). The producer side is verified in the VM100 test file.
