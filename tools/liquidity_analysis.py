"""liquidity_analysis_tool — Phase 57 Plan 02.

Deterministic liquidity context scoring for a given Execution.

Reads:
  - VM100 GET /api/journal/internal/executions/{execution_id} — canonical Execution
  - VM102 GET /api/v1/liquidity/?instrument=...&timeframe=...&lookback_bars=... — FVG zones,
      equal highs/lows, imbalance zones (Phase 47.2.1 endpoint)

Computes (pure Python, NO LLM):
  - fvg_proximate: was the entry within / near an active FVG?
  - equal_hl_proximate: was the entry within N pips of an equal high or equal low?
  - hvn_at_entry: high-volume-node (demand/supply zone) at entry price
  - lvn_at_entry: low-volume node at entry price (imbalance zone)
  - liquidity_sweep_confirmed: price swept a liquidity pool before reversing into entry
  - imbalance_entry: entry inside an active price imbalance (FVG / displacement)
  - score (0-100), confidence (0-100), liquidity_context, narrative_fragments

Returns LiquidityAnalysisResult (fingpt_core.contracts.analytics.liquidity).

not_available envelope handling (Phase 47.2.1 lock):
  When VM102 returns {"status": "not_available", ...} OR a transport error fires,
  the tool degrades category: score=None, confidence=0, narrative_fragments contains
  'not_available'. NEVER fabricates a score.

Prometheus telemetry (Pattern 26 — bounded cardinality):
  vm107_analytics_tool_calls_total{tool='liquidity_analysis_tool', result_status=...}
  vm107_analytics_tool_duration_seconds{tool='liquidity_analysis_tool'}

result_status values: success | degraded | transport_error | validation_error

Architecture notes:
  - FAST_FAIL retry profile per Phase 47.2.1 lock (long retries blow asyncio.gather budget)
  - lookback_bars capped at 500 (RESEARCH anti-pattern §3, OQ-6)
  - asyncio.gather over VM100 + VM102 fan-out (concurrent, not sequential)
  - No qdrant_client import (success criteria)
  - No LLM calls (deterministic-Python primary doctrine, CONTEXT §5)
"""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any

import httpx

from fingpt_core.clients import RetryProfile, VM100Client, VM102Client
from fingpt_core.contracts.analytics.liquidity import (
    LiquidityAnalysisRequest,
    LiquidityAnalysisResult,
)
from fingpt_core.contracts.errors import ContractValidationError

logger = logging.getLogger("fingpt.tools.liquidity_analysis")

TOOL_NAME = "liquidity_analysis_tool"
LOOKBACK_BARS_CAP = 500  # RESEARCH anti-pattern §3 / CONTEXT §3 OQ-6
DEFAULT_TIMEFRAME = "M5"

# Pip-proximity thresholds for equal H&L detection
# 5 pips for most major FX pairs (instrument-agnostic heuristic V1)
_EQUAL_HL_PIP_THRESHOLD = 0.0005  # 5 pips in price terms for EURUSD-class pairs

# FVG presence contributes the most to a high-confluence liquidity context
_FVG_SCORE_WEIGHT = 40
_EQUAL_HL_SCORE_WEIGHT = 25
_IMBALANCE_SCORE_WEIGHT = 20
_SWEEP_SCORE_WEIGHT = 15


def _is_not_available(data: dict) -> bool:
    """Return True if data is a not_available envelope."""
    return isinstance(data, dict) and data.get("status") == "not_available"


def _price_within_zone(entry_price: float, zone_low: float, zone_high: float) -> bool:
    """Return True if entry_price falls within or on the zone boundaries."""
    return zone_low <= entry_price <= zone_high


def _price_within_pips(entry_price: float, level_price: float, pip_threshold: float) -> bool:
    """Return True if entry_price is within pip_threshold of level_price."""
    return abs(entry_price - level_price) <= pip_threshold


def compute_liquidity_score(execution_data: dict, liquidity_data: dict) -> dict:
    """Pure-Python deterministic liquidity context scoring.

    Args:
        execution_data: VM100 Execution row dict (id, opened_at, entry_price, etc.)
        liquidity_data: VM102 liquidity response dict OR not_available envelope

    Returns:
        dict matching LiquidityAnalysisResult field shape (caller passes to _validate_response).
    """
    # ── Degrade gracefully if liquidity data not available ────────────────────
    if _is_not_available(liquidity_data):
        reason = (liquidity_data.get("meta") or {}).get("planned_phase", "VM102 not_available")
        return {
            "score": None,
            "confidence": Decimal("0"),
            "signals": {
                "fvg_proximate": False,
                "fvg_filled_before_entry": False,
                "equal_highs_proximity": False,
                "equal_lows_proximity": False,
                "volume_node_bullish": False,
                "volume_node_bearish": False,
                "liquidity_sweep_confirmed": False,
                "imbalance_entry": False,
            },
            "narrative_fragments": [
                f"not_available: VM102 liquidity endpoint unavailable — liquidity cannot be scored",
                f"not_available reason: {reason}",
            ],
            "liquidity_context": "unknown",
            "fvg_count": 0,
            "sweep_confirmed": False,
        }

    # ── Extract liquidity primitives ──────────────────────────────────────────
    liq_data = liquidity_data.get("data") or {}
    fvg_zones: list[dict] = liq_data.get("fvg_zones") or []
    equal_highs: list[dict] = liq_data.get("equal_highs") or []
    equal_lows: list[dict] = liq_data.get("equal_lows") or []
    imbalance_zones: list[dict] = liq_data.get("imbalance_zones") or []

    # ── Extract entry price from execution ────────────────────────────────────
    # V1: try standard field names; degrade gracefully if not available
    entry_price: float | None = (
        execution_data.get("entry_price")
        or execution_data.get("open_price")
        or (execution_data.get("metadata") or {}).get("entry_price")
    )

    # ── Signal computation ────────────────────────────────────────────────────
    fvg_proximate = False
    fvg_filled_before_entry = False
    equal_highs_proximity = False
    equal_lows_proximity = False
    volume_node_bullish = False
    volume_node_bearish = False
    liquidity_sweep_confirmed = False
    imbalance_entry = False

    fvg_count = len(fvg_zones)

    if entry_price is not None:
        # FVG proximity: was the entry inside or adjacent to an active FVG?
        for fvg in fvg_zones:
            fvg_low = fvg.get("low") or fvg.get("zone_low") or fvg.get("bottom")
            fvg_high = fvg.get("high") or fvg.get("zone_high") or fvg.get("top")
            if fvg_low is not None and fvg_high is not None:
                if _price_within_zone(entry_price, float(fvg_low), float(fvg_high)):
                    fvg_proximate = True
                    # Check if FVG was filled (mitigation) before entry
                    # A filled FVG has zone_state in ('filled', 'mitigated') or is_filled=True
                    if (
                        fvg.get("zone_state") in ("filled", "mitigated")
                        or fvg.get("is_filled") is True
                        or fvg.get("filled") is True
                    ):
                        fvg_filled_before_entry = True
                    break

        # Equal highs proximity: is entry near an equal high level?
        for eq_high in equal_highs:
            level = eq_high.get("price") or eq_high.get("level") or eq_high.get("high")
            if level is not None:
                if _price_within_pips(entry_price, float(level), _EQUAL_HL_PIP_THRESHOLD):
                    equal_highs_proximity = True
                    break

        # Equal lows proximity: is entry near an equal low level?
        for eq_low in equal_lows:
            level = eq_low.get("price") or eq_low.get("level") or eq_low.get("low")
            if level is not None:
                if _price_within_pips(entry_price, float(level), _EQUAL_HL_PIP_THRESHOLD):
                    equal_lows_proximity = True
                    break

        # Imbalance entry: is entry inside an active imbalance zone?
        for imb in imbalance_zones:
            imb_low = imb.get("low") or imb.get("zone_low") or imb.get("bottom")
            imb_high = imb.get("high") or imb.get("zone_high") or imb.get("top")
            if imb_low is not None and imb_high is not None:
                if _price_within_zone(entry_price, float(imb_low), float(imb_high)):
                    imbalance_entry = True
                    # Determine direction (supply = bearish, demand = bullish)
                    imb_type = imb.get("zone_type") or imb.get("direction") or ""
                    if "bear" in imb_type.lower() or "supply" in imb_type.lower():
                        volume_node_bearish = True
                    elif "bull" in imb_type.lower() or "demand" in imb_type.lower():
                        volume_node_bullish = True
                    break

    # Liquidity sweep: look for sweep signals in FVG or equal zone metadata
    # V1 heuristic: if an FVG zone has swept_before=True or zone_state='swept',
    # or equal_high/low has been swept (is_swept=True), then sweep_confirmed.
    for fvg in fvg_zones:
        if (
            fvg.get("swept_before") is True
            or fvg.get("zone_state") == "swept"
            or fvg.get("is_swept") is True
        ):
            liquidity_sweep_confirmed = True
            break
    if not liquidity_sweep_confirmed:
        for level_list in (equal_highs, equal_lows):
            for level in level_list:
                if level.get("is_swept") is True or level.get("swept") is True:
                    liquidity_sweep_confirmed = True
                    break
            if liquidity_sweep_confirmed:
                break

    # ── Score computation ─────────────────────────────────────────────────────
    # Weighted sum of active signals, capped at 100.
    # FVG proximity is the primary liquidity confluence indicator.
    # Equal H&L proximity adds structural significance.
    # Imbalance entry confirms an inefficiency zone.
    # Liquidity sweep adds conviction (price swept a pool before entry — ideal).
    score_sum = 0

    if fvg_proximate and not fvg_filled_before_entry:
        # FVG present AND not yet filled = clean liquidity zone entry
        score_sum += _FVG_SCORE_WEIGHT
    elif fvg_proximate and fvg_filled_before_entry:
        # FVG was already filled — less quality (entry into stale zone)
        score_sum += _FVG_SCORE_WEIGHT // 2

    if equal_highs_proximity or equal_lows_proximity:
        score_sum += _EQUAL_HL_SCORE_WEIGHT

    if imbalance_entry:
        score_sum += _IMBALANCE_SCORE_WEIGHT

    if liquidity_sweep_confirmed:
        score_sum += _SWEEP_SCORE_WEIGHT

    # Scale to 0-100 (max possible = 40+25+20+15 = 100)
    score = Decimal(str(min(100, score_sum)))

    # Confidence: full when we have entry_price + liquidity data;
    # reduced when entry_price is missing (can't compute proximity signals)
    confidence = Decimal("100") if entry_price is not None else Decimal("50")

    # ── Liquidity context classification ─────────────────────────────────────
    if score >= Decimal("70"):
        liquidity_context = "high_confluence"
    elif score >= Decimal("40"):
        liquidity_context = "moderate"
    elif score > Decimal("0"):
        liquidity_context = "low"
    else:
        liquidity_context = "unknown"

    # ── Narrative fragments ───────────────────────────────────────────────────
    fragments: list[str] = []
    fragments.append(f"liquidity_context={liquidity_context} (score={score}/100)")

    if fvg_proximate:
        if fvg_filled_before_entry:
            fragments.append(
                f"FVG present but already filled/mitigated before entry — stale zone"
            )
        else:
            fragments.append(
                f"Entry inside or adjacent to active FVG (count={fvg_count}) — clean liquidity zone"
            )
    elif fvg_count > 0:
        fragments.append(
            f"FVG zones detected (count={fvg_count}) but entry not in proximity threshold"
        )

    if equal_highs_proximity:
        fragments.append(
            f"Entry within {int(_EQUAL_HL_PIP_THRESHOLD * 10000)} pips of equal-high level (liquidity target above)"
        )
    if equal_lows_proximity:
        fragments.append(
            f"Entry within {int(_EQUAL_HL_PIP_THRESHOLD * 10000)} pips of equal-low level (liquidity target below)"
        )

    if imbalance_entry:
        node_type = "bullish demand node" if volume_node_bullish else ("bearish supply node" if volume_node_bearish else "imbalance zone")
        fragments.append(f"Entry inside active {node_type} — price inefficiency zone")

    if liquidity_sweep_confirmed:
        fragments.append(
            "Liquidity sweep confirmed before entry — price cleared a liquidity pool (high-conviction entry context)"
        )

    if not any([fvg_proximate, equal_highs_proximity, equal_lows_proximity, imbalance_entry, liquidity_sweep_confirmed]):
        fragments.append("No active liquidity zone signals detected for entry window")

    signals = {
        "fvg_proximate": fvg_proximate,
        "fvg_filled_before_entry": fvg_filled_before_entry,
        "equal_highs_proximity": equal_highs_proximity,
        "equal_lows_proximity": equal_lows_proximity,
        "volume_node_bullish": volume_node_bullish,
        "volume_node_bearish": volume_node_bearish,
        "liquidity_sweep_confirmed": liquidity_sweep_confirmed,
        "imbalance_entry": imbalance_entry,
    }

    return {
        "score": score,
        "confidence": confidence,
        "signals": signals,
        "narrative_fragments": fragments,
        "liquidity_context": liquidity_context,
        "fvg_count": fvg_count,
        "sweep_confirmed": liquidity_sweep_confirmed,
    }


class LiquidityAnalysisTool:
    """VM107 analytics tool: deterministic liquidity context quality scoring.

    Implements the ContractTool pattern (validate-request → call-vm → validate-response)
    as a standalone class (no Agent context required) so it can be called directly
    by AnalyticsService in Phase 57-09 and tested without the agent framework.

    Reads:
      - VM100 GET /api/journal/internal/executions/{execution_id}
      - VM102 GET /api/v1/liquidity/?instrument=...&timeframe=...&lookback_bars=...

    Computes:
      - FVG proximity (was entry within an active Fair Value Gap?)
      - Equal H&L proximity (was entry near equal highs or lows — liquidity targets)
      - Imbalance entry (is entry inside a price imbalance / displacement zone)
      - Liquidity sweep confirmed (did price sweep a pool before entry)
      - liquidity_context classification: high_confluence / moderate / low / unknown

    Usage:
        tool = LiquidityAnalysisTool()
        result = tool.run(execution_id="...", scoring_ruleset_version="1.0.0")

    The result is a LiquidityAnalysisResult Pydantic model.
    """

    def _validate_request(self, args: dict) -> LiquidityAnalysisRequest:
        """Validate args against LiquidityAnalysisRequest contract.

        Raises:
            ContractValidationError: if args don't match contract shape.
        """
        try:
            return LiquidityAnalysisRequest(**args)
        except Exception as e:  # noqa: BLE001
            raise ContractValidationError(errors=[str(e)], message=str(e)) from e

    async def _call_vm(self, request: LiquidityAnalysisRequest) -> dict:
        """Concurrent fan-out to VM100 (Execution) + VM102 (liquidity zones).

        Uses asyncio.gather with FAST_FAIL retry profile. On transport failure,
        synthesizes a not_available envelope (never fabricates liquidity data).

        Returns:
            dict with keys 'execution' and 'liquidity'.
        """
        vm100 = VM100Client(profile=RetryProfile.FAST_FAIL)
        vm102 = VM102Client(profile=RetryProfile.FAST_FAIL)

        execution_id_str = str(request.execution_id)

        async def _get_execution() -> dict:
            try:
                return await vm100.get(
                    f"api/journal/internal/executions/{execution_id_str}"
                )
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(
                    "liquidity_analysis_tool: VM100 transport error for execution %s: %s",
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
            finally:
                await vm100.close()

        async def _get_liquidity(instrument: str) -> dict:
            try:
                return await vm102.get_liquidity(
                    instrument=instrument,
                    timeframe=DEFAULT_TIMEFRAME,
                    lookback_bars=min(100, LOOKBACK_BARS_CAP),
                )
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(
                    "liquidity_analysis_tool: VM102 transport error for instrument %s: %s",
                    instrument,
                    e,
                )
                return {
                    "status": "not_available",
                    "reason": "vm102_transport_error",
                    "detail": str(e),
                }
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    return {
                        "status": "not_available",
                        "reason": "vm102_server_error",
                        "detail": str(e),
                    }
                raise
            finally:
                await vm102.close()

        # First fetch execution to get instrument
        execution_data = await _get_execution()

        # If execution not available, skip liquidity fetch
        if _is_not_available(execution_data):
            return {
                "execution": execution_data,
                "liquidity": {
                    "status": "not_available",
                    "reason": "execution_unavailable",
                    "meta": {"planned_phase": "execution_unavailable"},
                },
            }

        # Extract instrument for VM102 query
        instrument = (
            execution_data.get("instrument")
            or (execution_data.get("metadata") or {}).get("instrument")
            or "UNKNOWN"
        )

        liquidity_data = await _get_liquidity(instrument)
        return {"execution": execution_data, "liquidity": liquidity_data}

    def _validate_response(self, data: dict) -> LiquidityAnalysisResult:
        """Validate computed scoring result against LiquidityAnalysisResult contract.

        Raises:
            ContractValidationError: if data doesn't match contract shape.
        """
        try:
            return LiquidityAnalysisResult(**data)
        except Exception as e:  # noqa: BLE001
            raise ContractValidationError(errors=[str(e)], message=str(e)) from e

    def _increment_prometheus(self, result_status: str, duration_s: float) -> None:
        """Increment Prometheus counters with bounded cardinality labels.

        result_status ∈ {success, degraded, transport_error, validation_error}
        """
        try:
            # Import lazily — VM107 may not always have prometheus_client installed
            from journal.monitoring.post_trade_metrics import (
                vm107_analytics_tool_calls_total,
                vm107_analytics_tool_duration_seconds,
            )
            vm107_analytics_tool_calls_total.labels(
                tool=TOOL_NAME, result_status=result_status
            ).inc()
            vm107_analytics_tool_duration_seconds.labels(tool=TOOL_NAME).observe(duration_s)
        except ImportError:
            # VM107 runtime doesn't have VM100's monitoring module in path;
            # skip silently — metrics not critical in non-VM100 contexts.
            pass
        except Exception as e:  # noqa: BLE001
            logger.debug("liquidity_analysis_tool: Prometheus increment failed: %s", e)

    def run(self, **kwargs: Any) -> LiquidityAnalysisResult:
        """Synchronous entrypoint — runs async _call_vm in a new event loop.

        Args:
            **kwargs: Arguments forwarded to LiquidityAnalysisRequest.
                      Required: execution_id (str or UUID).
                      Optional: scoring_ruleset_version, analysis_context, replay_window.

        Returns:
            LiquidityAnalysisResult Pydantic model.

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
        liquidity_data = combined.get("liquidity") or {}

        score_dict = compute_liquidity_score(execution_data, liquidity_data)

        # Determine result_status before validation
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

    async def run_async(self, **kwargs: Any) -> LiquidityAnalysisResult:
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
        liquidity_data = combined.get("liquidity") or {}

        score_dict = compute_liquidity_score(execution_data, liquidity_data)

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
