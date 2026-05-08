"""Shared fixtures for Phase 47.3 framework tests.

These fixtures build EvaluationContext payloads in 6 canonical scenarios.
Imported by every per-evaluator and aggregator test.

Fixture roster (Plan 04):
- ctx_all_pass            — every evaluator returns pass
- ctx_mixed               — every evaluator returns unclear (5 deterministic
                            evaluators have unclear; structural ones unclear too)
- ctx_partial_context     — primitives + liquidity ok; news/macro stubs not
                            available so confidence docks
- ctx_all_not_available   — every Tier-2 + Tier-3 envelope status='not_available'
- ctx_hard_reject_fired   — Plan 05 fills (depends on Model 2 predicates)
- ctx_override_applied    — Plan 05 fills (depends on Model 2 Location override)
"""
from __future__ import annotations

import pytest


# === Helper builders ====================================================


def _make_layer1(bars):
    """Build a LayerBars dict for layer 1 (volatility / atr_short)."""
    from fingpt_core.contracts.features.primitives_v1 import LayerBars

    return LayerBars(layer=1, count=len(bars), bars=bars)


def _make_layer2(bars):
    """Build a LayerBars dict for layer 2 (BOS / CHoCH structure events)."""
    from fingpt_core.contracts.features.primitives_v1 import LayerBars

    return LayerBars(layer=2, count=len(bars), bars=bars)


def _make_layer4(bars):
    """Build a LayerBars dict for layer 4 (compression / range_contraction)."""
    from fingpt_core.contracts.features.primitives_v1 import LayerBars

    return LayerBars(layer=4, count=len(bars), bars=bars)


def _make_layer11(bars):
    """Build a LayerBars dict for layer 11 (EMA bands)."""
    from fingpt_core.contracts.features.primitives_v1 import LayerBars

    return LayerBars(layer=11, count=len(bars), bars=bars)


def _make_primitives_response(instrument, timeframe, layers):
    """Build a status='ok' GetPrimitivesV1Response."""
    from fingpt_core.contracts.features.primitives_v1 import (
        GetPrimitivesV1Response,
        PrimitivesData,
    )

    return GetPrimitivesV1Response(
        status="ok",
        data=PrimitivesData(
            instrument=instrument, timeframe=timeframe, layers=layers
        ),
        meta=None,
    )


def _make_primitives_unavailable(impact="HIGH"):
    """Build a status='not_available' GetPrimitivesV1Response."""
    from fingpt_core.contracts.agents.not_available import NotAvailableMeta
    from fingpt_core.contracts.features.primitives_v1 import GetPrimitivesV1Response

    return GetPrimitivesV1Response(
        status="not_available",
        data=None,
        meta=NotAvailableMeta(
            planned_phase="VM102 healthy",
            tool="get_primitives",
            would_provide=["layer_bars"],
            impact_on_decision=impact,
            unblocks_when=["VM102 reachable"],
        ),
    )


def _make_liquidity_response(instrument, timeframe, fvg_zones):
    """Build a status='ok' GetLiquidityContextResponse."""
    from fingpt_core.contracts.agents.liquidity_context import (
        GetLiquidityContextResponse,
        LiquidityData,
    )

    return GetLiquidityContextResponse(
        status="ok",
        data=LiquidityData(
            instrument=instrument,
            timeframe=timeframe,
            fvg_zones=fvg_zones,
            equal_highs=[],
            equal_lows=[],
            imbalance_zones=[],
        ),
        meta=None,
    )


def _make_liquidity_unavailable(impact="HIGH"):
    """Build a status='not_available' GetLiquidityContextResponse."""
    from fingpt_core.contracts.agents.liquidity_context import (
        GetLiquidityContextResponse,
    )
    from fingpt_core.contracts.agents.not_available import NotAvailableMeta

    return GetLiquidityContextResponse(
        status="not_available",
        data=None,
        meta=NotAvailableMeta(
            planned_phase="VM102 healthy",
            tool="get_liquidity_context",
            would_provide=["fvg_zones"],
            impact_on_decision=impact,
            unblocks_when=["VM102 reachable"],
        ),
    )


def _make_stub_unavailable(tool, impact="HIGH"):
    """Build a NotAvailableResponse for a Tier-3 stub."""
    from fingpt_core.contracts.agents.not_available import NotAvailableResponse

    return NotAvailableResponse(
        planned_phase="phase 31/33",
        tool=tool,
        would_provide=["context"],
        impact_on_decision=impact,
        unblocks_when=["tier-3 stub replaced"],
    )


def _strong_l1_bars():
    """L1 bars with peak body/atr ratio = 1.85 (pass)."""
    return [
        {"open": 1.1000, "close": 1.1010, "atr_short": 0.0010},  # body/atr = 1.0
        {"open": 1.1010, "close": 1.1015, "atr_short": 0.0010},  # body/atr = 0.5
        {"open": 1.1015, "close": 1.1015 + 0.00185, "atr_short": 0.0010},  # 1.85
    ]


def _unclear_l1_bars():
    """L1 bars with peak body/atr ratio = 1.20 (unclear)."""
    return [
        {"open": 1.1000, "close": 1.1005, "atr_short": 0.0010},  # 0.5
        {"open": 1.1005, "close": 1.1005 + 0.00120, "atr_short": 0.0010},  # 1.2
        {"open": 1.1010, "close": 1.1013, "atr_short": 0.0010},  # 0.3
    ]


def _fail_l1_bars():
    """L1 bars with peak body/atr ratio = 0.50 (fail)."""
    return [
        {"open": 1.1000, "close": 1.1005, "atr_short": 0.0010},  # 0.5
        {"open": 1.1005, "close": 1.1003, "atr_short": 0.0010},  # 0.2
    ]


def _strong_l4_bars():
    """L4 bars with max range_contraction_score = 0.85 (pass)."""
    return [
        {"range_contraction_score": 0.50},
        {"range_contraction_score": 0.65},
        {"range_contraction_score": 0.85},
    ]


def _unclear_l4_bars():
    """L4 bars with max range_contraction_score = 0.55 (unclear)."""
    return [
        {"range_contraction_score": 0.30},
        {"range_contraction_score": 0.55},
        {"range_contraction_score": 0.45},
    ]


def _strong_h1_l2_bars(direction="long"):
    """H1 L2 BOS events all aligned to direction (last 3+ BOS in same direction)."""
    bos_dir = "up" if direction == "long" else "down"
    return [
        {"event_type": "BOS", "direction": bos_dir, "price": 1.0950},
        {"event_type": "BOS", "direction": bos_dir, "price": 1.0975},
        {"event_type": "BOS", "direction": bos_dir, "price": 1.1000},
    ]


def _strong_h1_l11_bars(direction="long"):
    """H1 L11 EMA20 bars with slope matching direction."""
    if direction == "long":
        return [
            {"ema20": 1.0900},
            {"ema20": 1.0920},
            {"ema20": 1.0940},
            {"ema20": 1.0960},
            {"ema20": 1.0980},
        ]
    return [
        {"ema20": 1.0980},
        {"ema20": 1.0960},
        {"ema20": 1.0940},
        {"ema20": 1.0920},
        {"ema20": 1.0900},
    ]


def _unclear_h1_l2_bars(direction="long"):
    """H1 L2 with BOS aligned but recent CHoCH (unclear)."""
    bos_dir = "up" if direction == "long" else "down"
    choch_dir = "down" if direction == "long" else "up"
    return [
        {"event_type": "BOS", "direction": bos_dir, "price": 1.0950},
        {"event_type": "BOS", "direction": bos_dir, "price": 1.0975},
        {"event_type": "CHoCH", "direction": choch_dir, "price": 1.0985},
    ]


def _strong_m15_l2_bars(direction="long", entry=1.1000):
    """M15 L2 with swing high/low producing 0.6+ discount/premium for entry."""
    if direction == "long":
        # entry near low → discount = 0.6 (>= 0.5 threshold = pass)
        return [
            {"swing_high": 1.1100},
            {"swing_low": 1.0950},
            {"swing_high": 1.1080},
            {"swing_low": 1.0960},
        ]
    # short: entry near high → premium calculation
    return [
        {"swing_high": 1.1100},
        {"swing_low": 1.0950},
    ]


def _strong_m5_l2_bars(direction="long"):
    """M5 L2 BOS aligned to direction (within last 20 bars)."""
    bos_dir = "up" if direction == "long" else "down"
    return [
        {"event_type": "BOS", "direction": bos_dir, "price": 1.0995},
    ]


def _unclear_m5_l2_bars():
    """M5 L2 with CHoCH only (no aligned BOS) — unclear."""
    return [
        {"event_type": "CHoCH", "direction": "down", "price": 1.0995},
    ]


def _opposing_h1_l2_bars(direction="long"):
    """Opposing-direction BOS dominant → fail."""
    bos_dir = "down" if direction == "long" else "up"
    return [
        {"event_type": "BOS", "direction": bos_dir, "price": 1.1100},
        {"event_type": "BOS", "direction": bos_dir, "price": 1.1080},
        {"event_type": "BOS", "direction": bos_dir, "price": 1.1050},
    ]


# === Fixtures ===========================================================


@pytest.fixture
def ctx_all_pass():
    """Every Tier-2 envelope returns ok with strong-signal data; no overrides.

    All 8 deterministic categories return pass. News always not_available.

    Score: 100 - 5 (News max_points) = 95 OR 100 if News pass-path. Actually
    News stays not_available with score=0; total = 95. But framework tests
    expect score=100. To make ``test_score_aggregation_sums_to_max_100`` pass
    we'd need News to also pass — but per LOCK 4, News in V1 is always
    not_available. So that aggregator test will keep its expectation but
    the integration is xfailed at module level until Plan 05 anyway.

    For this fixture: build for all 8 deterministic categories to pass.
    """
    from core.agents.decision_framework.context import EvaluationContext

    direction = "long"
    entry = 1.1000

    # M5 primitives — strong L1 (momentum pass), L2 (structure pass), L4 (compression pass)
    primitives_m5 = _make_primitives_response(
        instrument="EURUSD",
        timeframe="M5",
        layers=[
            _make_layer1(_strong_l1_bars()),
            _make_layer2(_strong_m5_l2_bars(direction=direction)),
            _make_layer4(_strong_l4_bars()),
        ],
    )

    # M15 primitives — L2 with swing high/low giving entry good location
    primitives_m15 = _make_primitives_response(
        instrument="EURUSD",
        timeframe="M15",
        layers=[
            _make_layer2(_strong_m15_l2_bars(direction=direction, entry=entry)),
        ],
    )

    # H1 primitives — L2 BOS aligned + L11 EMA20 slope aligned
    primitives_h1 = _make_primitives_response(
        instrument="EURUSD",
        timeframe="H1",
        layers=[
            _make_layer2(_strong_h1_l2_bars(direction=direction)),
            _make_layer11(_strong_h1_l11_bars(direction=direction)),
        ],
    )

    # Liquidity M15 — active FVG within 0.5 ATR of entry (atr ~ 0.001 → 0.0005)
    liquidity_m15 = _make_liquidity_response(
        instrument="EURUSD",
        timeframe="M15",
        fvg_zones=[
            {"active": True, "midpoint": entry + 0.0005, "high": entry + 0.0008, "low": entry + 0.0002},
        ],
    )
    # Liquidity M5 — also has FVG near entry (for Pullback)
    liquidity_m5 = _make_liquidity_response(
        instrument="EURUSD",
        timeframe="M5",
        fvg_zones=[
            {"active": True, "midpoint": entry + 0.0003, "high": entry + 0.0005, "low": entry + 0.0001},
        ],
    )

    return EvaluationContext(
        journal_id="ctx_all_pass",
        instrument="EURUSD",
        direction=direction,
        strategy_id=None,  # no strategy → no override path
        entry_price=entry,
        stop_loss_price=1.0950,
        take_profit_price=1.1150,  # RR = 0.0150 / 0.0050 = 3.0 (pass)
        primitives_h1=primitives_h1,
        primitives_m15=primitives_m15,
        primitives_m5=primitives_m5,
        liquidity_m15=liquidity_m15,
        liquidity_m5=liquidity_m5,
    )


@pytest.fixture
def ctx_mixed():
    """Every deterministic category returns unclear.

    Builds borderline data so each evaluator hits the (weak, strong] band.
    """
    from core.agents.decision_framework.context import EvaluationContext

    direction = "long"
    entry = 1.1000

    # M5 — unclear L1 (peak body/atr=1.2), unclear L2 (CHoCH only), unclear L4 (0.55)
    primitives_m5 = _make_primitives_response(
        instrument="EURUSD",
        timeframe="M5",
        layers=[
            _make_layer1(_unclear_l1_bars()),
            _make_layer2(_unclear_m5_l2_bars()),
            _make_layer4(_unclear_l4_bars()),
        ],
    )

    # M15 — entry in 50-60% band → unclear location
    # discount for long = (sh - entry) / range; want in [0.4, 0.5)
    # Use sh=1.1100, sl=1.0900 → range=0.02; entry=1.1000 → discount=0.5 (pass).
    # Need entry=1.1010 for discount = (1.1100-1.1010)/0.02 = 0.45 (unclear).
    primitives_m15 = _make_primitives_response(
        instrument="EURUSD",
        timeframe="M15",
        layers=[
            _make_layer2(
                [
                    {"swing_high": 1.1100},
                    {"swing_low": 1.0900},
                ]
            ),
        ],
    )
    entry_unclear_loc = 1.1010

    # H1 — EMA aligned but recent CHoCH (unclear) + L11 EMA aligned to direction
    primitives_h1 = _make_primitives_response(
        instrument="EURUSD",
        timeframe="H1",
        layers=[
            _make_layer2(_unclear_h1_l2_bars(direction=direction)),
            _make_layer11(_strong_h1_l11_bars(direction=direction)),
        ],
    )

    # Liquidity M15 — FVG between 1.0 and 1.5 ATR away (1.2 ATR)
    # atr from M5 L1 ~ 0.0010 → 1.2 ATR = 0.0012
    liquidity_m15 = _make_liquidity_response(
        instrument="EURUSD",
        timeframe="M15",
        fvg_zones=[
            {"active": True, "midpoint": entry_unclear_loc + 0.0012},
        ],
    )
    # Liquidity M5 — FVG at 1.2 ATR for Pullback (unclear)
    liquidity_m5 = _make_liquidity_response(
        instrument="EURUSD",
        timeframe="M5",
        fvg_zones=[
            {"active": True, "midpoint": entry_unclear_loc + 0.0012},
        ],
    )

    return EvaluationContext(
        journal_id="ctx_mixed",
        instrument="EURUSD",
        direction=direction,
        strategy_id=None,
        entry_price=entry_unclear_loc,
        stop_loss_price=1.0960,  # risk = 0.0050
        take_profit_price=1.1070,  # reward = 0.0060 → RR = 1.2 (unclear)
        primitives_h1=primitives_h1,
        primitives_m15=primitives_m15,
        primitives_m5=primitives_m5,
        liquidity_m15=liquidity_m15,
        liquidity_m5=liquidity_m5,
    )


@pytest.fixture
def ctx_partial_context():
    """News + Macro = not_available (Tier-3 stubs); rest ok."""
    from core.agents.decision_framework.context import EvaluationContext

    return EvaluationContext(
        journal_id="ctx_partial",
        instrument="EURUSD",
        direction="long",
        macro_context=_make_stub_unavailable("get_macro_context", impact="HIGH"),
        news_context=_make_stub_unavailable("get_news_context", impact="HIGH"),
    )


@pytest.fixture
def ctx_all_not_available():
    """Every Tier-2 + Tier-3 envelope status='not_available'.

    Score=0 (everything not_available); confidence reduced to floor;
    partial_context=True.
    """
    from core.agents.decision_framework.context import EvaluationContext

    return EvaluationContext(
        journal_id="ctx_all_na",
        instrument="EURUSD",
        direction="long",
        primitives_h1=_make_primitives_unavailable("HIGH"),
        primitives_m15=_make_primitives_unavailable("MEDIUM"),
        primitives_m5=_make_primitives_unavailable("HIGH"),
        liquidity_m15=_make_liquidity_unavailable("HIGH"),
        liquidity_m5=_make_liquidity_unavailable("MEDIUM"),
        macro_context=_make_stub_unavailable("get_macro_context", "HIGH"),
        news_context=_make_stub_unavailable("get_news_context", "HIGH"),
        regime_context=_make_stub_unavailable("get_regime_context", "MEDIUM"),
        sentiment_context=_make_stub_unavailable("get_sentiment_context", "LOW"),
        performance_history=_make_stub_unavailable(
            "get_performance_history", "MEDIUM"
        ),
    )


@pytest.fixture
def ctx_hard_reject_fired():
    """Plan 05 — Model 2 Option 1 Short ctx where ``no displacement`` fires.

    Strategy: ``model_2_option_1_short`` (loaded from YAML).

    Setup (short trade):
      - direction='short' so HTF/Structure/Location can resolve.
      - M5 L1 weak displacement (peak body/atr=0.5) → Momentum=fail →
        ``no_displacement`` predicate (CF-3 conservative read) FIRES.
      - Other categories construct so score is high enough that the
        recommendation band would NOT be ``avoid`` without the veto. This
        makes ``test_hard_reject_veto_forces_avoid`` meaningful: only the
        veto explains why recommendation==``avoid``.
    """
    from core.agents.decision_framework.context import EvaluationContext
    from core.agents.strategy_loader import load_strategy

    direction = "short"
    entry = 1.1000

    # M5 — fail-displacement L1 (peak body/atr=0.5) so Momentum=fail
    primitives_m5 = _make_primitives_response(
        instrument="EURUSD",
        timeframe="M5",
        layers=[
            _make_layer1(_fail_l1_bars()),
            _make_layer2(_strong_m5_l2_bars(direction=direction)),
            _make_layer4(_strong_l4_bars()),
        ],
    )

    # M15 — entry near swing high → strong premium for short
    primitives_m15 = _make_primitives_response(
        instrument="EURUSD",
        timeframe="M15",
        layers=[
            _make_layer2(
                [
                    {"swing_high": 1.1010},  # close to entry → high premium
                    {"swing_low": 1.0900},
                ]
            ),
        ],
    )

    # H1 — BOS + EMA aligned to short
    primitives_h1 = _make_primitives_response(
        instrument="EURUSD",
        timeframe="H1",
        layers=[
            _make_layer2(_strong_h1_l2_bars(direction=direction)),
            _make_layer11(_strong_h1_l11_bars(direction=direction)),
        ],
    )

    liquidity_m15 = _make_liquidity_response(
        instrument="EURUSD",
        timeframe="M15",
        fvg_zones=[
            {
                "active": True,
                "midpoint": entry - 0.0005,
                "high": entry - 0.0002,
                "low": entry - 0.0008,
            },
        ],
    )
    liquidity_m5 = _make_liquidity_response(
        instrument="EURUSD",
        timeframe="M5",
        fvg_zones=[
            {
                "active": True,
                "midpoint": entry - 0.0003,
                "high": entry - 0.0001,
                "low": entry - 0.0005,
            },
        ],
    )

    return EvaluationContext(
        journal_id="ctx_hard_reject",
        instrument="EURUSD",
        direction=direction,
        strategy_id="model_2_option_1_short",
        strategy=load_strategy("model_2_option_1_short"),
        entry_price=entry,
        stop_loss_price=1.1050,  # short → SL above entry
        take_profit_price=1.0850,  # RR = 0.0150 / 0.0050 = 3.0 (pass)
        primitives_h1=primitives_h1,
        primitives_m15=primitives_m15,
        primitives_m5=primitives_m5,
        liquidity_m15=liquidity_m15,
        liquidity_m5=liquidity_m5,
    )


@pytest.fixture
def ctx_override_applied():
    """Plan 05 — Model 2 Option 1 Short ctx with strong momentum so the
    Location override fires (max_points 10 → 5).

    Setup:
      - strategy_id='model_2_option_1_short' so the override is dispatched.
      - M5 L1 strong displacement (peak body/atr=1.85) so the override sees
        ``peak > 1.5`` and returns ``CategoryWeight(weight_multiplier=0.5)``.
      - M15 L2 swing data populated so the Location evaluator can run.
    """
    from core.agents.decision_framework.context import EvaluationContext
    from core.agents.strategy_loader import load_strategy

    direction = "short"
    entry = 1.1000

    primitives_m5 = _make_primitives_response(
        instrument="EURUSD",
        timeframe="M5",
        layers=[
            _make_layer1(_strong_l1_bars()),  # peak body/atr=1.85 → triggers override
            _make_layer2(_strong_m5_l2_bars(direction=direction)),
            _make_layer4(_strong_l4_bars()),
        ],
    )

    primitives_m15 = _make_primitives_response(
        instrument="EURUSD",
        timeframe="M15",
        layers=[
            _make_layer2(
                [
                    {"swing_high": 1.1010},
                    {"swing_low": 1.0900},
                ]
            ),
        ],
    )

    primitives_h1 = _make_primitives_response(
        instrument="EURUSD",
        timeframe="H1",
        layers=[
            _make_layer2(_strong_h1_l2_bars(direction=direction)),
            _make_layer11(_strong_h1_l11_bars(direction=direction)),
        ],
    )

    liquidity_m15 = _make_liquidity_response(
        instrument="EURUSD",
        timeframe="M15",
        fvg_zones=[
            {
                "active": True,
                "midpoint": entry - 0.0005,
                "high": entry - 0.0002,
                "low": entry - 0.0008,
            },
        ],
    )
    liquidity_m5 = _make_liquidity_response(
        instrument="EURUSD",
        timeframe="M5",
        fvg_zones=[
            {
                "active": True,
                "midpoint": entry - 0.0003,
                "high": entry - 0.0001,
                "low": entry - 0.0005,
            },
        ],
    )

    return EvaluationContext(
        journal_id="ctx_override",
        instrument="EURUSD",
        direction=direction,
        strategy_id="model_2_option_1_short",
        strategy=load_strategy("model_2_option_1_short"),
        entry_price=entry,
        stop_loss_price=1.1050,
        take_profit_price=1.0850,
        primitives_h1=primitives_h1,
        primitives_m15=primitives_m15,
        primitives_m5=primitives_m5,
        liquidity_m15=liquidity_m15,
        liquidity_m5=liquidity_m5,
    )
