"""WS invalidation publisher for macro indicator updates (Phase 85 Plan 11).

Publishes a thin-invalidation message to the Redis topic
``macro.indicator.<indicator_id>.updated`` when all 3 Phase 85 agents have
completed their analysis for a given release event.

Phase 74 contract (thin-invalidation):
  WS message contains ONLY ``topic`` + ``snapshot_id``.
  No body — the frontend re-fetches all 5 VM102 APIs on receipt.

D3 lock:
  Per-indicator topic ``macro.indicator.<id>.updated``.
  NEVER the bulk ``macro.indicators.updated``.

REDIS_URL fail-fast:
  The ``REDIS_URL`` env var is resolved at module load time via ``_required()``.
  Missing REDIS_URL → RuntimeError immediately (fail-fast beats silent
  misconfiguration at runtime).

Failure handling:
  Redis publish errors are logged (observability degradation) but never
  propagated to the caller. Brain goal completion is the source of truth;
  the frontend will re-fetch on next page load if WS fails.
"""
from __future__ import annotations

import json
import logging
import os
from uuid import uuid4

import redis

logger = logging.getLogger(__name__)


def _required(key: str) -> str:
    """Return env var value or raise RuntimeError if missing (fail-fast — no fallbacks)."""
    v = os.environ.get(key)
    if v is None:
        raise RuntimeError(
            f"Required env var {key!r} not set — fail-fast (Phase 85 env-driven config). "
            f"Set {key} in your environment before starting."
        )
    return v


# Module-level fail-fast: raises RuntimeError if REDIS_URL is not set.
REDIS_URL: str = _required("REDIS_URL")


def publish_indicator_updated(indicator_id: str) -> None:
    """Publish a thin-invalidation WS message for the given indicator.

    Message shape (Phase 74 contract — NO body fields):
        {"topic": "macro.indicator.<id>.updated", "snapshot_id": "<uuid>"}

    D3 lock: one topic per indicator_id, never a bulk ``macro.indicators.updated``.

    Args:
        indicator_id: FRED series code (e.g. "CPIAUCSL").
    """
    topic = f"macro.indicator.{indicator_id}.updated"
    msg = {"topic": topic, "snapshot_id": str(uuid4())}
    try:
        r = redis.from_url(REDIS_URL)
        r.publish(topic, json.dumps(msg))
        r.close()
        logger.info({"event": "phase85_ws_published", "topic": topic})
    except Exception as exc:  # noqa: BLE001
        logger.error({
            "event": "phase85_ws_publish_failed",
            "topic": topic,
            "error": str(exc),
        })
