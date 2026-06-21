"""Phase 89 Wave 4 — correlation scanner for macro relationship discovery.

Sweeps (indicator, asset) and (indicator, indicator) pairs over a configurable
window using VM102 endpoints:
  - POST /indicator/correlations  → { r, p_value, rolling_correlation, sample_size }
  - POST /indicator/lead-lag      → { peak_lag, peak_r, p_value }

Thresholds (from agent profile YAML — Decision 4 / REQ-89-4):
  r_min: 0.30
  p_max: 0.05
  n_min: 30
  window_months: 12

Only pairs that pass ALL three thresholds produce a CandidateEdge.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default thresholds (match agent profile YAML — Decision 4)
DEFAULT_R_MIN: float = 0.30
DEFAULT_P_MAX: float = 0.05
DEFAULT_N_MIN: int = 30


class CorrelationScanner:
    """Scans indicator/asset pairs for statistically significant correlations.

    Args:
        vm102_client: Client that exposes:
            - indicator_correlations(indicator_a, indicator_b, window_months) →
              { r, p_value, sample_size, period_start, period_end }
            - indicator_lead_lag(indicator_a, indicator_b, max_lag_months) →
              { peak_lag, peak_r, p_value }
        window_months: Rolling window for correlation computation (default 12).
        r_min: Minimum absolute correlation threshold (default 0.30).
        p_max: Maximum p-value threshold (default 0.05).
        n_min: Minimum sample size threshold (default 30).
    """

    def __init__(
        self,
        vm102_client: Any,
        window_months: int = 12,
        r_min: float = DEFAULT_R_MIN,
        p_max: float = DEFAULT_P_MAX,
        n_min: int = DEFAULT_N_MIN,
    ) -> None:
        self._client = vm102_client
        self._window_months = window_months
        self._r_min = r_min
        self._p_max = p_max
        self._n_min = n_min

    def scan(self, pairs: list[tuple[str, str]]) -> list[dict]:
        """Scan all given pairs; return surviving CandidateEdge dicts.

        Each CandidateEdge dict contains:
            from_node, to_node, correlation, p_value, sample_size,
            lag_months, period_start, period_end, evidence_release_ids

        Args:
            pairs: List of (from_node, to_node) tuples to evaluate.

        Returns:
            List of CandidateEdge dicts that passed all thresholds.
        """
        candidates: list[dict] = []

        for from_node, to_node in pairs:
            candidate = self._evaluate_pair(from_node, to_node)
            if candidate is not None:
                candidates.append(candidate)

        logger.info({
            "event": "phase89_discovery_scan_complete",
            "pairs_scanned": len(pairs),
            "candidates_found": len(candidates),
            "r_min": self._r_min,
            "p_max": self._p_max,
            "n_min": self._n_min,
        })
        return candidates

    def _evaluate_pair(self, from_node: str, to_node: str) -> dict | None:
        """Evaluate a single pair; return CandidateEdge or None if below threshold.

        Calls VM102 for both correlation and lead-lag stats. Applies:
          - abs(r) >= r_min
          - p_value <= p_max
          - sample_size >= n_min
        """
        try:
            corr_result = self._client.indicator_correlations(
                indicator_a=from_node,
                indicator_b=to_node,
                window_months=self._window_months,
            )
        except Exception as exc:
            logger.warning({
                "event": "phase89_vm102_correlations_failed",
                "from_node": from_node,
                "to_node": to_node,
                "error": str(exc),
            })
            return None

        r = corr_result.get("r", 0.0)
        p_value = corr_result.get("p_value", 1.0)
        n = corr_result.get("sample_size", 0)
        period_start = corr_result.get("period_start", "")
        period_end = corr_result.get("period_end", "")

        # Apply all three thresholds (Decision 4 / REQ-89-4)
        if abs(r) < self._r_min:
            logger.debug({
                "event": "phase89_pair_rejected_r",
                "from_node": from_node,
                "to_node": to_node,
                "r": r,
                "r_min": self._r_min,
            })
            return None

        if p_value > self._p_max:
            logger.debug({
                "event": "phase89_pair_rejected_p",
                "from_node": from_node,
                "to_node": to_node,
                "p_value": p_value,
                "p_max": self._p_max,
            })
            return None

        if n < self._n_min:
            logger.debug({
                "event": "phase89_pair_rejected_n",
                "from_node": from_node,
                "to_node": to_node,
                "sample_size": n,
                "n_min": self._n_min,
            })
            return None

        # Fetch lead-lag stats
        lag_months: float | None = None
        try:
            lag_result = self._client.indicator_lead_lag(
                indicator_a=from_node,
                indicator_b=to_node,
                max_lag_months=self._window_months,
            )
            peak_lag = lag_result.get("peak_lag", 0.0)
            if peak_lag is not None and abs(peak_lag) >= 0.5:
                lag_months = peak_lag
        except Exception as exc:
            logger.warning({
                "event": "phase89_vm102_lead_lag_failed",
                "from_node": from_node,
                "to_node": to_node,
                "error": str(exc),
            })

        # Build candidate — evidence_release_ids derived from node IDs
        candidate: dict = {
            "from_node": from_node,
            "to_node": to_node,
            "correlation": r,
            "p_value": p_value,
            "sample_size": n,
            "lag_months": lag_months,
            "period_start": period_start,
            "period_end": period_end,
            "evidence_release_ids": [f"release:{from_node}-{period_end}"],
        }

        logger.info({
            "event": "phase89_candidate_found",
            "from_node": from_node,
            "to_node": to_node,
            "r": r,
            "p_value": p_value,
            "sample_size": n,
            "lag_months": lag_months,
        })
        return candidate
