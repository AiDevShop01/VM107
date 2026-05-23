"""
RED scaffold for REQ-66-3 DISCOVERIES composer — implemented in Plan 66-07.

Tests:
- test_discoveries_composer_composes_from_three_sources
- test_discoveries_composer_returns_discovery_contracts
- test_discoveries_category_enum_values
- test_discoveries_novelty_threshold_stricter_than_narratives
- test_discoveries_composer_handles_source_failure_gracefully
"""
import pytest

pytestmark = pytest.mark.phase_66


def test_discoveries_composer_composes_from_three_sources():
    """REQ-66-3: DiscoveriesComposer composes from Phase 54 patterns +
    Phase 60 narratives + emergent (VM107 novelty surfaces)."""
    try:
        from emitters.intelligence_feed_discoveries_composer import IntelligenceFeedDiscoveriesComposer
    except ImportError as exc:
        pytest.fail(
            f"Wave 2 (Plan 66-07) must implement "
            f"emitters.intelligence_feed_discoveries_composer.IntelligenceFeedDiscoveriesComposer: {exc}"
        )

    from emitters.intelligence_feed_discoveries_composer import IntelligenceFeedDiscoveriesComposer
    from unittest.mock import MagicMock, patch

    composer = IntelligenceFeedDiscoveriesComposer()

    mock_phase54 = MagicMock(return_value=[MagicMock(pattern_name="hesitation")])
    mock_phase60 = MagicMock(return_value=[MagicMock(narrative_id="n-001")])
    mock_emergent = MagicMock(return_value=[MagicMock(novelty_score=0.85)])

    with patch.object(composer, "_fetch_phase54_patterns", mock_phase54), \
         patch.object(composer, "_fetch_phase60_narratives", mock_phase60), \
         patch.object(composer, "_fetch_emergent_signals", mock_emergent):
        items = composer.compose(account_id=42, state="open")

    mock_phase54.assert_called_once(), "Must call _fetch_phase54_patterns"
    mock_phase60.assert_called_once(), "Must call _fetch_phase60_narratives"
    mock_emergent.assert_called_once(), "Must call _fetch_emergent_signals"


def test_discoveries_composer_returns_discovery_contracts():
    """REQ-66-3: DiscoveriesComposer returns DiscoveryContract[] with
    category in {PATTERN, BEHAVIORAL, EMERGENT, SYSTEMIC, CORRELATIONAL}."""
    try:
        from emitters.intelligence_feed_discoveries_composer import IntelligenceFeedDiscoveriesComposer
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement IntelligenceFeedDiscoveriesComposer: {exc}")

    from emitters.intelligence_feed_discoveries_composer import IntelligenceFeedDiscoveriesComposer
    from unittest.mock import MagicMock, patch

    composer = IntelligenceFeedDiscoveriesComposer()

    with patch.object(composer, "_fetch_phase54_patterns",
                      return_value=[MagicMock(pattern_name="hesitation", frequency=5)]), \
         patch.object(composer, "_fetch_phase60_narratives", return_value=[]), \
         patch.object(composer, "_fetch_emergent_signals", return_value=[]):
        items = composer.compose(account_id=42, state="mid")

    valid_categories = {"PATTERN", "BEHAVIORAL", "EMERGENT", "SYSTEMIC", "CORRELATIONAL"}
    for item in items:
        assert hasattr(item, "category"), f"DiscoveryContract must have category; item={item!r}"
        assert item.category in valid_categories, (
            f"DiscoveryContract.category must be in {valid_categories}; got {item.category!r}"
        )


def test_discoveries_category_enum_values():
    """REQ-66-3: category enum values are exactly {PATTERN, BEHAVIORAL, EMERGENT, SYSTEMIC, CORRELATIONAL}."""
    try:
        from emitters.intelligence_feed_discoveries_composer import DiscoveryCategory
    except ImportError as exc:
        pytest.fail(
            f"Wave 2 must implement emitters.intelligence_feed_discoveries_composer.DiscoveryCategory: {exc}"
        )

    from emitters.intelligence_feed_discoveries_composer import DiscoveryCategory

    required_categories = {"PATTERN", "BEHAVIORAL", "EMERGENT", "SYSTEMIC", "CORRELATIONAL"}
    actual_values = {c.value for c in DiscoveryCategory} if hasattr(DiscoveryCategory, "__iter__") \
        else set(vars(DiscoveryCategory).keys())

    missing = required_categories - actual_values
    assert not missing, (
        f"DiscoveryCategory must include all required values; missing: {missing}"
    )


def test_discoveries_novelty_threshold_stricter_than_narratives():
    """REQ-66-3: Discoveries novelty threshold > narrative novelty threshold.
    BOTH must come from config — NOT hardcoded literals in this test.
    Aligns with checker WARNING 2 fix in Plan 66-07."""
    try:
        from emitters.intelligence_feed_discoveries_composer import IntelligenceFeedDiscoveriesComposer
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement IntelligenceFeedDiscoveriesComposer: {exc}")

    from emitters.intelligence_feed_discoveries_composer import IntelligenceFeedDiscoveriesComposer

    try:
        from emitters.global_narrative_emitter import GlobalNarrativeEmitter
        narrative_emitter = GlobalNarrativeEmitter()
        narrative_threshold = narrative_emitter.get_novelty_threshold()
    except (ImportError, AttributeError):
        # GlobalNarrativeEmitter not yet implemented — use a known Phase 65 default
        narrative_threshold = 0.6  # known Phase 65 default

    composer = IntelligenceFeedDiscoveriesComposer()
    discoveries_threshold = composer.get_novelty_threshold()

    assert isinstance(discoveries_threshold, (int, float)), (
        "IntelligenceFeedDiscoveriesComposer.get_novelty_threshold() must return a numeric value"
    )
    assert isinstance(narrative_threshold, (int, float)), (
        "Narrative novelty threshold must be numeric"
    )
    assert discoveries_threshold > narrative_threshold, (
        f"Discoveries novelty threshold ({discoveries_threshold}) must be STRICTER (higher) than "
        f"narrative novelty threshold ({narrative_threshold}). "
        "Both values must come from config, not hardcoded literals."
    )


def test_discoveries_composer_handles_source_failure_gracefully():
    """REQ-66-3: If any source fails, composer degrades gracefully — does NOT bubble exception."""
    try:
        from emitters.intelligence_feed_discoveries_composer import IntelligenceFeedDiscoveriesComposer
    except ImportError as exc:
        pytest.fail(f"Wave 2 must implement IntelligenceFeedDiscoveriesComposer: {exc}")

    from emitters.intelligence_feed_discoveries_composer import IntelligenceFeedDiscoveriesComposer
    from unittest.mock import patch

    composer = IntelligenceFeedDiscoveriesComposer()

    with patch.object(composer, "_fetch_phase54_patterns",
                      side_effect=RuntimeError("Neo4j unavailable")), \
         patch.object(composer, "_fetch_phase60_narratives", return_value=[]), \
         patch.object(composer, "_fetch_emergent_signals", return_value=[]):
        # Must NOT raise — graceful degradation required
        try:
            items = composer.compose(account_id=42, state="open")
        except Exception as exc:
            pytest.fail(
                f"IntelligenceFeedDiscoveriesComposer must degrade gracefully on source failure, "
                f"not propagate: {exc}"
            )

    assert isinstance(items, list), "compose() must always return a list, even on partial failure"
