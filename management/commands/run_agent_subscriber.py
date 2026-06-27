"""Phase 94-06 — Generic agent-subscriber listener entrypoint.

A single management command that bootstraps any of the 4 event-driven
Wave 3b agents as a long-running EventBus subscriber:

* ``executive_summary``
* ``theme_monitor``
* ``timeline``
* ``central_bank_summariser``

Per ``feedback_mgmt_commands_need_compose_service``: each of these is
shipped as a sibling service in ``VM107/docker-compose.yml`` so the
worker survives backend restarts. Per ``env-driven-no-fallbacks``:
``REDIS_HOST`` / ``REDIS_PORT`` are read by the EventBus client; missing
env raises ``KeyError`` at import time.

Usage::

    python -m management.commands.run_agent_subscriber --agent executive_summary
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from typing import Any, Callable

from contracts.economic_intelligence.events import EconomicEvent, EventType
from core.event_bus import EventBus

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────── agent registry
#
# Each entry: agent_id → (agent_factory, handler_method_name).
# The handler is invoked with the EconomicEvent; its return value (if any)
# is intentionally ignored — persistence is the SnapshotCoordinator's job
# (94-07). Wave 3b logs every fire for traceability.


def _build_executive_summary():
    from agents.executive_summary import ExecutiveSummary

    return ExecutiveSummary()


def _build_theme_monitor():
    from agents.theme_monitor import ThemeMonitor

    return ThemeMonitor()


def _build_timeline():
    from agents.timeline import Timeline

    return Timeline()


def _build_central_bank_summariser():
    from agents.central_bank_summariser import CentralBankSummariser

    return CentralBankSummariser()


_AGENT_REGISTRY: dict[str, dict[str, Any]] = {
    "executive_summary": {
        "factory": _build_executive_summary,
        "subscribed_events": (
            EventType.MACRO_RELEASE,
            EventType.CENTRAL_BANK,
            EventType.REGIME_CHANGE,
            EventType.FORECAST_UPDATE,
        ),
        "handler_attr": "on_event",
    },
    "theme_monitor": {
        "factory": _build_theme_monitor,
        # ThemeMonitor doesn't subscribe directly — it reads from the theme_engine.
        # We register it on the broad evidence-shifting set as a downstream snapshot
        # trigger; the actual invoke happens via the SnapshotCoordinator (94-07).
        "subscribed_events": (
            EventType.MACRO_RELEASE,
            EventType.REGIME_CHANGE,
            EventType.RESEARCH,
        ),
        "handler_attr": None,   # Wave 3b: log fires; aggregator invokes the agent
    },
    "timeline": {
        "factory": _build_timeline,
        "subscribed_events": (
            EventType.MACRO_RELEASE,
            EventType.CENTRAL_BANK,
            EventType.REGIME_CHANGE,
            EventType.DISCOVERY,
            EventType.FORECAST_UPDATE,
            EventType.RESEARCH,
            EventType.ALERT,
            EventType.STRUCTURAL_UPDATE,
        ),
        "handler_attr": "on_event",
    },
    "central_bank_summariser": {
        "factory": _build_central_bank_summariser,
        "subscribed_events": (EventType.CENTRAL_BANK,),
        "handler_attr": "on_event",
    },
}


# ─────────────────────────────────────────────────────────── helpers


def _build_handler(agent: Any, handler_attr: str | None) -> Callable[[EconomicEvent], None]:
    """Construct the EventBus-compatible handler closure.

    ``handler_attr`` may be ``None`` for agents whose Wave 3b lifecycle is
    "log + defer to aggregator" (e.g., theme_monitor — the SnapshotCoordinator
    invokes it). For agents with an ``on_event`` method we call that
    directly inside a try/except so one bad event can't kill the bus.
    """
    if handler_attr is None:
        def _log_only(event: EconomicEvent) -> None:
            logger.info(
                {"event": "subscriber_log_only", "event_id": event.event_id,
                 "event_type": event.event_type.value, "agent": agent.__class__.__name__}
            )

        return _log_only

    method = getattr(agent, handler_attr)

    def _handler(event: EconomicEvent) -> None:
        try:
            method(event)
        except Exception as exc:  # noqa: BLE001 — one handler must not kill the bus
            logger.exception(
                "run_agent_subscriber: %s handler raised on event %s: %s",
                agent.__class__.__name__,
                event.event_id,
                exc,
            )

    return _handler


def _install_signal_handlers() -> None:
    def _handle(signum: int, _frame: Any) -> None:
        logger.info("run_agent_subscriber: signal %s received, shutting down.", signum)
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_agent_subscriber",
        description="Phase 94 Wave 3b agent-subscriber listener.",
    )
    p.add_argument(
        "--agent",
        required=True,
        choices=sorted(_AGENT_REGISTRY.keys()),
        help="Agent module to bootstrap as an EventBus subscriber.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    args = _parse_args(argv)
    spec = _AGENT_REGISTRY[args.agent]

    _install_signal_handlers()

    agent = spec["factory"]()
    handler = _build_handler(agent, spec["handler_attr"])
    bus = EventBus()
    for event_type in spec["subscribed_events"]:
        bus.subscribe(event_type, handler)
    logger.info(
        "run_agent_subscriber: agent=%s subscribed to %d event types.",
        args.agent,
        len(spec["subscribed_events"]),
    )

    try:
        bus.run()
    except KeyboardInterrupt:
        logger.info("run_agent_subscriber: KeyboardInterrupt — exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
