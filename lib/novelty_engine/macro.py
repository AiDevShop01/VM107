"""Live MacroNovelty dimension — used by Plan 09 IntelligenceFeedMacroComposer.

Phase 83 Plan 08 V1 implementation. Deterministic scoring only — no LLM calls.
Phase 66 Lock E1: same input always produces same output.

Scoring rules V1:
  +0.3 if releasing_authority == 'FED' (rare → high novelty)
  +0.2 if severity == 'CRITICAL'
  +0.3 if indicator_code is FIRST EVER occurrence in history_provider (cold start)
  +0.2 if event_date is within the next 6 hours (urgency = novelty proxy)
  Cap at 1.0

Future iterations (V2+) may adjust weights based on observed novelty distribution
or add indicator-family clustering. When that happens, bump the version string
in this module and document the scoring change.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Callable, Optional

from .engine import NoveltyScore

_SCORING_VERSION = "V1"


def score_macro(
    payload: dict,
    history_provider: Optional[Callable] = None,
    threshold: float = 0.5,
) -> NoveltyScore:
    """Score macro novelty for a single economic event payload.

    Live implementation (Phase 83 V1). Deterministic. No LLM.

    Args:
        payload: Dict with the following keys:
            - indicator_code (str): e.g. "CPIAUCSL", "FOMC_RATE"
            - releasing_authority (str): e.g. "BLS", "FED", "BEA"
            - event_date (str): ISO 8601 datetime string for when the event fires
            - severity (str): one of CRITICAL | HIGH | MEDIUM | LOW
            - actual_value (float | None): optional — not used in V1 scoring
            - reference_period_date (str | None): optional — not used in V1 scoring

        history_provider: Optional callable(indicator_code: str) -> int
            Returns the prior occurrence count for the given indicator_code.
            Return 0 for cold start (first ever occurrence → +0.3 bonus).
            If None, cold-start detection is skipped.

        threshold: Score threshold for threshold_crossed. Default 0.5.

    Returns:
        NoveltyScore — always deterministic for the same input.

    Scoring rule codes:
        AUTH_FED              — releasing_authority is 'FED' (+0.3)
        SEV_CRITICAL          — severity is 'CRITICAL' (+0.2)
        FIRST_EVER_OCCURRENCE — history_provider returned 0 (+0.3)
        URGENT_RELEASE        — event_date within next 6 hours (+0.2)
    """
    raw_score: float = 0.0
    factors: list[str] = []
    codes: list[str] = []

    # Rule 1: +0.3 if releasing authority is FED (rare, high novelty)
    releasing_authority = payload.get("releasing_authority", "")
    if releasing_authority == "FED":
        raw_score += 0.3
        factors.append("FED-issued release")
        codes.append("AUTH_FED")

    # Rule 2: +0.2 if severity == CRITICAL
    severity = payload.get("severity", "")
    if severity == "CRITICAL":
        raw_score += 0.2
        factors.append("Critical severity classification")
        codes.append("SEV_CRITICAL")

    # Rule 3: +0.3 if first-ever occurrence (cold start)
    indicator_code = payload.get("indicator_code")
    if history_provider is not None and indicator_code:
        prior_count = history_provider(indicator_code)
        if prior_count == 0:
            raw_score += 0.3
            factors.append(f"First observed occurrence of {indicator_code}")
            codes.append("FIRST_EVER_OCCURRENCE")

    # Rule 4: +0.2 if event fires within next 6 hours (urgency = novelty proxy)
    event_date_iso = payload.get("event_date")
    if event_date_iso:
        try:
            evt = datetime.fromisoformat(str(event_date_iso).replace("Z", "+00:00"))
            if evt.tzinfo is None:
                evt = evt.replace(tzinfo=timezone.utc)
            time_until_event = evt - datetime.now(timezone.utc)
            if timedelta(0) <= time_until_event <= timedelta(hours=6):
                raw_score += 0.2
                factors.append("Imminent release (within 6 hours)")
                codes.append("URGENT_RELEASE")
        except (ValueError, TypeError):
            # Malformed event_date — skip urgency rule, don't crash
            pass

    # Cap at 1.0
    final_score = min(raw_score, 1.0)

    return NoveltyScore(
        score=final_score,
        contributing_factors=factors,
        threshold_crossed=(final_score >= threshold),
        reason_codes=codes,
    )


class MacroNovelty:
    """Class wrapper around score_macro for consumers that prefer OOP style.

    Back-compat: existing code in intelligence_feed_macro_composer.py may
    reference MacroNovelty as a class. This wrapper delegates to score_macro().
    """

    def score(
        self,
        payload: dict,
        history_provider: Optional[Callable] = None,
        threshold: float = 0.5,
    ) -> NoveltyScore:
        """Delegate to the module-level score_macro function."""
        return score_macro(payload, history_provider=history_provider, threshold=threshold)
