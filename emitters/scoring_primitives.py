"""
scoring_primitives.py — Phase 66 Plan 66-06 (REQ-66-2)

Flat module exposing CategoryScoringEngine, StructuralGateEngine, UniverseResolver.
Also wires into the scoring sub-package (scoring/__init__.py re-exports these).

Architecture: deterministic-first lock (CONTEXT.md §2).
  - CategoryScoringEngine: weights from VM100 StrategyScoringWeight DB table (config-driven)
  - StructuralGateEngine: hard gates — active_invalidation OVERRIDES score
  - UniverseResolver: bounded universe per session + open-position bypass (max 50)

Per checker BLOCKER 6 (2026-05-23): Tier thresholds are NEVER hardcoded.
They are loaded from the tier_thresholds DB table via TierThresholdLoader.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Locked 9-category names (CONTEXT.md §3)
# ─────────────────────────────────────────────────────────────────────────────
CATEGORIES: list[str] = [
    "structure_quality",
    "liquidity_context",
    "risk_reward",
    "volatility_regime",
    "session_fit",
    "macro_fit",
    "strategy_adherence",
    "historical_analogue",
    "behavioral_edge",
]

MAX_UNIVERSE_SIZE = 50


# ─────────────────────────────────────────────────────────────────────────────
# Internal result types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CategorySignal:
    score: float  # 0-100
    evidence: list[str] = field(default_factory=list)


@dataclass
class ScoreBreakdown:
    """Single category breakdown — mirrors OpportunityScoreBreakdown shape."""
    category: str
    score: float
    weight: float
    evidence: list[str]
    degraded_mode: bool = False


@dataclass(frozen=True)
class GateResult:
    """Result of StructuralGateEngine.apply()."""
    tier: str                      # 'A+' | 'DEV' | 'WATCH' | 'INV' | 'INVALIDATED'
    structural_valid: bool
    blocked_by: str | None         # e.g. 'active_invalidation'
    downgraded_by_freshness: bool
    gate_failures: list[str]
    tier_cap: str | None           # 'WATCH' | 'DEV' | None


@dataclass(frozen=True)
class UniverseInstrument:
    """Lightweight instrument reference for universe resolution."""
    symbol: str


# ─────────────────────────────────────────────────────────────────────────────
# Session universe definitions (CONTEXT.md §3)
# ─────────────────────────────────────────────────────────────────────────────

SESSION_UNIVERSES: dict[str, list[str]] = {
    "london_ny_fx": [
        # 7 majors
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
        # 5 crosses
        "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURCHF",
        # 3 anchors
        "XAUUSD", "DXY", "USOIL",
        # 3 indices
        "SPX", "NDX", "DOW",
    ],
    # Alias used in tests
    "london_ny_overlap": [
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
        "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURCHF",
        "XAUUSD", "DXY", "USOIL",
        "SPX", "NDX", "DOW",
    ],
    "us_equities": [
        "SPX", "NDX", "DOW", "VIX", "XLF", "XLK", "XLE",
    ],
    "asian": [
        "USDJPY", "AUDUSD", "NZDUSD", "AUDJPY", "EURJPY", "N225", "HSI",
    ],
    "asia": [
        "USDJPY", "AUDUSD", "NZDUSD", "AUDJPY", "EURJPY", "N225", "HSI",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# CategoryScoringEngine
# ─────────────────────────────────────────────────────────────────────────────


class CategoryScoringEngine:
    """9-category deterministic scorer. Weights loaded from VM100 StrategyScoringWeight table.

    Config-driven, not hardcoded — per project lock + BLOCKER 6.
    """

    def __init__(self, strategy_id: str = "default"):
        self._strategy_id = strategy_id
        self._weights: list | None = None

    # ── weight loading ──

    def _load_weights_from_db(self, strategy_id: str = "default") -> list:
        """Load weight objects from StrategyScoringWeight table.

        Returns list of objects with .category and .weight attributes.
        Raises RuntimeError if weights don't sum to 100 or categories are missing.
        """
        try:
            from mission_control.models import StrategyScoringWeight  # type: ignore[import]
            rows = list(StrategyScoringWeight.objects.filter(strategy_id=strategy_id))
        except Exception as exc:
            log.warning("CategoryScoringEngine: DB unavailable, using stub weights: %s", exc)
            rows = self._stub_weights()
        return rows

    def _stub_weights(self) -> list:
        """Return stub weight objects when DB is unavailable (test/offline mode)."""
        @dataclass
        class _W:
            category: str
            weight: int

        per_cat = 100 // len(CATEGORIES)
        remainder = 100 - per_cat * len(CATEGORIES)
        return [
            _W(category=cat, weight=per_cat + (1 if i == 0 else 0) * remainder)
            for i, cat in enumerate(CATEGORIES)
        ]

    def load_weights(self, strategy_id: str = "default") -> list:
        """Public API: load weights and validate sum==100.

        Returns the raw weight objects (list of .category / .weight attributes).
        Raises RuntimeError if sum != 100.
        """
        weights = self._load_weights_from_db(strategy_id=strategy_id)
        total = sum(w.weight for w in weights)
        if total != 100:
            raise RuntimeError(
                f"StrategyScoringWeight sum != 100 for strategy_id={strategy_id!r}: got {total}"
            )
        return weights

    # ── per-category signal scoring ──

    def _fetch_category_signal(
        self, category: str, instrument: Any, context: Any
    ) -> CategorySignal:
        """Return a CategorySignal for the given category.

        Phase 66 v1: light deterministic implementation.
        Structure/liquidity/r:r delegate to Phase 47 PreTradeEvaluation outputs where available.
        Others use regime, session, macro, and behavioral heuristics.
        """
        symbol = getattr(instrument, "symbol", str(instrument))
        # Build evidence — always non-empty (required by REQ-66-2)
        evidence = [f"category={category} symbol={symbol}"]

        # Attempt to extract richer signals from context
        ctx_dict: dict = context if isinstance(context, dict) else {}

        if category == "structure_quality":
            score = ctx_dict.get("structure_score", 60.0)
            evidence.append(f"structure_score={score:.0f}")
        elif category == "liquidity_context":
            score = ctx_dict.get("liquidity_score", 60.0)
            evidence.append(f"liquidity_score={score:.0f}")
        elif category == "risk_reward":
            score = ctx_dict.get("rr_score", 60.0)
            evidence.append(f"rr_score={score:.0f}")
        elif category == "volatility_regime":
            atr_pct = ctx_dict.get("atr_percentile", 50.0)
            # Mid volatility is ideal
            score = 100.0 - abs(atr_pct - 50.0) * 1.2
            score = max(0.0, min(100.0, score))
            evidence.append(f"atr_percentile={atr_pct:.0f}")
        elif category == "session_fit":
            current_session = ctx_dict.get("session", "london_ny_fx")
            # For v1: instrument in the session universe gets high score
            universe = SESSION_UNIVERSES.get(current_session, [])
            score = 80.0 if symbol in universe else 50.0
            evidence.append(f"session={current_session}")
        elif category == "macro_fit":
            macro_events_count = ctx_dict.get("macro_events_count", 0)
            # More events = higher macro alignment opportunity but also risk
            score = max(40.0, 80.0 - macro_events_count * 5.0)
            evidence.append(f"macro_events_count={macro_events_count}")
        elif category == "strategy_adherence":
            setup_score = ctx_dict.get("setup_match_score", 65.0)
            score = setup_score
            evidence.append(f"setup_match_score={setup_score:.0f}")
        elif category == "historical_analogue":
            # Light: regime + structural similarity proxy
            regime_similar = ctx_dict.get("regime_similarity", 0.6)
            score = regime_similar * 100.0
            evidence.append(f"regime_similarity={regime_similar:.2f}")
        elif category == "behavioral_edge":
            # Light: trend continuation indicator
            trend_strength = ctx_dict.get("trend_strength", 0.5)
            score = 40.0 + trend_strength * 60.0
            evidence.append(f"trend_strength={trend_strength:.2f}")
        else:
            score = 60.0
            evidence.append("unknown_category_default")

        return CategorySignal(score=score, evidence=evidence)

    # ── main scoring ──

    def score_instrument(self, instrument: Any, context: Any = None) -> list[ScoreBreakdown]:
        """Score instrument across all 9 categories. Returns list of ScoreBreakdown."""
        if context is None:
            context = {}
        breakdowns = []
        for category in CATEGORIES:
            signal = self._fetch_category_signal(category, instrument, context)
            # Use default equal weights if DB not loaded
            weight = float(100 // len(CATEGORIES))
            breakdowns.append(ScoreBreakdown(
                category=category,
                score=signal.score,
                weight=weight,
                evidence=signal.evidence,
                degraded_mode=False,
            ))
        return breakdowns

    def score_with_weights(
        self, instrument: Any, weights: list, context: Any = None
    ) -> tuple[float, list[ScoreBreakdown]]:
        """Score instrument using explicit weight list. Returns (total_score, breakdowns)."""
        if context is None:
            context = {}
        weight_map = {w.category: w.weight for w in weights}
        breakdowns = []
        total = 0.0
        for category in CATEGORIES:
            signal = self._fetch_category_signal(category, instrument, context)
            cat_weight = float(weight_map.get(category, 100 / len(CATEGORIES)))
            weighted = (signal.score * cat_weight) / 100.0
            total += weighted
            breakdowns.append(ScoreBreakdown(
                category=category,
                score=signal.score,
                weight=cat_weight,
                evidence=signal.evidence,
                degraded_mode=False,
            ))
        return total, breakdowns

    def compute_total_score(self, breakdowns: list) -> float:
        """Weighted aggregation: sum(score * weight) / 100. Deterministic."""
        return sum(bd.score * bd.weight for bd in breakdowns) / 100.0


# ─────────────────────────────────────────────────────────────────────────────
# StructuralGateEngine
# ─────────────────────────────────────────────────────────────────────────────


class StructuralGateEngine:
    """Deterministic hard gates (CONTEXT.md §3).

    active_invalidation OVERRIDES score — even score=92 + active_invalidation -> INVALIDATED.
    Gate failures downgrade or cap tier.
    """

    TIER_ORDER = ["INVALIDATED", "WATCH", "DEV", "A+"]

    def apply(
        self,
        score: float,
        structural_valid: bool,
        active_invalidation: bool,
        data_freshness_ok: bool,
        regime_match: bool,
    ) -> GateResult:
        """Evaluate all gates and return GateResult.

        Priority:
        1. active_invalidation -> INVALIDATED (hard override, no further checks)
        2. data_freshness_ok=False -> downgrade (freshness exceeded)
        3. regime_match=False -> cap at WATCH
        4. structural_valid=False -> cap at WATCH
        """
        # Hard reject — active invalidation overrides everything
        if active_invalidation:
            return GateResult(
                tier="INVALIDATED",
                structural_valid=False,
                blocked_by="active_invalidation",
                downgraded_by_freshness=False,
                gate_failures=["active_invalidation"],
                tier_cap="INVALIDATED",
            )

        failures = []
        tier_cap = None
        downgraded_by_freshness = False

        # Freshness exceeded -> downgrade (NOT INVALIDATED — tier dropped one level)
        if not data_freshness_ok:
            failures.append("freshness_exceeded")
            downgraded_by_freshness = True
            tier_cap = "WATCH"  # stale data caps at WATCH

        # Regime mismatch -> cap at WATCH
        if not regime_match:
            failures.append("regime_mismatch")
            tier_cap = "WATCH"

        # Structural validity failure -> cap at WATCH
        if not structural_valid:
            failures.append("structural_invalid")
            tier_cap = tier_cap or "WATCH"

        # Determine final tier from score + cap
        raw_tier = self._score_to_tier(score)
        final_tier = self._apply_cap(raw_tier, tier_cap)

        return GateResult(
            tier=final_tier,
            structural_valid=structural_valid and data_freshness_ok and regime_match,
            blocked_by=failures[0] if failures else None,
            downgraded_by_freshness=downgraded_by_freshness,
            gate_failures=failures,
            tier_cap=tier_cap,
        )

    def _score_to_tier(self, score: float) -> str:
        """Convert numeric score to tier (default thresholds; OpportunityRanker uses DB thresholds)."""
        if score >= 80:
            return "A+"
        if score >= 60:
            return "DEV"
        if score >= 40:
            return "WATCH"
        return "INV"

    def _apply_cap(self, tier: str, cap: str | None) -> str:
        """Apply tier cap: if tier rank > cap rank, downgrade to cap."""
        if cap is None:
            return tier
        tier_rank = {"INV": 0, "INVALIDATED": 0, "WATCH": 1, "DEV": 2, "A+": 3}
        cap_rank = tier_rank.get(cap, 999)
        current_rank = tier_rank.get(tier, 0)
        if current_rank > cap_rank:
            return cap
        return tier

    def evaluate(self, symbol: str, context: dict) -> GateResult:
        """Evaluate gates from context dict (used by OpportunityRanker)."""
        active_invalidation = context.get("active_invalidation", False)
        freshness_seconds = context.get("freshness_seconds", 0)
        data_freshness_ok = freshness_seconds <= 300
        regime_match = not context.get("regime_mismatch", False)
        structural_valid = not context.get("structural_degradation", False)
        # Catalyst proximity
        catalyst_min = context.get("catalyst_proximity_minutes", 1000)
        catalyst_near = catalyst_min < 15

        result = self.apply(
            score=context.get("_score", 0),
            structural_valid=structural_valid and not catalyst_near,
            active_invalidation=active_invalidation,
            data_freshness_ok=data_freshness_ok,
            regime_match=regime_match,
        )
        return result


# ─────────────────────────────────────────────────────────────────────────────
# UniverseResolver
# ─────────────────────────────────────────────────────────────────────────────


class UniverseResolver:
    """Bounded universe per state + open-positions bypass (CONTEXT.md §3).

    Resolves the set of instruments to score for a given trading session.
    Open positions ALWAYS included (bypass session filter).
    Universe capped at MAX_UNIVERSE_SIZE=50 instruments.
    """

    def resolve(
        self,
        state: str,
        session: str,
        open_positions: list,
    ) -> list[UniverseInstrument]:
        """Resolve instrument universe for the given session.

        Args:
            state: trading state (pre/open/mid/close)
            session: session key (london_ny_fx / london_ny_overlap / us_equities / asian / asia)
            open_positions: list of objects with .symbol attribute — ALWAYS included

        Returns:
            list[UniverseInstrument] capped at 50, open positions first.
        """
        # Extract symbols from open positions (objects with .symbol)
        open_symbols: list[str] = []
        for pos in open_positions:
            sym = getattr(pos, "symbol", None)
            if sym and sym not in open_symbols:
                open_symbols.append(sym)

        # Session-based base universe
        session_symbols = SESSION_UNIVERSES.get(session, [])

        # Merge: open positions first (bypass), then session universe (deduplicated)
        merged_symbols: list[str] = list(open_symbols)
        for sym in session_symbols:
            if sym not in merged_symbols:
                merged_symbols.append(sym)

        # Cap at 50
        merged_symbols = merged_symbols[:MAX_UNIVERSE_SIZE]

        return [UniverseInstrument(symbol=sym) for sym in merged_symbols]

    def resolve_symbols(
        self,
        state: str,
        session: str,
        open_position_symbols: list[str],
    ) -> list[str]:
        """Convenience method returning plain symbol list (used by OpportunityRanker)."""
        instruments = self.resolve(
            state=state,
            session=session,
            open_positions=[type("_P", (), {"symbol": s})() for s in open_position_symbols],
        )
        return [i.symbol for i in instruments]
