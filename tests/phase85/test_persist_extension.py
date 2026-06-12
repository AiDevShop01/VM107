"""Phase 85 Plan 02 — Task 2 (RED): _20_persist_reasoning_artifact extension tests.

Tests the PersistReasoningArtifact extension class at slot 20 in
reasoning_stream_end. Uses mocks so no live DB required.

Key behaviors verified:
- Skips non-macro profiles (returns early, no INSERT)
- Writes exactly one B1 row for macro_* profiles
- B1 failure (get_analytics_conn raises) does NOT propagate; agent loop continues
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.phase_85


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_agent(profile_id: str, data: dict | None = None) -> MagicMock:
    """Build a minimal fake agent object with get_data() and set_data()."""
    _store = {
        "profile_id": profile_id,
        "sub_profile_id": None,
        "iteration": 1,
        "parent_envelope_id": None,
        "_reasoning_stream_text": "Test reasoning from macro agent.",
        "_response_text": "Test response.",
        "reasoning_tokens": 20,
        "response_tokens": 10,
        "tool_called": None,
        "tool_args": None,
        "model_version": "claude-test",
        "prompt_version": "macro_v1",
        "citations": [],
    }
    if data:
        _store.update(data)

    agent = MagicMock()
    agent.get_data = MagicMock(side_effect=lambda key: _store.get(key))
    agent.set_data = MagicMock()
    return agent


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skips_non_macro_profile():
    """Non-macro profile → get_analytics_conn is never called, no INSERT."""
    with patch(
        "extensions.python.reasoning_stream_end._20_persist_reasoning_artifact.get_analytics_conn"
    ) as mock_conn_factory:
        from extensions.python.reasoning_stream_end._20_persist_reasoning_artifact import (
            PersistReasoningArtifact,
        )
        ext = PersistReasoningArtifact(agent=None)
        agent = _make_agent(profile_id="vm107.market_analyst")
        await ext.execute(agent=agent)
        mock_conn_factory.assert_not_called()


@pytest.mark.asyncio
async def test_writes_row_for_macro_release_analyst():
    """macro_release_analyst profile → INSERT called exactly once with all 16 params."""
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
        agent = _make_agent(profile_id="vm107.macro_release_analyst")
        await ext.execute(agent=agent)

    # One INSERT call
    assert fake_cur.execute.call_count == 1
    call_args = fake_cur.execute.call_args
    sql = call_args[0][0]
    params = call_args[0][1]

    assert "INSERT INTO agent_reasoning_artifact" in sql
    assert "artifact_id" in params
    assert params["agent_profile_id"] == "vm107.macro_release_analyst"
    assert params["reasoning_text"] == "Test reasoning from macro agent."
    assert params["response_text"] == "Test response."
    assert params["model_version"] == "claude-test"
    assert params["confidence_self_report"] is None


@pytest.mark.asyncio
async def test_writes_row_for_any_macro_prefix():
    """vm107.macro_* prefix covers any macro sub-profile."""
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
        for profile_id in ("vm107.macro_fx_analyst", "vm107.macro_equities"):
            fake_cur.reset_mock()
            agent = _make_agent(profile_id=profile_id)
            await ext.execute(agent=agent)
            assert fake_cur.execute.call_count == 1, f"Expected INSERT for {profile_id}"


@pytest.mark.asyncio
async def test_b1_failure_does_not_raise(caplog):
    """When get_analytics_conn raises, extension returns normally; error is logged."""
    with patch(
        "extensions.python.reasoning_stream_end._20_persist_reasoning_artifact.get_analytics_conn",
        side_effect=RuntimeError("POSTGRES_HOST not set"),
    ), caplog.at_level(logging.ERROR):
        from extensions.python.reasoning_stream_end._20_persist_reasoning_artifact import (
            PersistReasoningArtifact,
        )
        ext = PersistReasoningArtifact(agent=None)
        agent = _make_agent(profile_id="vm107.macro_release_analyst")

        # Must NOT raise
        await ext.execute(agent=agent)

    # Error must be logged
    assert any("b1_persist_failed" in record.message or "b1_persist_failed" in str(record.args) for record in caplog.records), \
        f"Expected b1_persist_failed in logs. Got: {[r.message for r in caplog.records]}"


@pytest.mark.asyncio
async def test_no_agent_returns_early():
    """Missing agent kwarg → extension returns without error, no DB call."""
    with patch(
        "extensions.python.reasoning_stream_end._20_persist_reasoning_artifact.get_analytics_conn"
    ) as mock_conn_factory:
        from extensions.python.reasoning_stream_end._20_persist_reasoning_artifact import (
            PersistReasoningArtifact,
        )
        ext = PersistReasoningArtifact(agent=None)
        await ext.execute()  # no agent kwarg
        mock_conn_factory.assert_not_called()
