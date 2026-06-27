"""Phase 94 Wave 1 — EventBus package.

Exports:
- :class:`EventBus`: Redis-backed pub/sub for EconomicEvent objects with
  idempotency via SET NX EX (24h TTL).
- :data:`CHANNEL_PREFIX`: pub/sub channel namespace (``economic_event_bus``).
- :data:`DEDUPE_KEY_TTL`: idempotency window in seconds (86400 == 24h).
"""

from __future__ import annotations

from core.event_bus.bus import CHANNEL_PREFIX, DEDUPE_KEY_TTL, EventBus

__all__ = ["EventBus", "CHANNEL_PREFIX", "DEDUPE_KEY_TTL"]
