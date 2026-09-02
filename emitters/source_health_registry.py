"""Tracks per-source health for the DegradationPolicyEngine.

Phase 66 — in-memory health registry.  Redis-backed in a future phase.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceHealthKey:
    """Object-carried immutable key for a *context-scoped* health record.

    D-03 / SC-5 (Phase 172): mirrors the 135-06 object-carried immutable-key
    pattern (``AgentContext.id`` in ``core/agents/invocation.py``). The recurring
    last-write-wins race in this registry came from callers composing the scoped
    key by hand as ``f"{subsystem}:{ctxid}"`` — a convention the type system could
    not enforce, so a caller could silently forget the ``ctxid`` suffix and collide
    two concurrent contexts onto one bare key.

    Making the composed key a frozen value object turns "remember the ctxid" from a
    convention into a structural guarantee: a scoped key *cannot be constructed*
    without a non-empty ``ctxid``. ``.key`` reproduces the exact historical
    ``f"{subsystem}:{ctxid}"`` string so existing snapshot readers still match.
    """

    subsystem: str
    ctxid: str

    def __post_init__(self) -> None:
        # A scoped key is meaningless without a context id — reject at construction
        # so a caller can never build a "scoped" report that silently degrades to a
        # last-write-wins collision on the bare subsystem key.
        if not self.subsystem:
            raise ValueError("SourceHealthKey requires a non-empty subsystem")
        if not self.ctxid:
            raise ValueError(
                "SourceHealthKey requires a non-empty ctxid — a context-scoped "
                "health report cannot exist without a context id (D-03/SC-5)"
            )

    @property
    def key(self) -> str:
        """Deterministic composed key, identical to the historical convention."""
        return f"{self.subsystem}:{self.ctxid}"


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
        source_id: str | SourceHealthKey,
        available: bool,
        failure_reason: str | None = None,
    ) -> None:
        """Record a health observation for a single source.

        ``source_id`` accepts either a bare ``str`` (the historical, unchanged path
        used by the ~60 bare-string emitter callers) or a frozen
        :class:`SourceHealthKey` (the context-scoped recall/assess-path callers,
        D-03/SC-5). A ``SourceHealthKey`` is stored under its deterministic ``.key``
        composed string, so ``snapshot()`` stays ``dict[str, SourceHealth]`` and all
        bare-string readers match byte-for-byte. This is a non-breaking union widen
        (Pitfall 2 — the 64-caller floor): the base signature does NOT require the
        key object.
        """
        resolved_id = source_id.key if isinstance(source_id, SourceHealthKey) else source_id
        self._health[resolved_id] = SourceHealth(
            source_id=resolved_id,
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
