"""Phase 87 Wave 4b — Plan 87-08 Task 2 — REQ-87-6 B6 episodic citations.

The macro_story_tracker's narration prompt MUST include the
``## Relevant prior episodes`` block injected by Plan 87-07's
``message_loop_prompts_before_b6`` helper, complete with
``[ref:episode:<uuid>]`` citation tokens.

This test does NOT spin up Qdrant — it stubs the EpisodicMemoryService and
asserts the helper's output shape (the helper is the bridge between any
agent that wants B6 and the service). The agent's ``_build_prompt``
concatenates the helper's output unchanged, so this guarantees the
citation reaches the LLM at run-time.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from core.memory.episodic_memory_service import (
    CitationRef,
    EpisodicResult,
    MemoryRecord,
)
from core.memory.message_loop_prompts_before_b6 import (
    message_loop_prompts_before_b6,
)

pytestmark = pytest.mark.phase_87


def test_story_tracker_prompt_includes_episode_citations() -> None:
    """The B6 hook injects the prescribed block; tracker prompt concatenates it."""
    mid = uuid.uuid4()
    svc = MagicMock()
    svc.query.return_value = EpisodicResult(
        query_id=uuid.uuid4(),
        memories_retrieved=[
            MemoryRecord(
                memory_id=mid,
                memory_type="episodic",
                text="On 2022-03-10 CPI printed 7.9% (surprise +0.3)",
                embedding=[0.0] * 768,
                created_at=datetime.now(tz=timezone.utc),
                decay_weight=0.8,
                citations=[
                    CitationRef(
                        citation_ref=f"[ref:episode:{mid}]",
                        kind="episode",
                        target_id=str(mid),
                    )
                ],
            )
        ],
        retrieval_latency_ms=5,
        cache_hit=False,
        confidence=0.85,
    )
    block = message_loop_prompts_before_b6(
        agent_profile_id="vm107.macro_story_tracker",
        query_text="CPI surprise pattern",
        episodic_memory_service=svc,
    )
    assert "## Relevant prior episodes" in block
    assert f"[ref:episode:{mid}]" in block
    assert "2022-03-10" in block


def test_b6_hook_emits_explicit_no_episodes_line_on_empty() -> None:
    """LOCK-6 — never let the LLM hallucinate prior context that was empty."""
    svc = MagicMock()
    svc.query.return_value = EpisodicResult(
        query_id=uuid.uuid4(),
        memories_retrieved=[],
        retrieval_latency_ms=2,
        cache_hit=False,
        confidence=0.0,
    )
    block = message_loop_prompts_before_b6(
        agent_profile_id="vm107.macro_story_tracker",
        query_text="quiet macro window",
        episodic_memory_service=svc,
    )
    # The Plan 87-07 LOCK-6 contract: visible (no relevant prior episodes) line.
    assert "(no relevant prior episodes)" in block


def test_story_tracker_agent_concatenates_b6_block_into_prompt() -> None:
    """The agent's _build_prompt MUST embed the b6 block at the top."""
    from agents.macro_story_tracker.agent import MacroStoryTracker

    tracker = MacroStoryTracker(
        poller=MagicMock(),
        episodic_memory_service=MagicMock(),
        b6_hook=lambda **_kw: "## Relevant prior episodes\n- [ref:episode:abc] hello",
        llm_router=MagicMock(),
        embedding_service=MagicMock(),
        envelope_repo=MagicMock(),
        persist_repo=MagicMock(),
        ws_publisher=MagicMock(),
    )
    prompt = tracker._build_prompt(
        releases=[
            {"indicator_id": "CPIAUCSL", "release_date": "2026-06-12",
             "actual": 3.4, "forecast": 3.3, "surprise": +0.1},
        ],
        pattern={"has_pattern": False, "correlated_indicators": [], "direction": 0},
        episode_block="## Relevant prior episodes\n- [ref:episode:abc] hello",
    )
    assert "## Relevant prior episodes" in prompt
    assert "[ref:episode:abc]" in prompt
    assert "CPIAUCSL" in prompt
