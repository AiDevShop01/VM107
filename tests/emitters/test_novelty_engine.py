"""
RED scaffold for NoveltyEngine (shared, used by REQ-66-1 and REQ-66-3) — implemented in Plan 66-02.

Tests:
- test_novelty_engine_is_deterministic
- test_novelty_engine_all_5_dimensions_contribute
- test_threshold_crossed_when_score_ge_configured_threshold
- test_reason_codes_populated_when_threshold_crossed
- test_no_llm_calls_inside_novelty_engine
"""
import pytest

pytestmark = pytest.mark.phase_66


def test_novelty_engine_is_deterministic():
    """NoveltyEngine: same input -> same NoveltyScore; no randomness."""
    try:
        from emitters.novelty_engine import NoveltyEngine
    except ImportError as exc:
        pytest.fail(
            f"Wave 1 (Plan 66-02) must implement emitters.novelty_engine.NoveltyEngine: {exc}"
        )

    from emitters.novelty_engine import NoveltyEngine

    engine = NoveltyEngine()
    test_input = {
        "macro": {"regime_shift": True, "catalyst_count": 2},
        "regime": {"label": "TREND/HIGH_VOL", "confidence": 0.82},
        "structural": {"fvg_count": 3, "sweep_detected": True},
        "volatility": {"atr_multiple": 1.4},
        "behavioral": {"session_edge_score": 0.75},
    }

    score_1 = engine.score(test_input)
    score_2 = engine.score(test_input)

    assert score_1.score == score_2.score, (
        f"NoveltyEngine must be deterministic: same input must produce same score. "
        f"Got {score_1.score} then {score_2.score}. Remove any randomness."
    )
    assert score_1.threshold_crossed == score_2.threshold_crossed, (
        "threshold_crossed must be deterministic across repeated calls"
    )


def test_novelty_engine_all_5_dimensions_contribute():
    """NoveltyEngine: all 5 dimensions {macro, regime, structural, volatility, behavioral}
    contribute to the composite score."""
    try:
        from emitters.novelty_engine import NoveltyEngine
    except ImportError as exc:
        pytest.fail(f"Wave 1 must implement NoveltyEngine: {exc}")

    from emitters.novelty_engine import NoveltyEngine

    engine = NoveltyEngine()

    base_input = {
        "macro": {"regime_shift": False, "catalyst_count": 0},
        "regime": {"label": "RANGE/LOW_VOL", "confidence": 0.5},
        "structural": {"fvg_count": 0, "sweep_detected": False},
        "volatility": {"atr_multiple": 0.8},
        "behavioral": {"session_edge_score": 0.3},
    }

    base_score = engine.score(base_input).score

    # Modify each dimension and verify score changes
    dimension_sensitivity = {}
    for dim in ("macro", "regime", "structural", "volatility", "behavioral"):
        modified = {k: v for k, v in base_input.items()}
        if dim == "macro":
            modified[dim] = {"regime_shift": True, "catalyst_count": 5}
        elif dim == "regime":
            modified[dim] = {"label": "TREND/HIGH_VOL/CHOPPY", "confidence": 0.95}
        elif dim == "structural":
            modified[dim] = {"fvg_count": 8, "sweep_detected": True}
        elif dim == "volatility":
            modified[dim] = {"atr_multiple": 2.5}
        elif dim == "behavioral":
            modified[dim] = {"session_edge_score": 0.95}

        modified_score = engine.score(modified).score
        dimension_sensitivity[dim] = abs(modified_score - base_score)

    for dim, delta in dimension_sensitivity.items():
        assert delta > 0, (
            f"Dimension {dim!r} did not affect NoveltyScore (delta=0). "
            "All 5 dimensions must contribute to the composite score."
        )


def test_threshold_crossed_when_score_ge_configured_threshold():
    """NoveltyEngine: threshold_crossed=True when score >= configured threshold.
    Threshold is config-driven, not hardcoded to 0.7."""
    try:
        from emitters.novelty_engine import NoveltyEngine
    except ImportError as exc:
        pytest.fail(f"Wave 1 must implement NoveltyEngine: {exc}")

    from emitters.novelty_engine import NoveltyEngine
    from unittest.mock import patch

    engine = NoveltyEngine()
    configured_threshold = engine.get_threshold()

    assert isinstance(configured_threshold, (int, float)), (
        "NoveltyEngine.get_threshold() must return a numeric value (config-driven)"
    )

    # Build an input that produces a score >= threshold
    high_novelty_input = {
        "macro": {"regime_shift": True, "catalyst_count": 5},
        "regime": {"label": "TREND/HIGH_VOL/CHOPPY", "confidence": 0.95},
        "structural": {"fvg_count": 8, "sweep_detected": True},
        "volatility": {"atr_multiple": 2.5},
        "behavioral": {"session_edge_score": 0.95},
    }

    result = engine.score(high_novelty_input)
    if result.score >= configured_threshold:
        assert result.threshold_crossed is True, (
            f"threshold_crossed must be True when score={result.score} >= threshold={configured_threshold}"
        )


def test_reason_codes_populated_when_threshold_crossed():
    """NoveltyEngine: reason_codes is non-empty when threshold_crossed=True."""
    try:
        from emitters.novelty_engine import NoveltyEngine
    except ImportError as exc:
        pytest.fail(f"Wave 1 must implement NoveltyEngine: {exc}")

    from emitters.novelty_engine import NoveltyEngine
    from unittest.mock import patch

    engine = NoveltyEngine()

    # Force threshold to 0 so any input crosses it
    with patch.object(engine, "get_threshold", return_value=0.0):
        result = engine.score({
            "macro": {"regime_shift": False, "catalyst_count": 0},
            "regime": {"label": "RANGE", "confidence": 0.3},
            "structural": {"fvg_count": 0, "sweep_detected": False},
            "volatility": {"atr_multiple": 0.5},
            "behavioral": {"session_edge_score": 0.2},
        })

    assert result.threshold_crossed is True, (
        "With threshold=0, any input must cross the threshold"
    )
    assert result.reason_codes, (
        "reason_codes must be non-empty when threshold_crossed=True. "
        "NoveltyEngine must explain WHY the threshold was crossed."
    )


def test_no_llm_calls_inside_novelty_engine():
    """NoveltyEngine: NEVER makes LLM/HTTP calls. Pure deterministic computation only."""
    try:
        from emitters.novelty_engine import NoveltyEngine
        import inspect
        from pathlib import Path
    except ImportError as exc:
        pytest.fail(f"Wave 1 must implement NoveltyEngine: {exc}")

    from emitters.novelty_engine import NoveltyEngine
    from pathlib import Path
    import inspect

    engine = NoveltyEngine()
    source_file = Path(inspect.getfile(NoveltyEngine)).read_text(encoding="utf-8")

    # No HTTP client imports
    assert "import httpx" not in source_file, (
        "NoveltyEngine must NOT import httpx — it is a pure deterministic engine, no HTTP calls"
    )
    assert "import anthropic" not in source_file, (
        "NoveltyEngine must NOT import anthropic — LLM calls forbidden in novelty computation"
    )
    assert "import requests" not in source_file, (
        "NoveltyEngine must NOT import requests — pure computation only"
    )
