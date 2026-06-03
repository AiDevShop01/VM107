"""Shared Redis observation publisher (Phase 74 REQ-74-5).

Used by:
- supervisory_emitter.py (supervisory category)
- cost_anomaly_detector.py (cost_anomaly category)

Architecture lock: ONE channel for ALL observation categories.
Plan 03's VM100 MissionControlConsumer subscribes to `vm107.observations`
once and routes by ``category`` field.  Per-category channels would defeat
the unified Observation pipeline (CONTEXT §1).

Env var: VM107_SUPERVISORY_REDIS_URL — resolved fail-fast at module load.
No fallback defaults (env-driven-no-fallbacks lock).
"""
from __future__ import annotations

import os
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

# Unified channel name — ALL observation categories flow through here.
# Plan 03 (VM100 relay) subscribes to this channel.
OBSERVATIONS_CHANNEL = "vm107.observations"


# ─────────────────────────────────────────────────────────────────────────────
# Fail-fast env var resolution
# ─────────────────────────────────────────────────────────────────────────────

def _required(key: str) -> str:
    """Return env var value or raise RuntimeError. No fallback defaults."""
    v = os.environ.get(key)
    if v is None:
        raise RuntimeError(
            f"Required env var {key!r} not set — fail-fast "
            f"(env-driven-no-fallbacks lock, Phase 74)"
        )
    return v


# Module-level: resolved at import time so misconfiguration surfaces immediately.
_REDIS_URL: str = _required("VM107_SUPERVISORY_REDIS_URL")

# Lazy client factory — avoids connection at module load time (tests patch redis.from_url).
_redis_client = None


def _get_client():
    """Return the Redis client, creating it on first call."""
    global _redis_client
    if _redis_client is None:
        import redis
        _redis_client = redis.from_url(_REDIS_URL, decode_responses=True)
    return _redis_client


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def publish_observation(observation) -> int:
    """Publish an Observation to the Redis ``vm107.observations`` channel.

    Parameters
    ----------
    observation:
        A ``fingpt_core.contracts.observation.Observation`` instance.
        Must be an Observation — anything else raises ``TypeError``.

    Returns
    -------
    int
        The number of subscribers that received the message (from Redis).

    Raises
    ------
    TypeError
        If ``observation`` is not an ``Observation`` instance.
    Exception
        Any Redis connection error propagates — never silently swallowed.
    """
    from fingpt_core.contracts.observation import Observation

    if not isinstance(observation, Observation):
        raise TypeError(
            f"publish_observation expects an Observation instance, "
            f"got {type(observation).__name__!r}"
        )

    payload = observation.model_dump_json()
    client = _get_client()
    return client.publish(OBSERVATIONS_CHANNEL, payload)
