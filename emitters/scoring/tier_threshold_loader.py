"""
tier_threshold_loader.py — Phase 66 Plan 66-06 (per checker BLOCKER 6, 2026-05-23)

Reads {A+: int, DEV: int, WATCH: int} from the tier_thresholds Postgres table
seeded by Plan 66-00 migration 0041. NEVER returns hardcoded literals.

Phase 73 will tune per-strategy thresholds via this same table without code changes.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

REQUIRED_TIERS = ("A+", "DEV", "WATCH")  # INV is implicit: gate-failure OR < WATCH


class TierThresholdLoader:
    """Load tier thresholds from tier_thresholds DB table.

    Per checker BLOCKER 6 (2026-05-23): OpportunityRanker MUST use this loader at
    __init__ time. NEVER hardcode {'A+': 80, 'DEV': 60, 'WATCH': 40} in source.
    """

    def load(self, strategy_id: str = "default") -> dict[str, int]:
        """Load tier thresholds for the given strategy from DB.

        Returns:
            dict like {'A+': 80, 'DEV': 60, 'WATCH': 40}

        Raises:
            RuntimeError if strategy_id has no rows OR any required tier is missing.
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

        thresholds = {r.tier: r.min_score for r in rows}
        missing = [t for t in REQUIRED_TIERS if t not in thresholds]
        if missing:
            raise RuntimeError(
                f"tier_thresholds missing required tiers {missing} for "
                f"strategy_id={strategy_id!r} (BLOCKER 6 — config-driven)"
            )

        return thresholds
