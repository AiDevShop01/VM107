"""Phase 95-12 — DomainAnalystSubscriber unit tests.

5 behaviour tests required by the plan:

1. Subscribes to MACRO_RELEASE filtered by ``affected_domains``.
2. 30s debounce per (slug, snapshot_version).
3. Idempotency via (event_id, snapshot_version).
4. Broadcast event reaches all 12 analysts.
5. One analyst raising MUST NOT break the rest (resilience).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

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

# Contract-faithful Domain builder (all 12 slugs) — reuse, never hand-roll.
from tests.agents.test_domain_analyst_contract import _fake_domain


def _event(
    *,
    event_id: str = "evt-1",
    event_type: EventType = EventType.MACRO_RELEASE,
    affected_domains: list[str] | None = None,
    snapshot_version: int = 1,
) -> EconomicEvent:
    payload: dict = {"snapshot_version": snapshot_version}
    if affected_domains is not None:
        payload["affected_domains"] = affected_domains
    return EconomicEvent(
        event_id=event_id,
        event_type=event_type,
        severity=EventSeverity.MEDIUM,
        country="US",
        occurred_at=datetime.now(tz=timezone.utc),
        source="vm101.economic_event",
        payload=payload,
    )


def _stub_analysts(slugs: list[str] | None = None) -> dict[str, MagicMock]:
    slugs = slugs if slugs is not None else DOMAIN_SLUGS
    return {slug: MagicMock(name=f"{slug}_analyst") for slug in slugs}


def _domain_fetcher_factory():
    """Returns a fetcher that yields a real, validated ``Domain`` per call.

    D-03 fidelity: the production fetcher returns a validated VM107-local
    ``Domain`` (not a bare ``object()``), so the tests must exercise the real
    contract — otherwise ``invoke()``'s ``assert domain.slug == DOMAIN_SLUG``
    (domain_agent.py:122) is never reached in test.
    """

    def fetcher(slug: str, event: EconomicEvent):
        return _fake_domain(slug)

    return fetcher


# ---------------------------------------------------------------------------
# 1. Filtered by affected_domains
# ---------------------------------------------------------------------------


def test_subscribes_to_macro_release_filtered_by_affected_domains():
    analysts = _stub_analysts()
    sub = DomainAnalystSubscriber(
        analysts=analysts,
        domain_fetcher=_domain_fetcher_factory(),
    )
    sub.handle(_event(affected_domains=["growth", "inflation"]))

    analysts["growth"].invoke.assert_called_once()
    analysts["inflation"].invoke.assert_called_once()
    for slug in DOMAIN_SLUGS:
        if slug not in {"growth", "inflation"}:
            analysts[slug].invoke.assert_not_called()


def test_non_macro_release_events_are_ignored():
    analysts = _stub_analysts()
    sub = DomainAnalystSubscriber(
        analysts=analysts,
        domain_fetcher=_domain_fetcher_factory(),
    )
    sub.handle(
        _event(
            event_type=EventType.CENTRAL_BANK,
            affected_domains=["growth"],
        )
    )
    for slug in DOMAIN_SLUGS:
        analysts[slug].invoke.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Debounce 30s
# ---------------------------------------------------------------------------


def test_debounce_30s():
    """Two events for the same slug within debounce window ⇒ one invoke."""
    analysts = _stub_analysts()
    clock = MagicMock()
    clock.side_effect = [0.0, 5.0]  # 5s apart, well within 30s window
    sub = DomainAnalystSubscriber(
        analysts=analysts,
        domain_fetcher=_domain_fetcher_factory(),
        clock=clock,
    )
    sub.handle(_event(event_id="evt-1", affected_domains=["growth"], snapshot_version=1))
    sub.handle(_event(event_id="evt-2", affected_domains=["growth"], snapshot_version=2))
    assert analysts["growth"].invoke.call_count == 1


def test_debounce_window_expires_after_30s():
    """After debounce_seconds elapses, the analyst fires again."""
    analysts = _stub_analysts()
    clock = MagicMock()
    clock.side_effect = [0.0, float(DEBOUNCE_SECONDS) + 1.0]
    sub = DomainAnalystSubscriber(
        analysts=analysts,
        domain_fetcher=_domain_fetcher_factory(),
        clock=clock,
    )
    sub.handle(_event(event_id="evt-1", affected_domains=["growth"], snapshot_version=1))
    sub.handle(_event(event_id="evt-2", affected_domains=["growth"], snapshot_version=2))
    assert analysts["growth"].invoke.call_count == 2


# ---------------------------------------------------------------------------
# 3. Idempotency via (event_id, snapshot_version)
# ---------------------------------------------------------------------------


def test_idempotency_via_event_id_snapshot_version():
    """Same (event_id, snapshot_version) ⇒ second handle is a no-op."""
    analysts = _stub_analysts()
    clock = MagicMock()
    clock.side_effect = [0.0, float(DEBOUNCE_SECONDS) + 100.0]  # well outside debounce
    sub = DomainAnalystSubscriber(
        analysts=analysts,
        domain_fetcher=_domain_fetcher_factory(),
        clock=clock,
    )
    evt = _event(event_id="evt-1", affected_domains=["growth"], snapshot_version=7)
    sub.handle(evt)
    sub.handle(evt)
    assert analysts["growth"].invoke.call_count == 1


# ---------------------------------------------------------------------------
# 4. Broadcast event reaches all 12 analysts
# ---------------------------------------------------------------------------


def test_subscriber_dispatches_to_all_12_analysts_when_event_lists_all_domains():
    analysts = _stub_analysts()
    sub = DomainAnalystSubscriber(
        analysts=analysts,
        domain_fetcher=_domain_fetcher_factory(),
    )
    sub.handle(_event(affected_domains=DOMAIN_SLUGS.copy()))
    for slug in DOMAIN_SLUGS:
        analysts[slug].invoke.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Resilience — one analyst raising must not break others
# ---------------------------------------------------------------------------


def test_subscriber_resilient_to_one_analyst_raising():
    analysts = _stub_analysts()
    analysts["growth"].invoke.side_effect = RuntimeError("boom")
    sub = DomainAnalystSubscriber(
        analysts=analysts,
        domain_fetcher=_domain_fetcher_factory(),
    )
    # Should not raise — the bad analyst is logged and skipped.
    sub.handle(_event(affected_domains=DOMAIN_SLUGS.copy()))

    # All other 11 analysts must have been invoked.
    for slug in DOMAIN_SLUGS:
        if slug == "growth":
            continue
        analysts[slug].invoke.assert_called_once()


# ---------------------------------------------------------------------------
# 6. Unknown slug in affected_domains is gracefully skipped
# ---------------------------------------------------------------------------


def test_unknown_slug_is_skipped_silently():
    analysts = _stub_analysts()
    sub = DomainAnalystSubscriber(
        analysts=analysts,
        domain_fetcher=_domain_fetcher_factory(),
    )
    sub.handle(_event(affected_domains=["growth", "nonexistent_domain"]))
    analysts["growth"].invoke.assert_called_once()


# ---------------------------------------------------------------------------
# 7. Missing affected_domains payload is gracefully skipped
# ---------------------------------------------------------------------------


def test_missing_affected_domains_payload_is_noop():
    analysts = _stub_analysts()
    sub = DomainAnalystSubscriber(
        analysts=analysts,
        domain_fetcher=_domain_fetcher_factory(),
    )
    sub.handle(_event(affected_domains=None))
    for slug in DOMAIN_SLUGS:
        analysts[slug].invoke.assert_not_called()


# ---------------------------------------------------------------------------
# 8. Failed analyst does NOT consume the idempotency slot — retryable
# ---------------------------------------------------------------------------


def test_failed_analyst_does_not_burn_idempotency_slot():
    analysts = _stub_analysts()
    # First call raises; second call succeeds.
    analysts["growth"].invoke.side_effect = [RuntimeError("boom"), None]
    clock = MagicMock()
    clock.side_effect = [0.0, float(DEBOUNCE_SECONDS) + 1.0]
    sub = DomainAnalystSubscriber(
        analysts=analysts,
        domain_fetcher=_domain_fetcher_factory(),
        clock=clock,
    )
    evt = _event(event_id="evt-1", affected_domains=["growth"], snapshot_version=1)
    sub.handle(evt)
    # Second call: same event_id+snapshot_version, but the first failed —
    # idempotency slot was NOT marked, so the retry fires.
    sub.handle(evt)
    assert analysts["growth"].invoke.call_count == 2


# ---------------------------------------------------------------------------
# 9. main() wires a real (non-None) DomainSnapshotFetcher (AZE-02 acceptance #1)
# ---------------------------------------------------------------------------


def test_main_wires_real_fetcher():
    """``main()`` constructs the subscriber with a real ``DomainSnapshotFetcher``
    (no longer ``domain_fetcher=None``) — the blocker-B1 fix."""
    with patch(
        "agents.domain_analyst_subscriber.subscriber.EventBus"
    ), patch(
        "agents.domain_analyst_subscriber.subscriber.DomainAnalystSubscriber"
    ) as MockSub, patch(
        "agents.domain_analyst_subscriber.domain_fetcher.DomainSnapshotFetcher"
    ) as MockFetcher, patch(
        "agents.domain_analyst_subscriber.subscriber._install_signal_handlers"
    ):
        # main() logs len(subscriber.analysts) — give the mock a real length.
        MockSub.return_value.analysts = {}

        from agents.domain_analyst_subscriber.subscriber import main

        main()

    MockSub.assert_called_once()
    _, kwargs = MockSub.call_args
    assert kwargs.get("domain_fetcher") is not None
    assert kwargs["domain_fetcher"] is MockFetcher.return_value


# ---------------------------------------------------------------------------
# 10. Transient miss (fetcher returns None) does NOT burn the idempotency slot
# ---------------------------------------------------------------------------


def test_transient_miss_does_not_burn_idempotency_slot():
    """A transient miss (fetcher returns ``None`` — snapshot not ready) must NOT
    mark the idempotency/debounce slot, so the release is re-processed when the
    snapshot lands (D-02 permanent-drop fix — subscriber EDIT 2)."""
    analysts = _stub_analysts()

    calls = {"n": 0}

    def fetcher(slug: str, event: EconomicEvent):
        calls["n"] += 1
        return None if calls["n"] == 1 else _fake_domain(slug)

    clock = MagicMock()
    clock.side_effect = [0.0, float(DEBOUNCE_SECONDS) + 1.0]
    sub = DomainAnalystSubscriber(
        analysts=analysts,
        domain_fetcher=fetcher,
        clock=clock,
    )
    evt = _event(event_id="evt-1", affected_domains=["growth"], snapshot_version=1)
    sub.handle(evt)  # miss -> None -> NOT marked
    sub.handle(evt)  # retry -> real Domain -> analyst fires
    assert analysts["growth"].invoke.call_count == 1
