"""Phase 87 Wave 4b — Plan 87-08 Task 2 — REQ-87-9 multi-indicator joint pattern.

VALIDATION row 87-04-03: seed N simultaneous-direction releases, the
``detect_joint_pattern`` skill MUST identify ≥2 anchors moving correlated
and the LLM directive MUST name them so the eventual story headline is
multi-indicator rather than single-indicator-noise.
"""
import pytest

from agents.macro_story_tracker.skill_multi_indicator_pattern import (
    ANCHOR_INDICATORS,
    detect_joint_pattern,
    joint_pattern_prompt_directive,
)

pytestmark = pytest.mark.phase_87


def test_detects_joint_pattern_when_three_anchors_correlated() -> None:
    releases = [
        {"indicator_id": "CPIAUCSL", "release_date": "2026-06-12", "surprise": +0.2},
        {"indicator_id": "UNRATE",   "release_date": "2026-06-12", "surprise": +0.3},
        {"indicator_id": "NAPMPMI",  "release_date": "2026-06-12", "surprise": +0.1},
    ]
    pattern = detect_joint_pattern(releases)
    assert pattern["has_pattern"] is True
    assert set(pattern["correlated_indicators"]) >= {"CPIAUCSL", "UNRATE"}
    assert pattern["direction"] == +1


def test_directive_names_indicators_and_includes_marker() -> None:
    pattern = {
        "has_pattern": True,
        "correlated_indicators": ["CPIAUCSL", "UNRATE", "NAPMPMI"],
        "direction": +1,
    }
    directive = joint_pattern_prompt_directive(pattern)
    # All three names appear so the LLM can pick 2-3 of them.
    assert "CPIAUCSL" in directive
    assert "UNRATE" in directive
    assert "NAPMPMI" in directive
    # The structural marker the agent's prompt asserts on (REQ-87-9 spec).
    assert "MULTI-INDICATOR" in directive
    assert "rising" in directive


def test_directive_says_falling_for_negative_direction() -> None:
    pattern = {
        "has_pattern": True,
        "correlated_indicators": ["CPIAUCSL", "GDP"],
        "direction": -1,
    }
    assert "falling" in joint_pattern_prompt_directive(pattern)


def test_no_pattern_with_only_one_indicator() -> None:
    releases = [
        {"indicator_id": "CPIAUCSL", "release_date": "2026-06-12", "surprise": +0.2},
    ]
    pattern = detect_joint_pattern(releases)
    assert pattern["has_pattern"] is False
    assert pattern["correlated_indicators"] == []
    assert pattern["direction"] == 0
    assert joint_pattern_prompt_directive(pattern) == ""


def test_ignores_non_anchor_indicators() -> None:
    """Even if 5 non-anchors agree, no pattern fires."""
    releases = [
        {"indicator_id": "NONANCHOR1", "release_date": "2026-06-12", "surprise": +0.2},
        {"indicator_id": "NONANCHOR2", "release_date": "2026-06-12", "surprise": +0.2},
        {"indicator_id": "NONANCHOR3", "release_date": "2026-06-12", "surprise": +0.2},
    ]
    pattern = detect_joint_pattern(releases)
    assert pattern["has_pattern"] is False


def test_anchor_set_locked() -> None:
    """Anchor set must include the 5 RESEARCH §Wave 4 indicators."""
    assert {"CPIAUCSL", "UNRATE", "GDP", "NAPMPMI", "PAYEMS"} == ANCHOR_INDICATORS
