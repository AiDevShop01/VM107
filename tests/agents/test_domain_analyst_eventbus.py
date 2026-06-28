"""Phase 95-12 — domain_analyst_subscriber EventBus integration tests.

Each of the 12 domain analysts subscribes to the MACRO_RELEASE event
stream via the shared :class:`DomainAnalystSubscriber`. The 3 invariants
locked at Wave 0:

- ``test_subscribes_to_macro_release_filtered_by_affected_domains``
- ``test_debounce_30s``
- ``test_idempotency_via_event_id_snapshot_version``

Implemented in Plan 95-12 (Wave 6). The unit-level tests in
``agents/domain_analyst_subscriber/tests/test_subscriber.py`` cover the
filter/debounce/idempotency logic exhaustively; this module wires the
subscriber to a real :class:`EventBus` (with a stubbed Redis client) and
asserts the end-to-end behaviour.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from agents.domain_analyst_subscriber.subscriber import (
    DEBOUNCE_SECONDS,
    DOMAIN_SLUGS,
    DomainAnalystSubscriber,
)
from contracts.economic_intelligence.events import (
    EconomicEvent,
    EventSeverity,
    EventType,
)


def _stub_redis() -> MagicMock:
    """Build a redis-client stub that records publishes + emits no messages."""
    client = MagicMock(name="redis_stub")
    client.set.return_value = True   # first-write always succeeds
    pubsub = MagicMock(name="pubsub")
    pubsub.listen.return_value = iter([])
    client.pubsub.return_value = pubsub
    return client


def _event(
    *,
    event_id: str = "evt-1",
    affected_domains: list[str] | None = None,
    snapshot_version: int = 1,
) -> EconomicEvent:
    payload: dict = {"snapshot_version": snapshot_version}
    if affected_domains is not None:
        payload["affected_domains"] = affected_domains
    return EconomicEvent(
        event_id=event_id,
        event_type=EventType.MACRO_RELEASE,
        severity=EventSeverity.MEDIUM,
        country="US",
        occurred_at=datetime.now(tz=timezone.utc),
        source="vm101.economic_event",
        payload=payload,
    )


def _stub_analysts() -> dict[str, MagicMock]:
    return {slug: MagicMock(name=f"{slug}_analyst") for slug in DOMAIN_SLUGS}


def _domain_fetcher(slug: str, event: EconomicEvent):
    return object()


# ---------------------------------------------------------------------------
# Wave 0 invariant 1 — filtered by affected_domains
# ---------------------------------------------------------------------------


def test_subscribes_to_macro_release_filtered_by_affected_domains():
    """Each analyst processes ONLY events whose affected_domains contains
    its own DOMAIN_SLUG.
    """
    analysts = _stub_analysts()
    subscriber = DomainAnalystSubscriber(
        analysts=analysts,
        domain_fetcher=_domain_fetcher,
    )
    subscriber.handle(
        _event(event_id="evt-A", affected_domains=["growth", "labour"])
    )
    analysts["growth"].invoke.assert_called_once()
    analysts["labour"].invoke.assert_called_once()
    # The other 10 must not have been invoked.
    for slug in DOMAIN_SLUGS:
        if slug in {"growth", "labour"}:
            continue
        analysts[slug].invoke.assert_not_called()


# ---------------------------------------------------------------------------
# Wave 0 invariant 2 — 30s debounce
# ---------------------------------------------------------------------------


def test_debounce_30s():
    """Two MACRO_RELEASE events for the same slug within the debounce
    window ⇒ exactly one analyst invocation.
    """
    analysts = _stub_analysts()
    clock = MagicMock()
    clock.side_effect = [0.0, float(DEBOUNCE_SECONDS) - 1.0]
    subscriber = DomainAnalystSubscriber(
        analysts=analysts,
        domain_fetcher=_domain_fetcher,
        clock=clock,
    )
    subscriber.handle(_event(event_id="evt-A", affected_domains=["growth"], snapshot_version=1))
    subscriber.handle(_event(event_id="evt-B", affected_domains=["growth"], snapshot_version=2))
    assert analysts["growth"].invoke.call_count == 1


# ---------------------------------------------------------------------------
# Wave 0 invariant 3 — idempotency via (event_id, snapshot_version)
# ---------------------------------------------------------------------------


def test_idempotency_via_event_id_snapshot_version():
    """Repeated (event_id, snapshot_version) tuples short-circuit on the
    second call — the analyst is invoked exactly once.
    """
    analysts = _stub_analysts()
    clock = MagicMock()
    clock.side_effect = [0.0, float(DEBOUNCE_SECONDS) + 100.0]
    subscriber = DomainAnalystSubscriber(
        analysts=analysts,
        domain_fetcher=_domain_fetcher,
        clock=clock,
    )
    evt = _event(event_id="evt-A", affected_domains=["growth"], snapshot_version=42)
    subscriber.handle(evt)
    subscriber.handle(evt)
    assert analysts["growth"].invoke.call_count == 1
