"""similarity_analysis_tool — Phase 57 Plan 07.

Deterministic vectorless V1 similarity analysis for a given Execution.

Algorithm (per CONTEXT §4 LOCKED — deterministic vectorless only):
  1. Fetch execution details from VM100 (execution_id → instrument, strategy_id,
     regime, session, etc.)
  2. Call VM100 GET /api/journal/internal/snapshots/by-features to retrieve up
     to 50 historical snapshot candidates (last 90 days, same instrument or
     strategy_id). VM100 returns flat list — no ranking.
  3. Rank candidates in pure Python via weighted feature compare:
       setup_type              weight 0.20
       regime_classification   weight 0.15
       liquidity_context       weight 0.15
       atr_regime              weight 0.10
       session                 weight 0.10
       outcome_quality_bucket  weight 0.15
       execution_quality_bucket weight 0.05
       behavioral_markers      weight 0.10
     feature_match_indicator = 1.0 when both values present and match;
     0.5 when one value absent; 0.0 when both present but mismatch.
     similarity_score = sum(weight × match_indicator) × 100 (0-100)
  4. Sort candidates by similarity_score DESC; return top_n (default 10, max 50).

Returns SimilarityAnalysisResult with:
  - similar_trades: list[SimilarTrade] (sorted by similarity_score DESC)
  - top_n: int (actual top-N requested; capped at 50 by Pydantic Field(le=50))
  - narrative_fragments: explanation of match quality

Graceful degradation:
  When VM100 returns no candidates (new instrument, first 90 days), the tool
  returns SimilarityAnalysisResult(score=None, confidence=0, similar_trades=[],
  narrative_fragments=['not_available: no historical candidates'])

Prometheus telemetry (Pattern 26 — bounded cardinality):
  vm107_analytics_tool_calls_total{tool='similarity_analysis_tool', result_status=...}
  vm107_analytics_tool_duration_seconds{tool='similarity_analysis_tool'}

result_status values: success | degraded | transport_error | validation_error

Architecture notes (CONTEXT §7 + §9 + resolved Q2):
  - VM100 = system of record (returns flat candidates, no ranking)
  - VM107 = system of cognition (ranks candidates via weighted feature compare)
  - Master-plan alias get_similar_historical_trades → canonical similarity_analysis_tool
  - Master-plan alias find_similar_trades → canonical similarity_analysis_tool
  - FAST_FAIL retry profile per Phase 47.2.1 lock
  - NO embedding-database imports (REQ-57-10; V1 is intentionally vectorless)
  - NO LLM calls (deterministic-Python primary doctrine, CONTEXT §5)
  - top_n default=10, max=50 (resolved Q5)

Phase 60+ may add embedding-assisted reranking when behavioral cognition
workflows surface the need. Until then: pure Python weighted feature comparison only.
"""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any

import httpx

from fingpt_core.clients import RetryProfile, VM100Client
from fingpt_core.contracts.analytics.similarity import (
    SimilarityAnalysisRequest,
    SimilarityAnalysisResult,
    SimilarTrade,
)
from fingpt_core.contracts.errors import ContractValidationError

logger = logging.getLogger("fingpt.tools.similarity_analysis")

TOOL_NAME = "similarity_analysis_tool"

# ── Feature weights (sum = 1.00) ─────────────────────────────────────────────
# Per CONTEXT §4 + PLAN.md §task behavior
_WEIGHTS: dict[str, float] = {
    "setup_type":               0.20,
    "regime_classification":    0.15,
    "liquidity_context":        0.15,
    "atr_regime":               0.10,
    "session":                  0.10,
    "outcome_quality_bucket":   0.15,
    "execution_quality_bucket": 0.05,
    "behavioral_markers":       0.10,
}

# Minimum candidates threshold for "enough_history" signal
_MIN_HISTORY_COUNT = 5

# Similarity score threshold for "top_match_high_similarity" signal
_HIGH_SIMILARITY_THRESHOLD = 70.0


def _is_not_available(data: Any) -> bool:
    """Return True if data is a not_available envelope or transport error."""
    return not isinstance(data, (dict, list)) or (
        isinstance(data, dict) and (
            data.get("status") == "not_available"
            or data.get("error") is not None
        )
    )


def _normalize_value(value: Any) -> str | None:
    """Normalize a feature value to a comparable string (lowercased + stripped).

    Returns None for absent/null values.
    """
    if value is None:
        return None
    s = str(value).lower().strip()
    return s if s else None


def _extract_features(snapshot_or_execution: dict) -> dict[str, str | None]:
    """Extract comparable feature values from a snapshot candidate dict or execution dict.

    Feature sources within a candidate snapshot dict (as returned by
    /api/journal/internal/snapshots/by-features):
      - setup_type:               candidate['setup_type'] or candidate['metadata']['setup_type']
      - regime_classification:    candidate['regime_breakdown']['regime'] or candidate['regime_class']
      - liquidity_context:        candidate['liquidity_breakdown']['liquidity_context'] or ['liquidity_class']
      - atr_regime:               candidate['regime_breakdown']['volatility_class'] or ['atr_regime']
      - session:                  candidate['session'] or candidate['metadata']['session']
      - outcome_quality_bucket:   candidate['outcome_quality'] or candidate['result_r_bucket']
      - execution_quality_bucket: candidate['execution_quality_bucket']
      - behavioral_markers:       JSON string of sorted behavioral markers list

    All paths are defensive (missing keys → None).
    """
    d = snapshot_or_execution or {}
    metadata: dict = d.get("metadata") or {}
    regime_breakdown: dict = d.get("regime_breakdown") or {}
    liquidity_breakdown: dict = d.get("liquidity_breakdown") or {}
    behavioral_breakdown: dict = d.get("behavioral_breakdown") or {}

    # setup_type
    setup_type = (
        _normalize_value(d.get("setup_type"))
        or _normalize_value(metadata.get("setup_type"))
    )

    # regime_classification
    regime_classification = (
        _normalize_value(regime_breakdown.get("regime"))
        or _normalize_value(d.get("regime_class"))
        or _normalize_value(metadata.get("regime_class"))
        or _normalize_value(metadata.get("market_regime"))
    )

    # liquidity_context
    liquidity_context = (
        _normalize_value(liquidity_breakdown.get("liquidity_context"))
        or _normalize_value(d.get("liquidity_context"))
        or _normalize_value(d.get("liquidity_class"))
        or _normalize_value(metadata.get("liquidity_context"))
    )

    # atr_regime (maps to volatility_class in regime breakdown)
    atr_regime = (
        _normalize_value(regime_breakdown.get("volatility_class"))
        or _normalize_value(d.get("atr_regime"))
        or _normalize_value(d.get("volatility_class"))
        or _normalize_value(metadata.get("atr_regime"))
    )

    # session
    session = (
        _normalize_value(d.get("session"))
        or _normalize_value(metadata.get("session"))
        or _normalize_value(metadata.get("trade_session"))
    )

    # outcome_quality_bucket (win/loss bucketing from result_r)
    outcome_quality_bucket = (
        _normalize_value(d.get("outcome_quality"))
        or _normalize_value(d.get("result_r_bucket"))
        or _normalize_value(d.get("outcome_quality_bucket"))
    )
    # Compute from result_r if bucket not explicit
    if outcome_quality_bucket is None:
        result_r = d.get("result_r") or d.get("outcome_r")
        if result_r is not None:
            try:
                r_float = float(result_r)
                if r_float >= 2.0:
                    outcome_quality_bucket = "strong_win"
                elif r_float >= 0.5:
                    outcome_quality_bucket = "win"
                elif r_float >= -0.5:
                    outcome_quality_bucket = "scratch"
                elif r_float >= -2.0:
                    outcome_quality_bucket = "loss"
                else:
                    outcome_quality_bucket = "large_loss"
            except (TypeError, ValueError):
                pass

    # execution_quality_bucket
    execution_quality_bucket = (
        _normalize_value(d.get("execution_quality_bucket"))
        or _normalize_value(d.get("execution_quality_class"))
        or _normalize_value(metadata.get("execution_quality_bucket"))
    )
    # Compute from execution_quality_score if bucket not explicit
    if execution_quality_bucket is None:
        eq_score = d.get("execution_quality_score")
        if eq_score is not None:
            try:
                eq_float = float(eq_score)
                if eq_float >= 80:
                    execution_quality_bucket = "excellent"
                elif eq_float >= 60:
                    execution_quality_bucket = "good"
                elif eq_float >= 40:
                    execution_quality_bucket = "fair"
                else:
                    execution_quality_bucket = "poor"
            except (TypeError, ValueError):
                pass

    # behavioral_markers: sorted tuple of active behavioral signals
    behavioral_markers_raw: list[str] = []
    behavioral_signals: dict = behavioral_breakdown.get("signals") or d.get("behavioral_signals") or {}
    for marker_name, is_active in behavioral_signals.items():
        if is_active and isinstance(is_active, bool):
            # Only include negative behavioral markers (flags set to True)
            if any(k in marker_name.lower() for k in ("revenge", "fomo", "hesitation", "late")):
                behavioral_markers_raw.append(marker_name)

    # Fall back to explicit behavioral_markers field
    if not behavioral_markers_raw:
        markers_field = d.get("behavioral_markers") or metadata.get("behavioral_markers")
        if isinstance(markers_field, list):
            behavioral_markers_raw = [str(m) for m in markers_field]
        elif isinstance(markers_field, str):
            behavioral_markers_raw = [markers_field]

    behavioral_markers = (
        ",".join(sorted(behavioral_markers_raw)) if behavioral_markers_raw else None
    )

    return {
        "setup_type":               setup_type,
        "regime_classification":    regime_classification,
        "liquidity_context":        liquidity_context,
        "atr_regime":               atr_regime,
        "session":                  session,
        "outcome_quality_bucket":   outcome_quality_bucket,
        "execution_quality_bucket": execution_quality_bucket,
        "behavioral_markers":       behavioral_markers,
    }


def _feature_match_indicator(value_a: str | None, value_b: str | None) -> float:
    """Compute match indicator for a single feature pair.

    Rules:
      - Both present and match → 1.0
      - One or both absent    → 0.5 (neutral; no penalty for missing data)
      - Both present but mismatch → 0.0

    Partial match logic for regime: 'trending_bullish' ~ 'trending_bearish'
    both count as 'trending', so they match (indicator = 0.8 rather than 0.0).
    """
    if value_a is None or value_b is None:
        return 0.5  # neutral when data absent

    # Normalize regime families (trending_bullish / trending_bearish both = trending)
    a_norm = "trending" if value_a.startswith("trending") else value_a
    b_norm = "trending" if value_b.startswith("trending") else value_b

    if a_norm == b_norm:
        return 1.0

    # Same-family partial match for trend direction (bullish vs bearish within trend = partial)
    if value_a.startswith("trending") and value_b.startswith("trending"):
        return 0.8

    return 0.0


def compute_similarity_score(
    target_features: dict[str, str | None],
    candidate_features: dict[str, str | None],
) -> tuple[Decimal, list[str]]:
    """Compute weighted similarity score between target and candidate.

    Returns:
        (similarity_score_0_to_100, matched_feature_names)

    matched_features contains feature names where match_indicator >= 0.5
    (i.e., both present and matching, or at least one absent — any non-zero
    contribution is counted as "matched" for explanation purposes).
    """
    total_weight = 0.0
    weighted_score = 0.0
    matched_features: list[str] = []

    for feature_name, weight in _WEIGHTS.items():
        target_val = target_features.get(feature_name)
        candidate_val = candidate_features.get(feature_name)

        indicator = _feature_match_indicator(target_val, candidate_val)
        contribution = weight * indicator
        weighted_score += contribution
        total_weight += weight

        # Record as matched if indicator >= 0.5 (meaningful contribution)
        if indicator >= 0.5 and (target_val is not None or candidate_val is not None):
            matched_features.append(feature_name)

    # Normalize to 0-100 (total_weight should be ~1.0 per weights dict)
    if total_weight > 0:
        score_float = (weighted_score / total_weight) * 100.0
    else:
        score_float = 0.0

    score_float = max(0.0, min(100.0, score_float))
    similarity_score = Decimal(str(round(score_float, 2)))

    return similarity_score, matched_features


def rank_candidates(
    target_features: dict[str, str | None],
    candidates: list[dict],
    top_n: int,
) -> list[SimilarTrade]:
    """Rank candidate snapshots by weighted feature similarity.

    Pure Python weighted feature comparison — deterministic, vectorless (CONTEXT §4 LOCKED).

    Args:
        target_features: extracted feature dict for the target execution.
        candidates: list of candidate snapshot dicts from VM100.
        top_n: number of top results to return (1-50).

    Returns:
        List of SimilarTrade (sorted by similarity_score DESC, len <= top_n).
    """
    scored: list[tuple[Decimal, SimilarTrade]] = []

    for candidate in candidates:
        candidate_features = _extract_features(candidate)
        similarity_score, matched_features = compute_similarity_score(
            target_features, candidate_features
        )

        # Extract execution_id from candidate (key may vary by endpoint response shape)
        execution_id_raw = (
            candidate.get("execution_id")
            or candidate.get("execution")
        )
        snapshot_id_raw = candidate.get("snapshot_id") or candidate.get("id")
        outcome_r_raw = candidate.get("result_r") or candidate.get("outcome_r")

        if execution_id_raw is None:
            # Cannot build a SimilarTrade without execution_id — skip
            continue

        try:
            from uuid import UUID
            execution_uuid = UUID(str(execution_id_raw))
            snapshot_uuid = UUID(str(snapshot_id_raw)) if snapshot_id_raw else None
            outcome_r = Decimal(str(outcome_r_raw)) if outcome_r_raw is not None else None
        except (ValueError, TypeError):
            continue

        similar_trade = SimilarTrade(
            execution_id=execution_uuid,
            similarity_score=similarity_score,
            matched_features=matched_features,
            outcome_r=outcome_r,
            snapshot_id=snapshot_uuid,
        )
        scored.append((similarity_score, similar_trade))

    # Sort by similarity_score DESC
    scored.sort(key=lambda x: x[0], reverse=True)

    # Return top_n
    return [similar_trade for _, similar_trade in scored[:top_n]]


class SimilarityAnalysisTool:
    """VM107 analytics tool: deterministic vectorless V1 similarity analysis.

    Implements the ContractTool pattern (validate-request → call-vm → validate-response)
    as a standalone class (no Agent context required) so it can be called directly
    by AnalyticsService in Phase 57-09 and tested without the agent framework.

    Algorithm:
      1. Fetch execution from VM100 (to get instrument, strategy_id, and feature values)
      2. Fetch up to 50 historical snapshot candidates from VM100
         GET /api/journal/internal/snapshots/by-features?instrument=...&strategy_id=...
      3. Rank candidates by weighted feature compare (pure Python — deterministic, vectorless)
      4. Return top_n (default 10, max 50) as SimilarityAnalysisResult

    V1 design: no embedding databases, no vector search (CONTEXT §4 LOCKED).
    Phase 60+ may add advanced reranking when behavioral cognition stabilizes.

    Registry aliases:
      - get_similar_historical_trades (CONTEXT §9 master-plan vocabulary)
      - find_similar_trades

    Usage:
        tool = SimilarityAnalysisTool()
        result = tool.run(execution_id="...", scoring_ruleset_version="1.0.0", top_n=10)

    The result is a SimilarityAnalysisResult Pydantic model.
    """

    def _validate_request(self, args: dict) -> SimilarityAnalysisRequest:
        """Validate args against SimilarityAnalysisRequest contract.

        Raises:
            ContractValidationError: if args don't match contract shape.
        """
        try:
            return SimilarityAnalysisRequest(**args)
        except Exception as e:  # noqa: BLE001
            raise ContractValidationError(errors=[str(e)], message=str(e)) from e

    async def _call_vm(self, request: SimilarityAnalysisRequest) -> dict:
        """Fetch execution details and historical snapshot candidates from VM100.

        Step 1: GET /api/journal/internal/executions/{execution_id}
                → provides instrument, strategy_id via campaign, and feature context.
        Step 2 (concurrent after step 1): simultaneously fetch campaign (for strategy_id)
                and GET /api/journal/internal/snapshots/by-features?...
                → returns up to 50 historical snapshot candidates (flat, unranked).

        Resolved Q2: VM107 ranks; VM100 supplies candidates only.
        Resolved Q5: top_n default=10, max=50.
        Uses FAST_FAIL retry profile. On transport failure, synthesizes a
        not_available envelope for the affected data source.

        Returns:
            dict with keys:
              - 'execution': execution dict (or not_available envelope)
              - 'candidates': list of candidate snapshot dicts (or [])
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
                    "similarity_analysis_tool: VM100 transport error for execution %s: %s",
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
            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
                return {"status": "not_available"}

        async def _get_candidates(
            instrument: str | None,
            strategy_id: str | None,
        ) -> list:
            """Fetch snapshot candidates from VM100.

            VM100 returns flat candidates (unranked). Ranking is VM107's job
            (resolved Q2). Params follow the endpoint spec from 57-00.
            """
            params: dict[str, Any] = {"limit": 50, "days_lookback": 90}
            if instrument:
                params["instrument"] = instrument
            if strategy_id:
                params["strategy_id"] = strategy_id

            try:
                result = await vm100.get(
                    "api/journal/internal/snapshots/by-features",
                    params=params,
                )
                # Endpoint returns a list directly
                if isinstance(result, list):
                    return result
                # Or it may be wrapped in a dict
                if isinstance(result, dict):
                    return result.get("candidates") or result.get("results") or []
                return []
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(
                    "similarity_analysis_tool: VM100 candidates transport error: %s", e
                )
                return []
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    logger.warning(
                        "similarity_analysis_tool: VM100 candidates server error %s",
                        e.response.status_code,
                    )
                    return []
                raise

        try:
            # Step 1: fetch execution first (need campaign_id to get strategy_id)
            execution_data = await _get_execution()

            # Step 2: extract instrument + resolve campaign for strategy_id
            instrument: str | None = None
            strategy_id: str | None = None

            if not _is_not_available(execution_data):
                instrument = (
                    execution_data.get("instrument_id")
                    or execution_data.get("instrument")
                )
                campaign_id = execution_data.get("campaign_id")

                if campaign_id:
                    # Fetch campaign and candidates concurrently
                    campaign_data, candidates = await asyncio.gather(
                        _get_campaign(str(campaign_id)),
                        _get_candidates(instrument, None),
                    )
                    strategy_id = campaign_data.get("strategy_id") if not _is_not_available(campaign_data) else None
                else:
                    candidates = await _get_candidates(instrument, None)
            else:
                # Execution unavailable — can't filter by instrument or strategy
                candidates = []

        finally:
            await vm100.close()

        return {
            "execution": execution_data,
            "candidates": candidates,
        }

    def _validate_response(self, data: dict) -> SimilarityAnalysisResult:
        """Validate computed similarity result against SimilarityAnalysisResult contract.

        Raises:
            ContractValidationError: if data doesn't match contract shape.
        """
        try:
            return SimilarityAnalysisResult(**data)
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
            logger.debug("similarity_analysis_tool: Prometheus increment failed: %s", e)

    def _compute_result(
        self,
        execution_data: dict,
        candidates: list[dict],
        top_n: int,
    ) -> dict:
        """Compute SimilarityAnalysisResult dict from execution + candidates.

        Pure Python weighted feature compare (CONTEXT §4).

        Returns:
            dict matching SimilarityAnalysisResult field shape.
        """
        # Full degrade: no execution data
        if _is_not_available(execution_data):
            return {
                "score": None,
                "confidence": Decimal("0"),
                "signals": {
                    "enough_history": False,
                    "top_match_high_similarity": False,
                    "majority_winners": False,
                },
                "narrative_fragments": [
                    "not_available: Execution row unavailable — similarity analysis cannot be scored",
                ],
                "similar_trades": [],
                "top_n": top_n,
            }

        # No candidates: graceful degrade per test_not_available_envelope_handled
        if not candidates:
            return {
                "score": None,
                "confidence": Decimal("0"),
                "signals": {
                    "enough_history": False,
                    "top_match_high_similarity": False,
                    "majority_winners": False,
                },
                "narrative_fragments": [
                    "not_available: no historical candidates found within 90-day window "
                    "(new instrument or strategy — insufficient history for similarity scoring)"
                ],
                "similar_trades": [],
                "top_n": top_n,
            }

        # Extract target features from the execution row
        target_features = _extract_features(execution_data)

        # Rank candidates via weighted feature compare (pure Python, deterministic)
        top_similar = rank_candidates(target_features, candidates, top_n)

        # Compute aggregate similarity score = mean similarity_score of top-N
        if top_similar:
            mean_score = sum(float(t.similarity_score) for t in top_similar) / len(top_similar)
            score = Decimal(str(round(mean_score, 2)))
        else:
            score = None

        # Confidence degradation: < 5 comparable trades = reduced confidence
        enough_history = len(top_similar) >= _MIN_HISTORY_COUNT
        confidence_degrade = Decimal("0") if not top_similar else Decimal("0")

        if len(candidates) < _MIN_HISTORY_COUNT:
            confidence_degrade = Decimal("30")  # thin history pool

        confidence = max(Decimal("0"), Decimal("100") - confidence_degrade)

        # Compute signals
        top_match_high_similarity = (
            len(top_similar) > 0
            and float(top_similar[0].similarity_score) >= _HIGH_SIMILARITY_THRESHOLD
        )
        winning_count = sum(
            1 for t in top_similar
            if t.outcome_r is not None and float(t.outcome_r) > 0
        )
        majority_winners = (
            len(top_similar) > 0
            and winning_count > len(top_similar) / 2
        )

        signals = {
            "enough_history": enough_history,
            "top_match_high_similarity": top_match_high_similarity,
            "majority_winners": majority_winners,
        }

        # Narrative fragments
        narrative_fragments: list[str] = []
        if score is not None:
            narrative_fragments.append(
                f"Similarity score = {score}/100 (mean of top-{len(top_similar)} "
                f"matched trades from {len(candidates)} candidates)"
            )
        if not enough_history:
            narrative_fragments.append(
                f"Thin history pool: only {len(candidates)} candidates found in 90-day "
                f"window (< {_MIN_HISTORY_COUNT} preferred for reliable similarity stats)"
            )
        if top_match_high_similarity:
            narrative_fragments.append(
                f"Top match similarity {float(top_similar[0].similarity_score):.1f}/100 "
                "— high confidence match found"
            )
        if majority_winners:
            narrative_fragments.append(
                f"Historical pattern: {winning_count}/{len(top_similar)} similar trades "
                "were winning outcomes"
            )

        if score is None:
            score_final = None
        else:
            score_final = score

        return {
            "score": score_final,
            "confidence": confidence,
            "signals": signals,
            "narrative_fragments": narrative_fragments,
            "similar_trades": top_similar,
            "top_n": top_n,
        }

    def run(self, **kwargs: Any) -> SimilarityAnalysisResult:
        """Synchronous entrypoint — runs async _call_vm in a new event loop.

        Args:
            **kwargs: Arguments forwarded to SimilarityAnalysisRequest.
                      Required: execution_id (str or UUID).
                      Optional: top_n (default 10, max 50), scoring_ruleset_version,
                                analysis_context, replay_window.

        Returns:
            SimilarityAnalysisResult Pydantic model.

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
        candidates = combined.get("candidates") or []

        result_dict = self._compute_result(execution_data, candidates, request.top_n)

        if result_dict.get("score") is None or not result_dict.get("similar_trades"):
            result_status = "degraded"

        try:
            result = self._validate_response(result_dict)
        except ContractValidationError:
            result_status = "validation_error"
            self._increment_prometheus(result_status, time.monotonic() - start_time)
            raise

        self._increment_prometheus(result_status, time.monotonic() - start_time)
        return result

    async def run_async(self, **kwargs: Any) -> SimilarityAnalysisResult:
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
        candidates = combined.get("candidates") or []

        result_dict = self._compute_result(execution_data, candidates, request.top_n)

        if result_dict.get("score") is None or not result_dict.get("similar_trades"):
            result_status = "degraded"

        try:
            result = self._validate_response(result_dict)
        except ContractValidationError:
            result_status = "validation_error"
            self._increment_prometheus(result_status, time.monotonic() - start_time)
            raise

        self._increment_prometheus(result_status, time.monotonic() - start_time)
        return result
