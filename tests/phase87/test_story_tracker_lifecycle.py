"""Phase 87 Wave 4b — Plan 87-08 Task 1 — Story lifecycle decisions.

Tests the deterministic CREATE / REINFORCE / DROP branches of
``decide_update`` (the macro_story_tracker's update-skill) in isolation.

These tests do NOT touch Postgres, Qdrant, the LLM router, or VM101's typed
API — only the pure-Python decision function. The retirement branch is
covered separately in ``test_story_retirement_rule.py`` (Task 2).
"""
import uuid
from unittest.mock import MagicMock

import pytest

from agents.macro_story_tracker.skill_story_update import (
    CONFIDENCE_FLOOR,
    MAX_ACTIVE_STORIES,
    decide_update,
)

pytestmark = pytest.mark.phase_87


def test_create_on_empty_active_stories() -> None:
    decision = decide_update(
        candidate_headline="Inflation persistence trend emerging",
        candidate_embedding=[1.0] * 768,
        candidate_confidence=0.7,
        supporting_release_id="r1",
        supporting_indicators=["CPIAUCSL"],
        active_stories=[],
        embedding_service=MagicMock(),
    )
    assert decision.action == "CREATE"
    assert "no active" in decision.reason.lower()


def test_drop_on_low_confidence_with_empty_active() -> None:
    decision = decide_update(
        candidate_headline="weak signal",
        candidate_embedding=[1.0] * 768,
        candidate_confidence=0.3,
        supporting_release_id="r1",
        supporting_indicators=["CPIAUCSL"],
        active_stories=[],
        embedding_service=MagicMock(),
    )
    assert decision.action == "DROP"
    assert "confidence" in decision.reason.lower()


def test_reinforce_on_similar_active_story() -> None:
    """Identical embedding ⇒ cosine = 1.0 ⇒ above SIMILARITY_THRESHOLD."""
    existing_story_id = uuid.uuid4()
    existing = {
        "story_id": str(existing_story_id),
        "headline_embedding": [1.0] * 768,
    }
    decision = decide_update(
        candidate_headline="Inflation persistence trend",
        candidate_embedding=[1.0] * 768,
        candidate_confidence=0.7,
        supporting_release_id="r2",
        supporting_indicators=["CPIAUCSL"],
        active_stories=[existing],
        embedding_service=MagicMock(),
    )
    assert decision.action == "REINFORCE"
    assert decision.story_id == existing_story_id


def test_drop_at_max_active_stories_cap() -> None:
    """10 dissimilar active stories + dissimilar candidate ⇒ DROP (at cap)."""
    # Each existing story has a unique one-hot embedding (orthogonal).
    active = [
        {
            "story_id": str(uuid.uuid4()),
            "headline_embedding": [1.0 if j == i else 0.0 for j in range(768)],
        }
        for i in range(MAX_ACTIVE_STORIES)
    ]
    # Candidate is yet-another orthogonal direction (dim 100).
    cand_emb = [1.0 if j == 100 else 0.0 for j in range(768)]
    decision = decide_update(
        candidate_headline="brand-new pattern",
        candidate_embedding=cand_emb,
        candidate_confidence=0.7,
        supporting_release_id="r1",
        supporting_indicators=["CPIAUCSL"],
        active_stories=active,
        embedding_service=MagicMock(),
    )
    assert decision.action == "DROP"
    assert "MAX_ACTIVE_STORIES" in decision.reason


def test_constants_match_plan_spec() -> None:
    """Lock the policy constants the plan specifies."""
    assert MAX_ACTIVE_STORIES == 10
    assert CONFIDENCE_FLOOR == 0.5
