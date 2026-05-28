"""execution_quality_tool — Phase 57 Plan 04.

Deterministic execution quality scoring for a given Execution.

Reads (3-way concurrent fan-out via asyncio.gather):
  - VM100 GET /api/journal/internal/executions/{execution_id}
        — canonical Execution row (entry/exit prices, state, opened_at, closed_at)
  - VM100 GET /api/journal/internal/trade-outcomes/by-execution/{execution_id}
        — Phase 47.4 TradeOutcomeRecord (MAE/MFE/result_r/exit_quality_score)
  - VM100 GET /api/journal/internal/events/timeline?execution_id=...
        — Phase 56 event timeline (order_submitted, fill_received, position_closed)

Computes (pure Python, NO LLM):
  - slippage_pips: fill_received.payload.fill_price vs order_submitted.payload.intended_price
  - exit_efficiency: (exit_price - entry_price) / mfe_distance; > 0.7 = captured ≥70% of MFE
  - hold_duration_vs_atr: execution duration_seconds vs typical ATR window (heuristic)
  - score (0-100) weighted: slippage_pct (40), exit_efficiency (40), duration_appropriate (20)
  - execution_errors: enumerated error codes (OVEREXTENDED_ENTRY, EARLY_EXIT, etc.)

Returns ExecutionQualityResult (fingpt_core.contracts.analytics.execution_quality).

not_available envelope handling (Phase 47.2.1 lock / CONTEXT §3 discipline):
  When outcome endpoint returns 404 OR timeline returns empty events, the tool
  degrades category: score=None, confidence=0, narrative_fragments contains
  'not_available'. NEVER fabricates a score.

Prometheus telemetry (Pattern 26 — bounded cardinality):
  vm107_analytics_tool_calls_total{tool='execution_quality_tool', result_status=...}
  vm107_analytics_tool_duration_seconds{tool='execution_quality_tool'}

result_status values: success | degraded | transport_error | validation_error

Architecture notes (CONTEXT §7):
  - 3-way concurrent fan-out: all 3 calls parameterized from execution_id alone
    → asyncio.gather is correct (no dependency between fetches)
  - FAST_FAIL retry profile per Phase 47.2.1 lock
  - No qdrant_client import
  - No LLM calls (deterministic-Python primary doctrine, CONTEXT §5)
  - Scoring weights: slippage=40 + exit_efficiency=40 + hold_duration=20 = max 100
"""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any

import httpx

from fingpt_core.clients import RetryProfile, VM100Client
from fingpt_core.contracts.analytics.execution_quality import (
    ExecutionQualityPayload,
    ExecutionQualityRequest,
    ExecutionQualityResult,
)
from fingpt_core.contracts.errors import ContractValidationError
from fingpt_core.contracts.evidence import EvidenceCitation
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolProvenance

logger = logging.getLogger("fingpt.tools.execution_quality")

TOOL_NAME = "execution_quality_tool"

# Scoring weights per PLAN.md §task action spec
_SLIPPAGE_WEIGHT = 40       # 40 pts: fill quality vs intended price
_EXIT_EFFICIENCY_WEIGHT = 40  # 40 pts: exit captured % of MFE
_HOLD_DURATION_WEIGHT = 20   # 20 pts: hold duration vs typical ATR window

# Slippage thresholds (pips)
_SLIPPAGE_ACCEPTABLE_PIPS = 2.0   # ≤2.0 pips = acceptable slippage
_SLIPPAGE_SEVERE_PIPS = 5.0       # >5.0 pips = severe slippage

# Exit efficiency threshold
_EXIT_EFFICIENCY_GOOD = 0.70  # ≥70% of MFE captured = efficient exit
_EXIT_EFFICIENCY_MIN = 0.30   # ≥30% = minimal (below = early exit / poor exit)

# Hold duration vs ATR window heuristics
_HOLD_DURATION_TYPICAL_HOURS = 4.0       # 4h = typical M5 ATR observation window
_HOLD_DURATION_ACCEPTABLE_RANGE = (0.5, 4.0)  # 0.5–4.0× typical = acceptable


def _is_not_available(data: dict) -> bool:
    """Return True if data is a not_available envelope or error."""
    return isinstance(data, dict) and (
        data.get("status") == "not_available"
        or data.get("error") is not None
    )


def _extract_event_by_type(events: list[dict], event_type: str) -> dict | None:
    """Return the first event matching event_type, or None."""
    for e in events:
        if e.get("event_type") == event_type:
            return e
    return None


def compute_execution_quality_score(
    execution_data: dict,
    outcome_data: dict,
    timeline_data: dict,
) -> dict:
    """Pure-Python deterministic execution quality scoring.

    Scoring algorithm (per PLAN.md §task action):
      Slippage sub-score (weight=40):
        - fill_received.payload.fill_price vs order_submitted.payload.intended_price
        - slippage ≤ 2.0 pips → 40 pts
        - 2.0–5.0 pips → proportional decay (linear interpolation)
        - > 5.0 pips → 0 pts
        - Events missing → sub-score degraded (20 pts neutral + 'not_available')

      Exit efficiency sub-score (weight=40):
        - exit_efficiency = (exit - entry) / (mfe_distance) for longs
          (adapted for shorts via abs() on numerator)
        - ≥ 0.70 → 40 pts; linear decay below; < 0.30 → 0 pts
        - Outcome missing → sub-score degraded (neutral)

      Hold duration sub-score (weight=20):
        - compare holding_duration_minutes against typical ATR window
        - 0.5–4.0× typical (240 min = 4h M5 window) → 20 pts
        - Outside range → proportional penalty

    Execution errors (enumerated):
      - OVEREXTENDED_ENTRY: entry was after strong displacement (heuristic from
        fill timing vs order submission gap > 5 min)
      - EARLY_EXIT: exit_efficiency < 0.30
      - LATE_EXIT: exit occurred past MFE peak (exit_price < post_mfe_price)
        — detected from Phase 47.4 exit_quality_score < 0.3
      - SLIPPAGE_EXCESSIVE: slippage > _SLIPPAGE_SEVERE_PIPS
      - HOLD_TOO_SHORT: holding_duration_minutes < 0.5× typical window
      - HOLD_TOO_LONG: holding_duration_minutes > 4.0× typical window

    Args:
        execution_data: VM100 Execution row dict (or not_available envelope).
        outcome_data: VM100 TradeOutcomeRecord dict (or not_available envelope).
        timeline_data: VM100 timeline response dict (or not_available envelope).

    Returns:
        dict matching ExecutionQualityResult field shape.
    """
    execution_available = not _is_not_available(execution_data)
    outcome_available = not _is_not_available(outcome_data)
    timeline_events: list[dict] = []
    if not _is_not_available(timeline_data):
        timeline_events = timeline_data.get("events") or []

    # ── Degrade if execution completely unavailable ──────────────────────────
    if not execution_available:
        return {  # PROVENANCE-EXEMPT — internal scoring helper; consumed by _validate_response()
            "score": None,
            "confidence": Decimal("0"),
            "signals": {
                "entry_within_zone": False,
                "exit_at_target": False,
                "stop_respected": False,
                "r_target_achieved": False,
                "early_exit": False,
                "late_exit": False,
                "overextended_entry": False,
                "slippage_acceptable": False,
            },
            "narrative_fragments": [
                "not_available: Execution row unavailable — execution quality cannot be scored",
                "not_available reason: VM100 returned not_available or transport error",
            ],
            "entry_slippage_pips": None,
            "result_r": None,
            "exit_quality_score": None,
            "execution_errors": ["EXECUTION_UNAVAILABLE"],
        }

    # ── Extract execution fields ─────────────────────────────────────────────
    entry_price: float | None = (
        execution_data.get("entry_price")
        or (execution_data.get("metadata") or {}).get("entry_price")
    )
    exit_price: float | None = (
        execution_data.get("exit_price")
        or (execution_data.get("metadata") or {}).get("exit_price")
    )
    direction: str = (
        execution_data.get("direction")
        or (execution_data.get("metadata") or {}).get("direction")
        or "long"  # default to long for heuristic calculation
    )

    # Derive duration from opened_at / closed_at if holding_duration_minutes unavailable
    holding_duration_minutes: float | None = None
    if outcome_available:
        holding_duration_minutes = outcome_data.get("holding_duration_minutes")
    if holding_duration_minutes is None:
        opened_at_str = execution_data.get("opened_at")
        closed_at_str = execution_data.get("closed_at")
        if opened_at_str and closed_at_str:
            try:
                from datetime import datetime
                opened_at = datetime.fromisoformat(opened_at_str.replace("Z", "+00:00"))
                closed_at = datetime.fromisoformat(closed_at_str.replace("Z", "+00:00"))
                holding_duration_minutes = (closed_at - opened_at).total_seconds() / 60.0
            except (ValueError, AttributeError):
                pass

    # ── Extract outcome fields ───────────────────────────────────────────────
    mae: float | None = outcome_data.get("mae") if outcome_available else None
    mfe: float | None = outcome_data.get("mfe") if outcome_available else None
    result_r_raw: float | None = outcome_data.get("result_r") if outcome_available else None
    exit_quality_score_raw: float | None = (
        outcome_data.get("exit_quality_score") if outcome_available else None
    )
    outcome_entry_price: float | None = (
        outcome_data.get("entry_price") if outcome_available else None
    )
    outcome_exit_price: float | None = (
        outcome_data.get("exit_price") if outcome_available else None
    )

    # Use outcome prices as ground truth if execution prices missing
    if entry_price is None:
        entry_price = outcome_entry_price
    if exit_price is None:
        exit_price = outcome_exit_price

    # ── Extract timeline events ──────────────────────────────────────────────
    order_submitted = _extract_event_by_type(timeline_events, "order_submitted")
    fill_received = _extract_event_by_type(timeline_events, "fill_received")
    position_closed = _extract_event_by_type(timeline_events, "position_closed")

    # ── Sub-score 1: Slippage (weight=40) ────────────────────────────────────
    slippage_pips: float | None = None
    slippage_score = _SLIPPAGE_WEIGHT // 2  # neutral=20 when data missing
    slippage_available = False
    slippage_fragments: list[str] = []
    execution_errors: list[str] = []

    if order_submitted and fill_received:
        order_payload = order_submitted.get("payload") or {}
        fill_payload = fill_received.get("payload") or {}
        intended_price = order_payload.get("intended_price") or order_payload.get("entry_price")
        fill_price = fill_payload.get("fill_price") or fill_payload.get("price")

        if intended_price is not None and fill_price is not None:
            # Slippage = absolute difference (in pips, 4dp instruments: × 10000)
            raw_diff = abs(float(fill_price) - float(intended_price))
            # Convert price difference to pips (for Forex 5dp: × 100000; 4dp: × 10000)
            # Heuristic: if diff < 0.001, assume 5dp instrument (Forex); else 4dp
            if raw_diff < 0.001:
                slippage_pips = raw_diff * 100000  # 5dp Forex
            else:
                slippage_pips = raw_diff * 10000   # 4dp
            slippage_available = True

            if slippage_pips <= _SLIPPAGE_ACCEPTABLE_PIPS:
                slippage_score = _SLIPPAGE_WEIGHT  # full 40 pts
                slippage_fragments.append(
                    f"Slippage {slippage_pips:.1f} pips — within acceptable threshold "
                    f"(≤{_SLIPPAGE_ACCEPTABLE_PIPS:.0f} pips)"
                )
            elif slippage_pips <= _SLIPPAGE_SEVERE_PIPS:
                # Linear decay from 40 to 0 between 2.0 and 5.0 pips
                decay = (slippage_pips - _SLIPPAGE_ACCEPTABLE_PIPS) / (
                    _SLIPPAGE_SEVERE_PIPS - _SLIPPAGE_ACCEPTABLE_PIPS
                )
                slippage_score = int(_SLIPPAGE_WEIGHT * (1.0 - decay))
                slippage_fragments.append(
                    f"Slippage {slippage_pips:.1f} pips above intended; "
                    f"partially penalised ({slippage_score}/{_SLIPPAGE_WEIGHT} pts)"
                )
            else:
                slippage_score = 0
                execution_errors.append("SLIPPAGE_EXCESSIVE")
                slippage_fragments.append(
                    f"Slippage {slippage_pips:.1f} pips exceeds severe threshold "
                    f"(>{_SLIPPAGE_SEVERE_PIPS:.0f} pips) — fill quality poor"
                )

            # OVEREXTENDED_ENTRY: fill arrived >5 min after order submission
            order_time = order_submitted.get("occurred_at") or order_submitted.get("timestamp")
            fill_time = fill_received.get("occurred_at") or fill_received.get("timestamp")
            if order_time and fill_time:
                try:
                    from datetime import datetime
                    ot = datetime.fromisoformat(str(order_time).replace("Z", "+00:00"))
                    ft = datetime.fromisoformat(str(fill_time).replace("Z", "+00:00"))
                    fill_gap_minutes = (ft - ot).total_seconds() / 60.0
                    if fill_gap_minutes > 5.0:
                        execution_errors.append("OVEREXTENDED_ENTRY")
                        slippage_fragments.append(
                            f"Fill received {fill_gap_minutes:.1f} min after order submission — "
                            "possible overextended entry or delayed broker execution"
                        )
                except (ValueError, AttributeError):
                    pass
        else:
            slippage_fragments.append(
                "not_available: order_submitted/fill_received events present "
                "but intended_price or fill_price missing from payload"
            )
    elif not timeline_events:
        slippage_fragments.append(
            "not_available: event timeline empty — slippage cannot be computed"
        )
    else:
        slippage_fragments.append(
            "not_available: fill_received or order_submitted event missing from timeline; "
            f"available event types: {sorted({e.get('event_type') for e in timeline_events})}"
        )

    # ── Sub-score 2: Exit efficiency (weight=40) ─────────────────────────────
    exit_score = _EXIT_EFFICIENCY_WEIGHT // 2  # neutral=20 when data missing
    exit_efficiency: float | None = None
    exit_fragments: list[str] = []

    if outcome_available and mfe is not None and entry_price is not None and exit_price is not None:
        entry_f = float(entry_price)
        exit_f = float(exit_price)
        mfe_f = float(mfe)

        # mfe from TradeOutcomeRecord is already the favorable excursion distance
        # (Phase 47.4: mfe is the max favorable movement from entry in price terms)
        # For longs: mfe > 0; for shorts: mfe > 0 (absolute value)
        if abs(mfe_f) > 0.00001:
            # Exit efficiency: how much of the MFE did the exit capture?
            if direction.lower() == "long":
                captured = exit_f - entry_f
            else:
                captured = entry_f - exit_f

            exit_efficiency = captured / abs(mfe_f)

            if exit_efficiency >= _EXIT_EFFICIENCY_GOOD:
                exit_score = _EXIT_EFFICIENCY_WEIGHT  # 40 pts
                exit_fragments.append(
                    f"Exit captured {exit_efficiency:.0%} of MFE — efficient exit "
                    f"(≥{_EXIT_EFFICIENCY_GOOD:.0%} threshold)"
                )
            elif exit_efficiency >= _EXIT_EFFICIENCY_MIN:
                # Linear decay from 40 to 0 between 0.30 and 0.70
                decay = (_EXIT_EFFICIENCY_GOOD - exit_efficiency) / (
                    _EXIT_EFFICIENCY_GOOD - _EXIT_EFFICIENCY_MIN
                )
                exit_score = int(_EXIT_EFFICIENCY_WEIGHT * (1.0 - decay))
                exit_fragments.append(
                    f"Exit captured {exit_efficiency:.0%} of MFE "
                    f"({exit_score}/{_EXIT_EFFICIENCY_WEIGHT} pts)"
                )
            else:
                exit_score = 0
                execution_errors.append("EARLY_EXIT")
                exit_fragments.append(
                    f"Exit captured only {exit_efficiency:.0%} of MFE — "
                    "premature exit (< 30% of favorable move captured)"
                )
        else:
            # MFE is effectively zero — trade ended immediately or flat
            exit_score = _EXIT_EFFICIENCY_WEIGHT // 2  # neutral
            exit_fragments.append(
                "MFE near zero — trade did not develop favorable movement; "
                "exit efficiency undeterminable"
            )
    elif not outcome_available:
        exit_fragments.append(
            "not_available: TradeOutcomeRecord unavailable — exit efficiency cannot be scored"
        )
    else:
        exit_fragments.append(
            "not_available: entry_price, exit_price, or MFE missing from outcome data"
        )

    # Detect LATE_EXIT from exit_quality_score (Phase 47.4 CF-4)
    if exit_quality_score_raw is not None and float(exit_quality_score_raw) < 0.30:
        if "EARLY_EXIT" not in execution_errors:  # avoid double-flagging
            execution_errors.append("LATE_EXIT")
            exit_fragments.append(
                f"Phase 47.4 exit_quality_score={exit_quality_score_raw:.2f} < 0.30 — "
                "position held past MFE peak (gave back profits)"
            )

    # ── Sub-score 3: Hold duration vs ATR window (weight=20) ─────────────────
    hold_score = _HOLD_DURATION_WEIGHT // 2  # neutral=10 when data missing
    hold_fragments: list[str] = []
    typical_duration_minutes = _HOLD_DURATION_TYPICAL_HOURS * 60  # 240 min

    if holding_duration_minutes is not None:
        min_ok = _HOLD_DURATION_ACCEPTABLE_RANGE[0] * typical_duration_minutes
        max_ok = _HOLD_DURATION_ACCEPTABLE_RANGE[1] * typical_duration_minutes
        ratio = holding_duration_minutes / typical_duration_minutes

        if min_ok <= holding_duration_minutes <= max_ok:
            hold_score = _HOLD_DURATION_WEIGHT  # 20 pts
            hold_fragments.append(
                f"Hold duration {holding_duration_minutes:.0f} min = "
                f"{ratio:.1f}× typical ATR window — appropriate"
            )
        elif holding_duration_minutes < min_ok:
            hold_score = 0
            execution_errors.append("HOLD_TOO_SHORT")
            hold_fragments.append(
                f"Hold duration {holding_duration_minutes:.0f} min = "
                f"{ratio:.1f}× typical ATR window — too short (< 0.5× typical)"
            )
        else:
            hold_score = int(_HOLD_DURATION_WEIGHT * max(0.0, 1.0 - (ratio - 4.0) / 4.0))
            hold_score = max(0, hold_score)
            if ratio > 8.0:
                execution_errors.append("HOLD_TOO_LONG")
            hold_fragments.append(
                f"Hold duration {holding_duration_minutes:.0f} min = "
                f"{ratio:.1f}× typical ATR window — extended hold "
                f"({hold_score}/{_HOLD_DURATION_WEIGHT} pts)"
            )
    else:
        hold_fragments.append(
            "not_available: hold duration unavailable — duration scoring neutral"
        )

    # ── Aggregate score ───────────────────────────────────────────────────────
    score_sum = slippage_score + exit_score + hold_score
    score = Decimal(str(min(100, score_sum)))

    # Confidence: full when all 3 data sources available; degraded otherwise
    data_sources_available = sum([
        slippage_available,         # fill events present and priced
        outcome_available,          # TradeOutcomeRecord available
        bool(timeline_events),      # timeline events present
    ])
    if data_sources_available == 3:
        confidence = Decimal("100")
    elif data_sources_available == 2:
        confidence = Decimal("70")
    elif data_sources_available == 1:
        confidence = Decimal("40")
    else:
        confidence = Decimal("0")
        score = None  # no data sources → degrade score

    # ── Signals ──────────────────────────────────────────────────────────────
    signals = {
        "entry_within_zone": (
            slippage_pips is not None and slippage_pips <= _SLIPPAGE_ACCEPTABLE_PIPS
        ),
        "exit_at_target": (
            exit_efficiency is not None and exit_efficiency >= _EXIT_EFFICIENCY_GOOD
        ),
        "stop_respected": True,  # V1: default True; Phase 60+ wires stop_loss_moved events
        "r_target_achieved": (
            result_r_raw is not None and float(result_r_raw) >= 1.0
        ),
        "early_exit": "EARLY_EXIT" in execution_errors,
        "late_exit": "LATE_EXIT" in execution_errors,
        "overextended_entry": "OVEREXTENDED_ENTRY" in execution_errors,
        "slippage_acceptable": (
            slippage_pips is None or slippage_pips <= _SLIPPAGE_ACCEPTABLE_PIPS
        ),
    }

    # ── Primary narrative fragment (PLAN.md example template) ────────────────
    narrative_fragments: list[str] = []

    if score is not None:
        # PLAN.md example: 'Slippage 2.1 pips above intended; exit captured 67% of MFE;
        #                   hold duration 1.2x typical ATR window'
        slippage_display = (
            f"Slippage {slippage_pips:.1f} pips" if slippage_pips is not None
            else "Slippage: not_available"
        )
        exit_display = (
            f"exit captured {exit_efficiency:.0%} of MFE" if exit_efficiency is not None
            else "exit efficiency: not_available"
        )
        hold_display = (
            f"hold duration {holding_duration_minutes / typical_duration_minutes:.1f}x typical ATR window"
            if holding_duration_minutes is not None
            else "hold duration: not_available"
        )
        narrative_fragments.append(
            f"Execution quality = {score}/100: {slippage_display}; "
            f"{exit_display}; {hold_display}"
        )
    else:
        narrative_fragments.append(
            "not_available: Unable to score — all data sources unavailable "
            "(execution row, outcome record, and event timeline all missing)"
        )

    narrative_fragments.extend(slippage_fragments)
    narrative_fragments.extend(exit_fragments)
    narrative_fragments.extend(hold_fragments)

    if execution_errors:
        narrative_fragments.append(
            f"Execution errors detected: {', '.join(execution_errors)}"
        )

    return {  # PROVENANCE-EXEMPT — internal scoring helper; consumed by _validate_response()
        "score": score,
        "confidence": confidence,
        "signals": signals,
        "narrative_fragments": narrative_fragments,
        "entry_slippage_pips": (
            Decimal(str(round(slippage_pips, 2))) if slippage_pips is not None else None
        ),
        "result_r": (
            Decimal(str(round(float(result_r_raw), 4))) if result_r_raw is not None else None
        ),
        "exit_quality_score": (
            Decimal(str(round(float(exit_quality_score_raw), 2)))
            if exit_quality_score_raw is not None else None
        ),
        "execution_errors": execution_errors,
    }


class ExecutionQualityTool:
    """VM107 analytics tool: deterministic execution quality scoring.

    Implements the ContractTool pattern (validate-request → call-vm → validate-response)
    as a standalone class (no Agent context required) so it can be called directly
    by AnalyticsService in Phase 57-09 and tested without the agent framework.

    Reads (3-way concurrent fan-out via asyncio.gather):
      - VM100 GET /api/journal/internal/executions/{execution_id}
      - VM100 GET /api/journal/internal/trade-outcomes/by-execution/{execution_id}
      - VM100 GET /api/journal/internal/events/timeline?execution_id=...

    Computes:
      - Slippage from fill_received vs order_submitted events (weight=40)
      - Exit efficiency from MFE capture ratio (weight=40)
      - Hold duration vs ATR window heuristic (weight=20)
      - ExecutionQualityResult with score, confidence, signals, narrative_fragments

    Usage:
        tool = ExecutionQualityTool()
        result = tool.run(execution_id="...", scoring_ruleset_version="1.0.0")

    The result is an ExecutionQualityResult Pydantic model.
    """

    def _validate_request(self, args: dict) -> ExecutionQualityRequest:
        """Validate args against ExecutionQualityRequest contract.

        Raises:
            ContractValidationError: if args don't match contract shape.
        """
        try:
            return ExecutionQualityRequest(**args)
        except Exception as e:  # noqa: BLE001
            raise ContractValidationError(errors=[str(e)], message=str(e)) from e

    async def _call_vm(self, request: ExecutionQualityRequest) -> dict:
        """3-way concurrent fan-out to VM100 (execution + outcome + timeline).

        All 3 calls are parameterized from execution_id alone — no dependency
        between fetches — so asyncio.gather is correct here (unlike regime/
        liquidity/compression tools where instrument must come from Execution
        before VM102 can be queried).

        Uses FAST_FAIL retry profile. On transport failure, synthesizes a
        not_available envelope for the affected data source.

        Returns:
            dict with keys 'execution', 'outcome', 'timeline'.
        """
        vm100 = VM100Client(profile=RetryProfile.FAST_FAIL)

        execution_id_str = str(request.execution_id)
        event_types = ["order_submitted", "fill_received", "position_closed"]

        async def _get_execution() -> dict:
            try:
                return await vm100.get(
                    f"api/journal/internal/executions/{execution_id_str}"
                )
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(
                    "execution_quality_tool: VM100 transport error for execution %s: %s",
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

        async def _get_outcome() -> dict:
            try:
                return await vm100.get(
                    f"api/journal/internal/trade-outcomes/by-execution/{execution_id_str}"
                )
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(
                    "execution_quality_tool: VM100 transport error for outcome %s: %s",
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
                    # Outcome not yet computed — graceful degradation
                    return {
                        "error": "trade_outcome_not_found",
                        "execution_id": execution_id_str,
                    }
                if e.response.status_code >= 500:
                    return {
                        "status": "not_available",
                        "reason": "vm100_server_error",
                        "detail": str(e),
                    }
                raise

        async def _get_timeline() -> dict:
            try:
                params = {
                    "execution_id": execution_id_str,
                    "event_type": event_types,
                    "limit": 50,
                }
                return await vm100.get(
                    "api/journal/internal/events/timeline",
                    params=params,
                )
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(
                    "execution_quality_tool: VM100 timeline transport error for %s: %s",
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
            execution_data, outcome_data, timeline_data = await asyncio.gather(
                _get_execution(),
                _get_outcome(),
                _get_timeline(),
            )
        finally:
            await vm100.close()

        return {
            "execution": execution_data,
            "outcome": outcome_data,
            "timeline": timeline_data,
        }

    def _validate_response(self, data: dict) -> ExecutionQualityResult:
        """Validate computed scoring result against ExecutionQualityResult contract.

        Raises:
            ContractValidationError: if data doesn't match contract shape.
        """
        try:
            return ExecutionQualityResult(**data)
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
            logger.debug("execution_quality_tool: Prometheus increment failed: %s", e)

    def run(self, **kwargs: Any) -> ExecutionQualityResult:
        """Synchronous entrypoint — runs async _call_vm in a new event loop.

        Args:
            **kwargs: Arguments forwarded to ExecutionQualityRequest.
                      Required: execution_id (str or UUID).
                      Optional: scoring_ruleset_version, analysis_context, replay_window.

        Returns:
            ExecutionQualityResult Pydantic model.

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
        outcome_data = combined.get("outcome") or {}
        timeline_data = combined.get("timeline") or {}

        score_dict = compute_execution_quality_score(
            execution_data, outcome_data, timeline_data
        )

        # Phase 70.5 Plan 06: inject RICH provenance (Decision 5, Pitfall 9 pattern).
        score_dict["provenance"] = ToolProvenance(
            citations=(
                EvidenceCitation(
                    citation_kind="trade",
                    opaque_id=str(request.execution_id),
                    human_label=f"Execution {request.execution_id}",
                ),
                EvidenceCitation(
                    citation_kind="event",
                    opaque_id=f"fill_received:{request.execution_id}",
                    human_label="Fill received event",
                ),
            ),
            assumptions=(
                "assumes broker fill timestamps are server-authoritative (no client-clock skew)",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM100 trades API timed out",
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

    async def run_async(self, **kwargs: Any) -> ExecutionQualityResult:
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
        outcome_data = combined.get("outcome") or {}
        timeline_data = combined.get("timeline") or {}

        score_dict = compute_execution_quality_score(
            execution_data, outcome_data, timeline_data
        )

        # Phase 70.5 Plan 06: inject RICH provenance (Decision 5, Pitfall 9 pattern).
        score_dict["provenance"] = ToolProvenance(
            citations=(
                EvidenceCitation(
                    citation_kind="trade",
                    opaque_id=str(request.execution_id),
                    human_label=f"Execution {request.execution_id}",
                ),
                EvidenceCitation(
                    citation_kind="event",
                    opaque_id=f"fill_received:{request.execution_id}",
                    human_label="Fill received event",
                ),
            ),
            assumptions=(
                "assumes broker fill timestamps are server-authoritative (no client-clock skew)",
            ),
            declared_failure_modes=(
                FailureMode(
                    code=FailureModeCode.UPSTREAM_TIMEOUT,
                    detail="VM100 trades API timed out",
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
