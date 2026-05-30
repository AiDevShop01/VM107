"""Phase 73 Plan 08 Task 2 — TierThresholdLoader fail-fast on disallowed tiers.

Tightens the loader to fail-fast on any tier outside the Phase 73 allowed
set {"A+", "DEV", "WATCH"}. INV / INVALIDATED move to the lifecycle pill
(Decision 9), NOT the scoring-tier enum.

These tests run with a mocked TierThreshold backing (no live DB) — the
existing live-DB integration is exercised by the VM100 phase73_08_verify.py.
"""
from __future__ import annotations

import pytest


def test_loader_returns_allowed_tiers_only(monkeypatch):
    """A+ / DEV / WATCH rows load cleanly; loader returns {tier: min_score}."""
    from emitters.scoring import tier_threshold_loader as ttl_mod

    class _StubTierThreshold:
        def __init__(self, tier, min_score):
            self.tier = tier
            self.min_score = min_score

    class _StubManager:
        def filter(self, **_kwargs):
            return [
                _StubTierThreshold("A+", 80),
                _StubTierThreshold("DEV", 60),
                _StubTierThreshold("WATCH", 40),
            ]

    class _StubModel:
        objects = _StubManager()

    # Monkeypatch the import path inside the loader.
    import sys
    fake_models = type(sys)("mission_control.models")
    fake_models.TierThreshold = _StubModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mission_control.models", fake_models)

    result = ttl_mod.TierThresholdLoader().load(strategy_id="default")
    assert result == {"A+": 80, "DEV": 60, "WATCH": 40}


def test_loader_raises_on_invalidated_row(monkeypatch):
    """Stray INVALIDATED row (operator-hand-added) → fail-fast.

    Decision 9 lock: INVALIDATED moved to the lifecycle pill; any
    INVALIDATED row in tier_thresholds is a registry-hygiene defect.
    """
    from emitters.scoring import tier_threshold_loader as ttl_mod

    class _StubTierThreshold:
        def __init__(self, tier, min_score):
            self.tier = tier
            self.min_score = min_score

    class _StubManager:
        def filter(self, **_kwargs):
            return [
                _StubTierThreshold("A+", 80),
                _StubTierThreshold("DEV", 60),
                _StubTierThreshold("WATCH", 40),
                _StubTierThreshold("INVALIDATED", 0),  # stray row
            ]

    class _StubModel:
        objects = _StubManager()

    import sys
    fake_models = type(sys)("mission_control.models")
    fake_models.TierThreshold = _StubModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mission_control.models", fake_models)

    with pytest.raises(ValueError) as exc_info:
        ttl_mod.TierThresholdLoader().load(strategy_id="default")
    assert "INVALIDATED" in str(exc_info.value)
    # Message should point to migration 0049 / 0051 for context.
    assert (
        "0049" in str(exc_info.value)
        or "0051" in str(exc_info.value)
        or "lifecycle" in str(exc_info.value).lower()
    )


def test_loader_raises_on_inv_row(monkeypatch):
    """Stray INV row → fail-fast (same Decision 9 lock)."""
    from emitters.scoring import tier_threshold_loader as ttl_mod

    class _StubTierThreshold:
        def __init__(self, tier, min_score):
            self.tier = tier
            self.min_score = min_score

    class _StubManager:
        def filter(self, **_kwargs):
            return [
                _StubTierThreshold("A+", 80),
                _StubTierThreshold("DEV", 60),
                _StubTierThreshold("WATCH", 40),
                _StubTierThreshold("INV", 0),
            ]

    class _StubModel:
        objects = _StubManager()

    import sys
    fake_models = type(sys)("mission_control.models")
    fake_models.TierThreshold = _StubModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mission_control.models", fake_models)

    with pytest.raises(ValueError) as exc_info:
        ttl_mod.TierThresholdLoader().load(strategy_id="default")
    assert "INV" in str(exc_info.value)


def test_ranker_classify_tier_never_returns_inv_or_invalidated():
    """Phase 73 Decision 9 — classify_tier returns only A+ / DEV / WATCH."""
    from emitters.opportunity_ranker import OpportunityRanker

    ranker = OpportunityRanker()

    # active_invalidation case — previously returned "INVALIDATED"; now returns
    # the lowest valid tier (WATCH) and the lifecycle pill carries the
    # "this opportunity is invalidated" surface.
    tier_invalid = ranker.classify_tier(
        score=92, structural_valid=True, active_invalidation=True
    )
    assert tier_invalid in {"A+", "DEV", "WATCH"}, (
        f"Decision 9 lock: tier enum is {{A+, DEV, WATCH}} only; "
        f"got {tier_invalid!r}"
    )

    # structural_invalid case — previously returned "INV"; now returns WATCH.
    tier_no_struct = ranker.classify_tier(
        score=50, structural_valid=False, active_invalidation=False
    )
    assert tier_no_struct in {"A+", "DEV", "WATCH"}, (
        f"Decision 9 lock: tier enum is {{A+, DEV, WATCH}} only; "
        f"got {tier_no_struct!r}"
    )

    # Below WATCH threshold — previously returned "INV"; now returns WATCH
    # (lowest valid tier).
    tier_below = ranker.classify_tier(
        score=10, structural_valid=True, active_invalidation=False
    )
    assert tier_below in {"A+", "DEV", "WATCH"}, (
        f"Decision 9 lock: tier enum is {{A+, DEV, WATCH}} only; "
        f"got {tier_below!r}"
    )


def test_required_tiers_constant_excludes_inv_and_invalidated():
    """REQUIRED_TIERS module-level constant no longer mentions INV/INVALIDATED."""
    from emitters.scoring.tier_threshold_loader import REQUIRED_TIERS

    assert "INV" not in REQUIRED_TIERS
    assert "INVALIDATED" not in REQUIRED_TIERS
    assert set(REQUIRED_TIERS) == {"A+", "DEV", "WATCH"}
