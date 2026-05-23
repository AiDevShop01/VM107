"""Tier 1/2/3 graceful degradation policy (CONTEXT.md §2).

Tier 0 — HEALTHY     : all sources available  → full narrative, _demo=False
Tier 1 — minor       : one source down        → lower confidence, degraded badge, _demo=False
Tier 2 — moderate    : macro down OR ≥2 stale → simplified narrative, _demo=False
Tier 3 — critical    : majority unavailable   → fallback template, _demo=True
"""
from __future__ import annotations

from enum import Enum


class DegradationTier(Enum):
    HEALTHY = 0
    TIER_1 = 1  # minor: one source down
    TIER_2 = 2  # moderate: macro down OR multiple stale
    TIER_3 = 3  # critical: majority unavailable → _demo=True


class DegradationPolicyEngine:
    """Compute degradation tier from SourceHealthRegistry snapshot."""

    def tier_for(self, source_health: dict) -> DegradationTier:
        """Return the current DegradationTier given a health snapshot.

        Args:
            source_health: dict[source_id, SourceHealth] as returned by
                           SourceHealthRegistry.snapshot().

        Returns:
            DegradationTier enum value.
        """
        sources = list(source_health.values())
        if not sources:
            return DegradationTier.TIER_3

        available_count = sum(1 for s in sources if s.available)
        total = len(sources)
        ratio = available_count / total

        # Critical: majority unavailable → Tier 3
        if ratio < 0.5:
            return DegradationTier.TIER_3

        # Healthy: all available → Tier 0
        if ratio == 1.0:
            return DegradationTier.HEALTHY

        # Identify if macro source specifically is down (Tier 2 if so)
        macro_down = any(
            (not s.available) and "macro" in s.source_id.lower()
            for s in sources
        )
        if macro_down:
            return DegradationTier.TIER_2

        # Single source down but not macro → Tier 1
        return DegradationTier.TIER_1
