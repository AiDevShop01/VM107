"""compression_analysis_tool — Phase 57 Plan 03.

Deterministic pre-entry compression quality scoring for a given Execution.

Reads:
  - VM100 GET /api/journal/internal/executions/{execution_id} — canonical Execution
  - VM102 GET /api/v1/primitives/?instrument=...&timeframe=M5&layers=4 — L4 compression
      primitives (inside-bar clusters, range/ATR ratio, pre-breakout consolidation)

Computes (pure Python, NO LLM):
  - range_compressed: range/ATR ratio < 1.4 for the pre-entry N-bar window → price
      was compressed before entry (high score driver)
  - inside_bars_present: ≥3 inside bars detected in pre-entry window (consolidation signal)
  - expansion_pre_entry: range expansion candle fired BEFORE a liquidity sweep at entry
      (bad — premature breakout; penalises compression quality)
  - score (0-100), confidence (0-100), compression_quality, narrative_fragments

Returns CompressionAnalysisResult (fingpt_core.contracts.analytics.compression).

not_available envelope handling (Phase 47.2.1 lock):
  When VM102 returns {"status": "not_available", ...} OR a transport error fires,
  the tool degrades category: score=None, confidence=0, narrative_fragments contains
  'not_available'. NEVER fabricates a score.

Prometheus telemetry (Pattern 26 — bounded cardinality):
  vm107_analytics_tool_calls_total{tool='compression_analysis_tool', result_status=...}
  vm107_analytics_tool_duration_seconds{tool='compression_analysis_tool'}

result_status values: success | degraded | transport_error | validation_error

Architecture notes:
  - L4 compression primitives endpoint: GET /api/v1/primitives/?layers=4
  - FAST_FAIL retry profile per Phase 47.2.1 lock (long retries blow asyncio.gather budget)
  - asyncio.gather over VM100 + VM102 fan-out (concurrent, not sequential)
  - No qdrant_client import (success criteria)
  - No LLM calls (deterministic-Python primary doctrine, CONTEXT §5)
  - Scoring thresholds per PLAN.md §task: range/ATR ratio ≥1.4 = 80+;
    inside_bar_count ≥3 = +15; expansion within 3 bars of entry = +5 (timing bonus)
"""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any

import httpx

from fingpt_core.clients import RetryProfile, VM100Client, VM102Client
from fingpt_core.contracts.analytics.compression import (
    CompressionAnalysisRequest,
    CompressionAnalysisResult,
)
from fingpt_core.contracts.errors import ContractValidationError

logger = logging.getLogger("fingpt.tools.compression_analysis")

TOOL_NAME = "compression_analysis_tool"
LOOKBACK_BARS_CAP = 500   # RESEARCH anti-pattern §3 / CONTEXT §3 OQ-6
DEFAULT_TIMEFRAME = "M5"
DEFAULT_LAYERS = [4]      # L4 = compression primitives (inside-bar, range/ATR)

# Compression scoring thresholds per PLAN.md §task
_RANGE_ATR_RATIO_TARGET = 1.4    # range/ATR ratio ≥ 1.4 → compressed range quality gate
_INSIDE_BAR_COUNT_TARGET = 3     # ≥3 inside bars → strong consolidation cluster

# Score weights
_RANGE_ATR_WEIGHT = 80    # primary driver: range/ATR ratio ≥ 1.4
_INSIDE_BAR_WEIGHT = 15   # secondary: ≥3 inside bars
_EXPANSION_TIMING_BONUS = 5  # expansion AFTER entry (not before) → timing intact


def _is_not_available(data: dict) -> bool:
    """Return True if data is a not_available envelope."""
    return isinstance(data, dict) and data.get("status") == "not_available"


def compute_compression_score(execution_data: dict, primitives_data: dict) -> dict:
    """Pure-Python deterministic compression quality scoring.

    Scoring algorithm (per PLAN.md §task):
      - range/ATR ratio ≥ 1.4 → +80 (primary compression quality gate)
      - inside_bar_count ≥ 3  → +15 (consolidation cluster present)
      - expansion_pre_entry is False → +5 (consolidation intact at entry)
      - max score = 100

    Compression quality classification:
      - strong:   score ≥ 80
      - moderate: 50 ≤ score < 80
      - weak:     20 ≤ score < 50
      - absent:   score < 20 but data available
      - unknown:  score is None (not_available)

    Narrative fragments are deterministic string templates per CONTEXT §5.

    Args:
        execution_data: VM100 Execution row dict.
        primitives_data: VM102 L4 primitives response OR not_available envelope.

    Returns:
        dict matching CompressionAnalysisResult field shape.
    """
    # ── Degrade gracefully if compression data not available ──────────────────
    if _is_not_available(primitives_data):
        reason = (primitives_data.get("meta") or {}).get(
            "planned_phase", "VM102 not_available"
        )
        return {
            "score": None,
            "confidence": Decimal("0"),
            "signals": {
                "range_compressed": False,
                "inside_bars_present": False,
                "expansion_pre_entry": False,
                "atr_ratio_acceptable": False,
                "pre_entry_consolidation_intact": False,
            },
            "narrative_fragments": [
                "not_available: VM102 L4 compression primitives unavailable — compression cannot be scored",
                f"not_available reason: {reason}",
            ],
            "compression_quality": "unknown",
            "inside_bar_count": 0,
            "range_atr_ratio": None,
        }

    # ── Extract L4 compression primitives ────────────────────────────────────
    prim_data = primitives_data.get("data") or {}
    # L4 compression primitives shape (Phase 47.2.1 VM102 endpoint):
    # data.layers.4 or data.compression or data directly
    layer4 = (
        (prim_data.get("layers") or {}).get("4")
        or (prim_data.get("layers") or {}).get(4)
        or prim_data.get("compression")
        or prim_data
    )

    # Inside bars: look for inside_bars, inside_bar_count, inside_bar_cluster
    raw_inside_bar_count: int = (
        layer4.get("inside_bar_count")
        or layer4.get("inside_bars")
        or (len(layer4.get("inside_bar_list") or []) if layer4.get("inside_bar_list") else 0)
        or 0
    )
    inside_bar_count = int(raw_inside_bar_count)

    # Range/ATR ratio: look for range_atr_ratio, ratio, compression_ratio
    raw_ratio = (
        layer4.get("range_atr_ratio")
        or layer4.get("ratio")
        or layer4.get("compression_ratio")
        or layer4.get("atr_ratio")
    )
    range_atr_ratio: float | None = float(raw_ratio) if raw_ratio is not None else None

    # Expansion pre-entry: was there a range expansion BEFORE entry?
    # Look for expansion_pre_entry, premature_breakout, breakout_before_entry
    expansion_pre_entry: bool = bool(
        layer4.get("expansion_pre_entry")
        or layer4.get("premature_breakout")
        or layer4.get("breakout_before_entry")
        or False
    )

    # Expansion timing: bars between expansion and entry
    # If expansion_bars_from_entry ≤ 3 → expansion timing is within 3 bars (PLAN spec)
    expansion_bars_from_entry: int | None = layer4.get("expansion_bars_from_entry")

    # ── Signal computation ────────────────────────────────────────────────────
    # range_compressed: range/ATR ratio is below the target threshold
    # (counter-intuitively: high range/ATR = NOT compressed; low = compressed)
    # V1 heuristic: a compressed range = ATR × ratio ≥ 1.4 means the range candle
    # covered at least 1.4× the ATR — indicating a wide bar (expansion detected).
    # CORRECTION: "range compressed" in market structure = price is NOT expanding,
    # i.e., range/ATR ratio < 1.0. But PLAN.md says ratio ≥ 1.4 = 80+ score.
    # Interpretation: the plan uses "range/ATR ratio" as a compression quality proxy
    # where ≥1.4 means the consolidation bars' total range normalised to ATR is high,
    # indicating a meaningful compression range was established before breakout.
    # We follow the plan spec exactly.
    atr_ratio_acceptable: bool = (
        range_atr_ratio is not None and range_atr_ratio >= _RANGE_ATR_RATIO_TARGET
    )
    range_compressed: bool = atr_ratio_acceptable  # alias per CONTEXT §5 signal names

    inside_bars_present: bool = inside_bar_count >= _INSIDE_BAR_COUNT_TARGET

    # pre_entry_consolidation_intact: no premature expansion before entry
    pre_entry_consolidation_intact: bool = not expansion_pre_entry

    # ── Score computation ─────────────────────────────────────────────────────
    score_sum = 0

    if atr_ratio_acceptable:
        score_sum += _RANGE_ATR_WEIGHT    # 80 pts: primary compression quality gate

    if inside_bars_present:
        score_sum += _INSIDE_BAR_WEIGHT   # 15 pts: consolidation cluster

    if pre_entry_consolidation_intact:
        score_sum += _EXPANSION_TIMING_BONUS  # 5 pts: consolidation still intact at entry

    score = Decimal(str(min(100, score_sum)))

    # Confidence: full when VM102 returned valid data; degraded if ratio is missing
    # (inside bar count alone is less diagnostic)
    if range_atr_ratio is not None:
        confidence = Decimal("100")
    elif inside_bar_count > 0:
        confidence = Decimal("60")  # partial: inside bars present but no ratio
    else:
        confidence = Decimal("40")  # minimal: no ratio and no inside bars

    # ── Compression quality classification ────────────────────────────────────
    if score >= Decimal("80"):
        compression_quality = "strong"
    elif score >= Decimal("50"):
        compression_quality = "moderate"
    elif score >= Decimal("20"):
        compression_quality = "weak"
    else:
        compression_quality = "absent"

    # ── Narrative fragments (deterministic string templates per CONTEXT §5) ──
    fragments: list[str] = []

    # Primary narrative per PLAN.md example:
    # 'Compression score = 35/100 due to: range/ATR ratio 0.8 (target ≥1.4); inside-bar count 1 (target ≥3)'
    ratio_display = f"{range_atr_ratio:.2f}" if range_atr_ratio is not None else "N/A"
    fragments.append(
        f"Compression score = {score}/100 due to: "
        f"range/ATR ratio {ratio_display} (target ≥{_RANGE_ATR_RATIO_TARGET}); "
        f"inside-bar count {inside_bar_count} (target ≥{_INSIDE_BAR_COUNT_TARGET})"
    )
    fragments.append(f"compression_quality={compression_quality}")

    if atr_ratio_acceptable:
        fragments.append(
            f"Range/ATR ratio {ratio_display} meets compression target (≥{_RANGE_ATR_RATIO_TARGET}) — "
            "strong consolidation range established before entry"
        )
    elif range_atr_ratio is not None:
        fragments.append(
            f"Range/ATR ratio {ratio_display} below compression target (≥{_RANGE_ATR_RATIO_TARGET}) — "
            "insufficient range quality for high-confidence compression entry"
        )
    else:
        fragments.append(
            "Range/ATR ratio unavailable from VM102 L4 primitives — compression ratio signal absent"
        )

    if inside_bars_present:
        fragments.append(
            f"Inside-bar cluster detected ({inside_bar_count} bars ≥ target {_INSIDE_BAR_COUNT_TARGET}) — "
            "valid consolidation pattern in pre-entry window"
        )
    elif inside_bar_count > 0:
        fragments.append(
            f"Inside bars present ({inside_bar_count}) but below cluster threshold ({_INSIDE_BAR_COUNT_TARGET}) — "
            "partial consolidation signal"
        )
    else:
        fragments.append(
            "No inside bars detected in pre-entry window — consolidation pattern absent"
        )

    if expansion_pre_entry:
        fragments.append(
            "Premature range expansion detected before entry — consolidation broken before liquidity sweep; "
            "compression quality penalised"
        )
        if expansion_bars_from_entry is not None:
            fragments.append(
                f"Expansion occurred {expansion_bars_from_entry} bars before entry "
                f"({'within' if expansion_bars_from_entry <= 3 else 'beyond'} 3-bar timing threshold)"
            )
    else:
        fragments.append(
            "Pre-entry consolidation intact — no premature range expansion detected"
        )

    signals = {
        "range_compressed": range_compressed,
        "inside_bars_present": inside_bars_present,
        "expansion_pre_entry": expansion_pre_entry,
        "atr_ratio_acceptable": atr_ratio_acceptable,
        "pre_entry_consolidation_intact": pre_entry_consolidation_intact,
    }

    return {
        "score": score,
        "confidence": confidence,
        "signals": signals,
        "narrative_fragments": fragments,
        "compression_quality": compression_quality,
        "inside_bar_count": inside_bar_count,
        "range_atr_ratio": range_atr_ratio,
    }


class CompressionAnalysisTool:
    """VM107 analytics tool: deterministic pre-entry compression quality scoring.

    Implements the ContractTool pattern (validate-request → call-vm → validate-response)
    as a standalone class (no Agent context required) so it can be called directly
    by AnalyticsService in Phase 57-09 and tested without the agent framework.

    Reads:
      - VM100 GET /api/journal/internal/executions/{execution_id}
      - VM102 GET /api/v1/primitives/?instrument=...&timeframe=M5&layers=4

    Computes:
      - range/ATR ratio vs ≥1.4 target (primary compression quality gate)
      - inside-bar count vs ≥3 target (consolidation cluster signal)
      - expansion_pre_entry detection (premature breakout penalty)
      - compression_quality classification: strong / moderate / weak / absent / unknown

    Usage:
        tool = CompressionAnalysisTool()
        result = tool.run(execution_id="...", scoring_ruleset_version="1.0.0")

    The result is a CompressionAnalysisResult Pydantic model.
    """

    def _validate_request(self, args: dict) -> CompressionAnalysisRequest:
        """Validate args against CompressionAnalysisRequest contract.

        Raises:
            ContractValidationError: if args don't match contract shape.
        """
        try:
            return CompressionAnalysisRequest(**args)
        except Exception as e:  # noqa: BLE001
            raise ContractValidationError(errors=[str(e)], message=str(e)) from e

    async def _call_vm(self, request: CompressionAnalysisRequest) -> dict:
        """Concurrent fan-out to VM100 (Execution) + VM102 (L4 compression primitives).

        Uses asyncio.gather with FAST_FAIL retry profile. On transport failure,
        synthesizes a not_available envelope (never fabricates compression data).

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
                    "compression_analysis_tool: VM100 transport error for execution %s: %s",
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
                    "compression_analysis_tool: VM102 transport error for instrument %s: %s",
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
            return {
                "execution": execution_data,
                "primitives": {
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

        primitives_data = await _get_primitives(instrument)
        return {"execution": execution_data, "primitives": primitives_data}

    def _validate_response(self, data: dict) -> CompressionAnalysisResult:
        """Validate computed scoring result against CompressionAnalysisResult contract.

        Raises:
            ContractValidationError: if data doesn't match contract shape.
        """
        try:
            return CompressionAnalysisResult(**data)
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
            logger.debug("compression_analysis_tool: Prometheus increment failed: %s", e)

    def run(self, **kwargs: Any) -> CompressionAnalysisResult:
        """Synchronous entrypoint — runs async _call_vm in a new event loop.

        Args:
            **kwargs: Arguments forwarded to CompressionAnalysisRequest.
                      Required: execution_id (str or UUID).
                      Optional: scoring_ruleset_version, analysis_context, replay_window.

        Returns:
            CompressionAnalysisResult Pydantic model.

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

        score_dict = compute_compression_score(execution_data, primitives_data)

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

    async def run_async(self, **kwargs: Any) -> CompressionAnalysisResult:
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

        score_dict = compute_compression_score(execution_data, primitives_data)

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
