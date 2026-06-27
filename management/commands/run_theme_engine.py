"""Phase 94-05 — Theme Engine listener entrypoint.

Long-running listener that subscribes to the Phase 94 Event Bus (94-02)
for any event type that could move evidence on a tracked theme, then
re-evaluates the catalog via :class:`MacroThemeEngine` and persists the
resulting :class:`Theme` envelopes.

Per ``feedback_mgmt_commands_need_compose_service`` the sibling service
``theme_engine`` (VM107/docker-compose.yml) invokes this module.

Per ``env-driven-no-fallbacks``: ``REDIS_HOST`` / ``REDIS_PORT`` are read
by the EventBus client; missing env raises at import time.

Persistence in Wave 3a is a no-op log adapter — 94-07 wires the
SnapshotCoordinator to persist Theme envelopes into Redis snapshot
storage. This keeps the listener loop-closed today (warm-loop end-to-end)
without coupling to storage that lands later.

Usage::

    python -m management.commands.run_theme_engine
"""

from __future__ import annotations

import logging
import signal
import sys
from collections import defaultdict
from typing import Any

from contracts.economic_intelligence.events import EconomicEvent, EventType
from contracts.economic_intelligence.themes import Theme
from core.event_bus import EventBus
from macro_theme_engine import MacroThemeEngine

logger = logging.getLogger(__name__)

# Event types that may move evidence on at least one catalogued theme.
_SUBSCRIBED_EVENT_TYPES = (
    EventType.MACRO_RELEASE,
    EventType.CENTRAL_BANK,
    EventType.REGIME_CHANGE,
    EventType.RESEARCH,
    EventType.FORECAST_UPDATE,
    EventType.DISCOVERY,
)


class _EvidenceState:
    """In-memory rolling cache of satisfied evidence signals per theme.

    Wave 3a holds only enough state to keep the listener responsive — a
    Redis-backed cache lands when the SnapshotCoordinator (94-07) takes
    ownership of theme persistence.
    """

    def __init__(self) -> None:
        self._signals: dict[str, set[str]] = defaultdict(set)

    def add(self, theme_id: str, signal_key: str) -> None:
        self._signals[theme_id].add(signal_key)

    def signals(self, theme_id: str) -> set[str]:
        return set(self._signals.get(theme_id, set()))


def _signal_keys_for_event(event: EconomicEvent) -> list[str]:
    """Map an EconomicEvent to the canonical rule-signal keys it satisfies."""
    keys: list[str] = [f"event_type:{event.event_type.value}"]
    payload = event.payload or {}
    indicator = payload.get("indicator")
    if indicator:
        keys.append(f"indicator:{indicator}")
    forecast = payload.get("forecast_id")
    if forecast:
        keys.append(f"forecast:{forecast}")
    return keys


def _persist_theme(theme: Theme) -> None:
    """Wave 3a stub — log the evaluation; 94-07 wires snapshot storage."""
    logger.info(
        {
            "event": "theme_evaluated",
            "theme_id": theme.theme_id,
            "strength": theme.strength,
            "state": theme.state.value,
            "drivers_count": len(theme.drivers),
        }
    )


def build_handler(engine: MacroThemeEngine, state: _EvidenceState):
    """Construct a closure subscribed to every relevant event type."""

    def _handler(event: EconomicEvent) -> None:
        try:
            keys = _signal_keys_for_event(event)
            # Apply every signal to every theme — engine matches structurally,
            # non-matching keys are dropped during scoring.
            for theme_id in engine.catalog:
                for k in keys:
                    state.add(theme_id, k)
                theme = engine.evaluate_theme(
                    theme_id=theme_id,
                    satisfied_rule_signals=state.signals(theme_id),
                )
                _persist_theme(theme)
        except Exception as exc:  # noqa: BLE001 — one handler must not kill the bus
            logger.exception(
                "theme_engine handler raised on event %s: %s", event.event_id, exc
            )

    return _handler


def _install_signal_handlers() -> None:
    def _handle(signum: int, _frame: Any) -> None:
        logger.info("run_theme_engine: signal %s received, shutting down.", signum)
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    _install_signal_handlers()

    engine = MacroThemeEngine()
    state = _EvidenceState()
    bus = EventBus()
    handler = build_handler(engine, state)

    for event_type in _SUBSCRIBED_EVENT_TYPES:
        bus.subscribe(event_type, handler)
    logger.info(
        "run_theme_engine: subscribed to %d event types, catalog has %d themes.",
        len(_SUBSCRIBED_EVENT_TYPES),
        len(engine.catalog),
    )

    try:
        bus.run()
    except KeyboardInterrupt:
        logger.info("run_theme_engine: KeyboardInterrupt — exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
