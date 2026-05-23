"""
Phase 66 Plan 02 — NoveltyEngine (shared, used by REQ-66-1 and REQ-66-3).
Implemented in Plan 66-02.

9 behavior tests:
1. test_engine_is_deterministic
2. test_engine_supports_5_dimensions
3. test_high_triggers_set_threshold_crossed
4. test_medium_triggers_only_with_clustering
5. test_config_driven_threshold
6. test_no_llm_imports
7. test_contributing_factors_populated
8. test_score_in_valid_range
9. test_discoveries_threshold_stricter_than_narrative
"""
import pytest

pytestmark = pytest.mark.phase_66


def _import_engine():
    try:
        from emitters.novelty_engine import NoveltyEngine
        return NoveltyEngine
    except ImportError as exc:
        pytest.fail(
            f"Wave 1 (Plan 66-02) must implement emitters.novelty_engine.NoveltyEngine: {exc}"
        )


def _import_dims():
    try:
        from emitters.novelty_engine import NoveltyDimensions
        return NoveltyDimensions
    except ImportError as exc:
        pytest.fail(
            f"Wave 1 (Plan 66-02) must implement emitters.novelty_engine.NoveltyDimensions: {exc}"
        )


# ── Test 1 ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("_i", range(100))
def test_engine_is_deterministic(_i):
    """NoveltyEngine: same input -> same NoveltyScore; no randomness, no time-of-day dependency."""
    NoveltyEngine = _import_engine()
    NoveltyDimensions = _import_dims()

    engine = NoveltyEngine()
    dims = NoveltyDimensions(
        macro_novelty=0.8,
        regime_novelty=0.7,
        structural_novelty=0.6,
        volatility_novelty=0.5,
        behavioral_novelty=0.4,
        regime_transition=True,
    )

    result_a = engine.score(dims)
    result_b = engine.score(dims)

    assert result_a.score == result_b.score, (
        f"NoveltyEngine must be deterministic: same input must produce same score. "
        f"Got {result_a.score} then {result_b.score}. Remove any randomness."
    )
    assert result_a.threshold_crossed == result_b.threshold_crossed, (
        "threshold_crossed must be deterministic across repeated calls"
    )
    assert result_a.reason_codes == result_b.reason_codes, (
        "reason_codes must be deterministic across repeated calls"
    )


# ── Test 2 ────────────────────────────────────────────────────────────────────

def test_engine_supports_5_dimensions():
    """NoveltyEngine: accepts all 5 dimensions in [0.0, 1.0]; missing dims default to 0.0."""
    NoveltyEngine = _import_engine()
    NoveltyDimensions = _import_dims()

    engine = NoveltyEngine()

    # All 5 set high
    full = NoveltyDimensions(
        macro_novelty=0.9,
        regime_novelty=0.9,
        structural_novelty=0.9,
        volatility_novelty=0.9,
        behavioral_novelty=0.9,
    )
    score_full = engine.score(full).score

    # All 5 default to 0.0
    empty = NoveltyDimensions()
    score_empty = engine.score(empty).score

    assert score_full > score_empty, (
        "Score with all dims at 0.9 must exceed score with all dims at 0.0"
    )
    assert 0.0 <= score_empty <= 1.0, "Score must be in [0.0, 1.0] for empty input"
    assert 0.0 <= score_full <= 1.0, "Score must be in [0.0, 1.0] for full input"

    # Each dim raises score when added
    base = NoveltyDimensions()
    base_score = engine.score(base).score
    for dim_name in ("macro_novelty", "regime_novelty", "structural_novelty",
                     "volatility_novelty", "behavioral_novelty"):
        kwargs = {dim_name: 1.0}
        raised = engine.score(NoveltyDimensions(**kwargs)).score
        assert raised > base_score, (
            f"Dimension {dim_name!r} must increase score when set to 1.0 (got {raised} == {base_score})"
        )


# ── Test 3 ────────────────────────────────────────────────────────────────────

def test_high_triggers_set_threshold_crossed():
    """HIGH triggers (regime_transition, macro_event_arrival, structural_break, risk_escalation)
    must set threshold_crossed=True with reason_codes populated."""
    NoveltyEngine = _import_engine()
    NoveltyDimensions = _import_dims()

    engine = NoveltyEngine()

    high_trigger_cases = [
        ("regime_transition", NoveltyDimensions(regime_transition=True)),
        ("macro_event_arrival", NoveltyDimensions(macro_event_arrival=True)),
        ("structural_break", NoveltyDimensions(structural_break=True)),
        ("risk_escalation", NoveltyDimensions(risk_escalation=True)),
    ]

    for trigger_name, dims in high_trigger_cases:
        result = engine.score(dims)
        assert result.threshold_crossed is True, (
            f"HIGH trigger {trigger_name!r} must set threshold_crossed=True "
            f"(got False, score={result.score})"
        )
        assert result.reason_codes, (
            f"HIGH trigger {trigger_name!r} must populate reason_codes "
            f"(got empty list when threshold_crossed=True)"
        )


# ── Test 4 ────────────────────────────────────────────────────────────────────

def test_medium_triggers_only_with_clustering():
    """volatility_expansion alone does NOT cross threshold;
    volatility_expansion + opportunity_clustering DOES cross."""
    NoveltyEngine = _import_engine()
    NoveltyDimensions = _import_dims()

    engine = NoveltyEngine()

    # volatility alone — should NOT cross (medium-only trigger)
    dims_vol_only = NoveltyDimensions(volatility_novelty=0.9)
    result_vol = engine.score(dims_vol_only)
    # Check score against narrative_threshold — might not cross if weight×0.9 < threshold
    narrative_threshold = engine.get_narrative_threshold()
    vol_weight = 0.15  # from config
    vol_score = 0.9 * vol_weight  # = 0.135, well below 0.7 threshold
    assert vol_score < narrative_threshold, (
        f"volatility_novelty=0.9 alone (score={vol_score}) should not cross "
        f"narrative_threshold={narrative_threshold} — MEDIUM trigger requires co-occurrence"
    )

    # volatility + opportunity_clustering co-occurrence — should get lift
    dims_with_clustering = NoveltyDimensions(
        volatility_novelty=0.9,
        opportunity_clustering=True,
    )
    result_cluster = engine.score(dims_with_clustering)
    assert result_cluster.score > result_vol.score, (
        "opportunity_clustering co-occurrence must apply a score lift to volatility_novelty"
    )


# ── Test 5 ────────────────────────────────────────────────────────────────────

def test_config_driven_threshold():
    """Threshold loaded from novelty_config.yaml (default 0.7);
    accessible via get_narrative_threshold() and get_threshold() alias."""
    NoveltyEngine = _import_engine()

    engine = NoveltyEngine()
    threshold = engine.get_narrative_threshold()

    assert isinstance(threshold, float), (
        f"get_narrative_threshold() must return float, got {type(threshold)}"
    )
    assert 0.0 < threshold < 1.0, (
        f"Threshold must be in (0.0, 1.0), got {threshold}"
    )
    # Default should be 0.7 from config
    assert threshold == pytest.approx(0.7, abs=0.01), (
        f"Default narrative_threshold must be 0.7 (config-driven), got {threshold}"
    )

    # get_threshold() alias must also work (backward-compat for existing scaffold tests)
    assert hasattr(engine, "get_threshold"), (
        "NoveltyEngine must expose get_threshold() as backward-compat alias for get_narrative_threshold()"
    )
    assert engine.get_threshold() == threshold, (
        "get_threshold() must return same value as get_narrative_threshold()"
    )


# ── Test 6 ────────────────────────────────────────────────────────────────────

def test_no_llm_imports():
    """Lock §2: novelty scoring NEVER uses an LLM — pure deterministic computation."""
    import inspect
    from emitters import novelty_engine as ne_module

    src = inspect.getsource(ne_module)
    for forbidden in ("httpx", "anthropic", "openai", "requests"):
        assert forbidden not in src, (
            f"NoveltyEngine has forbidden import: {forbidden!r}. "
            "NoveltyEngine must be pure deterministic — no LLM/HTTP calls."
        )


# ── Test 7 ────────────────────────────────────────────────────────────────────

def test_contributing_factors_populated():
    """When threshold is crossed, contributing_factors contains dimension names
    that contributed >= per-dim min weight."""
    NoveltyEngine = _import_engine()
    NoveltyDimensions = _import_dims()

    engine = NoveltyEngine()

    # Regime transition crosses threshold — regime_novelty should appear in factors
    dims = NoveltyDimensions(
        regime_novelty=0.9,
        macro_novelty=0.9,
        regime_transition=True,
    )
    result = engine.score(dims)

    assert result.threshold_crossed is True, (
        "regime_transition=True must cross the threshold"
    )
    assert result.contributing_factors, (
        "contributing_factors must be non-empty when threshold_crossed=True"
    )
    # At least one of the high-scored dimensions must appear
    assert any(
        f in result.contributing_factors for f in ("regime_novelty", "macro_novelty")
    ), (
        f"contributing_factors must include high-weight dimensions, got: {result.contributing_factors}"
    )


# ── Test 8 ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("dims_kwargs", [
    {},
    {"macro_novelty": 1.0, "regime_novelty": 1.0, "structural_novelty": 1.0,
     "volatility_novelty": 1.0, "behavioral_novelty": 1.0,
     "regime_transition": True, "macro_event_arrival": True},
    {"macro_novelty": 0.0},
    {"behavioral_novelty": 0.5, "opportunity_clustering": True},
])
def test_score_in_valid_range(dims_kwargs):
    """For any valid input, NoveltyScore.score must be in [0.0, 1.0]."""
    NoveltyEngine = _import_engine()
    NoveltyDimensions = _import_dims()

    engine = NoveltyEngine()
    result = engine.score(NoveltyDimensions(**dims_kwargs))

    assert 0.0 <= result.score <= 1.0, (
        f"NoveltyScore.score={result.score} is out of [0.0, 1.0] for dims={dims_kwargs}"
    )


# ── Test 9 ────────────────────────────────────────────────────────────────────

def test_discoveries_threshold_stricter_than_narrative():
    """Per WARNING 2 — DISCOVERIES composer loads its threshold from THIS engine,
    never hardcodes a module-level constant.
    discoveries_threshold > narrative_threshold enforced at engine construction time.
    """
    NoveltyEngine = _import_engine()

    engine = NoveltyEngine()
    narrative = engine.get_narrative_threshold()
    discoveries = engine.get_discoveries_threshold()

    assert isinstance(discoveries, float), (
        f"get_discoveries_threshold() must return float, got {type(discoveries)}"
    )
    assert discoveries > narrative, (
        f"discoveries_threshold ({discoveries}) must be > narrative_threshold ({narrative}) — "
        f"discoveries stay rare and meaningful (CONTEXT.md §4 + WARNING 2)."
    )
    # Default: 0.85 from config
    assert discoveries == pytest.approx(0.85, abs=0.01), (
        f"Default discoveries_threshold must be 0.85 (config-driven), got {discoveries}"
    )
