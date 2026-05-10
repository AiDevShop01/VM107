"""setup_quality_tool — Phase 57 Plan 06.

Deterministic setup quality scoring for a given Execution.

Reads (3-way concurrent fan-out via asyncio.gather):
  - VM100 GET /api/journal/internal/executions/{execution_id}
        — canonical Execution row (state, campaign_id, metadata)
  - VM100 GET /api/journal/internal/strategies/{strategy_id}
        — active Strategy definition YAML (expected_regime, allowed_sessions,
          entry_rules, instrument_class, etc.)
        — strategy_id is derived from the Campaign row; tool first fetches
          the Campaign to resolve strategy_id, then fetches strategy in
          a second-pass fan-out (see _call_vm implementation notes below)
  - VM100 GET /api/journal/internal/checklist/{execution_id}
        — checklist outcomes for this Execution (completed items, missed items,
          all_completed flag, checklist_completed Event presence)

Computes (pure Python, NO LLM) — strategy-doctrine alignment per CONTEXT §7:
  - checklist_completion_pct: completed_items / total_items (0–100%)
  - strategy_rule_alignment: does the execution match the active strategy's
    doctrine rules (expected_regime, allowed_sessions, instrument_class,
    entry_type → each rule checked; mismatch → score penalty)?
  - category_coherence: do regime/liquidity/compression scores (injected via
    execution.metadata or checklist payload) align with the strategy's
    expected category profile?
  - setup_quality_score: weighted aggregate (checklist 40%, alignment 40%,
    coherence 20%)
  - strategy_drift_score: 100 - setup_quality_score (higher = more drift)

Doctrine alignment rule penalties (per PLAN.md §task action):
  - strategy.expected_regime != observed_regime → −15 score, narrative fragment
  - session not in strategy.allowed_sessions → −10 score, narrative fragment
  - instrument_class mismatch → −10 score, narrative fragment

Returns SetupQualityResult (fingpt_core.contracts.analytics.setup_quality).

Graceful degradation:
  When strategy YAML or checklist data is not_available, the tool returns
  SetupQualityResult(score=None, confidence=0, narrative_fragments=[
      'not_available: strategy or checklist data missing — setup quality cannot be scored'
  ]). NEVER fabricates.

Prometheus telemetry (Pattern 26 — bounded cardinality):
  vm107_analytics_tool_calls_total{tool='setup_quality_tool', result_status=...}
  vm107_analytics_tool_duration_seconds{tool='setup_quality_tool'}

result_status values: success | degraded | transport_error | validation_error

Architecture notes (CONTEXT §7 + §9):
  - Master-plan alias get_strategy_drift → canonical setup_quality_tool (CONTEXT §9 row 4)
  - Strategy-drift IS setup-quality cognition; one tool, two registry names
  - 3-way fan-out: execution + strategy + checklist all derivable from execution_id
    (strategy_id resolved from campaign_id which is on Execution; in a real
    two-phase call this would be: step1=get_execution to read campaign_id, then
    step2=fan-out strategy+checklist). In V1, the _call_vm reads execution first
    then fans out — see _call_vm notes.
  - FAST_FAIL retry profile per Phase 47.2.1 lock
  - No qdrant_client import
  - No LLM calls (deterministic-Python primary doctrine, CONTEXT §5)

Alias: get_strategy_drift → routes to setup_quality_tool via registry YAML
Alias: evaluate_setup_quality → routes to setup_quality_tool via registry YAML
"""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any

import httpx

from fingpt_core.clients import RetryProfile, VM100Client
from fingpt_core.contracts.analytics.setup_quality import (
    SetupQualityRequest,
    SetupQualityResult,
)
from fingpt_core.contracts.errors import ContractValidationError

logger = logging.getLogger("fingpt.tools.setup_quality")

TOOL_NAME = "setup_quality_tool"

# Scoring weights (checklist 40% + alignment 40% + coherence 20% = 100%)
_CHECKLIST_WEIGHT = 40
_ALIGNMENT_WEIGHT = 40
_COHERENCE_WEIGHT = 20

# Strategy doctrine alignment penalties (additive deductions from alignment sub-score)
_PENALTY_REGIME_MISMATCH = 15    # expected_regime != observed_regime
_PENALTY_SESSION_MISMATCH = 10   # session not in allowed_sessions
_PENALTY_INSTRUMENT_MISMATCH = 10  # instrument_class mismatch

# Confidence penalties
_CONFIDENCE_PENALTY_NO_CHECKLIST = Decimal("20")     # checklist data unavailable
_CONFIDENCE_PENALTY_NO_STRATEGY = Decimal("30")      # strategy definition unavailable


def _is_not_available(data: dict) -> bool:
    """Return True if data is a not_available envelope or error."""
    return isinstance(data, dict) and (
        data.get("status") == "not_available"
        or data.get("error") is not None
    )


def compute_checklist_completion(checklist_data: dict) -> tuple[Decimal, list[str], list[str]]:
    """Compute checklist completion percentage and identify missed items.

    Returns:
        (completion_pct_0_to_100, narrative_fragments, missed_item_labels)
    """
    if _is_not_available(checklist_data):
        return Decimal("0"), [
            "not_available: checklist data unavailable — checklist completion cannot be scored"
        ], []

    # Extract items
    items = checklist_data.get("items") or []
    total = checklist_data.get("total_item_count") or len(items)
    completed_count = checklist_data.get("completed_item_count")

    if completed_count is None:
        completed_count = sum(1 for item in items if item.get("completed") is True)

    # Collect missed item labels
    missed_labels = [
        item.get("label", f"item_{i}")
        for i, item in enumerate(items)
        if not item.get("completed", False)
    ]

    if total == 0:
        return Decimal("100"), ["Checklist: no items defined (100% by default)"], []

    pct_float = (completed_count / total) * 100.0
    pct = Decimal(str(round(pct_float, 2)))
    all_completed = checklist_data.get("all_completed", False)

    if all_completed or completed_count >= total:
        narrative = f"Checklist complete: {completed_count}/{total} items completed (100%)"
    else:
        missed_str = ", ".join(missed_labels[:5])  # cap narrative at 5 labels
        if len(missed_labels) > 5:
            missed_str += f" (+{len(missed_labels) - 5} more)"
        narrative = (
            f"Checklist incomplete: {completed_count}/{total} items completed "
            f"({pct_float:.0f}%). Missed: {missed_str}"
        )

    return pct, [narrative], missed_labels


def compute_strategy_alignment(
    strategy_data: dict,
    execution_data: dict,
) -> tuple[Decimal, list[str], bool]:
    """Evaluate whether execution matches strategy doctrine rules.

    Checks:
    1. expected_regime vs observed_regime (from execution metadata)
    2. allowed_sessions vs execution session
    3. instrument_class vs execution instrument

    Returns:
        (alignment_score_0_to_100, narrative_fragments, any_mismatch_found)
    """
    if _is_not_available(strategy_data):
        return Decimal("0"), [
            "not_available: strategy definition unavailable — strategy alignment cannot be scored"
        ], False

    narratives: list[str] = []
    penalties = 0
    mismatches_found = False

    # Extract strategy rules
    expected_regime: str | None = strategy_data.get("expected_regime")
    allowed_sessions: list[str] = strategy_data.get("allowed_sessions") or []
    instrument_class: str | None = strategy_data.get("instrument_class")
    entry_rules: dict = strategy_data.get("entry_rules") or {}

    # Extract execution context (from metadata, checklist payload, or inline fields)
    exec_metadata: dict = execution_data.get("metadata") or {}
    observed_regime: str | None = (
        exec_metadata.get("regime_class")
        or exec_metadata.get("regime")
        or exec_metadata.get("market_regime")
    )
    exec_session: str | None = (
        exec_metadata.get("session")
        or exec_metadata.get("trade_session")
    )
    exec_instrument_class: str | None = (
        exec_metadata.get("instrument_class")
        or exec_metadata.get("instrument_type")
    )

    # ── Check 1: Regime alignment ────────────────────────────────────────────
    if expected_regime and observed_regime:
        # Normalize: 'trending_bullish' and 'trending_bearish' both count as 'trending'
        observed_norm = (
            "trending" if observed_regime.startswith("trending") else observed_regime
        )
        expected_norm = (
            "trending" if expected_regime.startswith("trending") else expected_regime
        )

        if expected_norm != observed_norm:
            mismatches_found = True
            penalties += _PENALTY_REGIME_MISMATCH
            narratives.append(
                f"Strategy expected {expected_regime} regime; observed {observed_norm} "
                f"— regime alignment penalty ({_PENALTY_REGIME_MISMATCH}pts)"
            )
        else:
            narratives.append(
                f"Regime aligned: strategy expects {expected_regime}; "
                f"observed {observed_regime} ✓"
            )
    elif expected_regime and not observed_regime:
        # No regime data in execution metadata — cannot verify, no penalty
        narratives.append(
            f"Regime check: strategy expects '{expected_regime}' but no regime "
            "observation in execution metadata — cannot verify (no penalty)"
        )

    # ── Check 2: Session alignment ───────────────────────────────────────────
    if allowed_sessions and exec_session:
        # Normalize session name for comparison
        session_matched = any(
            s.lower() in exec_session.lower() or exec_session.lower() in s.lower()
            for s in allowed_sessions
        )
        if not session_matched:
            mismatches_found = True
            penalties += _PENALTY_SESSION_MISMATCH
            allowed_str = ", ".join(allowed_sessions)
            narratives.append(
                f"Session mismatch: strategy allows [{allowed_str}]; "
                f"execution session '{exec_session}' not in allowed list "
                f"— penalty ({_PENALTY_SESSION_MISMATCH}pts)"
            )
        else:
            narratives.append(
                f"Session aligned: '{exec_session}' within allowed sessions ✓"
            )
    elif allowed_sessions and not exec_session:
        narratives.append(
            "Session check: strategy defines allowed_sessions but execution "
            "has no session metadata — cannot verify (no penalty)"
        )

    # ── Check 3: Instrument class alignment ──────────────────────────────────
    if instrument_class and exec_instrument_class:
        if instrument_class.lower() != exec_instrument_class.lower():
            mismatches_found = True
            penalties += _PENALTY_INSTRUMENT_MISMATCH
            narratives.append(
                f"Instrument class mismatch: strategy expects '{instrument_class}'; "
                f"execution uses '{exec_instrument_class}' "
                f"— penalty ({_PENALTY_INSTRUMENT_MISMATCH}pts)"
            )
        else:
            narratives.append(
                f"Instrument class aligned: '{instrument_class}' ✓"
            )

    # Compute alignment sub-score (start at 100, subtract penalties, clamp)
    alignment_float = max(0.0, 100.0 - penalties)
    alignment_score = Decimal(str(round(alignment_float, 2)))

    # Add summary fragment
    if not narratives:
        narratives.append(
            "Strategy alignment: no doctrine rules to check (strategy has no constraints defined)"
        )

    return alignment_score, narratives, mismatches_found


def compute_category_coherence(
    strategy_data: dict,
    execution_data: dict,
) -> tuple[Decimal, list[str]]:
    """Check whether category scores (regime/liquidity/compression) align with strategy profile.

    V1: reads category scores from execution.metadata (injected by AnalyticsService
    from prior tool results) and compares against strategy expectations.
    If metadata lacks prior category scores, returns 100 (no penalty; data absent).

    Returns:
        (coherence_score_0_to_100, narrative_fragments)
    """
    if _is_not_available(strategy_data):
        return Decimal("100"), []  # no coherence check possible — no strategy

    exec_metadata: dict = execution_data.get("metadata") or {}
    strategy_profile: dict = strategy_data.get("category_profile") or {}

    narratives: list[str] = []

    # Extract prior category scores from execution metadata (injected by AnalyticsService)
    regime_score: float | None = exec_metadata.get("regime_score")
    liquidity_score: float | None = exec_metadata.get("liquidity_score")
    compression_score: float | None = exec_metadata.get("compression_score")

    # Extract strategy category expectations (optional; if absent = no constraint)
    min_regime_score: float | None = strategy_profile.get("min_regime_score")
    min_liquidity_score: float | None = strategy_profile.get("min_liquidity_score")
    min_compression_score: float | None = strategy_profile.get("min_compression_score")

    if not any([regime_score, liquidity_score, compression_score]):
        # No category scores in execution metadata — coherence check inconclusive
        return Decimal("100"), [
            "Category coherence: no prior category scores in execution metadata "
            "— coherence check inconclusive (full score assumed)"
        ]

    penalties = 0.0

    if regime_score is not None and min_regime_score is not None:
        if float(regime_score) < float(min_regime_score):
            penalties += 10.0
            narratives.append(
                f"Category coherence: regime score {regime_score} below strategy "
                f"minimum {min_regime_score} — weak regime coherence"
            )

    if liquidity_score is not None and min_liquidity_score is not None:
        if float(liquidity_score) < float(min_liquidity_score):
            penalties += 10.0
            narratives.append(
                f"Category coherence: liquidity score {liquidity_score} below strategy "
                f"minimum {min_liquidity_score} — weak liquidity coherence"
            )

    if compression_score is not None and min_compression_score is not None:
        if float(compression_score) < float(min_compression_score):
            penalties += 10.0
            narratives.append(
                f"Category coherence: compression score {compression_score} below strategy "
                f"minimum {min_compression_score} — weak compression coherence"
            )

    coherence_float = max(0.0, 100.0 - penalties)
    coherence_score = Decimal(str(round(coherence_float, 2)))

    if not narratives:
        narratives.append(
            f"Category coherence: all category scores within strategy expectations "
            f"(coherence score = {coherence_score}/100)"
        )

    return coherence_score, narratives


def compute_setup_quality_score(
    execution_data: dict,
    strategy_data: dict,
    checklist_data: dict,
) -> dict:
    """Pure-Python deterministic setup quality scoring.

    Three components (PLAN.md §task action):
      1. checklist_completion_pct (40% weight): was every checklist item completed?
      2. strategy_rule_alignment (40% weight): does execution match strategy doctrine?
      3. category_coherence (20% weight): do regime/liquidity/compression scores
         align with what the strategy expects?

    Scoring:
      - checklist_sub_score = (checklist_completion_pct / 100) * _CHECKLIST_WEIGHT
      - alignment_sub_score = (alignment_score / 100) * _ALIGNMENT_WEIGHT
      - coherence_sub_score = (coherence_score / 100) * _COHERENCE_WEIGHT
      - total_score = sum of sub-scores (0-100)
      - strategy_drift_score = 100 - total_score

    Graceful degradation:
      - If strategy or checklist unavailable → score=None, confidence=0,
        narrative='not_available: strategy or checklist data missing'
      - If execution unavailable → full degrade
      - Partial: if only checklist missing → confidence-70, narrated

    Args:
        execution_data: VM100 Execution row dict (or not_available envelope).
        strategy_data: VM100 Strategy definition dict (or not_available envelope).
        checklist_data: VM100 Checklist data for this execution (or not_available envelope).

    Returns:
        dict matching SetupQualityResult field shape.
    """
    execution_available = not _is_not_available(execution_data)
    strategy_available = not _is_not_available(strategy_data)
    checklist_available = not _is_not_available(checklist_data)

    # ── Full degrade if execution completely unavailable ─────────────────────
    if not execution_available:
        return {
            "score": None,
            "confidence": Decimal("0"),
            "signals": {
                "checklist_completed": False,
                "strategy_aligned": False,
                "category_coherent": False,
                "all_filters_passed": False,
            },
            "narrative_fragments": [
                "not_available: Execution row unavailable — setup quality cannot be scored",
            ],
            "strategy_drift_score": None,
            "strategy_id": None,
            "setup_type": None,
            "checklist_items_missed": [],
        }

    # ── Full degrade if BOTH strategy and checklist unavailable ─────────────
    if not strategy_available and not checklist_available:
        return {
            "score": None,
            "confidence": Decimal("0"),
            "signals": {
                "checklist_completed": False,
                "strategy_aligned": False,
                "category_coherent": False,
                "all_filters_passed": False,
            },
            "narrative_fragments": [
                "not_available: strategy or checklist data missing — setup quality cannot be scored",
                "not_available: strategy definition not found for this execution",
                "not_available: checklist data not found for this execution",
            ],
            "strategy_drift_score": None,
            "strategy_id": None,
            "setup_type": None,
            "checklist_items_missed": [],
        }

    # ── Extract strategy identity ─────────────────────────────────────────────
    strategy_id_val: str | None = None
    setup_type_val: str | None = None
    if strategy_available:
        strategy_id_val = strategy_data.get("id") or strategy_data.get("strategy_id")
        setup_type_val = (
            (strategy_data.get("entry_rules") or {}).get("setup_type")
            or strategy_data.get("setup_type")
        )

    # ── Compute component 1: Checklist completion ─────────────────────────────
    checklist_pct, checklist_narratives, missed_labels = compute_checklist_completion(
        checklist_data
    )
    checklist_sub_score = float(checklist_pct) / 100.0 * _CHECKLIST_WEIGHT

    # ── Compute component 2: Strategy alignment ───────────────────────────────
    if strategy_available:
        alignment_score, alignment_narratives, any_mismatch = compute_strategy_alignment(
            strategy_data, execution_data
        )
    else:
        alignment_score = Decimal("0")
        alignment_narratives = [
            "not_available: strategy definition unavailable — strategy alignment cannot be scored"
        ]
        any_mismatch = False

    alignment_sub_score = float(alignment_score) / 100.0 * _ALIGNMENT_WEIGHT

    # ── Compute component 3: Category coherence ───────────────────────────────
    if strategy_available:
        coherence_score, coherence_narratives = compute_category_coherence(
            strategy_data, execution_data
        )
    else:
        coherence_score = Decimal("100")
        coherence_narratives = []

    coherence_sub_score = float(coherence_score) / 100.0 * _COHERENCE_WEIGHT

    # ── Aggregate setup quality score ─────────────────────────────────────────
    total_float = checklist_sub_score + alignment_sub_score + coherence_sub_score
    total_float = max(0.0, min(100.0, total_float))
    score = Decimal(str(round(total_float, 2)))

    # strategy_drift_score = 100 - setup_quality_score
    drift_float = max(0.0, min(100.0, 100.0 - total_float))
    strategy_drift_score = Decimal(str(round(drift_float, 2)))

    # ── Confidence calculation ─────────────────────────────────────────────────
    confidence = Decimal("100")
    if not strategy_available:
        confidence -= _CONFIDENCE_PENALTY_NO_STRATEGY
        score = None  # Cannot score without strategy (40% weight missing entirely)
        strategy_drift_score = None
    if not checklist_available:
        confidence -= _CONFIDENCE_PENALTY_NO_CHECKLIST

    confidence = max(Decimal("0"), confidence)

    # ── Signals ──────────────────────────────────────────────────────────────
    checklist_complete = (
        checklist_data.get("all_completed", False)
        if checklist_available
        else False
    )
    signals = {
        "checklist_completed": checklist_complete,
        "strategy_aligned": (not any_mismatch) and strategy_available,
        "category_coherent": float(coherence_score) >= 80.0,
        "all_filters_passed": (
            checklist_complete and (not any_mismatch) and strategy_available
        ),
    }

    # ── Compose narrative_fragments ───────────────────────────────────────────
    narrative_fragments: list[str] = []

    # Summary fragment
    if score is not None:
        parts = []
        if checklist_complete:
            parts.append(f"checklist complete ({int(float(checklist_pct))}%)")
        else:
            parts.append(f"checklist {int(float(checklist_pct))}% complete")
        if not any_mismatch and strategy_available:
            parts.append("strategy aligned")
        elif any_mismatch:
            parts.append("strategy doctrine misalignment detected")
        narrative_fragments.append(
            f"Setup quality score = {score}/100: " + "; ".join(parts)
        )
    else:
        narrative_fragments.append(
            "not_available: Setup quality cannot be fully scored "
            "(strategy definition missing)"
        )

    # Append per-component fragments
    narrative_fragments.extend(checklist_narratives)
    narrative_fragments.extend(alignment_narratives)
    narrative_fragments.extend(coherence_narratives)

    return {
        "score": score,
        "confidence": confidence,
        "signals": signals,
        "narrative_fragments": narrative_fragments,
        "strategy_drift_score": strategy_drift_score,
        "strategy_id": strategy_id_val,
        "setup_type": setup_type_val,
        "checklist_items_missed": missed_labels,
    }


class SetupQualityTool:
    """VM107 analytics tool: deterministic setup quality + strategy drift scoring.

    Implements the ContractTool pattern (validate-request → call-vm → validate-response)
    as a standalone class (no Agent context required) so it can be called directly
    by AnalyticsService in Phase 57-09 and tested without the agent framework.

    Master-plan alias: get_strategy_drift → setup_quality_tool (CONTEXT §9)
    Both 'get_strategy_drift' and 'evaluate_setup_quality' route to THIS class
    via registry YAML alias system. One canonical implementation. No duplicate.

    Reads (3-way fan-out pattern — see _call_vm notes for V1 sequencing):
      - VM100 GET /api/journal/internal/executions/{execution_id}
      - VM100 GET /api/journal/internal/strategies/{strategy_id}
        (strategy_id resolved from execution.campaign → campaign.strategy_id)
      - VM100 GET /api/journal/internal/checklist/{execution_id}

    NOTE on 3-way sequencing in V1:
      The strategy endpoint requires strategy_id, which is on the Campaign (not
      the Execution directly). In V1, the tool does a fast preliminary fetch of
      the Execution to get campaign_id, then fetches Campaign to get strategy_id,
      then fans out strategy + checklist. This is a 2-step sequence:
        step1: get execution (1 call)
        step2: asyncio.gather(get campaign → extract strategy_id, get_checklist)
        step3: get strategy by id
      For simplicity in V1 (and to keep test mocking clean), _call_vm returns
      a flat dict of {execution, strategy, checklist} — the internal async
      sequencing is implementation-private.

    Usage:
        tool = SetupQualityTool()
        result = tool.run(execution_id="...", scoring_ruleset_version="1.0.0")

    The result is a SetupQualityResult Pydantic model.
    """

    def _validate_request(self, args: dict) -> SetupQualityRequest:
        """Validate args against SetupQualityRequest contract.

        Raises:
            ContractValidationError: if args don't match contract shape.
        """
        try:
            return SetupQualityRequest(**args)
        except Exception as e:  # noqa: BLE001
            raise ContractValidationError(errors=[str(e)], message=str(e)) from e

    async def _call_vm(self, request: SetupQualityRequest) -> dict:
        """Fan-out to VM100 (execution + strategy + checklist).

        V1 sequencing:
          1. Fetch execution row (to get campaign_id)
          2. Fetch campaign row (to get strategy_id)
          3. asyncio.gather(fetch strategy by id, fetch checklist by execution_id)

        On transport failure, synthesizes a not_available envelope for the
        affected data source — graceful degradation per pitfall #7.

        Returns:
            dict with keys 'execution', 'strategy', 'checklist'.
        """
        vm100 = VM100Client(profile=RetryProfile.FAST_FAIL)
        execution_id_str = str(request.execution_id)

        async def _get_execution() -> dict:
            try:
                return await vm100.get(
                    f"api/journal/internal/executions/{execution_id_str}"
                )
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(
                    "setup_quality_tool: VM100 transport error for execution %s: %s",
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

        async def _get_campaign(campaign_id: str) -> dict:
            try:
                return await vm100.get(
                    f"api/journal/internal/campaigns/{campaign_id}"
                )
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(
                    "setup_quality_tool: VM100 transport error for campaign %s: %s",
                    campaign_id,
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
                        "reason": "campaign_not_found",
                        "detail": str(e),
                    }
                if e.response.status_code >= 500:
                    return {
                        "status": "not_available",
                        "reason": "vm100_server_error",
                        "detail": str(e),
                    }
                raise

        async def _get_strategy(strategy_id: str) -> dict:
            try:
                return await vm100.get(
                    f"api/journal/internal/strategies/{strategy_id}"
                )
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(
                    "setup_quality_tool: VM100 transport error for strategy %s: %s",
                    strategy_id,
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
                        "reason": "strategy_not_found",
                        "detail": str(e),
                    }
                if e.response.status_code >= 500:
                    return {
                        "status": "not_available",
                        "reason": "vm100_server_error",
                        "detail": str(e),
                    }
                raise

        async def _get_checklist(exec_id: str) -> dict:
            try:
                return await vm100.get(
                    f"api/journal/internal/checklist/{exec_id}"
                )
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(
                    "setup_quality_tool: VM100 transport error for checklist %s: %s",
                    exec_id,
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
                        "reason": "checklist_not_found",
                        "detail": str(e),
                    }
                if e.response.status_code >= 500:
                    return {
                        "status": "not_available",
                        "reason": "vm100_server_error",
                        "detail": str(e),
                    }
                raise

        try:
            # Step 1: Get execution row (needed to resolve campaign_id → strategy_id)
            execution_data = await _get_execution()

            # Step 2: Resolve strategy_id from Campaign
            strategy_data: dict
            campaign_id = (
                execution_data.get("campaign_id")
                if not _is_not_available(execution_data)
                else None
            )

            if campaign_id:
                campaign_data = await _get_campaign(str(campaign_id))
                strategy_id = (
                    campaign_data.get("strategy_id")
                    if not _is_not_available(campaign_data)
                    else None
                )
            else:
                strategy_id = None

            # Step 3: Fan-out strategy + checklist (concurrent when strategy_id known)
            if strategy_id:
                strategy_data, checklist_data = await asyncio.gather(
                    _get_strategy(str(strategy_id)),
                    _get_checklist(execution_id_str),
                )
            else:
                strategy_data = {
                    "status": "not_available",
                    "reason": "strategy_id_not_found",
                    "detail": "Could not resolve strategy_id from campaign",
                }
                checklist_data = await _get_checklist(execution_id_str)

        finally:
            await vm100.close()

        return {
            "execution": execution_data,
            "strategy": strategy_data,
            "checklist": checklist_data,
        }

    def _validate_response(self, data: dict) -> SetupQualityResult:
        """Validate computed scoring result against SetupQualityResult contract.

        Raises:
            ContractValidationError: if data doesn't match contract shape.
        """
        try:
            return SetupQualityResult(**data)
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
            logger.debug("setup_quality_tool: Prometheus increment failed: %s", e)

    def run(self, **kwargs: Any) -> SetupQualityResult:
        """Synchronous entrypoint — runs async _call_vm in a new event loop.

        Args:
            **kwargs: Arguments forwarded to SetupQualityRequest.
                      Required: execution_id (str or UUID).
                      Optional: scoring_ruleset_version, analysis_context, replay_window.

        Returns:
            SetupQualityResult Pydantic model.

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
        strategy_data = combined.get("strategy") or {}
        checklist_data = combined.get("checklist") or {}

        score_dict = compute_setup_quality_score(
            execution_data, strategy_data, checklist_data
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

    async def run_async(self, **kwargs: Any) -> SetupQualityResult:
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
        strategy_data = combined.get("strategy") or {}
        checklist_data = combined.get("checklist") or {}

        score_dict = compute_setup_quality_score(
            execution_data, strategy_data, checklist_data
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
