"""REQ-83-E1 — NoveltyEngine V1: 5 novelty dimensions + macro_novelty live implementation.

Wave 4 Plan 09 will GREEN these tests by shipping:
  VM107/emitters/novelty_engine.py: NoveltyEngine with 5 dimension classes

REQ-83-E1 NoveltyEngine V1 requirements:
- 5 dimensions: macro_novelty (LIVE), regime_novelty, structural_novelty,
  volatility_novelty, behavioral_novelty (4 stubs returning 0.0)
- MacroNovelty.score(item) returns 0.0 for identical item, >0.0 for genuinely new item
- All 5 dimensions present in NoveltyEngine.DIMENSIONS list
"""
import pytest


@pytest.mark.phase83
def test_all_5_dimensions_present():
    """NoveltyEngine.DIMENSIONS contains all 5 novelty dimension classes.

    REQ-83-E1: The dimensions list must be exhaustive — omitting a dimension
    would silently under-filter MACRO tab items and cause LLM over-call.
    """
    from emitters.novelty_engine import NoveltyEngine  # noqa: F401

    pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this")


@pytest.mark.phase83
def test_macro_novelty_live_impl():
    """MacroNovelty.score() returns a float in [0.0, 1.0] for a sample item.

    REQ-83-E1: MacroNovelty is the only LIVE implementation in V1. It gates LLM
    narrative enrichment based on semantic similarity to the last N macro items.
    """
    from emitters.novelty_engine import MacroNovelty  # noqa: F401

    pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this")


@pytest.mark.phase83
def test_regime_novelty_stub():
    """RegimeNovelty.score() returns 0.0 (stub — V2 ships in a future phase).

    REQ-83-E1 V1 scope: regime_novelty is a stub returning 0.0. The full
    implementation is deferred to a future phase once the regime detector
    emits versioned snapshots with semantic embeddings.
    """
    from emitters.novelty_engine import RegimeNovelty  # noqa: F401

    pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this")


@pytest.mark.phase83
def test_structural_novelty_stub():
    """StructuralNovelty.score() returns 0.0 (stub — V2 ships in a future phase)."""
    from emitters.novelty_engine import StructuralNovelty  # noqa: F401

    pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this")


@pytest.mark.phase83
def test_volatility_novelty_stub():
    """VolatilityNovelty.score() returns 0.0 (stub — V2 ships in a future phase)."""
    from emitters.novelty_engine import VolatilityNovelty  # noqa: F401

    pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this")


@pytest.mark.phase83
def test_behavioral_novelty_stub():
    """BehavioralNovelty.score() returns 0.0 (stub — V2 ships in a future phase)."""
    from emitters.novelty_engine import BehavioralNovelty  # noqa: F401

    pytest.fail("RED skeleton — Wave 4 Plan 09 will GREEN this")
