"""REQ-83-6 — NoveltyEngine V1: 5 novelty dimensions + macro_novelty live implementation.

Plan 83-08 GREENs all tests in this file by shipping:
  VM107/lib/novelty_engine/: NoveltyEngine, NoveltyScore, NoveltyDimensions + 5 dimension modules
  VM107/emitters/novelty_engine.py: back-compat re-export shim (was live impl)
  VM107/services/novelty_engine.py: back-compat re-export shim (was re-export from emitters)

Phase 66 Lock E1: NoveltyScore is ALWAYS deterministic, NEVER LLM-supplied.
Phase 66 Lock E2: NoveltyEngine colocated in VM107/lib/ (shared infra for all emitters).

Import convention: VM107 root is on sys.path (see conftest.py), so imports use
  `from lib.novelty_engine import ...` (NOT `from VM107.lib.novelty_engine import ...`).
"""
import warnings
from datetime import datetime, timezone, timedelta

import pytest


# ── Task 1 tests: core lib + 5 dimensions ────────────────────────────────────

@pytest.mark.phase83
def test_all_5_dimensions_present():
    """NoveltyDimensions enum contains all 5 novelty dimensions.

    REQ-83-E1: The enum must have exactly MACRO, REGIME, STRUCTURAL, VOLATILITY,
    BEHAVIORAL — omitting a dimension would silently under-filter MACRO tab items.
    """
    from lib.novelty_engine import NoveltyDimensions

    expected = {"macro_novelty", "regime_novelty", "structural_novelty", "volatility_novelty", "behavioral_novelty"}
    actual = {d.value for d in NoveltyDimensions}
    assert actual == expected, f"Dimension mismatch: {actual} != {expected}"


@pytest.mark.phase83
def test_macro_novelty_live_impl():
    """score_macro() returns a NoveltyScore with score in [0.0, 1.0] and populated fields.

    REQ-83-E1: MacroNovelty is the only LIVE implementation in V1.
    """
    from lib.novelty_engine.macro import score_macro

    future_iso = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
    result = score_macro({
        "indicator_code": "CPIAUCSL",
        "releasing_authority": "BLS",
        "event_date": future_iso,
        "severity": "HIGH",
    })

    assert hasattr(result, "score"), "NoveltyScore missing .score"
    assert hasattr(result, "contributing_factors"), "NoveltyScore missing .contributing_factors"
    assert hasattr(result, "threshold_crossed"), "NoveltyScore missing .threshold_crossed"
    assert hasattr(result, "reason_codes"), "NoveltyScore missing .reason_codes"
    assert 0.0 <= result.score <= 1.0, f"score out of range: {result.score}"
    assert isinstance(result.contributing_factors, list)
    assert isinstance(result.reason_codes, list)


@pytest.mark.phase83
def test_macro_novelty_high_score_for_fed_critical_first_ever():
    """score_macro with FED + CRITICAL + cold-start history + imminent event → score > 0.7 + threshold_crossed=True.

    REQ-83-E1: Scoring rules V1 — FED(+0.3) + CRITICAL(+0.2) + cold-start(+0.3) + ≤6h(+0.2) = 1.0.
    """
    from lib.novelty_engine.macro import score_macro

    # history_provider returns 0 (cold start — never seen this indicator before)
    def cold_start_provider(indicator_code):
        return 0

    now_plus_2h = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    result = score_macro(
        {
            "indicator_code": "FOMC_RATE",
            "releasing_authority": "FED",
            "event_date": now_plus_2h,
            "severity": "CRITICAL",
        },
        history_provider=cold_start_provider,
        threshold=0.5,
    )

    assert result.score > 0.7, f"Expected score > 0.7 for FED+CRITICAL+cold-start+imminent, got {result.score}"
    assert result.threshold_crossed is True
    assert "AUTH_FED" in result.reason_codes
    assert "SEV_CRITICAL" in result.reason_codes
    assert "FIRST_EVER_OCCURRENCE" in result.reason_codes
    assert "URGENT_RELEASE" in result.reason_codes


@pytest.mark.phase83
def test_macro_novelty_low_score_for_familiar_low_severity():
    """score_macro with non-FED + LOW severity + warm history + non-urgent → score < 0.5 + threshold_crossed=False.

    REQ-83-E1: Familiar, low-severity, non-urgent releases get low novelty scores.
    """
    from lib.novelty_engine.macro import score_macro

    # history_provider returns many prior occurrences (warm — familiar indicator)
    def warm_provider(indicator_code):
        return 50

    far_future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    result = score_macro(
        {
            "indicator_code": "CPIAUCSL",
            "releasing_authority": "BLS",
            "event_date": far_future,
            "severity": "LOW",
        },
        history_provider=warm_provider,
        threshold=0.5,
    )

    assert result.score < 0.5, f"Expected score < 0.5 for non-FED+LOW+warm+not-urgent, got {result.score}"
    assert result.threshold_crossed is False


@pytest.mark.phase83
def test_regime_novelty_stub():
    """score_regime() raises NotImplementedError with message naming Phase 66 RegimeEmitter.

    REQ-83-E1: Stub dimensions must have informative error messages for Phase 66 emitter authors.
    """
    from lib.novelty_engine.regime import score_regime

    with pytest.raises(NotImplementedError) as exc_info:
        score_regime({"regime_label": "TREND"})

    assert "Phase 66" in str(exc_info.value), "NotImplementedError should mention Phase 66"
    assert "RegimeEmitter" in str(exc_info.value), "NotImplementedError should name RegimeEmitter"


@pytest.mark.phase83
def test_structural_novelty_stub():
    """score_structural() raises NotImplementedError with informative message."""
    from lib.novelty_engine.structural import score_structural

    with pytest.raises(NotImplementedError) as exc_info:
        score_structural({"fvg_count": 3})

    assert "Phase 66" in str(exc_info.value)
    assert "Structural" in str(exc_info.value) or "structural" in str(exc_info.value)


@pytest.mark.phase83
def test_volatility_novelty_stub():
    """score_volatility() raises NotImplementedError with informative message."""
    from lib.novelty_engine.volatility import score_volatility

    with pytest.raises(NotImplementedError) as exc_info:
        score_volatility({"atr_multiple": 1.5})

    assert "Phase 66" in str(exc_info.value)
    assert "Volatility" in str(exc_info.value) or "volatility" in str(exc_info.value)


@pytest.mark.phase83
def test_behavioral_novelty_stub():
    """score_behavioral() raises NotImplementedError with informative message."""
    from lib.novelty_engine.behavioral import score_behavioral

    with pytest.raises(NotImplementedError) as exc_info:
        score_behavioral({"session_edge_score": 0.8})

    assert "Phase 66" in str(exc_info.value)
    assert "Behavioral" in str(exc_info.value) or "behavioral" in str(exc_info.value)


@pytest.mark.phase83
def test_novelty_engine_dispatch():
    """NoveltyEngine.score(MACRO, payload) dispatches to score_macro; REGIME raises NotImplementedError."""
    from lib.novelty_engine import NoveltyEngine, NoveltyDimensions

    engine = NoveltyEngine()
    future_iso = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
    result = engine.score(
        NoveltyDimensions.MACRO,
        {
            "indicator_code": "CPIAUCSL",
            "releasing_authority": "BLS",
            "event_date": future_iso,
            "severity": "HIGH",
        },
    )
    assert 0.0 <= result.score <= 1.0

    with pytest.raises(NotImplementedError):
        engine.score(NoveltyDimensions.REGIME, {"regime_label": "TREND"})


@pytest.mark.phase83
def test_novelty_score_is_deterministic():
    """Calling score_macro twice with identical input returns identical NoveltyScore.

    Phase 66 Lock E1: NoveltyScore is ALWAYS deterministic, NEVER LLM-supplied.
    """
    from lib.novelty_engine.macro import score_macro

    fixed_iso = "2026-06-13T08:30:00+00:00"
    payload = {
        "indicator_code": "CPIAUCSL",
        "releasing_authority": "BLS",
        "event_date": fixed_iso,
        "severity": "HIGH",
    }
    result1 = score_macro(payload)
    result2 = score_macro(payload)

    assert result1 == result2, "score_macro must be deterministic for identical inputs"


@pytest.mark.phase83
def test_history_provider_redis_or_in_memory():
    """history_provider abstraction works with an in-memory dict provider.

    The history_provider callable takes an indicator_code and returns a count.
    For tests, an in-memory dict suffices. In production, a Redis provider is used.
    """
    from lib.novelty_engine.macro import score_macro

    history_store: dict = {}

    def in_memory_provider(indicator_code: str) -> int:
        return history_store.get(indicator_code, 0)

    # Cold start — no history for PCEPI
    now_plus_1h = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    cold_result = score_macro(
        {"indicator_code": "PCEPI", "releasing_authority": "BEA", "event_date": now_plus_1h, "severity": "MEDIUM"},
        history_provider=in_memory_provider,
    )
    assert "FIRST_EVER_OCCURRENCE" in cold_result.reason_codes, (
        "Cold start (0 prior occurrences) should produce FIRST_EVER_OCCURRENCE code"
    )

    # Warm — add history for PCEPI
    history_store["PCEPI"] = 10
    warm_result = score_macro(
        {"indicator_code": "PCEPI", "releasing_authority": "BEA", "event_date": now_plus_1h, "severity": "MEDIUM"},
        history_provider=in_memory_provider,
    )
    assert "FIRST_EVER_OCCURRENCE" not in warm_result.reason_codes, (
        "Warm history (10 prior occurrences) should NOT produce FIRST_EVER_OCCURRENCE code"
    )
    # cold score should be higher than warm (cold start adds +0.3)
    assert cold_result.score > warm_result.score


# ── Task 2 tests: back-compat shims ──────────────────────────────────────────

@pytest.mark.phase83
def test_emitters_shim_emits_deprecation_warning():
    """Importing from emitters.novelty_engine emits a DeprecationWarning.

    The warning message must mention 'VM107.lib.novelty_engine' so consumers
    know where to migrate their imports.
    """
    import importlib
    import sys

    # Remove any cached import so the warning fires fresh
    for key in list(sys.modules.keys()):
        if "emitters.novelty_engine" in key or key == "emitters.novelty_engine":
            del sys.modules[key]

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        importlib.import_module("emitters.novelty_engine")

    dep_warnings = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert dep_warnings, "Expected DeprecationWarning from emitters.novelty_engine import"
    assert any("VM107.lib.novelty_engine" in str(w.message) for w in dep_warnings), (
        "DeprecationWarning must mention VM107.lib.novelty_engine"
    )


@pytest.mark.phase83
def test_services_shim_emits_deprecation_warning():
    """Importing from services.novelty_engine emits a DeprecationWarning.

    The warning message must mention 'VM107.lib.novelty_engine'.
    """
    import importlib
    import sys

    for key in list(sys.modules.keys()):
        if "services.novelty_engine" in key or key == "services.novelty_engine":
            del sys.modules[key]

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        importlib.import_module("services.novelty_engine")

    dep_warnings = [w for w in captured if issubclass(w.category, DeprecationWarning)]
    assert dep_warnings, "Expected DeprecationWarning from services.novelty_engine import"
    assert any("VM107.lib.novelty_engine" in str(w.message) for w in dep_warnings), (
        "DeprecationWarning must mention VM107.lib.novelty_engine"
    )


@pytest.mark.phase83
def test_shim_re_exports_all_5_dimensions():
    """After import from the emitters shim, score_macro is callable + NoveltyDimensions has 5 members."""
    import importlib
    import sys

    for key in list(sys.modules.keys()):
        if "emitters.novelty_engine" in key or key == "emitters.novelty_engine":
            del sys.modules[key]

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        mod = importlib.import_module("emitters.novelty_engine")

    assert callable(getattr(mod, "score_macro", None)), "emitters shim must re-export score_macro"
    dims = getattr(mod, "NoveltyDimensions", None)
    assert dims is not None, "emitters shim must re-export NoveltyDimensions"
    assert len(list(dims)) == 5, f"NoveltyDimensions must have 5 members, got {len(list(dims))}"


@pytest.mark.phase83
def test_no_duplicate_implementation():
    """Neither shim file contains actual scoring function definitions.

    Regression guard: if someone re-adds scoring logic to the shim files (duplicating
    the canonical implementation), this test catches it at commit time.
    """
    import ast
    from pathlib import Path

    vm107_root = Path(__file__).resolve().parent.parent.parent
    shim_paths = [
        vm107_root / "emitters" / "novelty_engine.py",
        vm107_root / "services" / "novelty_engine.py",
    ]

    scoring_fn_names = {"score_macro", "score_regime", "score_structural", "score_volatility", "score_behavioral"}

    for shim_path in shim_paths:
        assert shim_path.exists(), f"Shim file not found: {shim_path}"
        tree = ast.parse(shim_path.read_text())
        defined_functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        violations = defined_functions & scoring_fn_names
        assert not violations, (
            f"{shim_path.name} must not define scoring functions (regression: duplication). "
            f"Found: {violations}"
        )
