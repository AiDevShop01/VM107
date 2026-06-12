"""Phase 85 REQ-85-7 — Router reachability fail-fast.

assert_router_reachable() pings Redis at REDIS_URL.
On any failure (env unset OR ping exception) it logs a structured critical
event and calls sys.exit(1).

Design lock (D2): NO Tier-1 deterministic fallback — silent misconfiguration
is the failure mode being eliminated. Phase 85 macro_* agents boot-fail loudly
rather than silently routing to a degraded path.

This module is called by the agent_init extension at slot 30
(_30_phase85_router_fail_fast.py) ONLY for profiles whose profile_id starts
with "vm107.macro_". All other agent profiles keep their existing graceful
degradation behavior from _20_router_deps.py.
"""
from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)


def assert_router_reachable() -> None:
    """Ping Redis at REDIS_URL. Exit with code 1 on any failure.

    Failure cases:
    - REDIS_URL env var is not set → sys.exit(1)
    - Redis ping raises any exception (connection refused, timeout, etc.) → sys.exit(1)

    Called during agent initialization for Phase 85 macro_* profiles only.
    """
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        logger.critical(
            {"event": "router_unreachable", "reason": "REDIS_URL not set", "phase": "85"}
        )
        sys.exit(1)

    try:
        import redis as _redis
        _redis.from_url(redis_url).ping()
    except Exception as exc:
        logger.critical(
            {"event": "router_unreachable", "error": str(exc), "phase": "85"}
        )
        sys.exit(1)
