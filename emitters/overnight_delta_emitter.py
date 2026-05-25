"""OvernightDeltaEmitter — Phase 67 Plan 06 (REQ-67-3).

Mirror of MorningBriefEmitter / GlobalNarrativeEmitter 5-step pipeline,
specialized for the 4-bucket overnight-move synthesis:

    FX → BONDS → COMMODITIES → CRYPTO

Each bucket gets a deterministic ``BucketDelta`` (headline + notable_symbols
+ direction + magnitude_label + confidence + _demo) derived from overnight
price-move dicts.  Top-level ``overall_summary`` is always populated;
``llm_enriched_summary`` is additive — populated only when novelty crosses.

Bucket magnitude classification (planner discretion, plan action notes):
    small    : <0.3%
    moderate : 0.3-1.0%
    large    : 1.0-2.5%
    extreme  : >2.5%

Bucket direction:
    up    : all symbols positive
    down  : all symbols negative
    mixed : split signs
    flat  : all symbols within ±0.1%
"""
from __future__ import annotations

import logging
import statistics
import uuid
from datetime import datetime, timezone
from typing import Any

from emitters.contracts.overnight_delta import (
    BucketDelta,
    OvernightDeltaContract,
)
from emitters.degradation_policy_engine import DegradationPolicyEngine
from emitters.novelty_engine import NoveltyDimensions, NoveltyEngine
from emitters.source_health_registry import SourceHealthRegistry

log = logging.getLogger(__name__)


_CONTEXT_SOURCES = ("vm100", "vm102")

_TIER_CONFIDENCE: dict[str, float] = {
    "FULL": 0.95,
    "PARTIAL": 0.65,
    "DEGRADED": 0.30,
}


# Bucket → canonical symbol list (planner discretion; Plan 13 may make YAML-driven).
_BUCKET_SYMBOLS: list[tuple[str, list[str]]] = [
    ("FX", ["EURUSD", "USDJPY", "GBPUSD"]),
    ("BONDS", ["US10Y", "DE10Y", "JP10Y"]),
    ("COMMODITIES", ["GC", "CL", "HG"]),
    ("CRYPTO", ["BTC", "ETH"]),
]


def _classify_tier(missing_count: int) -> str:
    if missing_count == 0:
        return "FULL"
    if missing_count == 1:
        return "PARTIAL"
    return "DEGRADED"


def _classify_direction(moves: dict[str, float]) -> str:
    """Direction lookup per the plan action block thresholds."""
    if not moves:
        return "flat"
    values = list(moves.values())
    # Flat first — all within ±0.1%
    if all(abs(v) < 0.001 for v in values):
        return "flat"
    positive = [v for v in values if v > 0.001]
    negative = [v for v in values if v < -0.001]
    if positive and not negative:
        return "up"
    if negative and not positive:
        return "down"
    return "mixed"


def _classify_magnitude(moves: dict[str, float]) -> str:
    """Magnitude label from the absolute mean move."""
    if not moves:
        return "small"
    avg_abs = statistics.fmean(abs(v) for v in moves.values())
    if avg_abs < 0.003:
        return "small"
    if avg_abs < 0.010:
        return "moderate"
    if avg_abs < 0.025:
        return "large"
    return "extreme"


def _bucket_headline(name: str, moves: dict[str, float], direction: str, magnitude: str) -> str:
    if not moves:
        return f"{name}: overnight data unavailable"
    return f"{name}: {magnitude} {direction} move across {len(moves)} symbol(s)"


def _notable_symbols(moves: dict[str, float], limit: int = 3) -> list[str]:
    """Top-N symbols by absolute move size."""
    if not moves:
        return []
    return [
        s for s, _ in sorted(moves.items(), key=lambda kv: abs(kv[1]), reverse=True)
    ][:limit]


class OvernightDeltaEmitter:
    """4-bucket overnight delta synthesis emitter.

    Shared NoveltyEngine + SourceHealthRegistry per Phase 66 lock; same
    5-step pipeline shape as MorningBriefEmitter and GlobalNarrativeEmitter.
    """

    def __init__(
        self,
        novelty_engine: NoveltyEngine | None = None,
        health_registry: SourceHealthRegistry | None = None,
        degradation_engine: DegradationPolicyEngine | None = None,
        vm100_client: Any | None = None,
    ) -> None:
        self._novelty = novelty_engine or NoveltyEngine.get_shared_instance()
        self._health = health_registry or SourceHealthRegistry.get_shared_instance()
        self._degradation = degradation_engine or DegradationPolicyEngine()
        self._vm100 = vm100_client

    # ── Public API ─────────────────────────────────────────────────────────

    def get_overnight_delta(self, account_id: int) -> OvernightDeltaContract:
        """Build an OvernightDeltaContract for the given account."""
        self._health.clear()

        ctx: dict[str, Any] = {}
        try:
            ctx = self._assemble_context(account_id)
        except Exception as exc:
            log.warning(
                "overnight_delta_context_assembly_failed: %s(%s)",
                type(exc).__name__,
                exc,
            )
            for src_id in _CONTEXT_SOURCES:
                self._health.report(src_id, available=False, failure_reason=str(exc))

        health_snapshot = self._health.snapshot()
        missing_sources = [sid for sid, h in health_snapshot.items() if not h.available]
        tier = _classify_tier(len(missing_sources))

        # 4-bucket deterministic base
        buckets = self._assemble_buckets(ctx)

        # Top-level _demo if EVERY bucket is demo OR tier is DEGRADED
        all_buckets_demo = all(b.demo for b in buckets)
        top_demo = all_buckets_demo or tier == "DEGRADED"

        overall = self._build_overall_summary(buckets, tier)

        # Novelty scoring (shared engine)
        dims = self._compute_novelty_dims(ctx, buckets)
        novelty = self._novelty.score(dims)

        # Optional LLM enrichment — additive only
        llm_summary: str | None = None
        if getattr(novelty, "threshold_crossed", False) and not top_demo:
            llm_summary = self._call_llm(overall, ctx, buckets, novelty)

        return OvernightDeltaContract(
            delta_id=f"od-{uuid.uuid4().hex[:12]}",
            account_id=account_id,
            generated_at=datetime.now(timezone.utc),
            buckets=buckets,
            overall_summary=overall,
            llm_enriched_summary=llm_summary,
            confidence_score=_TIER_CONFIDENCE[tier],
            confidence_tier=tier,  # type: ignore[arg-type]
            missing_sources=missing_sources,
            _demo=top_demo,
        )

    # ── Snapshot-before-publish hook ─────────────────────────────────────────

    def persist_and_publish(
        self,
        delta: OvernightDeltaContract,
        invalidation_reason: str = "SCHEDULED",
    ) -> None:
        """Snapshot-before-publish (REQ-66-5 lock) — same wiring as MorningBrief."""
        try:
            from django.db import transaction
        except ImportError:
            return

        try:
            from mission_control.services.snapshot_invalidation_publisher import (
                SnapshotInvalidationPublisher,
            )
        except ImportError:
            try:
                from services.snapshot_invalidation_publisher import (  # type: ignore[import]
                    SnapshotInvalidationPublisher,
                )
            except ImportError:
                log.warning(
                    "overnight_delta_emitter.persist_and_publish: "
                    "SnapshotInvalidationPublisher not available — skipping publish"
                )
                return

        publisher = SnapshotInvalidationPublisher()
        with transaction.atomic():
            publisher.publish_after_commit(
                topic="mission_control.pre.overnight_delta",
                snapshot_id=delta.delta_id,
                account_id=delta.account_id,
                invalidation_reason=invalidation_reason,
            )

    # ── Internal helpers ───────────────────────────────────────────────────

    def _assemble_context(self, account_id: int) -> dict:
        """Assemble overnight-delta context via VM100 chokepoint when available."""
        ctx: dict[str, Any] = {"account_id": account_id}

        if self._vm100 is not None:
            try:
                payload = self._vm100.get_overnight_moves(account_id) or {}
                ctx.update(payload)
                self._health.report("vm100", available=True)
            except Exception as exc:
                self._health.report("vm100", available=False, failure_reason=str(exc))
            try:
                # Analytics calendar service (Phase 66-03) optional augmentation
                self._vm100.get_analytics_calendar(account_id)
                self._health.report("vm102", available=True)
            except Exception as exc:
                self._health.report("vm102", available=False, failure_reason=str(exc))
        else:
            # Test / offline path — both sources up, empty payload.
            self._health.report("vm100", available=True)
            self._health.report("vm102", available=True)

        return ctx

    def _assemble_buckets(self, ctx: dict) -> list[BucketDelta]:
        """Deterministic 4-bucket assembly in fixed order."""
        out: list[BucketDelta] = []
        for bucket_name, _symbols in _BUCKET_SYMBOLS:
            moves_key = f"{bucket_name.lower()}_overnight_moves"
            moves = ctx.get(moves_key) or {}

            direction = _classify_direction(moves)
            magnitude = _classify_magnitude(moves)
            headline = _bucket_headline(bucket_name, moves, direction, magnitude)
            notable = _notable_symbols(moves)
            demo = not bool(moves)
            confidence = 0.85 if not demo else 0.30

            out.append(
                BucketDelta(
                    bucket=bucket_name,  # type: ignore[arg-type]
                    headline=headline,
                    notable_symbols=notable,
                    direction=direction,  # type: ignore[arg-type]
                    magnitude_label=magnitude,  # type: ignore[arg-type]
                    confidence=confidence,
                    _demo=demo,
                )
            )
        return out

    def _build_overall_summary(self, buckets: list[BucketDelta], tier: str) -> str:
        if tier == "DEGRADED":
            return "Overnight delta operating in degraded mode — upstream sources unavailable."
        real_buckets = [b for b in buckets if not b.demo]
        if not real_buckets:
            return "Overnight delta unavailable across all buckets."
        moves_desc = ", ".join(f"{b.bucket} {b.direction}" for b in real_buckets)
        return f"Overnight session: {moves_desc}."

    def _compute_novelty_dims(
        self, ctx: dict, buckets: list[BucketDelta]
    ) -> NoveltyDimensions:
        """Derive novelty dims from bucket magnitudes."""
        extreme_count = sum(1 for b in buckets if b.magnitude_label == "extreme")
        large_count = sum(1 for b in buckets if b.magnitude_label == "large")
        return NoveltyDimensions(
            volatility_novelty=min(1.0, extreme_count * 0.5 + large_count * 0.25),
            cross_asset_divergence=(
                sum(1 for b in buckets if b.direction in ("up", "down")) >= 3
            ),
        )

    def _call_llm(
        self,
        overall: str,
        ctx: dict,
        buckets: list[BucketDelta],
        novelty: Any,
    ) -> str | None:
        """Optional LLM enrichment of the overall summary.

        Mock-seam for tests: patch.object(emitter, '_call_llm', return_value='...')
        """
        try:
            import anthropic  # type: ignore[import]

            client = anthropic.Anthropic()
            novelty_codes = getattr(novelty, "reason_codes", [])
            bucket_lines = "\n".join(
                f"- {b.bucket}: {b.headline}" for b in buckets if not b.demo
            )
            prompt = (
                f"Base overnight summary: {overall}\n\n"
                f"Bucket detail:\n{bucket_lines}\n\n"
                f"Novelty signals: {', '.join(novelty_codes) or 'none'}.\n\n"
                f"Add 1-2 sentences of cross-bucket operational insight. "
                f"Do not contradict any base fact."
            )
            message = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text.strip()
        except Exception as exc:
            log.warning(
                "overnight_delta_llm_enrichment_failed: %s(%s)",
                type(exc).__name__,
                exc,
            )
            return None
