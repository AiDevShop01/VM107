"""Tracks per-source health for the DegradationPolicyEngine.

Phase 66 — in-memory health registry.  Redis-backed in a future phase.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceHealth:
    source_id: str
    available: bool
    last_ok_at: float | None  # epoch seconds; None when never OK or currently down
    failure_reason: str | None = None


class SourceHealthRegistry:
    """Tracks the availability of each context-assembly source.

    Each emitter calls `report()` after every API call so the
    DegradationPolicyEngine can compute the current tier in O(1).
    """

    # Phase 67 Plan 06 — shared-instance accessor for the multi-emitter setup.
    _shared_instance: "SourceHealthRegistry | None" = None

    @classmethod
    def get_shared_instance(cls) -> "SourceHealthRegistry":
        """Process-wide singleton accessor for SourceHealthRegistry.

        Tests that need an isolated registry should instantiate
        ``SourceHealthRegistry()`` directly and inject it.
        """
        if cls._shared_instance is None:
            cls._shared_instance = cls()
        return cls._shared_instance

    def __init__(self) -> None:
        self._health: dict[str, SourceHealth] = {}

    def report(
        self,
        source_id: str,
        available: bool,
        failure_reason: str | None = None,
    ) -> None:
        """Record a health observation for a single source."""
        self._health[source_id] = SourceHealth(
            source_id=source_id,
            available=available,
            last_ok_at=time.time() if available else None,
            failure_reason=failure_reason,
        )

    def snapshot(self) -> dict[str, SourceHealth]:
        """Return a point-in-time copy of all known source health records."""
        return dict(self._health)

    def clear(self) -> None:
        """Reset registry state (used between emit() calls)."""
        self._health.clear()
