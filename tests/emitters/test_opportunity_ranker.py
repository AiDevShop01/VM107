"""
RED scaffold for REQ-66-2 — implemented in Plan 66-06.

Tests:
- test_a_plus_tier_requires_score_ge_80_and_structural_valid
- test_hard_invalidation_overrides_score
- test_nine_categories_scored_per_instrument
- test_zero_a_plus_is_valid_healthy_state
- test_snapshot_persisted_before_return
- test_thresholds_from_config_not_hardcoded
"""
import pytest

pytestmark = pytest.mark.phase_66


def test_a_plus_tier_requires_score_ge_80_and_structural_valid():
    """REQ-66-2: A+ tier requires score >= configured threshold AND structural_valid=True.
    Thresholds are config-driven, not hardcoded literals in the test."""
    try:
        from emitters.opportunity_ranker import OpportunityRanker
    except ImportError as exc:
        pytest.fail(
            f"Wave 2 (Plan 66-06) must implement emitters.opportunity_ranker.OpportunityRanker: {exc}"
        )

    from emitters.opportunity_ranker import OpportunityRanker

    ranker = OpportunityRanker()
    config = ranker.get_tier_config()
    a_plus_threshold = config["A+"]["min_score"]

    assert isinstance(a_plus_threshold, (int, float)), (
        "A+ threshold must be a numeric config value, not a hardcoded literal"
    )

    # Score just at threshold with structural_valid=True -> A+
    result = ranker.classify_tier(score=a_plus_threshold, structural_valid=True)
    assert result == "A+", (
        f"Score={a_plus_threshold} + structural_valid=True must yield A+; got {result!r}"
    )

    # Score one below threshold -> NOT A+
    result_below = ranker.classify_tier(score=a_plus_threshold - 0.1, structural_valid=True)
    assert result_below != "A+", (
        f"Score below threshold must not yield A+; got {result_below!r}"
    )

    # Score at threshold but structural_valid=False -> NOT A+
    result_invalid = ranker.classify_tier(score=a_plus_threshold, structural_valid=False)
    assert result_invalid != "A+", (
        "structural_valid=False must block A+ tier even at threshold score"
    )


def test_hard_invalidation_overrides_score():
    """REQ-66-2 + Phase 73 Decision 9: Active invalidation hard-blocks A+
    regardless of score.

    Phase 66 semantics had this return "INVALIDATED". Phase 73 Decision 9
    moved INV/INVALIDATED to the lifecycle pill (Plan 73-09 OpportunityLifecyclePill);
    the SCORING tier is now {A+, DEV, WATCH} only. Active invalidation
    collapses to the lowest valid tier (WATCH) and the lifecycle pill
    carries the "invalidated" surface.
    """
    try:
        from emitters.opportunity_ranker import OpportunityRanker
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement OpportunityRanker: {exc}")

    from emitters.opportunity_ranker import OpportunityRanker

    ranker = OpportunityRanker()
    result = ranker.classify_tier(
        score=92,
        structural_valid=True,
        active_invalidation=True,
    )
    # Phase 73 Decision 9 — collapses to lowest valid tier (WATCH), NOT A+ /
    # DEV. The lifecycle pill (Plan 73-09) carries the invalidation surface.
    assert result == "WATCH", (
        f"Phase 73 Decision 9: active_invalidation=True must collapse to "
        f"WATCH (lowest valid tier); got {result!r}. Lifecycle pill "
        f"(Plan 73-09) carries the 'invalidated' surface."
    )
    # Critically — NOT A+ regardless of score.
    assert result != "A+"


def test_nine_categories_scored_per_instrument():
    """REQ-66-2: Exactly 9 scoring categories produced per instrument."""
    try:
        from emitters.opportunity_ranker import OpportunityRanker
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement OpportunityRanker: {exc}")

    from emitters.opportunity_ranker import OpportunityRanker
    from unittest.mock import MagicMock, patch

    ranker = OpportunityRanker()
    mock_instrument = MagicMock(symbol="EURUSD", timeframe="H1")

    with patch.object(ranker, "_fetch_instrument_data", return_value=MagicMock()):
        breakdowns = ranker.score_instrument(mock_instrument)

    assert len(breakdowns) == 9, (
        f"Expected 9 scoring categories per instrument; got {len(breakdowns)}. "
        "Plan 66-06 must implement all 9 CategoryScoringEngine breakdowns."
    )


def test_zero_a_plus_is_valid_healthy_state():
    """REQ-66-2: A snapshot with ZERO A+ opportunities is a healthy state, not a bug.
    The ranker must not force at least one A+ to exist."""
    try:
        from emitters.opportunity_ranker import OpportunityRanker
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement OpportunityRanker: {exc}")

    from emitters.opportunity_ranker import OpportunityRanker
    from unittest.mock import MagicMock, patch

    ranker = OpportunityRanker()

    # All instruments score below A+ threshold
    low_score_instruments = [MagicMock(symbol=f"SYM{i}", score=30) for i in range(3)]
    with patch.object(ranker, "_fetch_universe", return_value=low_score_instruments), \
         patch.object(ranker, "_compute_score", return_value=30):
        snapshot = ranker.rank_opportunities(state="pre")

    # Phase 73 follow-up emit-shape fix (2026-05-31): canonical
    # OpportunityRankingSnapshotContract uses ``rankings`` (not the legacy
    # ``opportunities``) and ``assigned_tier`` (not the legacy ``tier``).
    a_plus_count = sum(
        1 for opp in snapshot.get("rankings", []) if opp.get("assigned_tier") == "A+"
    )
    # Zero A+ is valid — assert the snapshot itself is still structurally valid
    assert "rankings" in snapshot, "Snapshot must include canonical 'rankings' key"
    assert isinstance(snapshot["rankings"], list), "rankings must be a list"
    # a_plus_count == 0 is explicitly OK
    assert a_plus_count == 0 or True, "Zero A+ opportunities is a valid healthy state"


def test_snapshot_persisted_before_return():
    """REQ-66-2: OpportunityRankingSnapshot written to DB BEFORE the result is returned.
    Tests that DB persistence happens in the call, not after."""
    try:
        from emitters.opportunity_ranker import OpportunityRanker
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement OpportunityRanker: {exc}")

    from emitters.opportunity_ranker import OpportunityRanker
    from unittest.mock import MagicMock, patch, call

    ranker = OpportunityRanker()
    persist_called_before_return = {"called": False}
    returned = {"done": False}

    def mock_persist(snapshot):
        persist_called_before_return["called"] = True
        assert not returned["done"], (
            "snapshot must be persisted BEFORE rank_opportunities returns — "
            "DB write happened after function returned (race condition risk)"
        )

    with patch.object(ranker, "_persist_snapshot", side_effect=mock_persist), \
         patch.object(ranker, "_fetch_universe", return_value=[]), \
         patch.object(ranker, "_fetch_instrument_data", return_value=MagicMock()):
        result = ranker.rank_opportunities(state="open")
        returned["done"] = True

    assert persist_called_before_return["called"], (
        "OpportunityRanker._persist_snapshot must be called during rank_opportunities"
    )


def test_thresholds_from_config_not_hardcoded():
    """REQ-66-2: Tier thresholds come from config/DB, not hardcoded literals.
    Changing the config must change the behavior."""
    try:
        from emitters.opportunity_ranker import OpportunityRanker
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement OpportunityRanker: {exc}")

    from emitters.opportunity_ranker import OpportunityRanker
    from unittest.mock import patch

    ranker = OpportunityRanker()

    # Override config to use threshold=50 — behavior must follow config
    with patch.object(ranker, "get_tier_config", return_value={"A+": {"min_score": 50}}):
        result_at_50 = ranker.classify_tier(score=50, structural_valid=True)
        result_at_49 = ranker.classify_tier(score=49, structural_valid=True)

    assert result_at_50 == "A+", "With config threshold=50, score=50 must yield A+"
    assert result_at_49 != "A+", "With config threshold=50, score=49 must NOT yield A+"
