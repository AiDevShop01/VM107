"""
tier_threshold_loader.py — Phase 66 Plan 66-06 (per checker BLOCKER 6, 2026-05-23)
                          + Phase 73 Plan 08 Task 2 (Decision 9 enum tightening)

Reads {A+: int, DEV: int, WATCH: int} from the tier_thresholds Postgres table
seeded by Plan 66-00 migration 0041 (re-seeded by Phase 73 migration 0051 to
drop INVALIDATED rows). NEVER returns hardcoded literals.

Phase 73 Decision 9 lock — the tier enum is now {A+, DEV, WATCH} only.
INV / INVALIDATED moved to the OpportunityLifecyclePill (Phase 73 Plan 73-09)
because invalidation is a LIFECYCLE state, not a SCORING tier. The loader
fail-fasts on any row outside the allowed set so a stray operator-hand-added
INVALIDATED or INV entry surfaces loudly instead of corrupting the contract.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Phase 73 Decision 9 — scoring-tier enum is now exactly these three values.
# INV / INVALIDATED are LIFECYCLE states (Plan 73-09 OpportunityLifecyclePill),
# not scoring tiers. Any other value in tier_thresholds is a fail-fast.
ALLOWED_TIERS = frozenset({"A+", "DEV", "WATCH"})
REQUIRED_TIERS = ("A+", "DEV", "WATCH")


class TierThresholdLoader:
    """Load tier thresholds from tier_thresholds DB table.

    Per checker BLOCKER 6 (2026-05-23): OpportunityRanker MUST use this loader at
    __init__ time. NEVER hardcode {'A+': 80, 'DEV': 60, 'WATCH': 40} in source.

    Phase 73 Decision 9: fail-fast on rows outside ALLOWED_TIERS — INV /
    INVALIDATED rows are a registry-hygiene defect (cleaned up by migration
    0051 post-deploy; this guard catches re-introductions).
    """

    def load(self, strategy_id: str = "default") -> dict[str, int]:
        """Load tier thresholds for the given strategy from DB.

        Returns:
            dict like {'A+': 80, 'DEV': 60, 'WATCH': 40}

        Raises:
            RuntimeError if strategy_id has no rows OR any required tier is missing.
            ValueError if any row carries a tier outside ALLOWED_TIERS.
            Fail-fast: never silently fall back to hardcoded defaults (project lock).
        """
        try:
            from mission_control.models import TierThreshold  # type: ignore[import]
            rows = list(TierThreshold.objects.filter(strategy_id=strategy_id))
        except Exception as exc:
            log.warning(
                "TierThresholdLoader: DB unavailable for strategy_id=%r: %s — "
                "raising RuntimeError per fail-fast policy (BLOCKER 6)",
                strategy_id, exc,
            )
            raise RuntimeError(
                f"TierThresholdLoader: cannot load thresholds for strategy_id={strategy_id!r} "
                f"from DB: {exc}. Run Plan 66-00 migration 0041 seed."
            ) from exc

        if not rows:
            raise RuntimeError(
                f"tier_thresholds has no rows for strategy_id={strategy_id!r} — "
                f"run Plan 66-00 migration 0041 seed; NEVER hardcode thresholds (BLOCKER 6)."
            )

        # Phase 73 Decision 9 — fail-fast on disallowed tiers (INV / INVALIDATED
        # moved to lifecycle pill). The migration chain (0049 + 0051) prevents
        # these rows post-deploy; this guard catches any re-introduction.
        for r in rows:
            if r.tier not in ALLOWED_TIERS:
                raise ValueError(
                    f"Phase 73 Decision 9 lock: tier {r.tier!r} not allowed for "
                    f"strategy_id={strategy_id!r}. Allowed: {sorted(ALLOWED_TIERS)}. "
                    f"INV / INVALIDATED moved to lifecycle pill (Plan 73-09); "
                    f"check migration 0049 + 0051 application."
                )

        thresholds = {r.tier: r.min_score for r in rows}
        missing = [t for t in REQUIRED_TIERS if t not in thresholds]
        if missing:
            raise RuntimeError(
                f"tier_thresholds missing required tiers {missing} for "
                f"strategy_id={strategy_id!r} (BLOCKER 6 — config-driven)"
            )

        return thresholds
