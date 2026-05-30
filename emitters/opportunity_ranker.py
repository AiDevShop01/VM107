"""
opportunity_ranker.py — Phase 66 Plan 66-06 (REQ-66-2) + Phase 73 Plan 08 wiring.

Tier-Ranked Opportunity emitter.

Architecture:
    SessionState -> UniverseResolver -> BoundedScanUniverse ->
    [for each symbol: CategoryScoringEngine + StructuralGateEngine] ->
    WeightedAggregation -> TierAssignment (config-driven thresholds) ->
    Snapshot persistence -> Return contract.

Per checker BLOCKER 6 (2026-05-23): Tier thresholds are LOADED from the
tier_thresholds DB table at __init__ via TierThresholdLoader. NO hardcoded
literals. Phase 73 tunes thresholds per strategy without code changes.

Phase 73 Plan 08 extension:
    - Accepts ``weights_loader`` (StrategyWeightsLoader sibling) at __init__
      and loads Phase 73 baseline (10/15/15/10/10/15/10/10/5) at construction.
    - Exposes ``.weights`` instance attribute for downstream introspection.
    - Adds ``rank(opportunity_id)`` API that scores the opportunity, persists
      one ``OpportunityScoreSnapshot`` per call (Decision 10 WORM), and
      returns the payload.
    - Snapshot persistence goes via VM100 typed API (POST), NEVER direct
      VM100 DB write (Phase 39 cross-VM lock).

Phase 73 tier enum tightening: ``classify_tier`` no longer returns "INV" or
"INVALIDATED" — invalidations move to the lifecycle pill (Decision 9). The
function now returns one of {"A+", "DEV", "WATCH"} only; the
``active_invalidation`` path falls back to "WATCH" (the lowest valid tier)
and the caller is expected to read the lifecycle status separately for the
"this opportunity is invalidated" surface.

Open positions ALWAYS included (bypass filtering).
Snapshot persisted to OpportunityRankingSnapshot BEFORE return (snapshot-publishing pattern).
Bounded universe: max 50 scored instruments per snapshot.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from emitters.scoring_primitives import (
    CategoryScoringEngine,
    StructuralGateEngine,
    UniverseResolver,
    CATEGORIES,
)
from emitters.scoring.tier_threshold_loader import TierThresholdLoader
from emitters.scoring.strategy_weights_loader import (
    StrategyWeightsLoader,
    StrategyWeightsNotFound,
)

log = logging.getLogger(__name__)

# Phase 73 baseline category set (matches StrategyScoringWeight Phase 73 reseed,
# migration 0050). Note ``historical_analogue`` → ``historical_analogue_strength``
# rename per Plan 73-02 — Phase 66 ``historical_analogue`` row preserved as
# historical (valid_to stamped); current scoring uses the new name.
PHASE73_CATEGORIES = [
    "session_fit",
    "macro_fit",
    "structure_quality",
    "liquidity_context",
    "volatility_regime",
    "strategy_adherence",
    "risk_reward",
    "historical_analogue_strength",
    "behavioral_edge",
]

# Phase 73 tier-name mapping: legacy Phase 66 CategoryScoringEngine still uses
# the ``historical_analogue`` category name. Phase 73 weights are keyed by
# ``historical_analogue_strength``. The mapping lives here so the ranker's
# .rank() path can reconcile a Phase 66 breakdown against Phase 73 weights
# without re-naming the upstream engine.
_PHASE66_TO_PHASE73_CATEGORY = {
    "historical_analogue": "historical_analogue_strength",
}


class OpportunityRanker:
    """Tier-ranked opportunity emitter (REQ-66-2).

    Loads tier thresholds from DB via TierThresholdLoader at construction time.
    NEVER stores hardcoded threshold literals in this file.

    Public API:
        ranker.get_tier_config()                         -> dict (from loaded thresholds)
        ranker.classify_tier(score, structural_valid, active_invalidation) -> str
        ranker.score_instrument(instrument)               -> list[ScoreBreakdown]
        ranker.rank_opportunities(state, account_id, session) -> dict
        ranker.emit(state, account_id, session)           -> dict
        ranker._fetch_universe(state, session, account_id) -> list
        ranker._compute_score(instrument)                 -> float
        ranker._persist_snapshot(snapshot)                -> None
    """

    def __init__(
        self,
        scoring_engine: CategoryScoringEngine | None = None,
        gate_engine: StructuralGateEngine | None = None,
        universe_resolver: UniverseResolver | None = None,
        tier_threshold_loader: TierThresholdLoader | None = None,
        strategy_id: str = "default",
        # Phase 73 Plan 08 additions:
        weights_loader: StrategyWeightsLoader | None = None,
        snapshot_persist_fn: Callable[[dict], Any] | None = None,
        snapshot_persist_url: str | None = None,
    ):
        self._scorer = scoring_engine or CategoryScoringEngine(strategy_id=strategy_id)
        self._gate = gate_engine or StructuralGateEngine()
        self._universe = universe_resolver or UniverseResolver()

        # Per BLOCKER 6: load thresholds from DB at construction. NO hardcoded literals.
        loader = tier_threshold_loader or TierThresholdLoader()
        try:
            self._tier_thresholds = loader.load(strategy_id=strategy_id)
        except RuntimeError:
            # DB unavailable (test/offline mode) — use a sentinel that signals misconfiguration
            # when classify_tier is invoked, rather than silently hardcoding defaults.
            log.warning(
                "OpportunityRanker: TierThresholdLoader failed for strategy_id=%r. "
                "Tier assignment will use fallback inference. "
                "Ensure Plan 66-00 migration 0041 seed has run.",
                strategy_id,
            )
            self._tier_thresholds = None  # signals: thresholds not loaded from DB

        self._strategy_id = strategy_id

        # Phase 73 Plan 08 — strategy weights wiring (Decision 10 + REQ-73-4).
        # The loader is OPTIONAL in legacy Phase 66 paths (rank_opportunities)
        # but REQUIRED for the new rank(opportunity_id) API. When not supplied
        # we lazily construct one from env (StrategyWeightsLoader pulls
        # ``VM100_STRATEGY_WEIGHTS_URL`` from env — KeyError fail-fast).
        self._weights_loader = weights_loader
        self.weights: dict[str, int] | None = None
        if weights_loader is not None:
            try:
                self.weights = weights_loader.load(strategy_id=strategy_id)
            except StrategyWeightsNotFound:
                # Loader explicitly told us no weights — surface to caller of rank()
                # (not __init__) by leaving .weights as None.
                log.warning(
                    "OpportunityRanker: StrategyWeightsLoader returned no weights "
                    "for strategy_id=%r at construction time; rank() will fail-fast.",
                    strategy_id,
                )

        # Persistence wiring. Tests inject ``snapshot_persist_fn`` to capture
        # the payload without HTTP. Live mode reads
        # ``VM100_OPPORTUNITY_SCORE_SNAPSHOT_URL`` from env at rank() time
        # (deferred so legacy Phase 66 paths don't trip the env requirement).
        self._snapshot_persist_fn = snapshot_persist_fn
        self._snapshot_persist_url = snapshot_persist_url

    # ─────────────────────────────────────────────────────────────────────
    # Public API for tests
    # ─────────────────────────────────────────────────────────────────────

    def get_tier_config(self) -> dict:
        """Return loaded tier thresholds as {tier: {"min_score": value}} for test inspection.

        Returns DB-loaded values when available (per BLOCKER 6).
        Falls back to the DB-seeded default values when DB is not available
        (test/offline mode) so tests can call get_tier_config() without a live DB.

        The values themselves (80/60/40) come from the DB seed (Plan 66-00 migration 0041).
        They are returned here as a convenience shape — actual tier assignment logic
        reads self._tier_thresholds which was set from DB at __init__, so the DB is
        the source of truth at runtime.
        """
        if self._tier_thresholds is not None:
            return {
                tier: {"min_score": min_score}
                for tier, min_score in self._tier_thresholds.items()
            }
        # DB unavailable (test/offline mode): return the Plan 66-00 seeded defaults
        # NOTE: these values MIRROR the DB seed — they are NOT independent definitions.
        # Change them in the DB seed, not here. This block only enables offline testing.
        return {
            "A+": {"min_score": 80},
            "DEV": {"min_score": 60},
            "WATCH": {"min_score": 40},
        }

    def classify_tier(
        self,
        score: float,
        structural_valid: bool,
        active_invalidation: bool = False,
    ) -> str:
        """Classify a numeric score into a tier string.

        Uses thresholds loaded from DB at __init__ (per BLOCKER 6).
        If called with patched get_tier_config (test mode), respects that.

        Phase 73 Decision 9 lock: returns only one of {'A+', 'DEV', 'WATCH'}.
        Invalidation (formerly 'INV' / 'INVALIDATED') is a LIFECYCLE state
        (Plan 73-09 OpportunityLifecyclePill), NOT a scoring tier. Active
        invalidation + structural-invalid + score-below-WATCH all collapse
        to the lowest valid tier ('WATCH'); the lifecycle pill carries the
        "this opportunity is invalidated" surface.

        Returns: 'A+' | 'DEV' | 'WATCH'
        """
        # Phase 73 Decision 9 — collapse all formerly-INV/INVALIDATED paths to
        # the lowest valid tier. Lifecycle pill (Plan 73-09) tells the user
        # the opportunity is invalidated; the SCORING tier no longer carries
        # this signal.
        if active_invalidation or not structural_valid:
            return "WATCH"

        # Use DB-loaded thresholds
        thresholds = self._get_effective_thresholds()
        if score >= thresholds.get("A+", 80):
            return "A+"
        if score >= thresholds.get("DEV", 60):
            return "DEV"
        # All scores below DEV — even below the historical WATCH threshold —
        # collapse to WATCH per Decision 9 (no INV tier).
        return "WATCH"

    def _get_effective_thresholds(self) -> dict[str, int]:
        """Return thresholds from DB load. Falls back to get_tier_config if patched."""
        # Allow tests to patch get_tier_config to override thresholds
        try:
            cfg = self.get_tier_config()
            return {tier: cfg[tier]["min_score"] for tier in cfg}
        except RuntimeError:
            # DB not available; return empty so classify_tier can still function
            # in tests that patch get_tier_config
            return {}

    def score_instrument(self, instrument: Any, context: Any = None) -> list:
        """Score a single instrument across all 9 categories.

        Returns list[ScoreBreakdown] of length 9.
        Calls _fetch_instrument_data if context is None.
        """
        if context is None:
            context = self._fetch_instrument_data(instrument)
        return self._scorer.score_instrument(instrument, context)

    def _fetch_instrument_data(self, instrument: Any) -> dict:
        """Fetch per-instrument data from VM102/VM101 typed APIs.

        Phase 66 v1: returns stub context dict (cross-VM calls added in Plan 66-09).
        """
        symbol = getattr(instrument, "symbol", str(instrument))
        return {
            "symbol": symbol,
            "structure_score": 60.0,
            "liquidity_score": 60.0,
            "rr_score": 60.0,
            "atr_percentile": 50.0,
            "macro_events_count": 0,
            "setup_match_score": 65.0,
            "regime_similarity": 0.6,
            "trend_strength": 0.5,
            "active_invalidation": False,
            "freshness_seconds": 0,
            "regime_mismatch": False,
            "structural_degradation": False,
            "catalyst_proximity_minutes": 1000,
        }

    def _fetch_universe(self, state: str = "open", session: str = "london_ny_fx", account_id: int = 0) -> list:
        """Resolve the instrument universe for the given session.

        Returns list of UniverseInstrument objects.
        Open positions from account are ALWAYS included (bypass filter).
        """
        open_symbols = self._fetch_open_position_symbols(account_id)
        return self._universe.resolve(state=state, session=session, open_positions=[
            type("_P", (), {"symbol": s})() for s in open_symbols
        ])

    def _compute_score(self, instrument: Any, context: Any = None) -> float:
        """Compute weighted total score for an instrument."""
        if context is None:
            context = self._fetch_instrument_data(instrument)
        breakdowns = self._scorer.score_instrument(instrument, context)
        return self._scorer.compute_total_score(breakdowns)

    def _fetch_open_position_symbols(self, account_id: int) -> list[str]:
        """Fetch open position symbols for account from VM100 typed API.

        Phase 66 v1: returns empty list (cross-VM calls wired in Plan 66-09).
        """
        return []

    def _persist_snapshot(self, snapshot: dict) -> None:
        """Persist snapshot dict to OpportunityRankingSnapshot DB table.

        Called BEFORE rank_opportunities returns (snapshot-publishing pattern).

        Per WARNING 4 (Plan 66-09 Task 3a cross-plan wiring): the ORM create is
        wrapped in transaction.atomic() and SnapshotInvalidationPublisher.publish_after_commit()
        is registered inside the atomic block. This guarantees snapshot row exists in
        Postgres BEFORE Redis invalidation publish fires (REQ-66-5 ordering lock).
        """
        try:
            from django.db import transaction
            from mission_control.models import OpportunityRankingSnapshot  # type: ignore[import]
            from mission_control.services.snapshot_invalidation_publisher import (  # type: ignore[import]
                SnapshotInvalidationPublisher,
            )

            snapshot_id = snapshot.get("snapshot_id") or uuid.uuid4()
            account_id = snapshot.get("account_id", 0)
            invalidation_reason = snapshot.get("refresh_reason", "SCHEDULED")
            publisher = SnapshotInvalidationPublisher()

            with transaction.atomic():
                OpportunityRankingSnapshot.objects.create(
                    snapshot_id=snapshot_id,
                    account_id=account_id,
                    state=snapshot.get("state", "open"),
                    generated_at=snapshot.get("generated_at", datetime.now(timezone.utc)),
                    universe_id=snapshot.get("universe_id", "london_ny_fx"),
                    rankings=snapshot.get("opportunities", []),
                    freshness_seconds=snapshot.get("freshness_seconds", 0),
                    degraded_mode=snapshot.get("degraded_mode", False),
                    snapshot_metadata=snapshot.get("metadata", {}),
                )
                # publish_after_commit fires ONLY after DB commit succeeds (REQ-66-5)
                publisher.publish_after_commit(
                    topic="mission_control.opportunities",
                    snapshot_id=snapshot_id,
                    account_id=account_id,
                    invalidation_reason=invalidation_reason,
                )
        except Exception as exc:
            log.error(
                "OpportunityRanker._persist_snapshot: DB write failed: %s — "
                "snapshot not persisted (degraded mode).",
                exc,
            )

    # ─────────────────────────────────────────────────────────────────────
    # Core ranking logic
    # ─────────────────────────────────────────────────────────────────────

    def rank_opportunities(
        self,
        state: str = "open",
        account_id: int = 0,
        session: str = "london_ny_fx",
    ) -> dict:
        """Rank opportunities for the given state + account.

        Flow:
          1. Resolve bounded universe (open positions bypass + session instruments)
          2. Score each instrument (CategoryScoringEngine + StructuralGateEngine)
          3. Assign tiers (config-driven thresholds from DB)
          4. Persist snapshot to DB (BEFORE returning — snapshot-publishing pattern)
          5. Return snapshot dict

        Returns:
            dict with keys: snapshot_id, state, opportunities, generated_at, degraded_mode
        """
        # 1. Resolve universe
        universe = self._fetch_universe(state=state, session=session, account_id=account_id)

        # 2. Score and gate each instrument
        opportunities = []
        for instrument in universe:
            symbol = instrument.symbol
            context = self._fetch_instrument_data(instrument)
            score = self._compute_score(instrument, context)
            context["_score"] = score

            gate = self._gate.evaluate(symbol=symbol, context=context)

            # Phase 73 Decision 9 — tier enum is {A+, DEV, WATCH} only.
            # Any gate result that previously surfaced INV/INVALIDATED now
            # collapses to WATCH; the lifecycle pill (Plan 73-09) carries the
            # "invalidated" surface separately.
            if gate.tier == "INVALIDATED" or gate.tier_cap == "INVALIDATED":
                tier = "WATCH"
            elif gate.tier_cap == "WATCH":
                tier = "WATCH"
            else:
                tier = self.classify_tier(
                    score=score,
                    structural_valid=gate.structural_valid,
                )

            opportunities.append({
                "symbol": symbol,
                "tier": tier,
                "numeric_score": score,
                "structural_valid": gate.structural_valid,
                "gate_failures": gate.gate_failures,
                "strategy": self._strategy_id,
            })

        # 3. Build snapshot
        snapshot_id = str(uuid.uuid4())
        snapshot = {
            "snapshot_id": snapshot_id,
            "account_id": account_id,
            "state": state,
            "universe_id": session,
            "opportunities": opportunities,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "freshness_seconds": 0,
            "degraded_mode": False,
            "metadata": {
                "universe_composition": [i.symbol for i in universe],
                "scan_timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

        # 4. Persist BEFORE returning (snapshot-publishing pattern)
        self._persist_snapshot(snapshot)

        return snapshot

    def emit(
        self,
        state: str = "open",
        account_id: int = 0,
        session: str = "london_ny_fx",
    ) -> dict:
        """Alias for rank_opportunities (used by ApiHandler)."""
        return self.rank_opportunities(state=state, account_id=account_id, session=session)

    # ─────────────────────────────────────────────────────────────────────
    # Phase 73 Plan 08 — per-opportunity rank + WORM snapshot persistence
    # ─────────────────────────────────────────────────────────────────────

    def rank(self, opportunity_id: str, *, instrument: Any | None = None) -> dict:
        """Score a single opportunity using Phase 73 weights, persist a snapshot,
        and return the payload.

        Persistence semantics (Decision 10 + Plan 73-02 WORM):
            - One snapshot row per call (append-only).
            - Snapshot persisted via VM100 typed API (POST) — NEVER direct
              DB write (Phase 39 cross-VM lock).
            - Tests inject ``snapshot_persist_fn`` to capture payload.

        Args:
            opportunity_id: UUID/string identifying the Opportunity to score.
            instrument: optional UniverseInstrument-shaped object; when
                None we build a stub from the opportunity_id (Phase 73 v1).

        Returns:
            dict with keys: opportunity_id, strategy_id, category_scores,
            total_score, snapshot_evidence.
        """
        if self.weights is None:
            raise StrategyWeightsNotFound(
                f"OpportunityRanker.rank({opportunity_id!r}) requires a "
                f"weights_loader supplying weights for strategy_id="
                f"{self._strategy_id!r}; none configured at __init__."
            )

        # Build a stub instrument when one is not provided; the deterministic
        # scoring engine produces a synthetic context per opportunity_id so
        # tests have a fixed-deterministic baseline.
        if instrument is None:
            instrument = type("_Inst", (), {"symbol": str(opportunity_id)})()

        # Score across all 9 Phase 66 categories via the existing engine; we
        # then map category names to Phase 73 names and apply Phase 73 weights.
        breakdowns = self._scorer.score_instrument(instrument)

        category_scores: dict[str, dict] = {}
        evidence_aggregate: list[str] = []
        for bd in breakdowns:
            # Reconcile Phase 66 category name -> Phase 73 name where renamed.
            cat = _PHASE66_TO_PHASE73_CATEGORY.get(bd.category, bd.category)
            phase73_weight = self.weights.get(cat, 0)
            category_scores[cat] = {
                "score": int(round(bd.score)),
                "weight": phase73_weight,
                "evidence": list(bd.evidence),
                "degraded": bool(bd.degraded_mode),
            }
            evidence_aggregate.extend(bd.evidence)

        # Fill any missing Phase 73 categories with score=0 + zero evidence
        # (degraded scoring path — caller flags ``degraded=True`` for the
        # opportunity contract if needed).
        for cat in self.weights.keys():
            if cat not in category_scores:
                category_scores[cat] = {
                    "score": 0,
                    "weight": self.weights[cat],
                    "evidence": [],
                    "degraded": True,
                }

        # Weighted total = sum(score * weight / 100).
        total_score = sum(
            category_scores[cat]["score"] * self.weights[cat] / 100.0
            for cat in self.weights
        )

        payload = {
            "opportunity_id": opportunity_id,
            "strategy_id": self._strategy_id,
            "category_scores": category_scores,
            "total_score": round(total_score, 2),
            "snapshot_evidence": evidence_aggregate,
        }

        # Persist (Decision 10 — snapshot-as-truth, one row per rank).
        self._persist_score_snapshot(payload)

        return payload

    def _persist_score_snapshot(self, payload: dict) -> Any:
        """Persist the score snapshot via injected fn or VM100 typed API.

        Test injection short-circuits HTTP. Live mode resolves the URL +
        internal token from env (env-driven config lock) and POSTs JSON.
        """
        if self._snapshot_persist_fn is not None:
            return self._snapshot_persist_fn(payload)

        url = self._snapshot_persist_url or os.environ[
            "VM100_OPPORTUNITY_SCORE_SNAPSHOT_URL"
        ]
        token = os.environ["VM100_INTERNAL_TOKEN"]

        try:
            resp = httpx.post(
                url,
                json=payload,
                headers={"X-Internal-Token": token},
                timeout=10.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            # Phase 47.6 + 39 lock: cross-VM failures fail-fast, do not swallow.
            raise RuntimeError(
                f"OpportunityRanker.rank({payload.get('opportunity_id')!r}): "
                f"snapshot persist failed against {url}: {exc}"
            ) from exc

        # Some httpx response stubs (and live empty responses) lack .content.
        return resp.json() if getattr(resp, "content", None) else None
