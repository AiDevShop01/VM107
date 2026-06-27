"""Phase 94 Wave 1 — EventBus idempotency (publish-twice → handle-once).

Becomes GREEN in 94-02 (this plan).
"""

from __future__ import annotations

import importlib
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest


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


def _make_event(event_id: str) -> Any:
    from contracts.economic_intelligence.events import (
        EconomicEvent,
        EventSeverity,
        EventType,
    )

    return EconomicEvent(
        event_id=event_id,
        event_type=EventType.MACRO_RELEASE,
        severity=EventSeverity.HIGH,
        country="US",
        occurred_at=datetime(2026, 6, 27, 10, 0, 0, tzinfo=timezone.utc),
        source="phase85.release_pipeline",
        payload={"indicator": "CPIAUCSL"},
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
            for past_msg in self._parent._channel_buffer.get(ch, []):
                self._enqueue(ch, past_msg)

    def listen(self):
        for ch in self._subscribed_channels:
            yield {"type": "subscribe", "channel": ch, "data": 1}
        while self._queue:
            yield self._queue.pop(0)

    def _enqueue(self, channel: str, data: str) -> None:
        self._queue.append({"type": "message", "channel": channel, "data": data})


class StubRedis:
    def __init__(self) -> None:
        self._kv: dict[str, str] = {}
        self._subscribers: dict[str, list[_StubPubSub]] = {}
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


def test_same_event_id_processed_once(bus, stub_redis):
    """REQ-94-2 idempotency: publish twice with the same event_id → handler fires once."""
    received: list[Any] = []
    bus.subscribe("macro_release", lambda evt: received.append(evt))

    event_id = str(uuid.uuid4())
    event_a = _make_event(event_id)
    event_b = _make_event(event_id)

    assert bus.publish(event_a) is True
    # Second publish with same event_id must return False (dedupe HIT) and
    # MUST NOT enqueue a second message to subscribers.
    assert bus.publish(event_b) is False

    bus.run(max_messages=2)

    assert len(received) == 1, f"Expected handler to fire once, got {len(received)}"


def test_different_event_id_processed_separately(bus, stub_redis):
    received: list[Any] = []
    bus.subscribe("macro_release", lambda evt: received.append(evt))

    assert bus.publish(_make_event(str(uuid.uuid4()))) is True
    assert bus.publish(_make_event(str(uuid.uuid4()))) is True

    bus.run(max_messages=2)

    assert len(received) == 2
