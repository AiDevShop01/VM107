"""Phase 71 Plan 07 — GREEN tests for AIProvenanceContract round-trip through
ToolResultEnvelope (Phase 70.5 envelope substrate) + LegacyResponsePayload
formalization (RESEARCH Open Question 2 / GAP-70.5-B).

Plan 71-07 closes REQ-71-5 end-to-end:
- A payload that carries an ``ai_provenance: AIProvenanceContract`` field
  round-trips through dispatch_tool() unchanged (the dispatcher preserves
  the typed payload — it does NOT strip user-defined fields).
- ``freshness_seconds_to_class()`` is the platform-wide canonical mapper for
  the 4-class enum (CONTEXT Decision 6 + Pattern 5).
- The dispatcher's Response-dataclass coercion path emits a typed
  ``LegacyResponsePayload`` (Pydantic BaseModel), formally documented as the
  permanent path for the 4 coordination-only tools (call_subordinate,
  notify_user, persist_narrative, fetch_replay_frame). Citations are
  intentionally empty: coordination tools do not produce evidence.
- The LegacyResponsePayload import now comes from fingpt_core
  (option (a) per RESEARCH Open Question 2).

REQ-71-5 + GAP-70.5-B.

Spec sources:
- CONTEXT.md Decision 3: AIProvenanceContract field set
- CONTEXT.md Decision 6: 4-class freshness {live, recent, stale, invalidated}
- RESEARCH.md Pattern 5: mapper rules (live <= expected, recent <= 3*expected,
  stale > 3*expected, invalidated short-circuit on refused/failure)
- RESEARCH.md Open Question 2: LegacyResponsePayload disposition — option (a)
  formalize in fingpt_core (this plan's decision).
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from fingpt_core.contracts.invocation_context import InvocationContext
from fingpt_core.contracts.provenance import (
    AIProvenanceContract,
    FreshnessClass,
    freshness_seconds_to_class,
)
from fingpt_core.contracts.tool_envelope import (
    LegacyResponsePayload,
    ToolResultEnvelope,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx() -> InvocationContext:
    """Build a top-level InvocationContext for dispatch tests."""
    return InvocationContext(
        envelope_id=uuid.uuid4(),
        parent_envelope_id=None,
        trace_id=uuid.uuid4(),
        agent_id="agent_zero",
        conversation_id=None,
        execution_depth=0,
    )


def _make_entry(
    typical_confidence: float = 0.85,
    expected_freshness: int = 60,
    is_deterministic: bool = True,
    version: str = "1.0.0",
):
    """Build a ToolEntry stand-in matching the registry shape."""
    from core.agents.tool_registry import ToolEntry
    return ToolEntry(
        id="phase71_roundtrip_tool",
        status="real",
        source_module="tools.phase71_roundtrip_tool",
        typical_confidence=typical_confidence,
        expected_freshness_seconds=expected_freshness,
        is_deterministic=is_deterministic,
        version=version,
        is_facade=False,
    )


# Minimal typed payload carrying ai_provenance — exercises the round-trip
class _Phase71RoundTripPayload(BaseModel):
    """Typed payload that carries an AIProvenanceContract for round-trip verification."""

    model_config = ConfigDict(frozen=True)

    PAYLOAD_SCHEMA_VERSION: str = "1.0"
    summary: str
    ai_provenance: AIProvenanceContract


def _valid_provenance(**overrides) -> AIProvenanceContract:
    """Build a valid AIProvenanceContract for tests."""
    base = dict(
        confidence_0_100=78,
        uncertainty=0.22,
        evidence_count=3,
        evidence_summary="3 citations: 2 trades, 1 narrative",
        model_version="claude-opus-4-7",
        prompt_version="pre-trade-v3",
        generated_at=datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc),
        freshness_class=FreshnessClass.LIVE,
    )
    base.update(overrides)
    return AIProvenanceContract(**base)


# ---------------------------------------------------------------------------
# Test 1: AIProvenanceContract round-trips through dispatch_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_envelope_carries_ai_provenance_contract():
    """A payload with ``ai_provenance: AIProvenanceContract`` round-trips through
    dispatch_tool() unchanged.

    The dispatcher's _build_success_envelope path preserves the typed payload
    in envelope.payload — every user-defined field (including ai_provenance)
    survives the wrap.
    """
    from core.agents.tool_dispatcher import dispatch_tool

    entry = _make_entry()
    ctx = _make_ctx()

    provenance = _valid_provenance(confidence_0_100=78, uncertainty=0.22)
    payload = _Phase71RoundTripPayload(
        summary="phase71 round-trip",
        ai_provenance=provenance,
    )

    mock_reg = MagicMock()
    mock_reg.snapshot_hash = "sha256-phase71-roundtrip"
    mock_reg.lookup.return_value = None  # no refusal

    with (
        patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
        patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
        patch("core.agents.tool_dispatcher._lookup_summary", return_value=None),
        patch("core.agents.tool_dispatcher._invoke_resolver", return_value=payload),
    ):
        envelope = await dispatch_tool("phase71_roundtrip_tool", {}, ctx)

    # Envelope shape preserved
    assert isinstance(envelope, ToolResultEnvelope)
    assert envelope.outcome_class == "success"
    assert envelope.success is True

    # Payload round-trip — ai_provenance preserved unchanged
    assert isinstance(envelope.payload, _Phase71RoundTripPayload)
    assert envelope.payload.ai_provenance is provenance
    assert envelope.payload.ai_provenance.confidence_0_100 == 78
    assert envelope.payload.ai_provenance.uncertainty == pytest.approx(0.22)
    assert envelope.payload.ai_provenance.freshness_class == FreshnessClass.LIVE

    # Envelope's own freshness_seconds is populated from signals (None in this
    # path since the payload didn't declare ToolConfidenceSignals) — this is
    # expected; the AIProvenanceContract carries its own freshness_class.
    # Dispatcher's confidence/freshness computation is independent of the
    # AIProvenanceContract payload field.
    assert envelope.payload_schema_version == "1.0"


# ---------------------------------------------------------------------------
# Test 2: Freshness mapper integration
# ---------------------------------------------------------------------------


def test_provenance_freshness_class_matches_registry_expected_freshness():
    """freshness_seconds_to_class() — the canonical platform-wide mapper —
    derives FreshnessClass from envelope.freshness_seconds + tool registry's
    expected_freshness_seconds.

    Example: a tool registered with expected_freshness_seconds=60.
    - actual=30  -> LIVE        (30 <= 60)
    - actual=120 -> RECENT      (60 < 120 <= 180)
    - actual=500 -> STALE       (500 > 180)
    - outcome_class=refused     -> INVALIDATED (short-circuit)
    - outcome_class=failure     -> INVALIDATED (short-circuit)
    """
    expected = 60

    # LIVE: actual <= expected
    assert freshness_seconds_to_class(30, expected) == FreshnessClass.LIVE
    assert freshness_seconds_to_class(60, expected) == FreshnessClass.LIVE

    # RECENT: expected < actual <= 3*expected
    assert freshness_seconds_to_class(120, expected) == FreshnessClass.RECENT
    assert freshness_seconds_to_class(180, expected) == FreshnessClass.RECENT

    # STALE: actual > 3*expected
    assert freshness_seconds_to_class(500, expected) == FreshnessClass.STALE

    # INVALIDATED short-circuit on refused/failure (regardless of seconds)
    assert (
        freshness_seconds_to_class(30, expected, outcome_class="refused")
        == FreshnessClass.INVALIDATED
    )
    assert (
        freshness_seconds_to_class(30, expected, outcome_class="failure")
        == FreshnessClass.INVALIDATED
    )

    # str-Enum identity — bare string compares equal
    assert freshness_seconds_to_class(30, expected) == "live"
    assert freshness_seconds_to_class(500, expected) == "stale"


# ---------------------------------------------------------------------------
# Test 3: LegacyResponsePayload path emits empty citations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_response_payload_path_emits_empty_citations():
    """When a tool returns a helpers.tool.Response dataclass (not a Pydantic
    BaseModel), the dispatcher coerces it to LegacyResponsePayload. The
    resulting envelope carries citations=() — documented as the FORMALIZED
    expectation for coordination-only tools (call_subordinate, notify_user,
    persist_narrative, fetch_replay_frame).

    Per RESEARCH Open Question 2 / GAP-70.5-B option (a): this is the
    permanent supported path, not a bug to fix.
    """
    from core.agents.tool_dispatcher import dispatch_tool

    entry = _make_entry()
    ctx = _make_ctx()

    # Duck-type a helpers.tool.Response — the dispatcher checks
    # __class__.__name__ == "Response" + hasattr(message)
    class Response:
        def __init__(self, message: str, break_loop: bool = False):
            self.message = message
            self.break_loop = break_loop
            self.additional = None

    fake_response = Response(message="subordinate call completed", break_loop=False)

    mock_reg = MagicMock()
    mock_reg.snapshot_hash = "sha256-phase71-legacy"
    mock_reg.lookup.return_value = None

    with (
        patch("core.agents.tool_dispatcher._get_registry", return_value=mock_reg),
        patch("core.agents.tool_dispatcher._get_tool_entry", return_value=entry),
        patch("core.agents.tool_dispatcher._lookup_summary", return_value=None),
        patch("core.agents.tool_dispatcher._invoke_resolver", return_value=fake_response),
    ):
        envelope = await dispatch_tool("phase71_roundtrip_tool", {}, ctx)

    # Envelope shape preserved
    assert isinstance(envelope, ToolResultEnvelope)
    assert envelope.outcome_class == "success"

    # Payload coerced to typed LegacyResponsePayload (NOT the raw Response dataclass)
    assert isinstance(envelope.payload, LegacyResponsePayload)
    assert envelope.payload.message == "subordinate call completed"
    assert envelope.payload.break_loop is False

    # Citations empty — documented formalized behavior for coordination tools
    assert envelope.citations == ()
    assert envelope.assumptions == ()


# ---------------------------------------------------------------------------
# Test 4: LegacyResponsePayload is a frozen Pydantic BaseModel from fingpt_core
# ---------------------------------------------------------------------------


def test_legacy_response_payload_envelope_still_typed():
    """LegacyResponsePayload is the formalized fingpt_core Pydantic class
    (not a local dispatcher dataclass). It is frozen and constructs cleanly
    with the documented fields.

    Per RESEARCH Open Question 2 option (a): the class lives at
    ``fingpt_core.contracts.tool_envelope.LegacyResponsePayload`` and is the
    permanent supported path for coordination-only tools.
    """
    # Identity check: dispatcher imports LegacyResponsePayload from fingpt_core
    from core.agents.tool_dispatcher import LegacyResponsePayload as DispatcherImport

    assert DispatcherImport is LegacyResponsePayload

    # Pydantic BaseModel inheritance (not a local dataclass)
    assert issubclass(LegacyResponsePayload, BaseModel)

    # Constructs with documented field set
    payload = LegacyResponsePayload(
        message="hello",
        break_loop=False,
    )
    assert payload.message == "hello"
    assert payload.break_loop is False
    assert payload.PAYLOAD_SCHEMA_VERSION == "1.0"

    # Frozen — mutation raises ValidationError
    with pytest.raises((ValidationError, TypeError)):
        payload.message = "mutated"  # type: ignore[misc]
