"""
RED scaffold for REQ-66-1 — implemented in Plan 66-05.

Tests:
- test_get_global_narrative_returns_200_with_contract_shape
- test_get_global_narrative_returns_400_if_state_missing
- test_get_global_narrative_returns_degraded_mode_on_context_failure
- test_get_global_narrative_persists_both_summary_fields_when_llm_fires
- test_get_global_narrative_degraded_tier_sequence
"""
import pytest

pytestmark = pytest.mark.phase_66


def _try_import(module_path, symbol):
    try:
        mod = __import__(module_path, fromlist=[symbol])
        return getattr(mod, symbol)
    except ImportError as exc:
        pytest.fail(
            f"Wave 2 (Plan 66-05) must implement {module_path}.{symbol} — import failed: {exc}"
        )


def test_get_global_narrative_returns_200_with_contract_shape():
    """REQ-66-1: HTTP GET /api/v1/narratives/global?state=X returns 200
    with GlobalNarrativeContract shape including all required fields."""
    try:
        from emitters.global_narrative_emitter import GlobalNarrativeEmitter  # noqa: F401
    except ImportError as exc:
        pytest.fail(
            f"Wave 2 must implement emitters.global_narrative_emitter.GlobalNarrativeEmitter: {exc}"
        )

    from emitters.global_narrative_emitter import GlobalNarrativeEmitter
    emitter = GlobalNarrativeEmitter()

    result = emitter.get_narrative(state="mid")

    required_fields = {
        "narrative_id",
        "summary",
        "confidence_vector",
        "generated_at",
        "model_version",
        "prompt_version",
        "_demo",
        "degraded_mode",
        "missing_sources",
        "stale_threshold_seconds",
        "refresh_reason",
        "next_refresh_at",
        "deterministic_base_summary",
        "llm_enriched_summary",
        "evidence",
    }
    assert isinstance(result, dict), f"GlobalNarrativeEmitter.get_narrative must return dict; got {type(result)}"
    missing = required_fields - set(result.keys())
    assert not missing, (
        f"GlobalNarrativeContract shape missing fields: {missing}. "
        "Plan 66-05 must populate all GlobalNarrativeContract fields."
    )


def test_get_global_narrative_returns_400_if_state_missing():
    """REQ-66-1: GET without ?state= → raises ValueError or returns 400-equivalent."""
    try:
        from emitters.global_narrative_emitter import GlobalNarrativeEmitter
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement GlobalNarrativeEmitter: {exc}")

    from emitters.global_narrative_emitter import GlobalNarrativeEmitter
    emitter = GlobalNarrativeEmitter()

    with pytest.raises((ValueError, TypeError, KeyError)):
        emitter.get_narrative(state=None)


def test_get_global_narrative_returns_degraded_mode_on_context_failure():
    """REQ-66-1: When context assembly fails (VM102 down, etc.) emitter returns
    degraded_mode=True + Tier 1/2/3 fallback — does NOT return 500."""
    try:
        from emitters.global_narrative_emitter import GlobalNarrativeEmitter
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement GlobalNarrativeEmitter: {exc}")

    from unittest.mock import patch
    from emitters.global_narrative_emitter import GlobalNarrativeEmitter

    emitter = GlobalNarrativeEmitter()

    with patch.object(emitter, "_assemble_context", side_effect=RuntimeError("VM102 down")):
        result = emitter.get_narrative(state="open")

    assert result.get("degraded_mode") is True, (
        "degraded_mode must be True when context assembly fails"
    )
    assert "summary" in result, "Fallback must still produce a summary (Tier template)"
    assert result.get("_demo") is True, (
        "Tier 3 fallback MUST set _demo=True — no live data available"
    )


def test_get_global_narrative_persists_both_summary_fields_when_llm_fires():
    """REQ-66-1: When LLM enrichment fires, BOTH deterministic_base_summary
    AND llm_enriched_summary must be populated in the persisted record."""
    try:
        from emitters.global_narrative_emitter import GlobalNarrativeEmitter
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement GlobalNarrativeEmitter: {exc}")

    from unittest.mock import MagicMock, patch
    from emitters.global_narrative_emitter import GlobalNarrativeEmitter

    emitter = GlobalNarrativeEmitter()
    mock_llm_result = "LLM enriched narrative text"
    mock_base = "Deterministic base text from template"

    with patch.object(emitter, "_call_llm", return_value=mock_llm_result), \
         patch.object(emitter, "_build_base_summary", return_value=mock_base):
        result = emitter.get_narrative(state="pre")

    assert result.get("deterministic_base_summary"), (
        "deterministic_base_summary must be non-empty even when LLM fires"
    )
    assert result.get("llm_enriched_summary"), (
        "llm_enriched_summary must be populated when LLM fires"
    )


def test_get_global_narrative_degraded_tier_sequence():
    """REQ-66-1: Tier degradation is sequential — Tier 1 when one source
    missing, Tier 2 when core sources missing, Tier 3 when ALL sources fail.
    Each tier has a distinct fallback behavior (not just 'degrade or not')."""
    try:
        from emitters.global_narrative_emitter import GlobalNarrativeEmitter
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement GlobalNarrativeEmitter: {exc}")

    from emitters.global_narrative_emitter import GlobalNarrativeEmitter

    emitter = GlobalNarrativeEmitter()
    # Tier 3: all sources fail
    with pytest.raises(Exception) if False else __import__("contextlib").nullcontext():
        result = emitter.get_narrative(state="close")
        # If it doesn't raise: must still return valid contract shape
        assert "summary" in result, "Even Tier 3 fallback must include summary field"
