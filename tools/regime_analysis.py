"""regime_analysis_tool — Phase 57 Plan 01.

Deterministic market regime classification for a given Execution.

Reads:
  - VM100 GET /api/journal/internal/executions/{execution_id} — canonical Execution
  - VM102 GET /api/v1/primitives/?instrument=...&timeframe=M5&layers=1,2 — BOS/CHoCH, ATR

Computes (pure Python, NO LLM):
  - regime_classification (trending_bullish / trending_bearish / range_bound / unknown)
  - volatility_class (low / normal / high)
  - session context (london / ny / asia / overlap — derived from entry_time UTC hour)
  - score (0-100), confidence (0-100), signals, narrative_fragments

Returns RegimeAnalysisResult (fingpt_core.contracts.analytics.regime).

not_available envelope handling (Phase 47.2.1 lock):
  When VM102 returns {"status": "not_available", ...} OR a transport error fires,
  the tool degrades category: score=None, confidence=0, narrative_fragments contains
  'not_available'. NEVER fabricates a score.

Prometheus telemetry (Pattern 26 — bounded cardinality):
  vm107_analytics_tool_calls_total{tool='regime_analysis_tool', result_status=...}
  vm107_analytics_tool_duration_seconds{tool='regime_analysis_tool'}

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
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx

from fingpt_core.clients import RetryProfile, VM100Client, VM102Client
from fingpt_core.contracts.analytics.regime import (
    RegimeAnalysisRequest,
    RegimeAnalysisResult,
)
from fingpt_core.contracts.errors import ContractValidationError

logger = logging.getLogger("fingpt.tools.regime_analysis")

TOOL_NAME = "regime_analysis_tool"
LOOKBACK_BARS_CAP = 500  # RESEARCH anti-pattern §3 / CONTEXT §3 OQ-6
DEFAULT_TIMEFRAME = "M5"
DEFAULT_LAYERS = [1, 2]

# Session UTC-hour boundaries (inclusive start, exclusive end)
_SESSION_WINDOWS = {
    "london": (7, 16),    # 07:00–16:00 UTC
    "ny": (13, 22),       # 13:00–22:00 UTC (overlaps London 13-16)
    "asia": (0, 9),       # 00:00–09:00 UTC
}

# ATR regime thresholds (fraction of baseline)
_ATR_LOW_THRESHOLD = 0.75    # current ATR < 75% of baseline → low
_ATR_HIGH_THRESHOLD = 1.25   # current ATR > 125% of baseline → high


def _session_from_hour(utc_hour: int) -> str:
    """Classify trading session from UTC hour.

    Overlap (London+NY) takes priority when both sessions are active.
    Returns one of: london, ny, asia, overlap.
    """
    in_london = _SESSION_WINDOWS["london"][0] <= utc_hour < _SESSION_WINDOWS["london"][1]
    in_ny = _SESSION_WINDOWS["ny"][0] <= utc_hour < _SESSION_WINDOWS["ny"][1]
    in_asia = _SESSION_WINDOWS["asia"][0] <= utc_hour < _SESSION_WINDOWS["asia"][1]

    if in_london and in_ny:
        return "overlap"
    if in_london:
        return "london"
    if in_ny:
        return "ny"
    if in_asia:
        return "asia"
    # Between Asia close (09:00) and London open (07:00) next day — rare but possible
    return "unknown"


def _is_not_available(data: dict) -> bool:
    """Return True if data is a not_available envelope."""
    return isinstance(data, dict) and data.get("status") == "not_available"


def compute_regime_score(execution_data: dict, primitives_data: dict) -> dict:
    """Pure-Python deterministic regime scoring.

    Args:
        execution_data: VM100 Execution row dict (id, opened_at, metadata, etc.)
        primitives_data: VM102 primitives response dict OR not_available envelope

    Returns:
        dict matching RegimeAnalysisResult field shape (without base AnalysisResultBase fields
        that are already set to defaults — caller merges).
    """
    # ── Degrade gracefully if primitives not available ────────────────────────
    if _is_not_available(primitives_data):
        # Extract session from entry time if possible
        session = "unknown"
        opened_at_raw = execution_data.get("opened_at")
        if opened_at_raw:
            try:
                dt = datetime.fromisoformat(opened_at_raw.replace("Z", "+00:00"))
                session = _session_from_hour(dt.hour)
            except (ValueError, AttributeError):
                pass

        return {
            "score": None,
            "confidence": Decimal("0"),
            "signals": {
                "trend_bullish": False,
                "trend_bearish": False,
                "range_bound": False,
                "bos_confirmed": False,
                "choch_detected": False,
                "atr_above_baseline": False,
                "atr_below_baseline": False,
                "volatility_compressed": False,
                "session_confluence": False,
            },
            "narrative_fragments": [
                "not_available: VM102 primitives unavailable — regime cannot be scored",
                f"session={session} (derived from entry time; not scored)",
            ],
            "regime": "unknown",
            "volatility_class": "normal",
            "atr_value": None,
            "atr_percentile": None,
        }

    # ── Extract primitives layers ─────────────────────────────────────────────
    prim_data = primitives_data.get("data") or {}
    layer1 = prim_data.get("layer_1") or prim_data.get("layer1") or {}
    layer2 = prim_data.get("layer_2") or prim_data.get("layer2") or {}

    # ── Session classification ────────────────────────────────────────────────
    session = "unknown"
    opened_at_raw = execution_data.get("opened_at")
    if opened_at_raw:
        try:
            dt = datetime.fromisoformat(opened_at_raw.replace("Z", "+00:00"))
            session = _session_from_hour(dt.hour)
        except (ValueError, AttributeError):
            pass

    # ── ATR regime classification (Layer 1) ──────────────────────────────────
    atr_value: float | None = None
    atr_baseline: float | None = None
    atr_percentile: float | None = None
    volatility_class = "normal"
    atr_above_baseline = False
    atr_below_baseline = False
    volatility_compressed = False

    # Layer 1 may carry atr_current, atr_mean (baseline), atr_percentile
    if layer1:
        atr_value = layer1.get("atr_current") or layer1.get("atr") or layer1.get("atr_value")
        atr_baseline = layer1.get("atr_mean") or layer1.get("atr_baseline")
        atr_percentile = layer1.get("atr_percentile")

        if atr_value is not None and atr_baseline is not None and atr_baseline > 0:
            ratio = atr_value / atr_baseline
            if ratio < _ATR_LOW_THRESHOLD:
                volatility_class = "low"
                atr_below_baseline = True
                volatility_compressed = True
            elif ratio > _ATR_HIGH_THRESHOLD:
                volatility_class = "high"
                atr_above_baseline = True
            else:
                volatility_class = "normal"

        # Fallback: use percentile alone if no baseline
        if atr_percentile is not None and atr_value is None:
            if atr_percentile < 25:
                volatility_class = "low"
                volatility_compressed = True
                atr_below_baseline = True
            elif atr_percentile > 75:
                volatility_class = "high"
                atr_above_baseline = True

    # ── Regime classification (Layer 2: BOS/CHoCH) ───────────────────────────
    bos_confirmed = False
    choch_detected = False
    trend_bullish = False
    trend_bearish = False
    range_bound = False
    regime = "unknown"

    if layer2:
        # Typical Layer 2 keys from VM102 structure engine:
        # bos_bullish, bos_bearish, choch_bullish, choch_bearish,
        # structure_bias ('bullish'|'bearish'|'ranging'|'unknown')
        bos_bullish = bool(layer2.get("bos_bullish") or layer2.get("bullish_bos"))
        bos_bearish = bool(layer2.get("bos_bearish") or layer2.get("bearish_bos"))
        choch_bull = bool(layer2.get("choch_bullish") or layer2.get("bullish_choch"))
        choch_bear = bool(layer2.get("choch_bearish") or layer2.get("bearish_choch"))
        structure_bias = layer2.get("structure_bias") or layer2.get("bias") or "unknown"

        bos_confirmed = bos_bullish or bos_bearish
        choch_detected = choch_bull or choch_bear

        if structure_bias == "bullish" or bos_bullish:
            regime = "trending_bullish"
            trend_bullish = True
        elif structure_bias == "bearish" or bos_bearish:
            regime = "trending_bearish"
            trend_bearish = True
        elif structure_bias == "ranging" or (not bos_confirmed and not choch_detected):
            regime = "range_bound"
            range_bound = True
        elif choch_detected:
            # CHoCH without clear BOS → potential reversal forming
            # Map to regime based on choch direction
            if choch_bull:
                regime = "trending_bullish"
                trend_bullish = True
            elif choch_bear:
                regime = "trending_bearish"
                trend_bearish = True
        else:
            regime = "unknown"

    # ── Session confluence signal ─────────────────────────────────────────────
    session_confluence = session in ("london", "ny", "overlap")

    # ── Score computation ─────────────────────────────────────────────────────
    # Heuristic: trending + session match → higher score
    # ranging → moderate score
    # unknown → lower score
    base_score = 50
    if regime == "trending_bullish" or regime == "trending_bearish":
        base_score = 80
        if session_confluence:
            base_score = min(95, base_score + 10)
        if volatility_class == "high":
            base_score = min(85, base_score)
        if volatility_class == "low":
            base_score = max(60, base_score - 10)
    elif regime == "range_bound":
        base_score = 50
        if volatility_compressed:
            base_score = 60  # Compressed ranges can set up breakouts
    elif choch_detected and regime != "unknown":
        base_score = 65
    else:
        base_score = 30  # unknown regime

    score = Decimal(str(base_score))
    confidence = Decimal("100")  # full data available

    # ── Narrative fragments ───────────────────────────────────────────────────
    fragments = []
    if regime != "unknown":
        fragments.append(f"regime={regime}")
    fragments.append(f"volatility_class={volatility_class}")
    fragments.append(f"session={session}")
    if bos_confirmed:
        fragments.append("bos_confirmed=True (structural break detected)")
    if choch_detected:
        fragments.append("choch_detected=True (character change signal)")
    if session_confluence:
        fragments.append("session_confluence=True (high-liquidity session active)")

    signals = {
        "trend_bullish": trend_bullish,
        "trend_bearish": trend_bearish,
        "range_bound": range_bound,
        "bos_confirmed": bos_confirmed,
        "choch_detected": choch_detected,
        "atr_above_baseline": atr_above_baseline,
        "atr_below_baseline": atr_below_baseline,
        "volatility_compressed": volatility_compressed,
        "session_confluence": session_confluence,
    }

    return {
        "score": score,
        "confidence": confidence,
        "signals": signals,
        "narrative_fragments": fragments,
        "regime": regime,
        "volatility_class": volatility_class,
        "atr_value": atr_value,
        "atr_percentile": atr_percentile,
    }


class RegimeAnalysisTool:
    """VM107 analytics tool: deterministic market regime classification.

    Implements the ContractTool pattern (validate-request → call-vm → validate-response)
    as a standalone class (no Agent context required) so it can be called directly
    by AnalyticsService in Phase 57-09 and tested without the agent framework.

    Usage:
        tool = RegimeAnalysisTool()
        result = tool.run(execution_id="...", scoring_ruleset_version="1.0.0")

    The result is a RegimeAnalysisResult Pydantic model.
    """

    def _validate_request(self, args: dict) -> RegimeAnalysisRequest:
        """Validate args against RegimeAnalysisRequest contract.

        Raises:
            ContractValidationError: if args don't match contract shape.
        """
        try:
            return RegimeAnalysisRequest(**args)
        except Exception as e:  # noqa: BLE001
            raise ContractValidationError(errors=[str(e)], message=str(e)) from e

    async def _call_vm(self, request: RegimeAnalysisRequest) -> dict:
        """Concurrent fan-out to VM100 (Execution) + VM102 (primitives).

        Uses asyncio.gather with FAST_FAIL retry profile. On transport failure,
        synthesizes a not_available envelope (never fabricates primitives).

        Returns:
            dict with keys 'execution' and 'primitives'.
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
                    "regime_analysis_tool: VM100 transport error for execution %s: %s",
                    execution_id_str,
                    e,
                )
                return {"status": "not_available", "reason": "vm100_transport_error", "detail": str(e)}
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return {"status": "not_available", "reason": "execution_not_found", "detail": str(e)}
                if e.response.status_code >= 500:
                    return {"status": "not_available", "reason": "vm100_server_error", "detail": str(e)}
                raise
            finally:
                await vm100.close()

        async def _get_primitives(instrument: str) -> dict:
            try:
                return await vm102.get_primitives_v1(
                    instrument=instrument,
                    timeframe=DEFAULT_TIMEFRAME,
                    layers=DEFAULT_LAYERS,
                    lookback_bars=min(100, LOOKBACK_BARS_CAP),
                )
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(
                    "regime_analysis_tool: VM102 transport error for instrument %s: %s",
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

        # If execution not available, skip primitives fetch
        if _is_not_available(execution_data):
            return {"execution": execution_data, "primitives": {"status": "not_available", "reason": "execution_unavailable"}}

        # Extract instrument for VM102 query
        # Execution row has: id, campaign_id, state, metadata, ...
        # instrument may be in metadata or as a direct field
        instrument = (
            execution_data.get("instrument")
            or (execution_data.get("metadata") or {}).get("instrument")
            or "UNKNOWN"
        )

        primitives_data = await _get_primitives(instrument)
        return {"execution": execution_data, "primitives": primitives_data}

    def _validate_response(self, data: dict) -> RegimeAnalysisResult:
        """Validate computed scoring result against RegimeAnalysisResult contract.

        Raises:
            ContractValidationError: if data doesn't match contract shape.
        """
        try:
            return RegimeAnalysisResult(**data)
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
            logger.debug("regime_analysis_tool: Prometheus increment failed: %s", e)

    def run(self, **kwargs: Any) -> RegimeAnalysisResult:
        """Synchronous entrypoint — runs async _call_vm in a new event loop.

        Args:
            **kwargs: Arguments forwarded to RegimeAnalysisRequest.
                      Required: execution_id (str or UUID).
                      Optional: scoring_ruleset_version, analysis_context, replay_window.

        Returns:
            RegimeAnalysisResult Pydantic model.

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
        primitives_data = combined.get("primitives") or {}

        score_dict = compute_regime_score(execution_data, primitives_data)

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

    async def run_async(self, **kwargs: Any) -> RegimeAnalysisResult:
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
        primitives_data = combined.get("primitives") or {}

        score_dict = compute_regime_score(execution_data, primitives_data)

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
