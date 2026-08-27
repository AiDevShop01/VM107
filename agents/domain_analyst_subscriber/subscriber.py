"""Phase 95-12 — domain_analyst_subscriber listener service.

Single process subscribing all 12 long-lived domain analysts (CONTEXT §F)
to the EventBus :class:`EventType.MACRO_RELEASE` stream, filtered per
agent by ``event.payload.affected_domains`` containing the analyst's
``DOMAIN_SLUG``.

Keeps container count flat (1 sibling service for 12 agents — see plan
95-12 §F). Ships as a docker-compose sibling service per
``feedback_mgmt_commands_need_compose_service``: the listener must
survive backend restarts and never be a mgmt-command-only worker.

Design notes
------------
* Registry-driven dispatch — the 12 analyst classes are imported
  dynamically via :func:`load_analysts`; no hardcoded ``if`` ladder
  (Phase 47.6 capability registry lock).
* 30s debounce per ``(slug, snapshot_version)`` — a bursty release
  window collapses to one analyst invocation.
* Idempotency key ``(event_id, snapshot_version)`` — repeated events
  short-circuit before any analyst invoke (Pitfall 6 — race conditions).
* One analyst raising an exception MUST NOT break the others — every
  invoke is wrapped in try/except (Phase 94 §B.3 isolation lock).
* Fail-fast on missing env vars (``REDIS_HOST`` / ``REDIS_PORT``) — no
  fallback defaults per ``feedback_env_driven_no_fallbacks``.

Phase 94 pillar analyst code is UNCHANGED (Open Q 4 Path A resolution +
Pitfall 9 mitigation) — the Chief Economist Synthesizer composes the 12
new Domain SpecialistResponses + 4 existing Pillar SpecialistResponses
naturally via citation count.
"""

from __future__ import annotations

import importlib
import logging
import signal
import sys
import time
from typing import Any, Callable

from contracts.economic_intelligence.events import EconomicEvent, EventType
from core.event_bus import EventBus

logger = logging.getLogger(__name__)


# 12 canonical domain slugs — same list as
# tests/agents/test_domain_analyst_contract.py + the generator at
# scripts/generate_phase95_domain_analysts.py.
DOMAIN_SLUGS: list[str] = [
    "growth",
    "inflation",
    "labour",
    "housing",
    "credit",
    "monetary_policy",
    "fiscal",
    "external_sector",
    "manufacturing",
    "consumer",
    "financial_conditions",
    "commodities",
]


DEBOUNCE_SECONDS: int = 30


# ---------------------------------------------------------------------------
# Registry-driven loader (Phase 47.6 lock — no hardcoded specialist list)
# ---------------------------------------------------------------------------


def _class_name(slug: str) -> str:
    return "".join(part.title() for part in slug.split("_")) + "DomainAnalyst"


def load_analysts() -> dict[str, Any]:
    """Dynamically import and instantiate the 12 domain analyst classes.

    Returns a ``{slug: AnalystInstance}`` dict. Registry-driven — adding
    a 13th domain only requires (a) appending its slug to ``DOMAIN_SLUGS``
    and (b) shipping its ``agents/<slug>_domain_analyst`` directory; no
    edits to dispatch code (Phase 47.6 capability registry lock).
    """
    analysts: dict[str, Any] = {}
    for slug in DOMAIN_SLUGS:
        module = importlib.import_module(f"agents.{slug}_domain_analyst.agent")
        cls = getattr(module, _class_name(slug))
        analysts[slug] = cls()
    return analysts


# ---------------------------------------------------------------------------
# DomainAnalystSubscriber — debounce + idempotency + resilience
# ---------------------------------------------------------------------------


class DomainAnalystSubscriber:
    """Subscribes 12 domain analysts to MACRO_RELEASE EventBus traffic.

    Parameters
    ----------
    event_bus:
        Optional injected :class:`EventBus` (typically a stub in tests).
    analysts:
        Optional ``{slug: AnalystInstance}`` dict. If ``None`` the
        default 12 are loaded via :func:`load_analysts`.
    idempotency_store:
        Optional ``set``-like store of processed ``(event_id, snapshot_version)``
        tuples. Defaults to an in-memory ``set``. Production deployments
        may swap in a Redis-backed set for cross-restart durability.
    domain_fetcher:
        Callable ``(slug, event) -> Domain`` resolving the Domain payload
        from snapshot storage. Optional — if ``None`` the subscriber logs
        the event without invoking analysts (Wave 6 stub; SnapshotRepository
        wiring lands in 95-13).
    debounce_seconds:
        Override the 30s debounce window (default :data:`DEBOUNCE_SECONDS`).
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        analysts: dict[str, Any] | None = None,
        idempotency_store: set | None = None,
        domain_fetcher: Callable[[str, EconomicEvent], Any] | None = None,
        debounce_seconds: int = DEBOUNCE_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.event_bus = event_bus
        self.analysts = analysts if analysts is not None else load_analysts()
        self.processed: set = idempotency_store if idempotency_store is not None else set()
        # _last_invoke_ts is plain dict (NOT defaultdict) so missing slug ⇒
        # first invocation ⇒ debounce check skipped. Using defaultdict(float)
        # would cause a clock returning 0.0 on the first call to be wrongly
        # debounced against the 0.0 default.
        self._last_invoke_ts: dict[str, float] = {}
        self.domain_fetcher = domain_fetcher
        self.debounce_seconds = debounce_seconds
        self._clock = clock

    # ------------------------------------------------------------------ handle
    def handle(self, event: EconomicEvent) -> None:
        """Dispatch a single EconomicEvent to the matching analysts.

        Skips events whose ``event_type != MACRO_RELEASE`` or whose
        ``payload.affected_domains`` doesn't intersect any of the 12
        domain slugs. Applies debounce + idempotency before each analyst
        invoke. One analyst raising MUST NOT break the others.
        """
        if event.event_type != EventType.MACRO_RELEASE:
            return

        affected = event.payload.get("affected_domains") or []
        if not affected:
            return
        snapshot_version = event.payload.get("snapshot_version")

        # Phase 168 (D-06a / AGV-08 / T-168-10): read the run's point-in-time
        # as-of off the inbound EconomicEvent envelope and carry it IMMUTABLY
        # down the fan-out. This async MACRO_RELEASE hop is exactly where a
        # re-mint to ``now()`` would silently introduce temporal look-ahead
        # (the "collapse to latest" pitfall) — we NEVER re-stamp here, we
        # forward ``event.knowledge_time`` verbatim. ``None`` means the event
        # predates the knowledge_time carrier (168-01), in which case the
        # downstream analyst falls back to its own as-of.
        knowledge_time = event.knowledge_time

        for slug in affected:
            analyst = self.analysts.get(slug)
            if analyst is None:
                continue

            # Idempotency check — same (slug, event_id, snapshot_version) ⇒ skip.
            # Slug is part of the key so a broadcast event reaching all 12
            # analysts marks 12 separate idempotency slots, not one shared
            # slot that would suppress 11 of the 12.
            key = (slug, event.event_id, snapshot_version)
            if key in self.processed:
                logger.debug(
                    "domain_analyst_subscriber: idempotency hit "
                    "slug=%s event_id=%s snapshot_version=%s",
                    slug, event.event_id, snapshot_version,
                )
                continue

            # Debounce — same slug invoked within debounce_seconds ⇒ skip.
            # First-ever invocation for this slug is NEVER debounced.
            now = self._clock()
            last_ts = self._last_invoke_ts.get(slug)
            if last_ts is not None and now - last_ts < self.debounce_seconds:
                logger.debug(
                    "domain_analyst_subscriber: debounce skip "
                    "slug=%s event_id=%s",
                    slug, event.event_id,
                )
                continue

            try:
                domain = self._fetch_domain(slug, event)
                if domain is None:
                    logger.info(
                        "domain_analyst_subscriber: no domain payload "
                        "available slug=%s event_id=%s — logging only",
                        slug, event.event_id,
                    )
                else:
                    # D-06a: forward the event's as-of onto the analyst
                    # invocation via the existing ``context`` param (all 12
                    # domain analysts accept ``context: dict | None``) — an
                    # immutable passthrough, not a fresh stamp.
                    analyst.invoke(domain, {"knowledge_time": knowledge_time})
                # Successful (or log-only) dispatch marks the key.
                self.processed.add(key)
                self._last_invoke_ts[slug] = now
            except Exception as exc:  # noqa: BLE001 — one bad analyst must not kill the rest
                logger.exception(
                    "domain_analyst_subscriber: analyst %s raised on "
                    "event %s: %s",
                    slug, event.event_id, exc,
                )
                # Intentionally do NOT mark the key — retryable failure.
                continue

    # ------------------------------------------------------------------ helpers
    def _fetch_domain(self, slug: str, event: EconomicEvent) -> Any | None:
        """Resolve the current Domain payload for ``slug``.

        Delegates to the injected ``domain_fetcher`` if provided. Wave 6
        ships without SnapshotRepository wiring — 95-13 lands the
        production fetcher. Returning ``None`` is a valid no-op (the
        subscriber logs and continues).
        """
        if self.domain_fetcher is None:
            return None
        return self.domain_fetcher(slug, event)


# ---------------------------------------------------------------------------
# Entrypoint — runs as a docker-compose sibling service.
# ---------------------------------------------------------------------------


def _install_signal_handlers() -> None:
    def _handle(signum: int, _frame: Any) -> None:
        logger.info("domain_analyst_subscriber: signal %s — shutting down.", signum)
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


def main() -> None:
    """Run the subscriber loop. Fail-fast on missing env vars."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    # EventBus constructor reads REDIS_HOST + REDIS_PORT from env with NO
    # fallback defaults — KeyError at instantiation if missing (per
    # feedback_env_driven_no_fallbacks).
    bus = EventBus()
    subscriber = DomainAnalystSubscriber(event_bus=bus)
    bus.subscribe(EventType.MACRO_RELEASE, subscriber.handle)

    _install_signal_handlers()
    logger.info(
        "domain_analyst_subscriber: started with %d analysts subscribed "
        "to MACRO_RELEASE.",
        len(subscriber.analysts),
    )
    try:
        bus.run()
    except KeyboardInterrupt:
        logger.info("domain_analyst_subscriber: KeyboardInterrupt — exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
