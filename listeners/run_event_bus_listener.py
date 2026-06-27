"""Phase 94 Wave 1 — Event Bus listener entrypoint.

Long-running process that boots an :class:`EventBus`, lets agent modules
register their handlers via import-time registration (Wave 3+), and then
blocks on :meth:`EventBus.run` polling the ``economic_event_bus:*`` Redis
pub/sub channels.

Shipped as the docker-compose sibling service ``event_bus`` per the
``feedback_mgmt_commands_need_compose_service`` lock so the listener
survives backend restarts.

CLAUDE.md locks honoured:

* env-driven-no-fallbacks: ``REDIS_HOST`` + ``REDIS_PORT`` are required
  by :mod:`core.event_bus.bus`; missing env raises ``KeyError``.
* mgmt-cmd-needs-compose-service: this is the sibling-service command —
  never invoke via ad-hoc ``docker exec``.

Wave 1 ships the listener with **no handlers** — Wave 3+ agent modules
(executive_summary, theme_monitor, timeline, central_bank,
macro_ask_router) register their handlers by importing this module and
calling ``bus.subscribe(EventType.X, handler)`` from their own
package's ``__init__.py`` or a registration hook.

Usage::

    python -m listeners.run_event_bus_listener
"""

from __future__ import annotations

import logging
import signal
import sys

from core.event_bus import EventBus

logger = logging.getLogger(__name__)


# Module-global so agent modules can import + register handlers.
bus: EventBus | None = None


def _build_bus() -> EventBus:
    global bus
    if bus is None:
        bus = EventBus()
    return bus


def _install_signal_handlers() -> None:
    def _handle(signum, _frame):  # noqa: ANN001 — signal handler signature
        logger.info("event_bus_listener: received signal %s, shutting down.", signum)
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    _install_signal_handlers()

    event_bus = _build_bus()

    # Wave 3+ agent modules register handlers here via import-time hooks.
    # For Wave 1 we ship the listener with no handlers; it logs a warning
    # and exits cleanly via EventBus.run() if invoked alone.
    logger.info(
        "event_bus_listener: EventBus initialised; waiting for handlers from agent imports."
    )

    try:
        event_bus.run()
    except KeyboardInterrupt:
        logger.info("event_bus_listener: KeyboardInterrupt — exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
