"""Phase 70.5 Plan 03 — TDD RED tests for nested dispatch / recursion guard.

Tests cover:
- Top-level call: parent_envelope_id is None
- Nested call: parent_envelope_id matches the caller's envelope_id
- Recursion guard: depth > MAX_EXECUTION_DEPTH short-circuits without invoking resolver
- trace_id stability: same trace_id across both log lines in a session
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, ConfigDict

from fingpt_core.contracts.invocation_context import InvocationContext, MAX_EXECUTION_DEPTH
from fingpt_core.contracts.tool_envelope import ToolConfidenceSignals, ToolProvenance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DummyPayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    value: str = "nested_test"
    PAYLOAD_SCHEMA_VERSION: str = "1.0"


def _make_ctx(
    depth: int = 0,
    parent_id: uuid.UUID | None = None,
    trace_id: uuid.UUID | None = None,
    envelope_id: uuid.UUID | None = None,
) -> InvocationContext:
    return InvocationContext(
        envelope_id=envelope_id or uuid.uuid4(),
        parent_envelope_id=parent_id,
        trace_id=trace_id or uuid.uuid4(),
        agent_id="test_agent",
        conversation_id="conv-nest",
        execution_depth=depth,
        knowledge_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _make_mock_entry(
    status: str = "real",
    typical_confidence: float = 0.85,
    is_deterministic: bool = False,
    version: str = "1.0",
) -> MagicMock:
    entry = MagicMock()
    entry.id = "test_tool"
    entry.status = status
    entry.typical_confidence = typical_confidence
    entry.expected_freshness_seconds = 60
    entry.is_deterministic = is_deterministic
    entry.version = version
    entry.source_module = "tools.test_tool"
    entry.is_facade = False
    return entry


def _make_mock_registry(snapshot_hash: str = "snap123") -> MagicMock:
    reg = MagicMock()
    reg.snapshot_hash = snapshot_hash
    return reg


# ---------------------------------------------------------------------------
# Tests — lineage (parent_envelope_id)
# ---------------------------------------------------------------------------


class TestDispatchToolLineage:
    """Parent envelope ID threading through nested dispatch."""

    @pytest.mark.asyncio
    async def test_top_level_parent_envelope_id_is_none(self):
        """Top-level ctx (depth=0, parent_id=None) → envelope.parent_envelope_id is None."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx(depth=0, parent_id=None)
        mock_entry = _make_mock_entry()
        mock_payload = _DummyPayload()
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert result.parent_envelope_id is None

    @pytest.mark.asyncio
    async def test_nested_ctx_parent_envelope_id_matches_caller(self):
        """Nested ctx (depth=2, parent_id=caller_env_id) → envelope.parent_envelope_id == parent_id."""
        from core.agents.tool_dispatcher import dispatch_tool

        caller_envelope_id = uuid.uuid4()
        ctx = _make_ctx(depth=2, parent_id=caller_envelope_id)
        mock_entry = _make_mock_entry()
        mock_payload = _DummyPayload()
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert result.parent_envelope_id == caller_envelope_id


# ---------------------------------------------------------------------------
# Tests — recursion guard
# ---------------------------------------------------------------------------


class TestRecursionGuard:
    """Recursion guard fires at depth > MAX_EXECUTION_DEPTH without invoking resolver."""

    @pytest.mark.asyncio
    async def test_deep_ctx_produces_refused_envelope(self):
        """ctx.execution_depth > MAX_EXECUTION_DEPTH → refused envelope before resolver call."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx(depth=MAX_EXECUTION_DEPTH + 1)
        mock_reg = _make_mock_registry()

        invoke_mock = AsyncMock(return_value=_DummyPayload())

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=invoke_mock),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert result.outcome_class == "refused"
        assert result.success is False
        invoke_mock.assert_not_called()  # guard fired BEFORE resolver

    @pytest.mark.asyncio
    async def test_recursion_guard_refusal_reason(self):
        """Recursion guard refusal_reason contains 'recursion_depth_exceeded'."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx(depth=9)  # 9 > MAX_EXECUTION_DEPTH (8)
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock()),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        assert result.refusal_reason is not None
        assert "recursion_depth_exceeded" in result.refusal_reason

    @pytest.mark.asyncio
    async def test_depth_exactly_max_does_not_guard(self):
        """ctx.execution_depth == MAX_EXECUTION_DEPTH is allowed (guard is STRICTLY greater)."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx(depth=MAX_EXECUTION_DEPTH)  # == 8, should NOT guard
        mock_entry = _make_mock_entry()
        mock_payload = _DummyPayload()
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
            patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            patch("core.agents.tool_dispatcher.emit_envelope_log"),
        ):
            result = await dispatch_tool("test_tool", {}, ctx)

        # Should NOT be refused by recursion guard (depth == 8, guard at > 8)
        assert result.outcome_class != "refused" or (
            result.refusal_reason and "recursion_depth_exceeded" not in result.refusal_reason
        )

    @pytest.mark.asyncio
    async def test_recursion_guard_telemetry_called(self):
        """emit_envelope_log is called even when recursion guard fires."""
        from core.agents.tool_dispatcher import dispatch_tool

        ctx = _make_ctx(depth=9)
        mock_reg = _make_mock_registry()

        with (
            patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
            patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock()),
            patch("core.agents.tool_dispatcher.emit_envelope_log") as mock_tel,
        ):
            await dispatch_tool("test_tool", {}, ctx)

        mock_tel.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — trace_id stability
# ---------------------------------------------------------------------------


class TestTraceIdStability:
    """trace_id remains stable across all envelopes in a session."""

    @pytest.mark.asyncio
    async def test_trace_id_in_telemetry_log(self, caplog):
        """Two dispatch calls with same trace_id → both log lines carry the same trace_id."""
        from core.agents.envelope_telemetry import ENVELOPE_LOGGER_NAME
        from core.agents.tool_dispatcher import dispatch_tool

        shared_trace_id = uuid.uuid4()
        ctx1 = _make_ctx(depth=0, trace_id=shared_trace_id)
        ctx2 = _make_ctx(depth=0, trace_id=shared_trace_id)

        mock_entry = _make_mock_entry()
        mock_payload = _DummyPayload()
        mock_reg = _make_mock_registry()

        with caplog.at_level(logging.INFO, logger=ENVELOPE_LOGGER_NAME):
            with (
                patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
                patch("core.agents.tool_dispatcher.should_refuse", return_value=False),
                patch("core.agents.tool_dispatcher._get_tool_entry", return_value=mock_entry),
                patch("core.agents.tool_dispatcher._invoke_resolver", new=AsyncMock(return_value=mock_payload)),
            ):
                await dispatch_tool("test_tool", {}, ctx1)
                await dispatch_tool("test_tool", {}, ctx2)

        log_lines = [
            r for r in caplog.records if r.name == ENVELOPE_LOGGER_NAME
        ]
        assert len(log_lines) == 2

        parsed1 = json.loads(log_lines[0].getMessage())
        parsed2 = json.loads(log_lines[1].getMessage())

        assert parsed1["trace_id"] == str(shared_trace_id)
        assert parsed2["trace_id"] == str(shared_trace_id)
        assert parsed1["trace_id"] == parsed2["trace_id"]
