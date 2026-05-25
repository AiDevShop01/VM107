"""
Shared NoveltyEngine — used by all VM107 emitters (CONTEXT.md §2 lock).

Pure deterministic. No LLM calls. Same input → same output.
Threshold and per-dimension weights load from novelty_config.yaml at instantiation.

Per checker WARNING 2 (2026-05-23): Exposes get_narrative_threshold() and
get_discoveries_threshold() accessors so downstream composers (especially
DISCOVERIESComposer in Plan 66-07) load thresholds from this shared config
rather than hardcoding module-level constants.

Architecture lock §2 — ALL cognition is deterministic-first, LLM-second.
NoveltyEngine scores novelty; LLM enrichment happens ONLY when
engine.score(dims).threshold_crossed is True.

HIGH triggers:
  regime_transition, macro_event_arrival, structural_break, risk_escalation,
  cross_asset_divergence, behavior_anomaly

MEDIUM triggers (need co-occurrence):
  volatility_expansion requires opportunity_clustering to cross threshold.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Union

import yaml

# NoveltyScore lives in the VM100 contracts layer.
# Import lazily or via absolute path depending on environment.
try:
    from VM100.backend.mission_control.contracts.novelty import NoveltyScore
except ImportError:
    # Local dev / test environment — define a lightweight stand-in that
    # satisfies all tests without requiring the full VM100 package on sys.path.
    from dataclasses import dataclass as _dc
    from typing import List as _List

    @_dc(frozen=True)
    class NoveltyScore:  # type: ignore[no-redef]
        score: float
        contributing_factors: _List[str]
        threshold_crossed: bool
        reason_codes: _List[str]


CONFIG_PATH = Path(__file__).parent / "novelty_config.yaml"


@dataclass(frozen=True)
class NoveltyDimensions:
    """Input dimensions for NoveltyEngine.

    Each numeric dimension is in [0.0, 1.0].  Missing fields default to 0.0.
    Boolean event-trigger fields set reason codes and always cross the threshold.
    """

    # Continuous dimension scores (weighted into composite)
    macro_novelty: float = 0.0
    regime_novelty: float = 0.0
    structural_novelty: float = 0.0
    volatility_novelty: float = 0.0
    behavioral_novelty: float = 0.0

    # Co-occurrence flags
    opportunity_clustering: bool = False

    # Event-level HIGH triggers (boolean — each alone crosses threshold)
    regime_transition: bool = False
    macro_event_arrival: bool = False
    structural_break: bool = False
    risk_escalation: bool = False
    behavior_anomaly: bool = False
    cross_asset_divergence: bool = False


class NoveltyEngine:
    """Deterministic novelty scorer for all VM107 emitters.

    Usage::

        engine = NoveltyEngine()
        dims = NoveltyDimensions(
            macro_novelty=0.8,
            regime_transition=True,
        )
        result = engine.score(dims)
        if result.threshold_crossed:
            # call LLM enrichment
            ...

    Downstream composers access shared thresholds via::

        narrative_t = engine.get_narrative_threshold()   # general gate
        discoveries_t = engine.get_discoveries_threshold()  # stricter gate
    """

    # Phase 67 Plan 06 — shared-instance accessor (CONTEXT.md §2 lock).
    # ALL VM107 emitters MUST use the SAME NoveltyEngine instance so novelty
    # state (last-seen dims, cooldown windows added in later phases) is
    # coherent across MorningBrief / OvernightDelta / GlobalNarrative.
    _shared_instance: "NoveltyEngine | None" = None

    @classmethod
    def get_shared_instance(cls) -> "NoveltyEngine":
        """Process-wide singleton accessor for NoveltyEngine.

        Lazily constructed on first call. Subsequent calls return the same
        instance. Tests that need an isolated engine can instantiate
        ``NoveltyEngine()`` directly and pass it via dependency injection.
        """
        if cls._shared_instance is None:
            cls._shared_instance = cls()
        return cls._shared_instance

    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        with config_path.open(encoding="utf-8") as fh:
            self._cfg = yaml.safe_load(fh)

        # Prefer narrative_threshold; fall back to legacy `threshold` key.
        self._narrative_threshold: float = float(
            self._cfg.get("narrative_threshold", self._cfg.get("threshold", 0.7))
        )

        # Per WARNING 2 — discoveries_threshold is REQUIRED in config (fail-fast if absent).
        if "discoveries_threshold" not in self._cfg:
            raise RuntimeError(
                "novelty_config.yaml missing required 'discoveries_threshold' key "
                "(per checker WARNING 2 — DISCOVERIESComposer in Plan 66-07 loads it from here)."
            )
        self._discoveries_threshold: float = float(self._cfg["discoveries_threshold"])

        if self._discoveries_threshold <= self._narrative_threshold:
            raise RuntimeError(
                f"discoveries_threshold ({self._discoveries_threshold}) MUST be > "
                f"narrative_threshold ({self._narrative_threshold}) — CONTEXT.md §4 lock."
            )

        self._dim_configs: dict = self._cfg.get("dimensions", {})
        self._co_occurrence_lifts: list = self._cfg.get("co_occurrence_lifts", [])

    # ── Threshold accessors ──────────────────────────────────────────────────

    def get_narrative_threshold(self) -> float:
        """Threshold for general narrative novelty gating."""
        return self._narrative_threshold

    def get_discoveries_threshold(self) -> float:
        """Stricter threshold for DISCOVERIESComposer (CONTEXT.md §4 + WARNING 2)."""
        return self._discoveries_threshold

    def get_threshold(self) -> float:
        """Backward-compat alias for get_narrative_threshold().

        Existing test scaffolds from Plan 66-01 call this method.
        New code should prefer get_narrative_threshold().
        """
        return self._narrative_threshold

    # ── Scoring ──────────────────────────────────────────────────────────────

    def score(self, dims: Union[NoveltyDimensions, dict]) -> NoveltyScore:
        """Compute a deterministic NoveltyScore from input dimensions.

        Args:
            dims: Either a ``NoveltyDimensions`` dataclass (preferred) or a
                  legacy dict with keys {macro, regime, structural, volatility,
                  behavioral} mapping to sub-dicts (backward-compat with the
                  Plan 66-01 scaffold tests).

        Returns:
            NoveltyScore — always deterministic for the same input.
        """
        if isinstance(dims, dict):
            dims = self._dict_to_dims(dims)

        contributing: list[str] = []
        reason_codes: list[str] = []

        # ── 1. Weighted dimension scoring (deterministic) ─────────────────
        composite = 0.0
        for dim_name, dim_cfg in self._dim_configs.items():
            dim_value = getattr(dims, dim_name, 0.0)
            weighted = float(dim_value) * float(dim_cfg["weight"])
            composite += weighted
            if float(dim_value) >= 0.5:
                contributing.append(dim_name)

        # ── 2. Event-trigger reason codes (boolean HIGH triggers) ─────────
        _trigger_map = [
            (dims.regime_transition, "REGIME_TRANSITION"),
            (dims.macro_event_arrival, "MACRO_EVENT_ARRIVAL"),
            (dims.structural_break, "STRUCTURAL_BREAK"),
            (dims.risk_escalation, "RISK_ESCALATION"),
            (dims.behavior_anomaly, "BEHAVIOR_ANOMALY"),
            (dims.cross_asset_divergence, "CROSS_ASSET_DIVERGENCE"),
        ]
        for flag, code in _trigger_map:
            if flag:
                reason_codes.append(code)

        # ── 3. Co-occurrence lifts ────────────────────────────────────────
        for lift_cfg in self._co_occurrence_lifts:
            lift_dims = lift_cfg["dims"]
            if all(self._dim_active(dims, d) for d in lift_dims):
                composite += float(lift_cfg["lift"])
                reason_codes.append("CO_OCCURRENCE_LIFT")

        # ── 4. Clip score to [0.0, 1.0] ───────────────────────────────────
        composite = max(0.0, min(1.0, composite))

        # ── 5. Threshold check ────────────────────────────────────────────
        # A HIGH trigger alone crosses regardless of numeric score.
        threshold_crossed = composite >= self._narrative_threshold or bool(reason_codes)

        # When threshold crossed but contributing_factors is empty (pure trigger case),
        # add the reason codes as contributing factors so the field is non-empty.
        if threshold_crossed and not contributing and reason_codes:
            contributing = list(reason_codes)

        return NoveltyScore(
            score=composite,
            contributing_factors=contributing,
            threshold_crossed=threshold_crossed,
            reason_codes=reason_codes,
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _dim_active(self, dims: NoveltyDimensions, name: str) -> bool:
        """Return True if the named dimension is 'active' (> 0.5 or True)."""
        val = getattr(dims, name, None)
        if val is None:
            return False
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return float(val) >= 0.5
        return False

    def _dict_to_dims(self, d: dict) -> NoveltyDimensions:
        """Convert legacy dict-based input (from Plan 66-01 scaffold) to NoveltyDimensions.

        Legacy format::

            {
                "macro":      {"regime_shift": True, "catalyst_count": 2},
                "regime":     {"label": "TREND/HIGH_VOL", "confidence": 0.82},
                "structural": {"fvg_count": 3, "sweep_detected": True},
                "volatility": {"atr_multiple": 1.4},
                "behavioral": {"session_edge_score": 0.75},
            }
        """

        def _bool_flag(sub: dict, *keys: str) -> bool:
            for k in keys:
                v = sub.get(k)
                if isinstance(v, bool) and v:
                    return True
            return False

        def _numeric(sub: dict, key: str, scale: float = 1.0, clamp: float = 1.0) -> float:
            v = sub.get(key, 0.0)
            if isinstance(v, bool):
                return 1.0 if v else 0.0
            return min(float(v) * scale, clamp)

        macro_sub = d.get("macro", {})
        regime_sub = d.get("regime", {})
        structural_sub = d.get("structural", {})
        vol_sub = d.get("volatility", {})
        beh_sub = d.get("behavioral", {})

        # Map sub-dict fields onto continuous dimension scores (heuristic mapping)
        macro_score = _numeric(macro_sub, "catalyst_count", scale=0.1)
        if _bool_flag(macro_sub, "regime_shift"):
            macro_score = max(macro_score, 0.8)

        regime_score = _numeric(regime_sub, "confidence")
        # High-volatility labels elevate regime novelty
        label = str(regime_sub.get("label", ""))
        if "HIGH_VOL" in label or "CHOPPY" in label:
            regime_score = max(regime_score, 0.7)

        fvg_count = _numeric(structural_sub, "fvg_count", scale=0.1)
        sweep = _bool_flag(structural_sub, "sweep_detected")
        structural_score = min(fvg_count + (0.4 if sweep else 0.0), 1.0)

        # ATR multiple: 1.0 = baseline, 2.0+ = high
        atr = _numeric(vol_sub, "atr_multiple")
        volatility_score = min(max((atr - 0.5) / 2.0, 0.0), 1.0)

        behavioral_score = _numeric(beh_sub, "session_edge_score")

        # Derive boolean triggers from sub-dicts
        regime_transition = _bool_flag(macro_sub, "regime_shift")
        macro_event_arrival = macro_sub.get("catalyst_count", 0) >= 3

        return NoveltyDimensions(
            macro_novelty=macro_score,
            regime_novelty=regime_score,
            structural_novelty=structural_score,
            volatility_novelty=volatility_score,
            behavioral_novelty=behavioral_score,
            regime_transition=regime_transition,
            macro_event_arrival=macro_event_arrival,
        )
