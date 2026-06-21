"""Phase 89 Wave 4 — throughput governor for macro relationship discovery.

Enforces Decision 4 throughput targets:
  - ≥1 proposal/week: below this → log discovery-health WARNING + threshold_action='warned_low'
  - ≤10 proposals/week: above this → tighten thresholds (raise r_min by 0.05) + threshold_action='tightened'
  - Otherwise: threshold_action='ok'

All actions logged + persisted in macro_discovery_throughput (Postgres).

Per project lock: DISCOVERY_POSTGRES_URL from env — NO fallback default.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone

import psycopg2

logger = logging.getLogger(__name__)

# Decision 4 throughput targets
MIN_PER_WEEK = 1
MAX_PER_WEEK = 10

# Default r_min from agent profile YAML (Decision 4)
DEFAULT_R_MIN = 0.30
R_MIN_TIGHTEN_STEP = 0.05


class ThroughputGovernor:
    """Weekly proposal throughput tracker + threshold adjuster.

    Records weekly proposal counts in macro_discovery_throughput and applies
    Decision 4 threshold rules on evaluation.

    Args:
        base_r_min: Starting r_min threshold (default 0.30 from profile YAML).
        min_per_week: Minimum acceptable proposals/week (default 1).
        max_per_week: Maximum acceptable proposals/week (default 10).
        tighten_step: r_min increment when >max_per_week (default 0.05).
    """

    def __init__(
        self,
        base_r_min: float = DEFAULT_R_MIN,
        min_per_week: int = MIN_PER_WEEK,
        max_per_week: int = MAX_PER_WEEK,
        tighten_step: float = R_MIN_TIGHTEN_STEP,
    ) -> None:
        self._base_r_min = base_r_min
        self._min_per_week = min_per_week
        self._max_per_week = max_per_week
        self._tighten_step = tighten_step

    def _get_pg_url(self) -> str:
        """Return DISCOVERY_POSTGRES_URL — fail-fast if unset."""
        url = os.environ.get("DISCOVERY_POSTGRES_URL")
        if not url:
            raise RuntimeError(
                "Required env var 'DISCOVERY_POSTGRES_URL' not set — "
                "fail-fast per project env-driven config lock."
            )
        return url

    def _week_start(self) -> date:
        """Return the ISO date of the Monday starting the current week."""
        today = date.today()
        # date.weekday(): Mon=0, Sun=6
        return today - __import__("datetime").timedelta(days=today.weekday())

    def record_proposal(self, proposal_id: str) -> int:
        """Upsert this week's row and increment the proposal count.

        Args:
            proposal_id: UUID string of the new EdgeProposal.

        Returns:
            Updated proposal_count for the current week.
        """
        week_start = self._week_start()
        pg_url = self._get_pg_url()

        sql = """
            INSERT INTO macro_discovery_throughput (week_start_iso, proposal_count)
            VALUES (%s, 1)
            ON CONFLICT (week_start_iso) DO UPDATE
            SET proposal_count = macro_discovery_throughput.proposal_count + 1
            RETURNING proposal_count
        """
        conn = psycopg2.connect(pg_url)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (week_start,))
                row = cur.fetchone()
                count = row[0] if row else 1
            conn.commit()
        finally:
            conn.close()

        logger.info({
            "event": "phase89_throughput_proposal_recorded",
            "proposal_id": proposal_id,
            "week_start": week_start.isoformat(),
            "proposal_count": count,
        })
        return count

    def evaluate_threshold(self, this_week_count: int) -> str:
        """Evaluate the current week's count against Decision 4 targets.

        Args:
            this_week_count: Number of proposals created this week.

        Returns:
            "warned_low": count < min_per_week
            "tightened": count > max_per_week
            "ok": within target range
        """
        if this_week_count < self._min_per_week:
            logger.warning({
                "event": "phase89_discovery_health_warning_low",
                "this_week_count": this_week_count,
                "min_per_week": self._min_per_week,
                "action": "warned_low",
                "note": (
                    "Discovery throughput is below minimum. "
                    "Check VM102 connectivity + correlation pair coverage."
                ),
            })
            return "warned_low"

        if this_week_count > self._max_per_week:
            logger.warning({
                "event": "phase89_discovery_throughput_high",
                "this_week_count": this_week_count,
                "max_per_week": self._max_per_week,
                "action": "tightened",
                "note": (
                    "Discovery throughput exceeds maximum — thresholds will be tightened. "
                    "Too many proposals indicates noise mining."
                ),
            })
            return "tightened"

        logger.info({
            "event": "phase89_discovery_throughput_ok",
            "this_week_count": this_week_count,
            "target_range": f"[{self._min_per_week}, {self._max_per_week}]",
        })
        return "ok"

    def tighten_thresholds(self) -> float:
        """Raise r_min by tighten_step and persist to Postgres runtime config.

        Called automatically when weekly count exceeds max_per_week.
        The new r_min is written to macro_discovery_throughput for
        the current week so next week's scan reads the tighter floor.

        Returns:
            New r_min value after tightening.
        """
        new_r_min = round(self._base_r_min + self._tighten_step, 4)
        week_start = self._week_start()
        pg_url = self._get_pg_url()
        now = datetime.now(tz=timezone.utc)

        sql = """
            INSERT INTO macro_discovery_throughput (
                week_start_iso, proposal_count,
                threshold_action, threshold_action_at,
                r_min_applied, r_min_previous
            ) VALUES (%s, 0, %s, %s, %s, %s)
            ON CONFLICT (week_start_iso) DO UPDATE
            SET threshold_action = EXCLUDED.threshold_action,
                threshold_action_at = EXCLUDED.threshold_action_at,
                r_min_applied = EXCLUDED.r_min_applied,
                r_min_previous = EXCLUDED.r_min_previous
        """
        conn = psycopg2.connect(pg_url)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (week_start, "tightened", now, new_r_min, self._base_r_min))
            conn.commit()
        finally:
            conn.close()

        logger.info({
            "event": "phase89_thresholds_tightened",
            "old_r_min": self._base_r_min,
            "new_r_min": new_r_min,
            "tighten_step": self._tighten_step,
            "week_start": week_start.isoformat(),
        })

        self._base_r_min = new_r_min
        return new_r_min
