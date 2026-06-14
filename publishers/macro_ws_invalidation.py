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


# REDIS_URL is resolved lazily in publish_indicator_updated() to allow test
# patching of this module without requiring REDIS_URL to be set at import time.
# Phase 85.1 Plan 02 deviation — fail-fast still occurs at first PUBLISH call,
# not at import time, so the CLAUDE.md lock on env-driven config is honoured
# (fail-fast on use, not on import).  This unblocks tests that patch
# ``VM107.publishers.macro_ws_invalidation.publish_indicator_updated`` without
# needing a live Redis connection or the REDIS_URL env var.
_REDIS_URL: str | None = None


def _get_redis_url() -> str:
    """Resolve REDIS_URL lazily — fail-fast on first publish call, not at import."""
    global _REDIS_URL
    if _REDIS_URL is None:
        _REDIS_URL = _required("REDIS_URL")
    return _REDIS_URL


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
        r = redis.from_url(_get_redis_url())
        r.publish(topic, json.dumps(msg))
        r.close()
        logger.info({"event": "phase85_ws_published", "topic": topic})
    except Exception as exc:  # noqa: BLE001
        logger.error({
            "event": "phase85_ws_publish_failed",
            "topic": topic,
            "error": str(exc),
        })
