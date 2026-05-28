"""behavioral_analysis_tool — Phase 57 Plan 05.

Deterministic trader behavioral analysis for a given Execution.

Reads (3-way concurrent fan-out via asyncio.gather):
  - VM100 GET /api/journal/internal/executions/{execution_id}
        — canonical Execution row (state, opened_at, campaign_id)
  - VM100 GET /api/journal/internal/events/timeline?execution_id=...
        — Phase 56 event timeline for THIS execution
        (order_submitted, fill_received, stop_loss_moved, take_profit_modified,
         checklist_* events — all scoped to execution correlation_id chain)
  - VM100 GET /api/journal/internal/events/timeline?account_recent=...
        — Phase 56 recent account timeline: last N minutes before entry
        (used to detect revenge trade: prior LOSS execution within N minutes)

Computes (pure Python, NO LLM) — 6 V1 behavioral metrics per CONTEXT §11:
  - hesitation_seconds: fill_received.occurred_at - order_submitted.occurred_at
  - late_entry_score: heuristic comparing entry timing vs BOS signal window
  - stop_movement_count: count of stop_loss_moved events (0 if not yet emitted — §11 graceful degradation)
  - over_management_score: aggregates stop_movement_count + take_profit_modified count
  - revenge_trade_flag: entry within N=15 min of previous LOSS execution by same account
  - fomo_entry_flag: entry within N bars of strong displacement candle without checklist completion

Returns BehavioralAnalysisResult (fingpt_core.contracts.analytics.behavioral).

Graceful degradation per CONTEXT §11 + RESEARCH pitfall #7:
  When stop_loss_moved / take_profit_modified events are not yet emitted by
  any producer phase (expected in Phase 57 V1 — these ship in Phase 60+),
  the metric defaults to 0 (for counts) or None (for scores), and
  narrative_fragments include 'Insufficient event data for V1 scoring
  (stop_loss_moved producer not yet shipped)'. NEVER raises. NEVER fabricates.

Behavioral score aggregation (V1):
  - hesitation_seconds clamp: ≤ 30s → 100 pts; 30–90s → 50 pts; > 90s → 20 pts
  - late_entry_score: None → confidence drop (−10 confidence); non-None → no penalty
  - revenge_trade_flag: True → −20 score penalty
  - fomo_entry_flag: True → −25 score penalty
  - over_management_score: per stop_movement > 2 → −10 penalty each

Prometheus telemetry (Pattern 26 — bounded cardinality):
  vm107_analytics_tool_calls_total{tool='behavioral_analysis_tool', result_status=...}
  vm107_analytics_tool_duration_seconds{tool='behavioral_analysis_tool'}

result_status values: success | degraded | transport_error | validation_error

Architecture notes (CONTEXT §7):
  - 3-way concurrent fan-out: execution_id alone parameterizes all 3 VM100 calls
    → asyncio.gather is correct (no dependency between fetches — same as execution_quality_tool)
  - FAST_FAIL retry profile per Phase 47.2.1 lock
  - No qdrant_client import
  - No LLM calls (deterministic-Python primary doctrine, CONTEXT §5)
"""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any

import httpx

from fingpt_core.clients import RetryProfile, VM100Client
from fingpt_core.contracts.analytics.behavioral import (
    BehavioralAnalysisPayload,
    BehavioralAnalysisRequest,
    BehavioralAnalysisResult,  # backward compat alias
)
from fingpt_core.contracts.errors import ContractValidationError
from fingpt_core.contracts.evidence import EvidenceCitation
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolProvenance

logger = logging.getLogger("fingpt.tools.behavioral_analysis")

TOOL_NAME = "behavioral_analysis_tool"

# Behavioral scoring constants (PLAN.md §task action)
# Hesitation scoring (in seconds)
_HESITATION_HEALTHY_MAX_S = 30.0    # ≤ 30s = healthy execution timing → 100 pts
_HESITATION_MODERATE_MAX_S = 90.0   # 30–90s = moderate hesitation → 50 pts
# _HESITATION_HIGH = > 90s → 20 pts

# Revenge trade detection window
_REVENGE_TRADE_WINDOW_MINUTES = 15.0  # within 15 min of prior LOSS = revenge trade

# FOMO entry: N bars of strong displacement candle = 5 M5 bars = 25 min heuristic
_FOMO_DISPLACEMENT_WINDOW_MINUTES = 25.0

# Confidence penalties
_CONFIDENCE_PENALTY_LATE_ENTRY_DEGRADED = Decimal("10")  # late_entry_score absent
_CONFIDENCE_PENALTY_STOP_EVENTS_ABSENT = Decimal("10")   # stop_loss_moved not produced
_CONFIDENCE_PENALTY_TIMELINE_ABSENT = Decimal("30")       # no timeline at all

# Score penalties (additive deductions from base hesitation score)
_SCORE_PENALTY_REVENGE = 20     # revenge trade flag
_SCORE_PENALTY_FOMO = 25        # FOMO entry flag
_SCORE_PENALTY_PER_STOP_MOVE = 10  # per stop movement beyond 2

# Graceful degradation narrative constants
_NARRATIVE_INSUFFICIENT_STOP_LOSS = (
    "Insufficient event data for V1 scoring "
    "(stop_loss_moved producer not yet shipped)"
)
_NARRATIVE_INSUFFICIENT_TP_MODIFIED = (
    "Insufficient event data for V1 scoring "
    "(take_profit_modified producer not yet shipped)"
)


def _is_not_available(data: dict) -> bool:
    """Return True if data is a not_available envelope or error."""
    return isinstance(data, dict) and (
        data.get("status") == "not_available"
        or data.get("error") is not None
    )


def _extract_events_by_type(events: list[dict], event_type: str) -> list[dict]:
    """Return all events matching event_type."""
    return [e for e in events if e.get("event_type") == event_type]


def _extract_event_by_type(events: list[dict], event_type: str) -> dict | None:
    """Return the first event matching event_type, or None."""
    for e in events:
        if e.get("event_type") == event_type:
            return e
    return None


def _parse_iso_datetime(value: str | None):
    """Parse ISO 8601 datetime string to datetime, returning None on failure."""
    if not value:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def compute_hesitation_seconds(
    order_submitted: dict | None,
    fill_received: dict | None,
) -> tuple[Decimal | None, list[str]]:
    """Compute hesitation_seconds = fill_received.occurred_at - order_submitted.occurred_at.

    Returns:
        (hesitation_seconds_or_None, list_of_narrative_fragments)
    """
    if order_submitted is None or fill_received is None:
        return None, [
            "not_available: order_submitted or fill_received event missing from timeline; "
            "hesitation_seconds cannot be computed"
        ]

    order_time_str = order_submitted.get("occurred_at") or order_submitted.get("timestamp")
    fill_time_str = fill_received.get("occurred_at") or fill_received.get("timestamp")

    order_time = _parse_iso_datetime(order_time_str)
    fill_time = _parse_iso_datetime(fill_time_str)

    if order_time is None or fill_time is None:
        return None, [
            "not_available: occurred_at timestamps missing or unparseable in "
            "order_submitted/fill_received events"
        ]

    hesitation_s = (fill_time - order_time).total_seconds()
    if hesitation_s < 0:
        # Defensive: timestamps wrong order (data issue)
        hesitation_s = 0.0

    hes = Decimal(str(round(hesitation_s, 2)))

    if hesitation_s <= _HESITATION_HEALTHY_MAX_S:
        narrative = f"Hesitation {hesitation_s:.1f}s — within healthy range (≤{_HESITATION_HEALTHY_MAX_S:.0f}s)"
    elif hesitation_s <= _HESITATION_MODERATE_MAX_S:
        narrative = f"Hesitation {hesitation_s:.1f}s — moderate (30–90s range; possible UI hesitation or deliberate delay)"
    else:
        narrative = f"Hesitation {hesitation_s:.1f}s — high hesitation (>{_HESITATION_MODERATE_MAX_S:.0f}s; possible second-guessing or late execution)"

    return hes, [narrative]


def compute_hesitation_score(hesitation_seconds: Decimal | None) -> int:
    """Convert hesitation_seconds to behavioral score contribution (0-100).

    ≤ 30s → 100 pts
    30–90s → 50 pts
    > 90s → 20 pts
    None → 50 pts (neutral degradation)
    """
    if hesitation_seconds is None:
        return 50  # neutral when data missing
    hes_f = float(hesitation_seconds)
    if hes_f <= _HESITATION_HEALTHY_MAX_S:
        return 100
    elif hes_f <= _HESITATION_MODERATE_MAX_S:
        return 50
    else:
        return 20


def compute_late_entry_score(
    execution_data: dict,
    timeline_events: list[dict],
) -> tuple[Decimal | None, list[str]]:
    """Heuristic late entry score (0-100, higher = later entry relative to ideal window).

    V1 heuristic: if fill_received timestamp gap from order_submitted exceeds
    a typical confirmation window (N=5 minutes post-BOS signal), penalise progressively.
    In Phase 57 V1, the BOS signal time is not directly available, so we use the
    order_submitted-to-fill_received gap as a proxy for entry timing discipline.

    Phase 62+ may learn the ideal entry time from outcome correlation data.

    Returns:
        (late_entry_score_0_to_100_or_None, narrative_fragments)
    """
    # V1 heuristic: late entry = fill arrived significantly after order was placed
    # + execution opened_at vs the ideal entry window (unavailable in V1)
    # Use fill gap as timing signal: < 2min = on-time; 2-10min = late; > 10min = very late
    fill_received = _extract_event_by_type(timeline_events, "fill_received")
    order_submitted = _extract_event_by_type(timeline_events, "order_submitted")

    if order_submitted is None or fill_received is None:
        return None, [
            "late_entry_score: None — order_submitted or fill_received events missing; "
            "late entry heuristic cannot be computed (Phase 62+ will learn this from BOS signal timing)"
        ]

    order_time = _parse_iso_datetime(order_submitted.get("occurred_at") or order_submitted.get("timestamp"))
    fill_time = _parse_iso_datetime(fill_received.get("occurred_at") or fill_received.get("timestamp"))

    if order_time is None or fill_time is None:
        return None, [
            "late_entry_score: None — event timestamps unparseable"
        ]

    fill_gap_minutes = (fill_time - order_time).total_seconds() / 60.0

    # V1 heuristic: use opened_at from execution if available for broader lateness signal
    opened_at_str = execution_data.get("opened_at")
    opened_at = _parse_iso_datetime(opened_at_str)

    # Score: 0 = on-time; 100 = very late
    # Fill gap 0-2min → score 0 (on-time)
    # Fill gap 2-10min → score linear from 0 to 50
    # Fill gap > 10min → score 50-100 (very late)
    if fill_gap_minutes <= 2.0:
        score = Decimal("0.00")
        narrative = f"Entry on-time: fill arrived {fill_gap_minutes * 60:.0f}s after order submission — within 2-minute confirmation window"
    elif fill_gap_minutes <= 10.0:
        # Linear from 0 to 50 between 2 and 10 min
        fraction = (fill_gap_minutes - 2.0) / 8.0
        score = Decimal(str(round(fraction * 50.0, 2)))
        narrative = (
            f"Late entry score {score}/100: fill arrived {fill_gap_minutes:.1f} min after order — "
            "beyond 2-minute ideal window (V1 heuristic; BOS signal timing unknown)"
        )
    else:
        # Linear from 50 to 100 between 10 and 30 min, cap at 100
        fraction = min(1.0, (fill_gap_minutes - 10.0) / 20.0)
        score = Decimal(str(round(50.0 + fraction * 50.0, 2)))
        narrative = (
            f"Late entry score {score}/100: fill arrived {fill_gap_minutes:.1f} min after order — "
            "significantly delayed entry (possible re-entry chase or slow broker)"
        )

    return score, [narrative]


def compute_stop_movement_count(
    execution_timeline_events: list[dict],
) -> tuple[int, list[str], bool]:
    """Count stop_loss_moved events on this execution's timeline.

    Per CONTEXT §11 + RESEARCH pitfall #7: stop_loss_moved events are NOT yet
    emitted by any producer in Phase 57. This function ALWAYS returns
    stop_movement_count=0 with a narrative noting graceful degradation.

    Returns:
        (count, narrative_fragments, was_degraded)
        was_degraded: True when stop_loss_moved event type not found in any timeline event
    """
    stop_moved_events = _extract_events_by_type(execution_timeline_events, "stop_loss_moved")
    count = len(stop_moved_events)

    # Check if stop_loss_moved event type exists anywhere in the timeline
    all_event_types = {e.get("event_type") for e in execution_timeline_events}
    producer_shipped = "stop_loss_moved" in all_event_types

    if not producer_shipped:
        # Graceful degradation per pitfall #7
        return 0, [_NARRATIVE_INSUFFICIENT_STOP_LOSS], True
    else:
        if count == 0:
            return 0, ["stop_movement_count = 0: stop-loss not moved during trade (disciplined)"], False
        else:
            return count, [
                f"stop_movement_count = {count}: stop-loss moved {count} time(s) during execution"
            ], False


def compute_take_profit_modified_count(
    execution_timeline_events: list[dict],
) -> tuple[int, list[str], bool]:
    """Count take_profit_modified events on this execution's timeline.

    Returns:
        (count, narrative_fragments, was_degraded)
    """
    tp_events = _extract_events_by_type(execution_timeline_events, "take_profit_modified")
    count = len(tp_events)

    all_event_types = {e.get("event_type") for e in execution_timeline_events}
    producer_shipped = "take_profit_modified" in all_event_types

    if not producer_shipped:
        return 0, [_NARRATIVE_INSUFFICIENT_TP_MODIFIED], True
    else:
        if count == 0:
            return 0, ["take_profit_modified_count = 0: take-profit not adjusted during trade"], False
        else:
            return count, [
                f"take_profit_modified_count = {count}: take-profit modified {count} time(s)"
            ], False


def compute_over_management_score(
    stop_movement_count: int,
    tp_modified_count: int,
    stop_degraded: bool,
    tp_degraded: bool,
) -> tuple[Decimal | None, list[str]]:
    """Compute over_management_score from stop + TP intervention counts.

    When both sources are degraded → None (insufficient data).
    When either source is available → compute with available data.

    Scoring (V1):
    - stop_movement_count × 20 points each
    - tp_modified_count × 15 points each
    - Capped at 100

    Returns:
        (score_or_None, narrative_fragments)
    """
    if stop_degraded and tp_degraded:
        return None, [
            "over_management_score: None — both stop_loss_moved and take_profit_modified "
            "producer events not yet shipped; cannot compute over-management score in V1"
        ]

    raw_score = (stop_movement_count * 20) + (tp_modified_count * 15)
    score = Decimal(str(min(100, raw_score)))

    if raw_score == 0:
        narrative = "over_management_score = 0/100: no stop or TP modifications — trade managed cleanly"
    elif raw_score <= 30:
        narrative = (
            f"over_management_score = {score}/100: minimal intervention "
            f"({stop_movement_count} stop move(s), {tp_modified_count} TP change(s))"
        )
    else:
        narrative = (
            f"over_management_score = {score}/100: significant trade management "
            f"({stop_movement_count} stop move(s), {tp_modified_count} TP change(s)) — "
            "potential over-management"
        )

    fragments = [narrative]
    if stop_degraded:
        fragments.append(_NARRATIVE_INSUFFICIENT_STOP_LOSS)
    if tp_degraded:
        fragments.append(_NARRATIVE_INSUFFICIENT_TP_MODIFIED)

    return score, fragments


def compute_revenge_trade_flag(
    execution_data: dict,
    recent_account_events: list[dict],
) -> tuple[bool, list[str]]:
    """Detect revenge trade: entry within N=15 minutes of prior LOSS Execution.

    Reads the recent account timeline (pre-entry window) and looks for
    position_closed events with negative outcome (result_r < 0 or payload.outcome='loss').

    Returns:
        (is_revenge_trade, narrative_fragments)
    """
    # Get this execution's order submission time
    opened_at_str = execution_data.get("opened_at")
    opened_at = _parse_iso_datetime(opened_at_str)

    if opened_at is None:
        return False, [
            "revenge_trade_flag: False (default) — execution opened_at unavailable; "
            "cannot check prior loss within window"
        ]

    # Look for position_closed events in recent timeline with negative outcome
    position_closed_events = _extract_events_by_type(recent_account_events, "position_closed")

    revenge_detected = False
    prior_loss_details: str | None = None

    for event in position_closed_events:
        event_time = _parse_iso_datetime(event.get("occurred_at") or event.get("timestamp"))
        if event_time is None:
            continue

        # Check if this closing event was BEFORE our entry (and within window)
        if event_time >= opened_at:
            continue  # Not a prior trade

        minutes_before = (opened_at - event_time).total_seconds() / 60.0
        if minutes_before > _REVENGE_TRADE_WINDOW_MINUTES:
            continue  # Outside the revenge trade window

        # Check if this was a LOSS trade
        payload = event.get("payload") or {}
        result_r = payload.get("result_r")
        outcome = payload.get("outcome") or payload.get("result") or ""
        is_loss = False

        if result_r is not None:
            try:
                is_loss = float(result_r) < 0
            except (TypeError, ValueError):
                pass
        elif outcome.lower() in ("loss", "losing", "negative"):
            is_loss = True

        if is_loss:
            revenge_detected = True
            # Use event time in HH:MM format for narrative
            time_str = event_time.strftime("%H:%M")
            prior_loss_details = (
                f"Revenge trade flagged — entry {minutes_before:.0f} min after LOSS execution "
                f"closed at {time_str}"
            )
            break

    if revenge_detected and prior_loss_details:
        return True, [prior_loss_details]
    else:
        return False, [
            f"revenge_trade_flag: False — no LOSS execution found within "
            f"{_REVENGE_TRADE_WINDOW_MINUTES:.0f}-minute window before entry"
        ]


def compute_fomo_entry_flag(
    execution_data: dict,
    timeline_events: list[dict],
) -> tuple[bool, list[str]]:
    """Detect FOMO entry: entry within N bars of strong displacement without checklist.

    V1 heuristic:
    - Check if checklist was completed before fill_received event
    - Check if fill_received arrived within FOMO_DISPLACEMENT_WINDOW_MINUTES
      of order_submitted (rapid consecutive execution = possible impulse entry)
    - Check for displacement signal from regime context (if available in payload)

    If checklist_completed event is absent and execution was rapid after order,
    flags FOMO entry. Otherwise False.

    Returns:
        (is_fomo_entry, narrative_fragments)
    """
    fill_received = _extract_event_by_type(timeline_events, "fill_received")
    order_submitted = _extract_event_by_type(timeline_events, "order_submitted")
    checklist_completed = _extract_event_by_type(timeline_events, "checklist_completed")

    if order_submitted is None or fill_received is None:
        return False, [
            "fomo_entry_flag: False (default) — order_submitted or fill_received events "
            "missing; FOMO detection requires fill timing"
        ]

    order_time = _parse_iso_datetime(order_submitted.get("occurred_at") or order_submitted.get("timestamp"))
    fill_time = _parse_iso_datetime(fill_received.get("occurred_at") or fill_received.get("timestamp"))

    if order_time is None or fill_time is None:
        return False, ["fomo_entry_flag: False (default) — event timestamps unparseable"]

    fill_gap_minutes = (fill_time - order_time).total_seconds() / 60.0

    # Check checklist completion BEFORE the fill
    checklist_before_fill = False
    if checklist_completed is not None:
        checklist_time = _parse_iso_datetime(
            checklist_completed.get("occurred_at") or checklist_completed.get("timestamp")
        )
        if checklist_time is not None and fill_time is not None:
            checklist_before_fill = checklist_time < fill_time

    # Check for displacement signal in fill_received payload
    fill_payload = fill_received.get("payload") or {}
    displacement_noted = (
        fill_payload.get("displacement_detected") is True
        or fill_payload.get("entry_type") in ("breakout", "displacement_chase")
    )

    # FOMO conditions:
    # 1. Very rapid execution (within displacement window) AND
    # 2. No checklist completion before fill (or explicit displacement marker)
    rapid_entry = fill_gap_minutes <= _FOMO_DISPLACEMENT_WINDOW_MINUTES
    no_checklist = not checklist_before_fill

    if rapid_entry and no_checklist and (displacement_noted or fill_gap_minutes <= 1.0):
        # Strong FOMO signal: rapid entry without checklist on a displacement candle
        return True, [
            f"FOMO entry flagged — fill executed {fill_gap_minutes * 60:.0f}s after order "
            f"without prior checklist completion "
            f"({'displacement marker in payload' if displacement_noted else 'rapid order-to-fill gap'})"
        ]
    elif rapid_entry and no_checklist:
        # Weak FOMO signal: rapid but no displacement marker
        return False, [
            f"fomo_entry_flag: False — rapid entry {fill_gap_minutes:.1f}min but no "
            "displacement marker in payload; insufficient evidence for FOMO flag "
            "(V1 heuristic: requires checklist absence + displacement signal)"
        ]
    elif not checklist_before_fill:
        # No checklist but not rapid — borderline
        return False, [
            "fomo_entry_flag: False — checklist not completed before fill but "
            "entry timing not within displacement window"
        ]
    else:
        return False, [
            "fomo_entry_flag: False — checklist completed before fill; disciplined entry"
        ]


def compute_behavioral_metrics(
    execution_data: dict,
    execution_timeline: dict,
    recent_account_timeline: dict,
) -> dict:
    """Pure-Python deterministic behavioral metrics computation.

    6 V1 behavioral metrics (CONTEXT §11):
      1. hesitation_seconds: fill_received.occurred_at - order_submitted.occurred_at
      2. late_entry_score: heuristic from entry timing vs order submission gap
      3. stop_movement_count: count of stop_loss_moved events (0 + degraded fragment if absent)
      4. over_management_score: stop + TP intervention aggregation
      5. revenge_trade_flag: entry within 15 min of prior LOSS execution
      6. fomo_entry_flag: rapid entry without checklist completion

    Graceful degradation: each metric handles missing data independently.
    Confidence reflects metric availability.
    Score: base from hesitation, then penalties applied.

    Args:
        execution_data: VM100 Execution row dict (or not_available envelope).
        execution_timeline: VM100 timeline response for this execution
            (order_submitted, fill_received, stop_loss_moved, etc.)
        recent_account_timeline: VM100 recent account timeline (last N min before entry,
            used for revenge trade detection).

    Returns:
        dict matching BehavioralAnalysisResult field shape.
    """
    execution_available = not _is_not_available(execution_data)

    # Extract timeline events
    timeline_events: list[dict] = []
    if not _is_not_available(execution_timeline):
        timeline_events = execution_timeline.get("events") or []

    recent_events: list[dict] = []
    if not _is_not_available(recent_account_timeline):
        recent_events = recent_account_timeline.get("events") or []

    # ── Complete degrade if execution row unavailable ────────────────────────
    if not execution_available:
        return {
            "score": None,
            "confidence": Decimal("0"),
            "signals": {
                "hesitation_normal": False,
                "entry_on_time": False,
                "stop_not_moved": True,
                "managed_cleanly": False,
                "no_revenge_trade": True,
                "no_fomo": True,
            },
            "narrative_fragments": [
                "not_available: Execution row unavailable — behavioral analysis cannot be scored",
                "not_available reason: VM100 returned not_available or transport error",
            ],
            "hesitation_seconds": None,
            "late_entry_score": None,
            "stop_movement_count": 0,
            "over_management_score": None,
            "revenge_trade_flag": False,
            "fomo_entry_flag": False,
        }

    # ── Extract key timeline events ──────────────────────────────────────────
    order_submitted = _extract_event_by_type(timeline_events, "order_submitted")
    fill_received = _extract_event_by_type(timeline_events, "fill_received")

    # ── Metric 1: hesitation_seconds ─────────────────────────────────────────
    hesitation_seconds, hesitation_fragments = compute_hesitation_seconds(
        order_submitted, fill_received
    )
    hesitation_score_pts = compute_hesitation_score(hesitation_seconds)

    # ── Metric 2: late_entry_score ───────────────────────────────────────────
    late_entry_score, late_entry_fragments = compute_late_entry_score(
        execution_data, timeline_events
    )
    late_entry_degraded = late_entry_score is None

    # ── Metric 3: stop_movement_count ────────────────────────────────────────
    stop_movement_count, stop_fragments, stop_degraded = compute_stop_movement_count(
        timeline_events
    )

    # ── Metric 4a: take_profit_modified_count (feeds over_management_score) ─
    tp_modified_count, tp_fragments, tp_degraded = compute_take_profit_modified_count(
        timeline_events
    )

    # ── Metric 4: over_management_score ─────────────────────────────────────
    over_management_score, over_mgmt_fragments = compute_over_management_score(
        stop_movement_count, tp_modified_count, stop_degraded, tp_degraded
    )

    # ── Metric 5: revenge_trade_flag ─────────────────────────────────────────
    revenge_trade_flag, revenge_fragments = compute_revenge_trade_flag(
        execution_data, recent_events
    )

    # ── Metric 6: fomo_entry_flag ─────────────────────────────────────────────
    fomo_entry_flag, fomo_fragments = compute_fomo_entry_flag(
        execution_data, timeline_events
    )

    # ── Aggregate behavioral score ────────────────────────────────────────────
    # Base score comes from hesitation_score_pts (0-100)
    base_score = hesitation_score_pts

    # Apply penalties
    score_float = float(base_score)
    if revenge_trade_flag:
        score_float -= _SCORE_PENALTY_REVENGE
    if fomo_entry_flag:
        score_float -= _SCORE_PENALTY_FOMO
    # Per stop movement beyond 2 (Phase 57 V1: stop_movement_count is typically 0)
    if stop_movement_count > 2:
        score_float -= (stop_movement_count - 2) * _SCORE_PENALTY_PER_STOP_MOVE

    # Clamp score to [0, 100]
    score_float = max(0.0, min(100.0, score_float))

    # If timeline absent → degrade to None
    if not timeline_events:
        score = None
    else:
        score = Decimal(str(round(score_float, 2)))

    # ── Confidence calculation ────────────────────────────────────────────────
    # Start at 100; degrade based on data availability
    confidence = Decimal("100")

    if not timeline_events:
        # No timeline at all — full degrade
        confidence -= _CONFIDENCE_PENALTY_TIMELINE_ABSENT
        score = None

    if late_entry_degraded:
        confidence -= _CONFIDENCE_PENALTY_LATE_ENTRY_DEGRADED

    if stop_degraded:
        confidence -= _CONFIDENCE_PENALTY_STOP_EVENTS_ABSENT

    # Ensure confidence ≥ 0
    confidence = max(Decimal("0"), confidence)

    # If score is None after timeline degradation, set confidence to 0
    if score is None and not timeline_events:
        confidence = Decimal("0")

    # ── Signals ───────────────────────────────────────────────────────────────
    signals = {
        "hesitation_normal": (
            hesitation_seconds is not None and float(hesitation_seconds) < 30.0
        ),
        "entry_on_time": (
            late_entry_score is not None and float(late_entry_score) < 50.0
        ) if late_entry_score is not None else True,  # default True when unknown (no penalty)
        "stop_not_moved": stop_movement_count == 0,
        "managed_cleanly": (
            over_management_score is not None and float(over_management_score) < 30.0
        ) if over_management_score is not None else True,  # default True when data missing
        "no_revenge_trade": not revenge_trade_flag,
        "no_fomo": not fomo_entry_flag,
    }

    # ── Compose narrative_fragments ───────────────────────────────────────────
    narrative_fragments: list[str] = []

    if score is not None:
        # Summary fragment
        summary_parts = []
        if hesitation_seconds is not None:
            summary_parts.append(f"hesitation {float(hesitation_seconds):.1f}s")
        if revenge_trade_flag:
            summary_parts.append("revenge trade flagged")
        if fomo_entry_flag:
            summary_parts.append("FOMO entry flagged")
        if stop_movement_count > 0:
            summary_parts.append(f"{stop_movement_count} stop move(s)")

        if summary_parts:
            narrative_fragments.append(
                f"Behavioral score = {score}/100: "
                + "; ".join(summary_parts)
            )
        else:
            narrative_fragments.append(
                f"Behavioral score = {score}/100: no adverse behavioral signals detected"
            )
    else:
        narrative_fragments.append(
            "Insufficient event data for V1 scoring: behavioral score cannot be computed "
            "(event timeline unavailable from VM100)"
        )

    # Append per-metric fragments
    narrative_fragments.extend(hesitation_fragments)
    narrative_fragments.extend(late_entry_fragments)
    narrative_fragments.extend(stop_fragments)
    narrative_fragments.extend(tp_fragments)
    narrative_fragments.extend(over_mgmt_fragments)
    narrative_fragments.extend(revenge_fragments)
    narrative_fragments.extend(fomo_fragments)

    return {
        "score": score,
        "confidence": confidence,
        "signals": signals,
        "narrative_fragments": narrative_fragments,
        "hesitation_seconds": hesitation_seconds,
        "late_entry_score": late_entry_score,
        "stop_movement_count": stop_movement_count,
        "over_management_score": over_management_score,
        "revenge_trade_flag": revenge_trade_flag,
        "fomo_entry_flag": fomo_entry_flag,
    }


class BehavioralAnalysisTool:
    """VM107 analytics tool: deterministic trader behavioral analysis.

    Implements the ContractTool pattern (validate-request → call-vm → validate-response)
    as a standalone class (no Agent context required) so it can be called directly
    by AnalyticsService in Phase 57-09 and tested without the agent framework.

    Reads (3-way concurrent fan-out via asyncio.gather):
      - VM100 GET /api/journal/internal/executions/{execution_id}
      - VM100 GET /api/journal/internal/events/timeline?execution_id=...
        (execution-scoped behavioral events)
      - VM100 GET /api/journal/internal/events/timeline (recent account events,
        scoped to N minutes before execution entry — for revenge trade detection)

    Computes (6 V1 behavioral metrics per CONTEXT §11):
      - hesitation_seconds: fill delay from order submission
      - late_entry_score: heuristic entry timing vs confirmation window
      - stop_movement_count: count of stop_loss_moved events (graceful degradation)
      - over_management_score: stop + TP intervention aggregation
      - revenge_trade_flag: entry within 15 min of prior LOSS execution
      - fomo_entry_flag: rapid entry without checklist completion

    Usage:
        tool = BehavioralAnalysisTool()
        result = tool.run(execution_id="...", scoring_ruleset_version="1.0.0")

    The result is a BehavioralAnalysisResult Pydantic model.
    """

    def _validate_request(self, args: dict) -> BehavioralAnalysisRequest:
        """Validate args against BehavioralAnalysisRequest contract.

        Raises:
            ContractValidationError: if args don't match contract shape.
        """
        try:
            return BehavioralAnalysisRequest(**args)
        except Exception as e:  # noqa: BLE001
            raise ContractValidationError(errors=[str(e)], message=str(e)) from e

    async def _call_vm(self, request: BehavioralAnalysisRequest) -> dict:
        """3-way concurrent fan-out to VM100 (execution + execution-timeline + recent-account-timeline).

        All 3 calls are parameterized from execution_id alone — no dependency
        between fetches — so asyncio.gather is correct here (same as
        execution_quality_tool in 57-04).

        3rd call (recent account events) queries for position_closed events in
        the N=15 minute window before this execution's entry, for revenge trade
        detection. In V1, we use a wide time window and filter in Python.

        Uses FAST_FAIL retry profile. On transport failure, synthesizes a
        not_available envelope for the affected data source.

        Returns:
            dict with keys 'execution', 'execution_timeline', 'recent_account_timeline'.
        """
        vm100 = VM100Client(profile=RetryProfile.FAST_FAIL)
        execution_id_str = str(request.execution_id)

        # Event types for execution-scoped behavioral events
        execution_event_types = [
            "order_submitted",
            "fill_received",
            "position_closed",
            "stop_loss_moved",
            "take_profit_modified",
            "checklist_completed",
        ]

        async def _get_execution() -> dict:
            try:
                return await vm100.get(
                    f"api/journal/internal/executions/{execution_id_str}"
                )
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(
                    "behavioral_analysis_tool: VM100 transport error for execution %s: %s",
                    execution_id_str,
                    e,
                )
                return {
                    "status": "not_available",
                    "reason": "vm100_transport_error",
                    "detail": str(e),
                }
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return {
                        "status": "not_available",
                        "reason": "execution_not_found",
                        "detail": str(e),
                    }
                if e.response.status_code >= 500:
                    return {
                        "status": "not_available",
                        "reason": "vm100_server_error",
                        "detail": str(e),
                    }
                raise

        async def _get_execution_timeline() -> dict:
            try:
                params = {
                    "execution_id": execution_id_str,
                    "event_type": execution_event_types,
                    "limit": 100,
                }
                return await vm100.get(
                    "api/journal/internal/events/timeline",
                    params=params,
                )
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(
                    "behavioral_analysis_tool: VM100 execution timeline transport error for %s: %s",
                    execution_id_str,
                    e,
                )
                return {
                    "status": "not_available",
                    "reason": "vm100_transport_error",
                    "detail": str(e),
                }
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    return {
                        "status": "not_available",
                        "reason": "vm100_server_error",
                        "detail": str(e),
                    }
                raise

        async def _get_recent_account_timeline() -> dict:
            """Fetch recent position_closed events for revenge trade detection.

            Uses execution_id as the correlation reference. In V1, we request
            position_closed events with a recent_window scoped to the account;
            VM100 returns the last N events for the same account as this execution.
            Filter by timing is done in Python (compute_revenge_trade_flag).
            """
            try:
                params = {
                    "execution_id": execution_id_str,
                    "event_type": ["position_closed"],
                    "recent_account": True,  # VM100 flag: recent events for this account
                    "limit": 20,             # last 20 closings
                }
                return await vm100.get(
                    "api/journal/internal/events/timeline",
                    params=params,
                )
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(
                    "behavioral_analysis_tool: VM100 recent account timeline transport error for %s: %s",
                    execution_id_str,
                    e,
                )
                return {
                    "status": "not_available",
                    "reason": "vm100_transport_error",
                    "detail": str(e),
                }
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    return {
                        "status": "not_available",
                        "reason": "vm100_server_error",
                        "detail": str(e),
                    }
                raise

        try:
            execution_data, execution_timeline, recent_account_timeline = await asyncio.gather(
                _get_execution(),
                _get_execution_timeline(),
                _get_recent_account_timeline(),
            )
        finally:
            await vm100.close()

        return {
            "execution": execution_data,
            "execution_timeline": execution_timeline,
            "recent_account_timeline": recent_account_timeline,
        }

    def _validate_response(self, data: dict) -> BehavioralAnalysisResult:
        """Validate computed behavioral metrics against BehavioralAnalysisResult contract.

        Raises:
            ContractValidationError: if data doesn't match contract shape.
        """
        try:
            return BehavioralAnalysisResult(**data)
        except Exception as e:  # noqa: BLE001
            raise ContractValidationError(errors=[str(e)], message=str(e)) from e

    def _increment_prometheus(self, result_status: str, duration_s: float) -> None:
        """Increment Prometheus counters with bounded cardinality labels.

        result_status ∈ {success, degraded, transport_error, validation_error}
        """
        try:
            from journal.monitoring.post_trade_metrics import (
                vm107_analytics_tool_calls_total,
                vm107_analytics_tool_duration_seconds,
            )
            vm107_analytics_tool_calls_total.labels(
                tool=TOOL_NAME, result_status=result_status
            ).inc()
            vm107_analytics_tool_duration_seconds.labels(tool=TOOL_NAME).observe(duration_s)
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.debug("behavioral_analysis_tool: Prometheus increment failed: %s", e)

    def run(self, **kwargs: Any) -> BehavioralAnalysisResult:
        """Synchronous entrypoint — runs async _call_vm in a new event loop.

        Args:
            **kwargs: Arguments forwarded to BehavioralAnalysisRequest.
                      Required: execution_id (str or UUID).
                      Optional: scoring_ruleset_version, analysis_context, replay_window.

        Returns:
            BehavioralAnalysisResult Pydantic model.

        Raises:
            ContractValidationError: on request or response validation failure.
        """
        start_time = time.monotonic()
        result_status = "success"

        try:
            request = self._validate_request(kwargs)
        except ContractValidationError:
            result_status = "validation_error"
            self._increment_prometheus(result_status, time.monotonic() - start_time)
            raise

        try:
            combined = asyncio.run(self._call_vm(request))
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            result_status = "transport_error"
            self._increment_prometheus(result_status, time.monotonic() - start_time)
            raise ContractValidationError(errors=[str(e)], message=str(e)) from e

        execution_data = combined.get("execution") or {}
        execution_timeline = combined.get("execution_timeline") or {}
        recent_account_timeline = combined.get("recent_account_timeline") or {}

        score_dict = compute_behavioral_metrics(
            execution_data, execution_timeline, recent_account_timeline
        )

        # Phase 70.5 Plan 06: inject RICH provenance (Decision 5, Pitfall 9 pattern).
        score_dict["provenance"] = ToolProvenance(
            citations=(
                EvidenceCitation(
                    citation_kind="trade",
                    opaque_id=str(request.execution_id),
                    human_label=f"Execution {request.execution_id}",
                ),
            ),
            assumptions=(
                "assumes trades within lookback window represent a stable strategy regime",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.INSUFFICIENT_CONTEXT,
                    detail="lookback window had < N trades",
                ),
            ),
        )

        if score_dict.get("score") is None:
            result_status = "degraded"

        try:
            result = self._validate_response(score_dict)
        except ContractValidationError:
            result_status = "validation_error"
            self._increment_prometheus(result_status, time.monotonic() - start_time)
            raise

        self._increment_prometheus(result_status, time.monotonic() - start_time)
        return result

    async def run_async(self, **kwargs: Any) -> BehavioralAnalysisResult:
        """Async entrypoint for use in asyncio.gather (e.g., AnalyticsService §12).

        Same semantics as run() but does not create a new event loop.
        """
        start_time = time.monotonic()
        result_status = "success"

        try:
            request = self._validate_request(kwargs)
        except ContractValidationError:
            result_status = "validation_error"
            self._increment_prometheus(result_status, time.monotonic() - start_time)
            raise

        combined = await self._call_vm(request)
        execution_data = combined.get("execution") or {}
        execution_timeline = combined.get("execution_timeline") or {}
        recent_account_timeline = combined.get("recent_account_timeline") or {}

        score_dict = compute_behavioral_metrics(
            execution_data, execution_timeline, recent_account_timeline
        )

        # Phase 70.5 Plan 06: inject RICH provenance (Decision 5, Pitfall 9 pattern).
        score_dict["provenance"] = ToolProvenance(
            citations=(
                EvidenceCitation(
                    citation_kind="trade",
                    opaque_id=str(request.execution_id),
                    human_label=f"Execution {request.execution_id}",
                ),
            ),
            assumptions=(
                "assumes trades within lookback window represent a stable strategy regime",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.INSUFFICIENT_CONTEXT,
                    detail="lookback window had < N trades",
                ),
            ),
        )

        if score_dict.get("score") is None:
            result_status = "degraded"

        try:
            result = self._validate_response(score_dict)
        except ContractValidationError:
            result_status = "validation_error"
            self._increment_prometheus(result_status, time.monotonic() - start_time)
            raise

        self._increment_prometheus(result_status, time.monotonic() - start_time)
        return result
