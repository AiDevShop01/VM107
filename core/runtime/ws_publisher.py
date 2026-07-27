"""Plan 87-14 deploy-gate WS publisher bridge (additive).

The macro_story_tracker runner imports ``from core.runtime import ws_publisher``
and the agent calls ``ws_publisher.publish("macro.story.updated", payload=...)``
(see ``agents/macro_story_tracker/agent.py``) after a story is retired/updated,
so the VM100 frontend can invalidate its macro-story view.

Pattern source: ``publishers/macro_ws_invalidation.py`` (Phase 74 thin-
invalidation contract — the WS message carries only the topic; the frontend
re-fetches on receipt, no domain data on the wire).

Failure handling mirrors that publisher: Redis errors are logged (observability
degradation) but NEVER propagated — a WS hiccup must not crash the tracker tick.
``redis`` / ``REDIS_URL`` are resolved lazily at call time so importing this
module (deploy-gate guard, pytest collection) needs neither.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger(__name__)


def publish(topic: str, payload: Optional[Any] = None) -> None:
    """Publish a thin invalidation message to the Redis ``topic``.

    Args:
        topic: Redis pub/sub channel, e.g. "macro.story.updated".
        payload: Optional thin payload. Per the Phase 74 thin-invalidation
            contract the body is intentionally minimal — the frontend re-fetches
            on receipt — so ``None`` publishes ``{"topic": topic}`` alone.

    Never raises: Redis/connection errors are logged and swallowed.
    """
    try:
        import redis  # deferred — see module docstring

        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            log.warning(
                "ws_publisher.publish skipped — REDIS_URL unset (topic=%s)", topic
            )
            return

        message = {"topic": topic}
        if payload is not None:
            message["payload"] = payload

        client = redis.Redis.from_url(redis_url)
        client.publish(topic, json.dumps(message))
    except Exception as exc:  # noqa: BLE001 — WS failure must not crash the tick
        log.warning("ws_publisher.publish failed topic=%s err=%r", topic, exc)
