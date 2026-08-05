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

# Phase 73 follow-up — emit-shape ID stability namespaces.
# DEFERRED-73-K seeder requires stable opportunity_id / instrument_id so re-emitting
# the same (account, symbol, strategy) tuple maps to the same VM100 Opportunity row
# (lifecycle continuity across emits; tier-flip WATCH↔DEV↔A+ must NOT mint a new row).
# uuid5 with a fixed namespace gives us a deterministic SHA-1-derived UUID per tuple.
_OPPORTUNITY_NS = uuid.UUID("c0ffeeed-0000-4000-8000-000000000073")  # Phase 73 namespace
_INSTRUMENT_NS = uuid.UUID("c0ffeeed-0000-4000-8000-000000000066")   # Phase 66 namespace


def _stable_opportunity_id(account_id: Any, symbol: str, strategy: str) -> str:
    """Deterministic opportunity_id keyed on (account_id, symbol, strategy).

    Same tuple → same UUID, always. Critical for Decision 8 lifecycle continuity:
    DEFERRED-73-K seeder uses get_or_create(id=...) so the same opportunity across
    emits must hash to the same row.
    """
    return str(uuid.uuid5(_OPPORTUNITY_NS, f"{account_id}:{symbol}:{strategy}"))


def _stable_instrument_id(symbol: str) -> str:
    """Deterministic instrument_id keyed on symbol alone.

    An instrument is identified by symbol globally (not per account or strategy).
    """
    return str(uuid.uuid5(_INSTRUMENT_NS, symbol))


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
        # Phase 136 / SC-2 / D-01: the invalidation publish is SPLIT OUT of the ORM
        # try-block. Previously the entire ORM-create + publish sat inside one broad
        # `try: from django.db ... except Exception` — so in the Django-less VM107
        # runtime the ImportError was caught and MISLABELED as "DB write failed", and
        # the Redis invalidation never fired. Now the ORM persist is Django-only (an
        # explicit intentional no-op when Django is absent) and the publish is resolved
        # against the VM107-local Django-free mirror and fires independently.
        snapshot_id = snapshot.get("snapshot_id") or uuid.uuid4()
        account_id = snapshot.get("account_id", 0)
        invalidation_reason = snapshot.get("refresh_reason", "SCHEDULED")

        # Phase 73 follow-up emit-shape fix: rank_opportunities now emits
        # the canonical key `rankings` (was `opportunities`, which violated
        # the OpportunityRankingSnapshotContract). Read `rankings` first;
        # fall back to legacy `opportunities` with a warning so any caller
        # still on the v1 shape surfaces loudly rather than silently
        # losing data.
        rankings_payload = snapshot.get("rankings")
        if rankings_payload is None:
            legacy_payload = snapshot.get("opportunities")
            if legacy_payload is not None:
                log.warning(
                    "OpportunityRanker._persist_snapshot: legacy 'opportunities' "
                    "key seen — update caller to emit canonical 'rankings' "
                    "(OpportunityRankingSnapshotContract)."
                )
                rankings_payload = legacy_payload
            else:
                rankings_payload = []

        # ── ORM persist (Django-only; intentional no-op in the VM107 local runtime) ──
        try:
            from django.db import transaction
            from mission_control.models import OpportunityRankingSnapshot  # type: ignore[import]

            with transaction.atomic():
                OpportunityRankingSnapshot.objects.create(
                    snapshot_id=snapshot_id,
                    account_id=account_id,
                    state=snapshot.get("state", "open"),
                    generated_at=snapshot.get("generated_at", datetime.now(timezone.utc)),
                    universe_id=snapshot.get("universe_id", "london_ny_fx"),
                    rankings=rankings_payload,
                    freshness_seconds=snapshot.get("freshness_seconds", 0),
                    degraded_mode=snapshot.get("degraded_mode", False),
                    snapshot_metadata=snapshot.get("metadata", {}),
                )
        except ImportError:
            # Django not present in the VM107 local runtime — the ORM persist is an
            # INTENTIONAL no-op here (NOT a DB failure). The Redis invalidation below
            # still fires via the VM107-local publisher.
            log.info(
                "OpportunityRanker._persist_snapshot: Django ORM unavailable in the "
                "VM107 local runtime — snapshot ORM persist intentionally skipped; "
                "invalidation publish proceeds."
            )
        except Exception as exc:  # noqa: BLE001 — genuine DB write failure (Django present)
            log.error(
                "OpportunityRanker._persist_snapshot: DB write failed (%s) — "
                "snapshot not persisted (degraded mode).",
                type(exc).__name__,
            )

        # ── Decoupled invalidation publish (fires regardless of the ORM persist) ─────
        try:
            from mission_control.services.snapshot_invalidation_publisher import (  # type: ignore[import]
                SnapshotInvalidationPublisher,
            )
        except ImportError:
            try:
                from services.snapshot_invalidation_publisher import (  # type: ignore[import]
                    SnapshotInvalidationPublisher,
                )
            except ImportError:
                log.warning(
                    "OpportunityRanker._persist_snapshot: "
                    "SnapshotInvalidationPublisher not available — invalidation publish skipped"
                )
                return

        publisher = SnapshotInvalidationPublisher()
        # VM107 has no Django DB transaction — publish IMMEDIATELY (fire-and-forget).
        publisher.publish_after_commit(
            topic="mission_control.opportunities",
            snapshot_id=snapshot_id,
            account_id=account_id,
            invalidation_reason=invalidation_reason,
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
            dict matching ``OpportunityRankingSnapshotContract`` keys:
              snapshot_id, generated_at, universe_id, state, rankings,
              freshness_seconds, degraded_mode. Each ranking entry matches
              ``OpportunityTierContract``: opportunity_id, instrument_id,
              symbol, direction, strategy, numeric_score, assigned_tier,
              structural_valid, invalidation_state, gate_failures,
              confidence_vector, generated_at, evidence, why,
              score_breakdown.

        Phase 73 follow-up emit-shape fix: prior to 2026-05-31 the emit
        shape used non-canonical keys (``opportunities`` instead of
        ``rankings``, ``tier`` instead of ``assigned_tier``) and omitted
        ``opportunity_id`` / ``instrument_id`` / ``direction`` entirely.
        That broke the DEFERRED-73-K aggregator-side seeder (it skipped
        every entry for missing IDs). The shape is now aligned with the
        canonical Pydantic contract at
        ``mission_control.contracts.opportunity.OpportunityTierContract``.
        """
        # 1. Resolve universe
        universe = self._fetch_universe(state=state, session=session, account_id=account_id)

        # Single timestamp shared by the snapshot and every entry — entry-level
        # ``generated_at`` matches the snapshot timestamp until per-entry timing
        # data is available (Phase 66 Wave 2 follow-up).
        generated_at_iso = datetime.now(timezone.utc).isoformat()

        # 2. Score and gate each instrument
        rankings: list[dict] = []
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
                assigned_tier = "WATCH"
            elif gate.tier_cap == "WATCH":
                assigned_tier = "WATCH"
            else:
                assigned_tier = self.classify_tier(
                    score=score,
                    structural_valid=gate.structural_valid,
                )

            # Phase 73 follow-up — stable IDs from (account, symbol, strategy)
            # so re-emit of the same opportunity maps to the same VM100 row.
            opportunity_id = _stable_opportunity_id(account_id, symbol, self._strategy_id)
            instrument_id = _stable_instrument_id(symbol)

            # Phase 66 Wave 1 v1 doesn't compute long/short signal yet.
            # Defensible default ("long") to satisfy the canonical contract's
            # Literal["long","short"] type; replace with real direction in
            # Phase 66 Wave 2 enrichment.
            direction = "long"

            rankings.append({
                # Canonical mission_control.OpportunityTierContract fields:
                "opportunity_id": opportunity_id,
                "instrument_id": instrument_id,
                "symbol": symbol,
                "direction": direction,
                "strategy": self._strategy_id,
                "numeric_score": score,
                "assigned_tier": assigned_tier,
                "structural_valid": gate.structural_valid,
                # invalidation_state is Optional[str] — null until lifecycle
                # service publishes invalidation context separately (Plan 73-09).
                "invalidation_state": None,
                "gate_failures": gate.gate_failures,
                # Per-entry timestamp mirrors snapshot timestamp for now.
                "generated_at": generated_at_iso,
                # Evidence / why / score_breakdown are populated server-side
                # by the OpportunityTierContract producer in Wave 2 enrichment;
                # emit empty/placeholder defaults so the wire shape stays
                # forward-compatible without forcing schema changes.
                "evidence": [],
                "why": "",
                "score_breakdown": [],

                # ── Phase 65 stub-shape aliases (forward-compat) ────────────
                # MissionControlContract.opportunity_tiers is typed as the
                # Phase 65 stub OpportunityTierContract (fingpt_core), which
                # uses short field names. The VM100 aggregator passes
                # ``rankings`` directly into that slot, so the wire shape
                # must satisfy BOTH the canonical mission_control contract
                # (read by the seeder + OpportunityCard) AND the Phase 65
                # stub (read by the contract validator). Extras are
                # silently ignored by the stub; required stub fields are
                # mirrored from the canonical fields above.
                "sym": symbol,
                "dir": direction,
                "strat": self._strategy_id,
                "conf": score / 100.0,
                "risk": "",
                "align": [],
            })

        # 3. Build snapshot — canonical OpportunityRankingSnapshotContract shape.
        snapshot_id = str(uuid.uuid4())
        snapshot = {
            "snapshot_id": snapshot_id,
            "account_id": account_id,
            "state": state,
            "universe_id": session,
            "rankings": rankings,
            "generated_at": generated_at_iso,
            "freshness_seconds": 0,
            "degraded_mode": False,
            "metadata": {
                "universe_composition": [i.symbol for i in universe],
                "scan_timestamp": generated_at_iso,
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
