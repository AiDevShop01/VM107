"""Phase 87 Wave 4a — hook injection format test (Brain Part 2 §B6 verbatim).

The hook returns a prompt-injection string. Empty retrieval still emits a
visible '(no relevant prior episodes)' line so the LLM doesn't hallucinate
prior context.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.phase_87


def _make_result(n_records):
    from VM107.core.memory.episodic_memory_service import (
        CitationRef, EpisodicResult, MemoryRecord,
    )
    records = []
    for i in range(n_records):
        mid = uuid.uuid4()
        records.append(MemoryRecord(
            memory_id=mid, memory_type="episodic",
            text=f"On 2022-03-{10+i} CPI printed 7.{9+i}% (surprise +0.{i+1})",
            embedding=[0.0] * 768,
            created_at=datetime.now(tz=timezone.utc),
            decay_weight=0.9, citations=[CitationRef(
                citation_ref=f"[ref:episode:{mid}]", kind="episode",
                target_id=str(mid),
            )],
        ))
    return EpisodicResult(
        query_id=uuid.uuid4(), memories_retrieved=records,
        retrieval_latency_ms=10, cache_hit=False, confidence=0.8,
    )


def test_hook_format_brain_part_2_verbatim():
    from VM107.core.memory.message_loop_prompts_before_b6 import (
        message_loop_prompts_before_b6,
    )

    svc = MagicMock()
    svc.query.return_value = _make_result(3)
    out = message_loop_prompts_before_b6(
        agent_profile_id="vm107.macro_story_tracker",
        query_text="CPI surprise",
        episodic_memory_service=svc,
    )
    assert out.startswith("## Relevant prior episodes")
    lines = out.splitlines()
    assert len(lines) == 4  # header + 3 records
    assert lines[1].startswith("1. [ref:episode:")
    assert lines[2].startswith("2. [ref:episode:")
    assert lines[3].startswith("3. [ref:episode:")


def test_hook_empty_retrieval_emits_explicit_no_message():
    from VM107.core.memory.message_loop_prompts_before_b6 import (
        message_loop_prompts_before_b6,
    )

    svc = MagicMock()
    svc.query.return_value = _make_result(0)
    out = message_loop_prompts_before_b6(
        agent_profile_id="vm107.macro_story_tracker",
        query_text="x",
        episodic_memory_service=svc,
    )
    assert out == "## Relevant prior episodes\n(no relevant prior episodes)"


def test_hook_passes_top_k_into_query():
    """Verify the hook honours the top_k override (LOCK-6 = 5 by default)."""
    from VM107.core.memory.message_loop_prompts_before_b6 import (
        message_loop_prompts_before_b6,
    )

    svc = MagicMock()
    svc.query.return_value = _make_result(2)
    message_loop_prompts_before_b6(
        agent_profile_id="vm107.macro_story_tracker",
        query_text="x",
        episodic_memory_service=svc,
        top_k=7,
    )
    # The query argument is positional in our call; inspect kwargs/args
    args, kwargs = svc.query.call_args
    assert args, "expected query() to be called with a positional EpisodicQuery"
    eq = args[0]
    assert eq.top_k == 7
    assert eq.scope == {"collection": "macro_episode"}
    assert eq.memory_types_requested == ["episodic"]
    assert eq.requesting_profile == "vm107.macro_story_tracker"
