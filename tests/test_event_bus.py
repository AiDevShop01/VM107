"""Phase 94 Wave 1 — EventBus publish/subscribe tests.

EventBus lives at ``core/event_bus/bus.py`` (per Wave-0 scaffold expectation).
Publishes EconomicEvent objects over Redis pub/sub channel ``economic_event_bus``
with idempotency via SET NX EX (24h TTL).

Tests run with a stub Redis (no live server needed) — ``StubRedis`` below
mirrors the redis-py methods we call (``set``, ``publish``, ``pubsub``).

Becomes GREEN in 94-02 (this plan).
"""

from __future__ import annotations

import importlib
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest


# Ensure the fail-fast env vars are present before importing the bus module.
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")


def _import_bus_module():
    try:
        return importlib.import_module("core.event_bus.bus")
    except ImportError as exc:
        pytest.fail(
            "Wave 2 (94-02) must create core/event_bus/bus.py. "
            f"ImportError: {exc}"
        )


def _make_event(
    event_id: str | None = None,
    event_type_value: str = "macro_release",
    country: str = "US",
) -> Any:
    from contracts.economic_intelligence.events import (
        EconomicEvent,
        EventSeverity,
        EventType,
    )

    return EconomicEvent(
        event_id=event_id or str(uuid.uuid4()),
        event_type=EventType(event_type_value),
        severity=EventSeverity.HIGH,
        country=country,
        occurred_at=datetime(2026, 6, 27, 10, 0, 0, tzinfo=timezone.utc),
        source="phase85.release_pipeline",
        payload={"indicator": "CPIAUCSL", "value": 3.2},
    )


class _StubPubSub:
    def __init__(self, parent: "StubRedis") -> None:
        self._parent = parent
        self._subscribed_channels: list[str] = []
        self._queue: list[dict[str, Any]] = []

    def subscribe(self, *channels: str) -> None:
        for ch in channels:
            self._subscribed_channels.append(ch)
            self._parent._subscribers.setdefault(ch, []).append(self)
            # Replay any messages already published to this channel before
            # this pubsub instance subscribed — keeps unit tests order-
            # independent (real Redis would require subscribe-first).
            for past_msg in self._parent._channel_buffer.get(ch, []):
                self._enqueue(ch, past_msg)

    def listen(self):  # generator-like
        # First yield a subscription confirmation per channel (mirrors redis-py).
        for ch in self._subscribed_channels:
            yield {"type": "subscribe", "channel": ch, "data": 1}
        # Then drain queue (no blocking — tests inject messages directly).
        while self._queue:
            yield self._queue.pop(0)

    def _enqueue(self, channel: str, data: str) -> None:
        self._queue.append({"type": "message", "channel": channel, "data": data})


class StubRedis:
    """In-memory stand-in for redis.Redis used by EventBus tests."""

    def __init__(self) -> None:
        self._kv: dict[str, str] = {}
        self._subscribers: dict[str, list[_StubPubSub]] = {}
        # Buffer of all published messages per channel so late-subscribing
        # pubsubs can replay them — accommodates test order where publish()
        # happens before pubsub.subscribe(). Real Redis fires-and-forgets;
        # this stub is intentionally more permissive for unit testing.
        self._channel_buffer: dict[str, list[str]] = {}
        self.published: list[tuple[str, str]] = []

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self._kv:
            return False
        self._kv[key] = value
        return True

    def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        self._channel_buffer.setdefault(channel, []).append(message)
        for ps in self._subscribers.get(channel, []):
            ps._enqueue(channel, message)
        return len(self._subscribers.get(channel, []))

    def pubsub(self) -> _StubPubSub:
        return _StubPubSub(self)


@pytest.fixture
def stub_redis():
    return StubRedis()


@pytest.fixture
def bus(stub_redis):
    bus_module = _import_bus_module()
    return bus_module.EventBus(redis_client=stub_redis)


def test_publish_subscribe_roundtrip(bus, stub_redis):
    received: list[Any] = []

    bus.subscribe("macro_release", lambda evt: received.append(evt))

    event = _make_event()
    assert bus.publish(event) is True

    # Drain the listener once — pubsub.listen() will yield queued messages.
    bus.run(max_messages=1)

    assert len(received) == 1
    assert received[0].event_id == event.event_id
    assert received[0].event_type.value == "macro_release"
    assert received[0].country == "US"


def test_publish_multiple_subscribers(bus, stub_redis):
    counts = {"a": 0, "b": 0, "c": 0}

    bus.subscribe("macro_release", lambda evt: counts.__setitem__("a", counts["a"] + 1))
    bus.subscribe("macro_release", lambda evt: counts.__setitem__("b", counts["b"] + 1))
    bus.subscribe("macro_release", lambda evt: counts.__setitem__("c", counts["c"] + 1))

    bus.publish(_make_event())
    bus.run(max_messages=1)

    assert counts == {"a": 1, "b": 1, "c": 1}


def test_publish_wrong_event_type_not_received(bus, stub_redis):
    received: list[Any] = []

    bus.subscribe("macro_release", lambda evt: received.append(evt))

    # Publish a CENTRAL_BANK event — macro_release subscriber must not fire.
    bus.publish(_make_event(event_type_value="central_bank"))
    bus.run(max_messages=1)

    assert received == []


def test_publish_invalid_event_raises_validation_error(bus):
    from pydantic import ValidationError

    bus_module = _import_bus_module()

    # Calling publish() with a non-EconomicEvent object should raise BEFORE
    # touching Redis (idempotency key never written, no message published).
    with pytest.raises((TypeError, ValidationError)):
        bus.publish({"event_id": "x"})  # type: ignore[arg-type]
