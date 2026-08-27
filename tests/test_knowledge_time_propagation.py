"""Phase 168 Plan 04 (AGV-08 / D-06) — stamp-once + immutable-propagation pillar.

Proves the two propagation surfaces that close G3:

1. Nested dispatch (D-06c): a ``knowledge_time`` stamped once at the top
   ``InvocationContext`` is byte-identical across a deep ``_derive_child_ctx``
   chain — the frozen model forbids any downstream re-mint, so look-ahead can
   never be silently introduced at nesting.

2. Async MACRO_RELEASE fan-out (D-06a): an ``EconomicEvent`` carrying a PAST
   ``knowledge_time`` driven through the ``DomainAnalystSubscriber`` preserves
   that same as-of on the downstream analyst invocation — it is NOT collapsed
   to ``now()`` on the async hop (T-168-10).

Fixtures inject at the typed seam only (a real InvocationContext; a real
EconomicEvent; a recording analyst that captures the context it received). No
production business function is patched.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from agents.domain_analyst_subscriber.subscriber import DomainAnalystSubscriber
from contracts.economic_intelligence.events import (
    EconomicEvent,
    EventSeverity,
    EventType,
)
from core.agents.tool_dispatcher import _derive_child_ctx
from fingpt_core.contracts.invocation_context import InvocationContext


_AS_OF = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _root_ctx(knowledge_time: datetime) -> InvocationContext:
    return InvocationContext(
        envelope_id=uuid4(),
        trace_id=uuid4(),
        agent_id="test_agent",
        knowledge_time=knowledge_time,
    )


# ---------------------------------------------------------------------------
# Surface 1 — nested dispatch immutability (D-06c)
# ---------------------------------------------------------------------------


def test_nested_child_ctx_shares_root_knowledge_time():
    """Every child ctx down a 5-level _derive_child_ctx chain equals the root as-of."""
    root = _root_ctx(_AS_OF)
    ctx = root
    for _ in range(5):
        ctx = _derive_child_ctx(ctx, new_envelope_id=uuid4())
        assert ctx.knowledge_time == root.knowledge_time, (
            "child knowledge_time must equal the root's — stamp-once, immutable "
            "propagation, no re-mint at nesting (D-06c)"
        )
    # Depth advanced (proving we actually nested), as-of unchanged (proving immutability).
    assert ctx.execution_depth == root.execution_depth + 5
    assert ctx.knowledge_time == _AS_OF


def test_knowledge_time_is_frozen_immutable():
    """The frozen InvocationContext forbids re-minting knowledge_time downstream."""
    ctx = _root_ctx(_AS_OF)
    with pytest.raises(Exception):
        ctx.knowledge_time = datetime.now(timezone.utc)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Surface 2 — async MACRO_RELEASE fan-out preserves the event's as-of (D-06a)
# ---------------------------------------------------------------------------


class _RecordingAnalyst:
    """Typed-seam double: records the context passed to invoke (no business logic)."""

    def __init__(self) -> None:
        self.received_context: dict | None = None

    def invoke(self, domain, context: dict | None = None):
        self.received_context = context
        return None


def _macro_event(*, knowledge_time: datetime) -> EconomicEvent:
    return EconomicEvent(
        event_id="evt-pit-1",
        event_type=EventType.MACRO_RELEASE,
        severity=EventSeverity.MEDIUM,
        country="US",
        occurred_at=datetime.now(timezone.utc),
        source="vm101.economic_event",
        payload={"affected_domains": ["growth"], "snapshot_version": 1},
        knowledge_time=knowledge_time,
    )


def test_fanout_preserves_event_knowledge_time():
    """The subscriber forwards event.knowledge_time to the analyst — no collapse to now()."""
    past = datetime(2020, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    analyst = _RecordingAnalyst()
    subscriber = DomainAnalystSubscriber(
        analysts={"growth": analyst},
        idempotency_store=set(),
        domain_fetcher=lambda slug, event: object(),  # non-None => analyst invoked
    )

    subscriber.handle(_macro_event(knowledge_time=past))

    assert analyst.received_context is not None, "analyst was not invoked"
    forwarded = analyst.received_context["knowledge_time"]
    assert forwarded == past, (
        "the fan-out must carry the event's PAST as-of immutably — not re-mint "
        "to now() on the async hop (T-168-10)"
    )
    # Explicit no-collapse assertion: the forwarded as-of is not 'now'.
    assert forwarded != datetime.now(timezone.utc)


def test_fanout_none_knowledge_time_is_not_reminted():
    """A pre-carrier event (knowledge_time=None) forwards None, not a fresh now()."""
    analyst = _RecordingAnalyst()
    subscriber = DomainAnalystSubscriber(
        analysts={"growth": analyst},
        idempotency_store=set(),
        domain_fetcher=lambda slug, event: object(),
    )
    # Event without knowledge_time (defaults to None — pre-168-01 publisher).
    event = EconomicEvent(
        event_id="evt-pit-2",
        event_type=EventType.MACRO_RELEASE,
        severity=EventSeverity.MEDIUM,
        country="US",
        occurred_at=datetime.now(timezone.utc),
        source="vm101.economic_event",
        payload={"affected_domains": ["growth"], "snapshot_version": 1},
    )

    subscriber.handle(event)

    assert analyst.received_context is not None
    # None means "event predates the carrier" — downstream falls back to its own
    # as-of; the subscriber must NOT invent a now() here.
    assert analyst.received_context["knowledge_time"] is None
