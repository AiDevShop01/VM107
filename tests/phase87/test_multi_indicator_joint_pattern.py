"""Phase 87 Plan 10 — REQ-87-9 multi-indicator joint pattern detector.

When ≥3 anchor indicators in the 12h window share the same surprise
direction as the top-|surprise| indicator, the joint-pattern flag MUST
fire. The flag is then propagated to the ``regime_transition_detected``
event payload + Phase 74 notification metadata so the consumer can
render "joint pattern across X, Y, Z" copy.
"""
from __future__ import annotations

import pytest

from agents.macro_regime_monitor.skill_transition_detection import (
    _top_indicators,
)


pytestmark = pytest.mark.phase_87


def test_three_anchors_same_direction_joint_pattern():
    """3 anchors, all positive surprises → joint pattern detected."""
    releases = {
        "CPIAUCSL": [{"release_date": "2026-06-12T08:30:00Z", "surprise": +0.20}],
        "UNRATE":   [{"release_date": "2026-06-12T12:30:00Z", "surprise": +0.10}],
        "GDP":      [{"release_date": "2026-06-12T14:30:00Z", "surprise": +0.30}],
    }
    top3, joint = _top_indicators(releases)
    assert sorted(top3) == ["CPIAUCSL", "GDP", "UNRATE"]
    assert joint is True


def test_three_anchors_mixed_direction_no_joint_pattern():
    """3 anchors, mixed directions → no joint pattern (top-3 disagree)."""
    releases = {
        "CPIAUCSL": [{"release_date": "2026-06-12T08:30:00Z", "surprise": +0.20}],
        "UNRATE":   [{"release_date": "2026-06-12T12:30:00Z", "surprise": -0.10}],
        "GDP":      [{"release_date": "2026-06-12T14:30:00Z", "surprise": -0.30}],
    }
    top3, joint = _top_indicators(releases)
    # GDP is top by |surprise| (-0.30); GDP is negative; UNRATE negative
    # too, but CPIAUCSL positive → top-3 do not all agree.
    assert "GDP" in top3
    assert joint is False


def test_three_anchors_all_negative_joint_pattern():
    """3 anchors, all negative surprises → joint pattern fires."""
    releases = {
        "CPIAUCSL": [{"release_date": "2026-06-12T08:30:00Z", "surprise": -0.20}],
        "UNRATE":   [{"release_date": "2026-06-12T12:30:00Z", "surprise": -0.10}],
        "GDP":      [{"release_date": "2026-06-12T14:30:00Z", "surprise": -0.30}],
    }
    top3, joint = _top_indicators(releases)
    assert joint is True


def test_one_indicator_no_joint_pattern():
    """Single indicator → cannot establish joint pattern."""
    releases = {
        "CPIAUCSL": [{"release_date": "2026-06-12T08:30:00Z", "surprise": +0.20}],
    }
    top3, joint = _top_indicators(releases)
    assert top3 == ["CPIAUCSL"]
    assert joint is False


def test_two_indicators_no_joint_pattern():
    """REQ-87-9 — joint pattern requires ≥3 indicators in the window."""
    releases = {
        "CPIAUCSL": [{"release_date": "2026-06-12T08:30:00Z", "surprise": +0.20}],
        "UNRATE":   [{"release_date": "2026-06-12T12:30:00Z", "surprise": +0.10}],
    }
    top3, joint = _top_indicators(releases)
    assert sorted(top3) == ["CPIAUCSL", "UNRATE"]
    assert joint is False


def test_empty_releases_returns_empty_top3_no_joint():
    """No releases in window → empty top3, no joint pattern."""
    top3, joint = _top_indicators({})
    assert top3 == []
    assert joint is False


def test_zero_surprise_top_indicator_no_joint_pattern():
    """When the top indicator has surprise=0, direction is undefined."""
    releases = {
        "CPIAUCSL": [{"release_date": "2026-06-12T08:30:00Z", "surprise": 0.0}],
        "UNRATE":   [{"release_date": "2026-06-12T12:30:00Z", "surprise": 0.0}],
        "GDP":      [{"release_date": "2026-06-12T14:30:00Z", "surprise": 0.0}],
    }
    _top3, joint = _top_indicators(releases)
    assert joint is False
