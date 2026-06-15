"""Phase 87 Wave 2 — narrative hard-assertion regex retry-once-degrade gate.

Agent profile YAML declares:
  hard_assertions:
    - id: narrative_strength_for_3_hops
      regex: strength\\s*[=:]\\s*-?\\d
      min_matches: 3
    - id: narrative_period
      regex: \\d{4}-\\d{2}-\\d{2}/\\d{4}-\\d{2}-\\d{2}
      min_matches: 1
  retry_on_hard_assertion_fail: 1
  on_assertion_fail_after_retry: mark_envelope_degraded

This test pins:
  - Failure on attempt 1 → retry → success on attempt 2 → degraded=False
  - Failure on both attempts → degraded=True + deterministic Markdown fallback
  - The fallback STILL emits [ref:edge:...] citations so the evidence drawer
    works on the degraded path.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from agents.macro_transmission_analyst.agent import MacroTransmissionAnalyst
from agents.macro_transmission_analyst.skill_transmission_narration import (
    TransmissionNarrationSkill,
)
from tools.neo4j_macro_graph_walker import Hop

pytestmark = pytest.mark.phase_87


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID = (
    "strength=0.40 over 2021-01-01/2026-01-01 [ref:edge:CPIAUCSL:UNRATE]. "
    "strength=-0.55 over 2021-01-01/2026-01-01 [ref:edge:UNRATE:GDP]. "
    "strength=0.48 over 2021-01-01/2026-01-01 [ref:edge:GDP:DGS10]."
)
_MALFORMED = "release was significant but no numeric metrics"


def _agent_with_llm(llm_responses, episodic_memory_stub):
    walker = MagicMock()
    walker.walk.return_value = [
        Hop("CPIAUCSL", "UNRATE", "AFFECTS", 0.40, 0.70, 60, "2021-01-01/2026-01-01", 0),
        Hop("UNRATE", "GDP", "AFFECTS", -0.55, 0.74, 60, "2021-01-01/2026-01-01", 1),
        Hop("GDP", "DGS10", "AFFECTS", 0.48, 0.66, 60, "2021-01-01/2026-01-01", 2),
    ]
    llm = MagicMock()
    llm.complete.side_effect = list(llm_responses)
    envelope_repo = MagicMock()
    envelope_repo.persist.return_value = uuid.uuid4()
    b1_repo = MagicMock()
    b1_repo.persist.return_value = uuid.uuid4()
    persist = MagicMock()
    persist.create.return_value = uuid.uuid4()
    ws = MagicMock()
    agent = MacroTransmissionAnalyst(
        walker=walker,
        episodic_memory_service=episodic_memory_stub,
        narration_skill=TransmissionNarrationSkill(llm_router=llm),
        envelope_repo=envelope_repo,
        b1_repo=b1_repo,
        persist_repo=persist,
        ws_publisher=ws,
    )
    return agent, persist, llm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_first_attempt_passing_skips_retry(
    release_event_factory, episodic_memory_stub
):
    """Valid first attempt → no retry, no degrade."""
    agent, persist, llm = _agent_with_llm(
        llm_responses=[_VALID],
        episodic_memory_stub=episodic_memory_stub,
    )
    result = agent.run(release_event_factory())
    assert not result.degraded
    assert llm.complete.call_count == 1
    persist.create.assert_called_once()


def test_retry_succeeds_on_second_attempt(
    release_event_factory, episodic_memory_stub
):
    """First attempt fails regex → retry with corrective addendum → passes."""
    agent, persist, llm = _agent_with_llm(
        llm_responses=[_MALFORMED, _VALID],
        episodic_memory_stub=episodic_memory_stub,
    )
    result = agent.run(release_event_factory())
    assert not result.degraded
    assert llm.complete.call_count == 2
    persist.create.assert_called_once()


def test_degraded_when_both_attempts_malformed(
    release_event_factory, episodic_memory_stub
):
    """Both attempts fail regex → mark envelope degraded + deterministic fallback.

    Per agent profile YAML: on_assertion_fail_after_retry: mark_envelope_degraded.
    The fallback Markdown MUST still emit [ref:edge:<src>:<dst>] for each hop
    so the evidence drawer continues to function.
    """
    agent, persist, llm = _agent_with_llm(
        llm_responses=[_MALFORMED, "still no metrics in this one"],
        episodic_memory_stub=episodic_memory_stub,
    )
    result = agent.run(release_event_factory())
    assert result.degraded
    assert llm.complete.call_count == 2
    persist.create.assert_called_once()
    # Deterministic Markdown fallback renders each hop with citation
    assert "CPIAUCSL → UNRATE" in result.narrative_text
    assert "[ref:edge:CPIAUCSL:UNRATE]" in result.narrative_text
    assert "[ref:edge:UNRATE:GDP]" in result.narrative_text
    assert "[ref:edge:GDP:DGS10]" in result.narrative_text


def test_degraded_fallback_includes_strength_and_period(
    release_event_factory, episodic_memory_stub
):
    """Degraded Markdown fallback STILL surfaces strength + evidence_period.

    Phase 71 evidence drawer needs these on every emit (degraded or not) so
    the per-hop chip in the UI can show the same number whether the LLM
    succeeded or fell back to deterministic Markdown.
    """
    agent, persist, _ = _agent_with_llm(
        llm_responses=[_MALFORMED, _MALFORMED],
        episodic_memory_stub=episodic_memory_stub,
    )
    result = agent.run(release_event_factory())
    assert result.degraded
    assert "strength=0.40" in result.narrative_text
    assert "strength=-0.55" in result.narrative_text
    assert "2021-01-01/2026-01-01" in result.narrative_text
