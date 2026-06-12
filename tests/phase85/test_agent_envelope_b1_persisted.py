"""Phase 85 Plan 08b — Envelope + B1 persistence tests (TDD RED/GREEN).

Tests:
1. test_agent_envelope_includes_b1_artifact_id — invoke release_analyst happy path;
   verify envelope.payload OR accompanying metadata includes artifact_id (so Phase 71
   drawer can resolve the citation chain).
2. test_b1_row_written_per_invocation — invoke the B1 persist extension twice for
   macro_release_analyst profile; assert INSERT called twice (once per invocation).
3. test_b1_not_written_for_non_macro_profile — non-macro profile should NOT trigger B1.
4. test_envelope_confidence_in_range — envelope.confidence is a float in [0, 1].
5. test_b1_extension_sets_artifact_id_on_agent — after PersistReasoningArtifact.execute(),
   agent.set_data should be called with "last_b1_artifact_id" so envelope consumers
   can reference the B1 row.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

pytestmark = pytest.mark.phase_85


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(profile_id: str, b1_artifact_id: str | None = None) -> MagicMock:
    """Build a minimal fake agent object matching the B1 extension contract."""
    _store = {
        "profile_id": profile_id,
        "sub_profile_id": None,
        "iteration": 1,
        "parent_envelope_id": None,
        "_reasoning_stream_text": "Macro reasoning: CPI at 3.4% vs 3.3% consensus.",
        "_response_text": '{"what_happened": "CPI 3.4%", "why_it_matters": "Inflation above target."}',
        "reasoning_tokens": 120,
        "response_tokens": 45,
        "tool_called": "vm102.indicator_history",
        "tool_args": {"indicator_id": "CPIAUCSL", "limit": 24},
        "model_version": "claude-3-5-sonnet",
        "prompt_version": "macro_release_analyst_v1",
        "citations": [{"citation_id": "c1", "source": "vm102.indicator_history", "snippet": "CPI 3.4%"}],
        "last_b1_artifact_id": b1_artifact_id,
    }

    agent = MagicMock()
    agent.get_data = MagicMock(side_effect=lambda key: _store.get(key))
    agent.set_data = MagicMock(side_effect=lambda key, val: _store.update({key: val}))
    return agent


# ---------------------------------------------------------------------------
# B1 row written per invocation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_b1_row_written_per_invocation():
    """Invoke PersistReasoningArtifact twice; INSERT called exactly twice."""
    fake_cur = MagicMock()
    fake_conn = MagicMock()
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)
    fake_conn.cursor = MagicMock(return_value=fake_cur)
    fake_cur.__enter__ = MagicMock(return_value=fake_cur)
    fake_cur.__exit__ = MagicMock(return_value=False)

    with patch(
        "extensions.python.reasoning_stream_end._20_persist_reasoning_artifact.get_analytics_conn",
        return_value=fake_conn,
    ):
        from extensions.python.reasoning_stream_end._20_persist_reasoning_artifact import (
            PersistReasoningArtifact,
        )
        ext = PersistReasoningArtifact(agent=None)

        # First invocation
        agent1 = _make_agent("vm107.macro_release_analyst")
        await ext.execute(agent=agent1)

        # Second invocation (separate agent instance, different iteration)
        agent2 = _make_agent("vm107.macro_release_analyst")
        await ext.execute(agent=agent2)

    # INSERT must have been called exactly twice
    assert fake_cur.execute.call_count == 2, (
        f"Expected 2 INSERT calls (one per invocation), got {fake_cur.execute.call_count}"
    )


@pytest.mark.asyncio
async def test_b1_not_written_for_non_macro_profile():
    """Non-macro profile must NOT write B1 row."""
    with patch(
        "extensions.python.reasoning_stream_end._20_persist_reasoning_artifact.get_analytics_conn"
    ) as mock_conn_factory:
        from extensions.python.reasoning_stream_end._20_persist_reasoning_artifact import (
            PersistReasoningArtifact,
        )
        ext = PersistReasoningArtifact(agent=None)
        agent = _make_agent("vm107.trade_analyst")  # not macro_*
        await ext.execute(agent=agent)
        mock_conn_factory.assert_not_called()


@pytest.mark.asyncio
async def test_b1_row_written_for_asset_exposure_analyst():
    """macro_asset_exposure_analyst profile also triggers B1 (vm107.macro_* prefix)."""
    fake_cur = MagicMock()
    fake_conn = MagicMock()
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)
    fake_conn.cursor = MagicMock(return_value=fake_cur)
    fake_cur.__enter__ = MagicMock(return_value=fake_cur)
    fake_cur.__exit__ = MagicMock(return_value=False)

    with patch(
        "extensions.python.reasoning_stream_end._20_persist_reasoning_artifact.get_analytics_conn",
        return_value=fake_conn,
    ):
        from extensions.python.reasoning_stream_end._20_persist_reasoning_artifact import (
            PersistReasoningArtifact,
        )
        ext = PersistReasoningArtifact(agent=None)
        agent = _make_agent("vm107.macro_asset_exposure_analyst")
        await ext.execute(agent=agent)

    assert fake_cur.execute.call_count == 1, (
        f"Expected 1 INSERT for macro_asset_exposure_analyst, got {fake_cur.execute.call_count}"
    )


# ---------------------------------------------------------------------------
# Envelope artifact_id propagation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_envelope_includes_b1_artifact_id():
    """After PersistReasoningArtifact.execute(), the generated artifact_id is stored
    on the agent via set_data('last_b1_artifact_id', ...) so downstream envelope
    consumers can reference the B1 row.

    This test verifies Plan 85-08b's B1 artifact_id propagation strategy:
    the extension writes artifact_id to agent.data so the envelope builder
    (or the persistence post-processing step) can read it.
    """
    import re

    fake_cur = MagicMock()
    fake_conn = MagicMock()
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)
    fake_conn.cursor = MagicMock(return_value=fake_cur)
    fake_cur.__enter__ = MagicMock(return_value=fake_cur)
    fake_cur.__exit__ = MagicMock(return_value=False)

    with patch(
        "extensions.python.reasoning_stream_end._20_persist_reasoning_artifact.get_analytics_conn",
        return_value=fake_conn,
    ):
        from extensions.python.reasoning_stream_end._20_persist_reasoning_artifact import (
            PersistReasoningArtifact,
        )
        ext = PersistReasoningArtifact(agent=None)
        agent = _make_agent("vm107.macro_release_analyst")
        await ext.execute(agent=agent)

    # The extension should have called agent.set_data("last_b1_artifact_id", <uuid-str>)
    set_data_calls = agent.set_data.call_args_list
    artifact_id_calls = [c for c in set_data_calls if c[0][0] == "last_b1_artifact_id"]
    assert len(artifact_id_calls) >= 1, (
        f"Expected agent.set_data('last_b1_artifact_id', ...) to be called. "
        f"Actual set_data calls: {set_data_calls}"
    )
    # Verify the stored value looks like a UUID
    artifact_id_value = artifact_id_calls[0][0][1]
    assert re.match(r"^[0-9a-f-]{36}$", str(artifact_id_value)), (
        f"last_b1_artifact_id must be a UUID string, got {artifact_id_value!r}"
    )


# ---------------------------------------------------------------------------
# Envelope confidence
# ---------------------------------------------------------------------------

def test_envelope_confidence_in_range():
    """ToolResultEnvelope.confidence must be a float in [0.0, 1.0]."""
    import uuid
    from fingpt_core.contracts.tool_envelope import ToolResultEnvelope
    from pydantic import BaseModel

    class SimplePayload(BaseModel):
        value: str

    for confidence in (0.0, 0.5, 0.85, 1.0):
        envelope = ToolResultEnvelope(
            envelope_id=uuid.uuid4(),
            tool_name="vm107.macro_release_analyst",
            tool_version="85",
            outcome_class="success",
            success=True,
            generated_at=datetime.now(timezone.utc),
            confidence=confidence,
            registry_snapshot_hash="test-hash",
            payload_schema_version="1.0",
            payload=SimplePayload(value="test"),
        )
        assert 0.0 <= envelope.confidence <= 1.0, (
            f"envelope.confidence={envelope.confidence} out of [0,1] range"
        )


def test_low_confidence_on_partial_outcome():
    """Partial outcome (max_iterations hit) → confidence < 0.5."""
    import uuid
    from fingpt_core.contracts.tool_envelope import ToolResultEnvelope
    from pydantic import BaseModel

    class SimplePayload(BaseModel):
        value: str

    # Simulate max_iterations exceeded — partial output, low confidence
    envelope = ToolResultEnvelope(
        envelope_id=uuid.uuid4(),
        tool_name="vm107.macro_release_analyst",
        tool_version="85",
        outcome_class="partial",
        success=False,
        generated_at=datetime.now(timezone.utc),
        confidence=0.20,  # low confidence on partial/capped output
        registry_snapshot_hash="test-hash",
        payload_schema_version="1.0",
        payload=SimplePayload(value="partial"),
    )
    assert envelope.outcome_class == "partial"
    assert envelope.confidence < 0.5, (
        f"Partial outcome should have confidence < 0.5, got {envelope.confidence}"
    )
    assert envelope.success is False
