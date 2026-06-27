"""Phase 94 Wave 1 — EventBus (Redis pub/sub backbone for EconomicEvent).

Per CONTEXT.md §B, the Event Bus is the loose-coupling backbone between the
Snapshot Coordinator (Wave 2) and the 5 agents (Wave 3+). It ships with a
docker-compose sibling service (``event_bus``) per the
``feedback_mgmt_commands_need_compose_service`` lock so the listener
survives backend restarts.

Architecture
------------
* Publishers call :meth:`EventBus.publish` with an :class:`EconomicEvent`.
* Subscribers register handlers via :meth:`EventBus.subscribe` keyed on
  :class:`EventType`.
* The bus serialises events as JSON and pushes them to a per-type Redis
  pub/sub channel ``economic_event_bus:<event_type>``.
* Idempotency uses ``SET NX EX 86400`` against ``economic_event_bus:seen:
  <event_id>`` — a second publish of the same ``event_id`` is dropped
  before any pub/sub traffic.
* :meth:`EventBus.run` is the long-running listener loop invoked by the
  ``event_bus`` sibling service.

Env vars (no fallback defaults — :mod:`os.environ` raises ``KeyError`` at
import time per the env-driven-no-fallbacks lock):

* ``REDIS_HOST`` — Redis host (e.g. ``vm107-redis`` inside docker network).
* ``REDIS_PORT`` — Redis port (typically ``6379``).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

from contracts.economic_intelligence.events import EconomicEvent, EventType

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "economic_event_bus"
DEDUPE_KEY_TTL = 86_400  # 24h — idempotency window for duplicate event_id detection.


def _build_default_client() -> Any:
    """Build the default redis.Redis client; lazy so tests can inject a stub.

    Reads ``REDIS_HOST`` + ``REDIS_PORT`` from env with **no fallback defaults**
    (env-driven-no-fallbacks lock). Missing env raises ``KeyError`` rather
    than silently connecting to ``localhost``.
    """

    import redis  # imported here so unit tests don't require the lib at import time.

    return redis.Redis(
        host=os.environ["REDIS_HOST"],
        port=int(os.environ["REDIS_PORT"]),
        decode_responses=True,
    )


class EventBus:
    """Redis-backed publish/subscribe bus for :class:`EconomicEvent`.

    Parameters
    ----------
    redis_client:
        Optional injected client (typically a stub in tests). If ``None``
        the default client is built from ``REDIS_HOST`` / ``REDIS_PORT``.
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client if redis_client is not None else _build_default_client()
        self._handlers: dict[EventType, list[Callable[[EconomicEvent], None]]] = {}

    # ------------------------------------------------------------------ publish
    def publish(self, event: EconomicEvent) -> bool:
        """Publish an EconomicEvent.

        Returns ``True`` if the event was newly published, ``False`` if a
        duplicate ``event_id`` was already seen within :data:`DEDUPE_KEY_TTL`.

        Raises ``TypeError`` if ``event`` is not an :class:`EconomicEvent`
        (validation happens **before** any Redis write, so failed publishes
        never burn an idempotency slot).
        """

        if not isinstance(event, EconomicEvent):
            raise TypeError(
                f"EventBus.publish() requires an EconomicEvent, got {type(event).__name__}"
            )

        dedupe_key = f"{CHANNEL_PREFIX}:seen:{event.event_id}"
        # SET NX EX: only set if not already present, with 24h TTL.
        # Returns truthy on first write, None/False on duplicate.
        if not self._redis.set(dedupe_key, "1", nx=True, ex=DEDUPE_KEY_TTL):
            logger.debug("EventBus: dedupe hit for event_id=%s", event.event_id)
            return False

        channel = f"{CHANNEL_PREFIX}:{event.event_type.value}"
        payload = event.model_dump_json()
        self._redis.publish(channel, payload)
        return True

    # ---------------------------------------------------------------- subscribe
    def subscribe(
        self,
        event_type: EventType | str,
        handler: Callable[[EconomicEvent], None],
    ) -> None:
        """Register ``handler`` for a specific :class:`EventType`.

        Accepts an :class:`EventType` enum or its underlying string value so
        agent code that imports the string constant doesn't have to re-import
        the enum.
        """

        if isinstance(event_type, str) and not isinstance(event_type, EventType):
            event_type = EventType(event_type)
        self._handlers.setdefault(event_type, []).append(handler)

    # --------------------------------------------------------------------- run
    def run(self, max_messages: int | None = None) -> None:
        """Long-running listener loop — invoked by the sibling service.

        Subscribes to the pub/sub channel for every registered event_type and
        dispatches each message to the matching handler list.

        ``max_messages`` is a test-only escape hatch — production runs leave
        it ``None`` for infinite polling.
        """

        if not self._handlers:
            logger.warning("EventBus.run() called with no handlers registered.")
            return

        pubsub = self._redis.pubsub()
        for event_type in self._handlers:
            pubsub.subscribe(f"{CHANNEL_PREFIX}:{event_type.value}")

        processed = 0
        for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue  # Subscription confirmations etc.

            try:
                event = EconomicEvent.model_validate_json(msg["data"])
            except Exception as exc:  # pragma: no cover — invalid payload should be rare
                logger.exception("EventBus: failed to parse message %r: %s", msg, exc)
                continue

            for handler in self._handlers.get(event.event_type, []):
                try:
                    handler(event)
                except Exception as exc:  # one bad handler must not kill the bus
                    logger.exception(
                        "EventBus: handler %r raised %s on event %s",
                        handler,
                        exc,
                        event.event_id,
                    )

            processed += 1
            if max_messages is not None and processed >= max_messages:
                return
