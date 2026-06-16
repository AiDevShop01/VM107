"""Phase 87 Wave 4b — Plan 87-08 Task 2 — LOCK-7 retirement rule.

When a story's supporting indicators show ≥3 consecutive opposite-direction
releases, ``check_retirement`` returns ``(True, reason)``. The
macro_story_tracker agent then writes a new WORM row with
``supersedes_story_id`` pointing back at the active story and
``is_active = False``.

These tests cover only the deterministic predicate; the WORM-write side
effect is verified in the deploy-time soak (Plan 87-14).
"""
import pytest

from agents.macro_story_tracker.skill_story_update import check_retirement

pytestmark = pytest.mark.phase_87


def test_retires_on_three_consecutive_opposite() -> None:
    story = {
        "story_id": "s1",
        "supporting_indicators": ["CPIAUCSL"],
        "implied_direction": +1,  # "inflation persistence" ⇒ CPI rising
    }
    # All three latest releases turn negative (opposite of +1).
    recent = {
        "CPIAUCSL": [
            {"surprise": -0.10},
            {"surprise": -0.20},
            {"surprise": -0.30},
        ]
    }
    retire, reason = check_retirement(
        story=story, recent_releases_by_indicator=recent,
    )
    assert retire is True
    assert "3 consecutive" in reason
    assert "CPIAUCSL" in reason


def test_does_not_retire_on_two_opposite_one_same() -> None:
    story = {
        "story_id": "s1",
        "supporting_indicators": ["CPIAUCSL"],
        "implied_direction": +1,
    }
    recent = {
        "CPIAUCSL": [
            {"surprise": -0.10},
            {"surprise": -0.20},
            {"surprise": +0.10},  # latest reverts to story direction
        ]
    }
    retire, reason = check_retirement(
        story=story, recent_releases_by_indicator=recent,
    )
    assert retire is False
    assert reason is None


def test_does_not_retire_on_under_three_releases() -> None:
    story = {
        "story_id": "s1",
        "supporting_indicators": ["CPIAUCSL"],
        "implied_direction": +1,
    }
    recent = {"CPIAUCSL": [{"surprise": -0.1}, {"surprise": -0.2}]}
    retire, _ = check_retirement(
        story=story, recent_releases_by_indicator=recent,
    )
    assert retire is False


def test_retires_when_only_one_of_two_indicators_turns_all_opposite() -> None:
    """Any supporting indicator with 3 opposite ⇒ retire (the OR contract)."""
    story = {
        "story_id": "s1",
        "supporting_indicators": ["CPIAUCSL", "UNRATE"],
        "implied_direction": +1,
    }
    recent = {
        "CPIAUCSL": [{"surprise": +0.1}, {"surprise": +0.2}, {"surprise": +0.1}],
        # UNRATE flipped — 3 negatives ⇒ retire.
        "UNRATE":   [{"surprise": -0.1}, {"surprise": -0.2}, {"surprise": -0.3}],
    }
    retire, reason = check_retirement(
        story=story, recent_releases_by_indicator=recent,
    )
    assert retire is True
    assert "UNRATE" in reason


def test_negative_direction_story_retires_on_three_positive() -> None:
    """Symmetric — implied_direction = -1 ⇒ retire on 3 consecutive +."""
    story = {
        "story_id": "s1",
        "supporting_indicators": ["NAPMPMI"],
        "implied_direction": -1,  # "PMI deterioration"
    }
    recent = {
        "NAPMPMI": [
            {"surprise": +0.10},
            {"surprise": +0.20},
            {"surprise": +0.10},
        ]
    }
    retire, _ = check_retirement(
        story=story, recent_releases_by_indicator=recent,
    )
    assert retire is True
