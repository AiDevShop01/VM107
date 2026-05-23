"""
RED scaffold for REQ-66-2 scoring primitives — implemented in Plan 66-06 Task 1.

Tests CategoryScoringEngine, StructuralGateEngine, UniverseResolver.
Added per checker BLOCKER 5: consumed by Plan 66-06 Task 1 verify.

10 behaviors:
- test_category_scoring_loads_weights_from_db
- test_category_scoring_produces_9_breakdowns_per_instrument
- test_category_scoring_evidence_non_empty
- test_weighted_aggregation_correct
- test_structural_gate_active_invalidation_hard_rejects
- test_structural_gate_freshness_exceeded_downgrades
- test_structural_gate_regime_mismatch_caps_tier
- test_universe_resolver_london_ny_overlap
- test_universe_resolver_includes_open_positions
- test_universe_resolver_max_50_instruments
"""
import pytest

pytestmark = pytest.mark.phase_66


def test_category_scoring_loads_weights_from_db():
    """REQ-66-2: CategoryScoringEngine queries StrategyScoringWeight for
    strategy_id='default'; weights must sum to 100."""
    try:
        from emitters.scoring_primitives import CategoryScoringEngine
    except ImportError as exc:
        pytest.fail(
            f"Wave 2 (Plan 66-06 Task 1) must implement "
            f"emitters.scoring_primitives.CategoryScoringEngine: {exc}"
        )

    from emitters.scoring_primitives import CategoryScoringEngine
    from unittest.mock import patch, MagicMock

    engine = CategoryScoringEngine()

    mock_weights = [
        MagicMock(category="trend_alignment", weight=15),
        MagicMock(category="momentum", weight=12),
        MagicMock(category="volatility_regime", weight=12),
        MagicMock(category="liquidity_profile", weight=12),
        MagicMock(category="structural_clarity", weight=12),
        MagicMock(category="risk_reward_ratio", weight=12),
        MagicMock(category="session_fit", weight=10),
        MagicMock(category="macro_alignment", weight=8),
        MagicMock(category="behavioral_edge", weight=7),
    ]

    with patch.object(engine, "_load_weights_from_db", return_value=mock_weights):
        weights = engine.load_weights(strategy_id="default")

    total = sum(w.weight for w in weights)
    assert total == 100, (
        f"CategoryScoringEngine weights for strategy_id='default' must sum to 100; got {total}. "
        "Plan 66-06 Task 1 must enforce weight normalization."
    )


def test_category_scoring_produces_9_breakdowns_per_instrument():
    """REQ-66-2: score_instrument returns exactly 9 OpportunityScoreBreakdown items."""
    try:
        from emitters.scoring_primitives import CategoryScoringEngine
    except ImportError as exc:
        pytest.fail(f"Plan 66-06 Task 1 must implement CategoryScoringEngine: {exc}")

    from emitters.scoring_primitives import CategoryScoringEngine
    from unittest.mock import MagicMock, patch

    engine = CategoryScoringEngine()
    mock_instrument = MagicMock(symbol="EURUSD", timeframe="H1")
    mock_context = MagicMock()

    with patch.object(engine, "_load_weights_from_db", return_value=[
        MagicMock(category=f"cat_{i}", weight=11 if i < 1 else 11) for i in range(9)
    ]), patch.object(engine, "_fetch_category_signal", return_value=MagicMock(score=75, evidence=["ev1"])):
        breakdowns = engine.score_instrument(mock_instrument, context=mock_context)

    assert len(breakdowns) == 9, (
        f"CategoryScoringEngine.score_instrument must return 9 breakdowns; got {len(breakdowns)}. "
        "Exactly 9 categories are required by REQ-66-2."
    )


def test_category_scoring_evidence_non_empty():
    """REQ-66-2: Every OpportunityScoreBreakdown has non-empty evidence list."""
    try:
        from emitters.scoring_primitives import CategoryScoringEngine
    except ImportError as exc:
        pytest.fail(f"Plan 66-06 Task 1 must implement CategoryScoringEngine: {exc}")

    from emitters.scoring_primitives import CategoryScoringEngine
    from unittest.mock import MagicMock, patch

    engine = CategoryScoringEngine()
    mock_instrument = MagicMock(symbol="GBPUSD", timeframe="M15")

    with patch.object(engine, "_load_weights_from_db", return_value=[
        MagicMock(category=f"cat_{i}", weight=11) for i in range(9)
    ]), patch.object(engine, "_fetch_category_signal", return_value=MagicMock(
        score=60, evidence=["regime: TREND/HIGH_VOL", "session: london_ny_overlap"]
    )):
        breakdowns = engine.score_instrument(mock_instrument, context=MagicMock())

    for bd in breakdowns:
        assert bd.evidence, (
            f"Every breakdown must have non-empty evidence list; category={bd.category!r} is empty. "
            "Plan 66-06 Task 1 must populate evidence for all 9 categories."
        )


def test_weighted_aggregation_correct():
    """REQ-66-2: total_score = sum(category.score * category.weight) / 100; deterministic."""
    try:
        from emitters.scoring_primitives import CategoryScoringEngine
    except ImportError as exc:
        pytest.fail(f"Plan 66-06 Task 1 must implement CategoryScoringEngine: {exc}")

    from emitters.scoring_primitives import CategoryScoringEngine
    from unittest.mock import MagicMock, patch

    engine = CategoryScoringEngine()

    # Known input: 9 categories, each weight=11 except one at 11+1=12 (sums to 100)
    # scores: all 80 -> expected total = 80 (since uniform weights)
    breakdowns = [MagicMock(score=80, weight=11) for _ in range(8)]
    breakdowns.append(MagicMock(score=80, weight=12))

    with patch.object(engine, "score_instrument", return_value=breakdowns):
        total = engine.compute_total_score(breakdowns)

    expected = sum(bd.score * bd.weight for bd in breakdowns) / 100
    assert abs(total - expected) < 0.01, (
        f"total_score must equal sum(score*weight)/100={expected:.2f}; got {total:.2f}. "
        "Weighted aggregation formula is deterministic and must not vary."
    )


def test_structural_gate_active_invalidation_hard_rejects():
    """REQ-66-2: instrument with active_invalidation=True -> tier=INVALIDATED even if score=92."""
    try:
        from emitters.scoring_primitives import StructuralGateEngine
    except ImportError as exc:
        pytest.fail(
            f"Plan 66-06 Task 1 must implement emitters.scoring_primitives.StructuralGateEngine: {exc}"
        )

    from emitters.scoring_primitives import StructuralGateEngine

    gate = StructuralGateEngine()
    result = gate.apply(
        score=92,
        structural_valid=True,
        active_invalidation=True,
        data_freshness_ok=True,
        regime_match=True,
    )
    assert result.tier == "INVALIDATED", (
        f"active_invalidation=True must force tier=INVALIDATED regardless of score=92; got {result.tier!r}"
    )
    assert result.blocked_by == "active_invalidation", (
        "blocked_by field must explain WHY the gate fired"
    )


def test_structural_gate_freshness_exceeded_downgrades():
    """REQ-66-2: stale data (data_freshness_ok=False) downgrades tier by one level."""
    try:
        from emitters.scoring_primitives import StructuralGateEngine
    except ImportError as exc:
        pytest.fail(f"Plan 66-06 Task 1 must implement StructuralGateEngine: {exc}")

    from emitters.scoring_primitives import StructuralGateEngine

    gate = StructuralGateEngine()
    # A+ quality score but stale data -> should NOT remain A+
    result = gate.apply(
        score=85,
        structural_valid=True,
        active_invalidation=False,
        data_freshness_ok=False,  # stale
        regime_match=True,
    )
    assert result.tier != "A+", (
        "Stale data must downgrade tier; A+ must not be achievable with stale data. "
        f"Got tier={result.tier!r}"
    )
    assert result.downgraded_by_freshness is True, (
        "downgraded_by_freshness must be True when data_freshness_ok=False causes downgrade"
    )


def test_structural_gate_regime_mismatch_caps_tier():
    """REQ-66-2: regime mismatch caps maximum achievable tier at WATCH."""
    try:
        from emitters.scoring_primitives import StructuralGateEngine
    except ImportError as exc:
        pytest.fail(f"Plan 66-06 Task 1 must implement StructuralGateEngine: {exc}")

    from emitters.scoring_primitives import StructuralGateEngine

    gate = StructuralGateEngine()
    result = gate.apply(
        score=88,
        structural_valid=True,
        active_invalidation=False,
        data_freshness_ok=True,
        regime_match=False,  # regime mismatch
    )
    tier_rank = {"INVALIDATED": 0, "WATCH": 1, "B": 2, "A": 3, "A+": 4}
    result_rank = tier_rank.get(result.tier, -1)
    watch_rank = tier_rank["WATCH"]
    assert result_rank <= watch_rank, (
        f"regime_match=False must cap tier at WATCH or below; got tier={result.tier!r} "
        f"(rank={result_rank}, WATCH rank={watch_rank})"
    )


def test_universe_resolver_london_ny_overlap():
    """REQ-66-2: state=open + session=london_ny_overlap -> 7 majors + 5 crosses + 3 anchors
    + 3 indices per CONTEXT.md §3."""
    try:
        from emitters.scoring_primitives import UniverseResolver
    except ImportError as exc:
        pytest.fail(
            f"Plan 66-06 Task 1 must implement emitters.scoring_primitives.UniverseResolver: {exc}"
        )

    from emitters.scoring_primitives import UniverseResolver

    resolver = UniverseResolver()
    universe = resolver.resolve(state="open", session="london_ny_overlap", open_positions=[])

    symbols = [u.symbol for u in universe]

    # 7 majors: EURUSD, GBPUSD, USDJPY, USDCHF, USDCAD, AUDUSD, NZDUSD
    expected_majors = {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD"}
    present_majors = expected_majors.intersection(symbols)
    assert len(present_majors) == 7, (
        f"london_ny_overlap universe must include all 7 major pairs; missing: {expected_majors - set(symbols)}"
    )

    assert len(universe) >= 15, (
        f"london_ny_overlap universe must have >=15 instruments (7+5+3 min); got {len(universe)}"
    )


def test_universe_resolver_includes_open_positions():
    """REQ-66-2: Open positions are ALWAYS included in universe even outside session scope."""
    try:
        from emitters.scoring_primitives import UniverseResolver
    except ImportError as exc:
        pytest.fail(f"Plan 66-06 Task 1 must implement UniverseResolver: {exc}")

    from emitters.scoring_primitives import UniverseResolver
    from unittest.mock import MagicMock

    resolver = UniverseResolver()
    open_pos = [MagicMock(symbol="XAUUSD"), MagicMock(symbol="BTCUSD")]  # exotic symbols

    universe = resolver.resolve(state="pre", session="asian", open_positions=open_pos)
    symbols = [u.symbol for u in universe]

    assert "XAUUSD" in symbols, (
        "XAUUSD is in open_positions — must be included in universe regardless of session scope"
    )
    assert "BTCUSD" in symbols, (
        "BTCUSD is in open_positions — must be included in universe regardless of session scope"
    )


def test_universe_resolver_max_50_instruments():
    """REQ-66-2: Universe is capped at 50 instruments regardless of open positions."""
    try:
        from emitters.scoring_primitives import UniverseResolver
    except ImportError as exc:
        pytest.fail(f"Plan 66-06 Task 1 must implement UniverseResolver: {exc}")

    from emitters.scoring_primitives import UniverseResolver
    from unittest.mock import MagicMock

    resolver = UniverseResolver()
    # 60 open positions — should still cap at 50
    many_positions = [MagicMock(symbol=f"SYM{i}") for i in range(60)]

    universe = resolver.resolve(state="open", session="london_ny_overlap", open_positions=many_positions)

    assert len(universe) <= 50, (
        f"Universe must be capped at 50 instruments; got {len(universe)}. "
        "UniverseResolver must enforce the 50-instrument cap even with many open positions."
    )
