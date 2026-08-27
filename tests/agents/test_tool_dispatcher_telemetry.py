"""Phase 70.5 Plan 03 — TDD RED tests for envelope_telemetry.py.

Tests verify Decision 17 schema compliance:
- emit_envelope_log writes exactly one JSON line to ENVELOPE_LOGGER_NAME
- JSON record matches Decision 17 schema verbatim (every key present)
- Telemetry exception is swallowed; fallback logger receives WARNING
- JSON is compact single-line (no whitespace separators)
- generated_at is ISO 8601 parseable
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel, ConfigDict

from fingpt_core.contracts.evidence import EvidenceCitation
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.invocation_context import InvocationContext
from fingpt_core.contracts.tool_envelope import (
    ENVELOPE_SCHEMA_VERSION,
    ToolResultEnvelope,
)


# ---------------------------------------------------------------------------
# Helpers — synthetic payload model
# ---------------------------------------------------------------------------


class _DummyPayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    value: str = "test"
    PAYLOAD_SCHEMA_VERSION: str = "1.0"


def _make_envelope(
    outcome_class: str = "success",
    confidence: float | None = 0.85,
    freshness_seconds: int | None = 30,
    citations: tuple = (),
    failure_modes: tuple = (),
    normalization_warnings: tuple = (),
    parent_envelope_id: uuid.UUID | None = None,
) -> ToolResultEnvelope:
    """Build a synthetic ToolResultEnvelope[_DummyPayload] for tests."""
    from fingpt_core.contracts.tool_envelope import ToolResultEnvelope
    return ToolResultEnvelope[_DummyPayload](
        envelope_id=uuid.uuid4(),
        parent_envelope_id=parent_envelope_id,
        tool_name="test_tool",
        tool_version="1.0",
        outcome_class=outcome_class,
        success=(outcome_class not in ("failure", "refused")),
        generated_at=datetime.now(timezone.utc),
        confidence=confidence,
        confidence_reasoning=(),
        freshness_seconds=freshness_seconds,
        citations=citations,
        assumptions=(),
        failure_modes=failure_modes,
        normalization_warnings=normalization_warnings,
        registry_snapshot_hash="abc123def456",
        envelope_schema_version=ENVELOPE_SCHEMA_VERSION,
        payload_schema_version="1.0",
        payload=_DummyPayload(),
    )


def _make_ctx(depth: int = 0) -> InvocationContext:
    return InvocationContext(
        envelope_id=uuid.uuid4(),
        parent_envelope_id=None,
        trace_id=uuid.uuid4(),
        agent_id="test_agent",
        conversation_id="conv-123",
        execution_depth=depth,
        knowledge_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# DECISION 17 SCHEMA — required keys
# ---------------------------------------------------------------------------

DECISION_17_KEYS = {
    "event_type",
    "envelope_id",
    "parent_envelope_id",
    "trace_id",
    "agent_id",
    "conversation_id",
    "execution_depth",
    "tool_id",
    "tool_name",
    "tool_version",
    "outcome_class",
    "success",
    "confidence",
    "freshness_seconds",
    "registry_snapshot_hash",
    "generated_at",
    "len_failure_modes",
    "len_normalization_warnings",
    "len_citations",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmitEnvelopeLogBasic:
    """emit_envelope_log writes exactly one JSON line matching Decision 17 schema."""

    def test_emits_exactly_one_log_line(self, caplog):
        """Calling emit_envelope_log produces exactly one log record."""
        from core.agents.envelope_telemetry import (
            ENVELOPE_LOGGER_NAME,
            emit_envelope_log,
        )

        envelope = _make_envelope()
        ctx = _make_ctx()

        with caplog.at_level(logging.INFO, logger=ENVELOPE_LOGGER_NAME):
            emit_envelope_log(envelope, ctx)

        records = [r for r in caplog.records if r.name == ENVELOPE_LOGGER_NAME]
        assert len(records) == 1

    def test_json_parseable(self, caplog):
        """The emitted log message is valid JSON."""
        from core.agents.envelope_telemetry import (
            ENVELOPE_LOGGER_NAME,
            emit_envelope_log,
        )

        envelope = _make_envelope()
        ctx = _make_ctx()

        with caplog.at_level(logging.INFO, logger=ENVELOPE_LOGGER_NAME):
            emit_envelope_log(envelope, ctx)

        records = [r for r in caplog.records if r.name == ENVELOPE_LOGGER_NAME]
        parsed = json.loads(records[0].getMessage())
        assert isinstance(parsed, dict)

    def test_all_decision_17_keys_present(self, caplog):
        """Every key from the Decision 17 schema is present in the emitted JSON."""
        from core.agents.envelope_telemetry import (
            ENVELOPE_LOGGER_NAME,
            emit_envelope_log,
        )

        envelope = _make_envelope()
        ctx = _make_ctx()

        with caplog.at_level(logging.INFO, logger=ENVELOPE_LOGGER_NAME):
            emit_envelope_log(envelope, ctx)

        records = [r for r in caplog.records if r.name == ENVELOPE_LOGGER_NAME]
        parsed = json.loads(records[0].getMessage())

        missing = DECISION_17_KEYS - set(parsed.keys())
        assert not missing, f"Missing Decision 17 keys: {missing}"

    def test_event_type_value(self, caplog):
        """event_type == 'tool_result_envelope_emitted'."""
        from core.agents.envelope_telemetry import (
            ENVELOPE_LOG_EVENT_TYPE,
            ENVELOPE_LOGGER_NAME,
            emit_envelope_log,
        )

        envelope = _make_envelope()
        ctx = _make_ctx()

        with caplog.at_level(logging.INFO, logger=ENVELOPE_LOGGER_NAME):
            emit_envelope_log(envelope, ctx)

        records = [r for r in caplog.records if r.name == ENVELOPE_LOGGER_NAME]
        parsed = json.loads(records[0].getMessage())
        assert parsed["event_type"] == ENVELOPE_LOG_EVENT_TYPE
        assert parsed["event_type"] == "tool_result_envelope_emitted"

    def test_envelope_id_matches(self, caplog):
        """envelope_id in log matches the envelope's UUID."""
        from core.agents.envelope_telemetry import (
            ENVELOPE_LOGGER_NAME,
            emit_envelope_log,
        )

        envelope = _make_envelope()
        ctx = _make_ctx()

        with caplog.at_level(logging.INFO, logger=ENVELOPE_LOGGER_NAME):
            emit_envelope_log(envelope, ctx)

        records = [r for r in caplog.records if r.name == ENVELOPE_LOGGER_NAME]
        parsed = json.loads(records[0].getMessage())
        assert parsed["envelope_id"] == str(envelope.envelope_id)

    def test_parent_envelope_id_null_when_none(self, caplog):
        """parent_envelope_id is JSON null when envelope.parent_envelope_id is None."""
        from core.agents.envelope_telemetry import (
            ENVELOPE_LOGGER_NAME,
            emit_envelope_log,
        )

        envelope = _make_envelope(parent_envelope_id=None)
        ctx = _make_ctx()

        with caplog.at_level(logging.INFO, logger=ENVELOPE_LOGGER_NAME):
            emit_envelope_log(envelope, ctx)

        records = [r for r in caplog.records if r.name == ENVELOPE_LOGGER_NAME]
        parsed = json.loads(records[0].getMessage())
        assert parsed["parent_envelope_id"] is None

    def test_parent_envelope_id_populated_when_set(self, caplog):
        """parent_envelope_id in log matches the envelope's parent UUID string."""
        from core.agents.envelope_telemetry import (
            ENVELOPE_LOGGER_NAME,
            emit_envelope_log,
        )

        parent_id = uuid.uuid4()
        envelope = _make_envelope(parent_envelope_id=parent_id)
        ctx = _make_ctx()

        with caplog.at_level(logging.INFO, logger=ENVELOPE_LOGGER_NAME):
            emit_envelope_log(envelope, ctx)

        records = [r for r in caplog.records if r.name == ENVELOPE_LOGGER_NAME]
        parsed = json.loads(records[0].getMessage())
        assert parsed["parent_envelope_id"] == str(parent_id)

    def test_trace_id_from_ctx(self, caplog):
        """trace_id in log comes from ctx.trace_id."""
        from core.agents.envelope_telemetry import (
            ENVELOPE_LOGGER_NAME,
            emit_envelope_log,
        )

        ctx = _make_ctx(depth=3)
        envelope = _make_envelope()

        with caplog.at_level(logging.INFO, logger=ENVELOPE_LOGGER_NAME):
            emit_envelope_log(envelope, ctx)

        records = [r for r in caplog.records if r.name == ENVELOPE_LOGGER_NAME]
        parsed = json.loads(records[0].getMessage())
        assert parsed["trace_id"] == str(ctx.trace_id)
        assert parsed["execution_depth"] == 3

    def test_len_fields_correct(self, caplog):
        """len_failure_modes, len_normalization_warnings, len_citations reflect array lengths."""
        from core.agents.envelope_telemetry import (
            ENVELOPE_LOGGER_NAME,
            emit_envelope_log,
        )

        citations = (
            EvidenceCitation(citation_kind="trade", opaque_id="t1"),
            EvidenceCitation(citation_kind="event", opaque_id="e1"),
        )
        failure_modes = (
            FailureMode(code=FailureModeCode.UPSTREAM_TIMEOUT, detail="timed out"),
        )
        normalization_warnings = ("missing_source_timestamp",)

        envelope = _make_envelope(
            citations=citations,
            failure_modes=failure_modes,
            normalization_warnings=normalization_warnings,
        )
        ctx = _make_ctx()

        with caplog.at_level(logging.INFO, logger=ENVELOPE_LOGGER_NAME):
            emit_envelope_log(envelope, ctx)

        records = [r for r in caplog.records if r.name == ENVELOPE_LOGGER_NAME]
        parsed = json.loads(records[0].getMessage())

        assert parsed["len_citations"] == 2
        assert parsed["len_failure_modes"] == 1
        assert parsed["len_normalization_warnings"] == 1

    def test_generated_at_is_iso8601(self, caplog):
        """generated_at in the JSON is parseable as an ISO 8601 datetime."""
        from core.agents.envelope_telemetry import (
            ENVELOPE_LOGGER_NAME,
            emit_envelope_log,
        )

        envelope = _make_envelope()
        ctx = _make_ctx()

        with caplog.at_level(logging.INFO, logger=ENVELOPE_LOGGER_NAME):
            emit_envelope_log(envelope, ctx)

        records = [r for r in caplog.records if r.name == ENVELOPE_LOGGER_NAME]
        parsed = json.loads(records[0].getMessage())

        # Should parse without ValueError
        parsed_dt = datetime.fromisoformat(parsed["generated_at"])
        assert isinstance(parsed_dt, datetime)

    def test_compact_json_no_whitespace(self, caplog):
        """JSON uses compact separators (',', ':') — no whitespace in string."""
        from core.agents.envelope_telemetry import (
            ENVELOPE_LOGGER_NAME,
            emit_envelope_log,
        )

        envelope = _make_envelope()
        ctx = _make_ctx()

        with caplog.at_level(logging.INFO, logger=ENVELOPE_LOGGER_NAME):
            emit_envelope_log(envelope, ctx)

        records = [r for r in caplog.records if r.name == ENVELOPE_LOGGER_NAME]
        line = records[0].getMessage()

        # Compact JSON has no ': ' or ', ' — only ':' and ','
        assert ": " not in line, "JSON should not contain ': ' (compact separators expected)"
        assert ", " not in line, "JSON should not contain ', ' (compact separators expected)"


class TestEmitEnvelopeLogErrorHandling:
    """Telemetry failure is swallowed; fallback logger receives WARNING."""

    def test_ioerror_swallowed(self):
        """IOError from the envelope logger is caught; emit_envelope_log returns normally."""
        from core.agents.envelope_telemetry import emit_envelope_log

        envelope = _make_envelope()
        ctx = _make_ctx()

        with patch("core.agents.envelope_telemetry._logger") as mock_logger:
            mock_logger.info.side_effect = IOError("disk full")
            # Should NOT raise
            emit_envelope_log(envelope, ctx)

    def test_fallback_warning_on_ioerror(self, caplog):
        """When main logger raises, fallback logger receives a WARNING."""
        from core.agents.envelope_telemetry import (
            ENVELOPE_FALLBACK_LOGGER_NAME,
            emit_envelope_log,
        )

        envelope = _make_envelope()
        ctx = _make_ctx()

        with caplog.at_level(logging.WARNING, logger=ENVELOPE_FALLBACK_LOGGER_NAME):
            with patch("core.agents.envelope_telemetry._logger") as mock_logger:
                mock_logger.info.side_effect = RuntimeError("some io error")
                emit_envelope_log(envelope, ctx)

        fallback_records = [
            r for r in caplog.records if r.name == ENVELOPE_FALLBACK_LOGGER_NAME
        ]
        assert len(fallback_records) == 1
        assert fallback_records[0].levelno == logging.WARNING

    def test_envelope_returned_normally_after_error(self):
        """emit_envelope_log returns None (not raises) even when logging fails."""
        from core.agents.envelope_telemetry import emit_envelope_log

        envelope = _make_envelope()
        ctx = _make_ctx()

        with patch("core.agents.envelope_telemetry._logger") as mock_logger:
            mock_logger.info.side_effect = Exception("unexpected")
            result = emit_envelope_log(envelope, ctx)

        # Function should return None (no return value) and not raise
        assert result is None


class TestEmitEnvelopeLogConstants:
    """Module-level constants are exported with correct values."""

    def test_logger_name_constant(self):
        from core.agents.envelope_telemetry import ENVELOPE_LOGGER_NAME
        assert ENVELOPE_LOGGER_NAME == "fingpt.envelope.tool"

    def test_fallback_logger_name_constant(self):
        from core.agents.envelope_telemetry import ENVELOPE_FALLBACK_LOGGER_NAME
        assert ENVELOPE_FALLBACK_LOGGER_NAME == "fingpt.envelope.tool.fallback"

    def test_event_type_constant(self):
        from core.agents.envelope_telemetry import ENVELOPE_LOG_EVENT_TYPE
        assert ENVELOPE_LOG_EVENT_TYPE == "tool_result_envelope_emitted"
