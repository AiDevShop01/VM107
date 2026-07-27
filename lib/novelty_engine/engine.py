"""Core NoveltyEngine, NoveltyScore dataclass, and NoveltyDimensions enum.

Phase 66 Lock E1: NoveltyScore is ALWAYS deterministic, NEVER LLM-supplied.
Phase 66 Lock E2: NoveltyEngine colocated here (VM107/lib/) as shared infra
                  for all VM107 emitters — no per-emitter NoveltyEngine drift.

All composers gate LLM enrichment on `NoveltyScore.threshold_crossed == True`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Any


@dataclass(frozen=True)
class NoveltyScore:
    """Phase 66 Lock E1 canonical contract — always deterministic, never LLM-supplied.

    Produced by NoveltyEngine.score() and all dimension scorer functions.
    Composers use threshold_crossed to gate LLM enrichment calls.
    """

    score: float
    """Novelty score in [0.0, 1.0]. 0.0 = no novelty, 1.0 = maximum novelty."""

    contributing_factors: list[str]
    """Human-readable factor names explaining why the score is what it is."""

    threshold_crossed: bool
    """True when score >= threshold. Composers use this to gate LLM enrichment."""

    reason_codes: list[str]
    """Machine-parseable codes (e.g. 'FIRST_EVER_OCCURRENCE', 'Z_SCORE_GT_2', 'AUTH_FED')."""


class NoveltyDimensions(str, Enum):
    """The 5 novelty dimensions tracked by the NoveltyEngine.

    Phase 66 Lock E1: Each dimension maps to a scorer function in its own module.
    V1 (Phase 83): MACRO is live; REGIME/STRUCTURAL/VOLATILITY/BEHAVIORAL are stubs.
    V2+ (Phase 66): Stubs will be filled by future Phase 66 emitter authors.
    """

    MACRO = "macro_novelty"
    REGIME = "regime_novelty"
    STRUCTURAL = "structural_novelty"
    VOLATILITY = "volatility_novelty"
    BEHAVIORAL = "behavioral_novelty"


class NoveltyEngine:
    """Shared scorer across all VM107 emitters (Phase 66 Lock E2 — colocated infra).

    Dispatches to per-dimension scorer functions. In V1, only MACRO has a live
    implementation; the other 4 dimensions raise NotImplementedError (stubs
    for future Phase 66 emitter authors to implement against).

    Usage::

        engine = NoveltyEngine()
        result = engine.score(NoveltyDimensions.MACRO, payload, threshold=0.5)
        if result.threshold_crossed:
            # call LLM enrichment
            ...

    For tests, pass an in-memory dict-based history_provider. In production,
    pass a Redis-backed callable that returns a prior-occurrence count for an
    indicator_code.
    """

    def __init__(self, history_provider: Optional[Callable] = None) -> None:
        """Create a NoveltyEngine.

        Args:
            history_provider: Optional callable(indicator_code: str) -> int
                returning the prior occurrence count for cold-start detection.
                If None, cold-start detection is skipped (score_macro treats
                every indicator as if it has prior history).
        """
        self._history = history_provider

        # Lazy import to keep test surface clean and avoid circular imports
        from .macro import score_macro
        from .regime import score_regime
        from .structural import score_structural
        from .volatility import score_volatility
        from .behavioral import score_behavioral

        self._dispatch: dict[NoveltyDimensions, Callable] = {
            NoveltyDimensions.MACRO: score_macro,
            NoveltyDimensions.REGIME: score_regime,
            NoveltyDimensions.STRUCTURAL: score_structural,
            NoveltyDimensions.VOLATILITY: score_volatility,
            NoveltyDimensions.BEHAVIORAL: score_behavioral,
        }

    def score(
        self,
        dimension: NoveltyDimensions,
        payload: dict,
        threshold: float = 0.5,
    ) -> NoveltyScore:
        """Score a payload against a single novelty dimension.

        Args:
            dimension: Which NoveltyDimension to evaluate.
            payload: Dimension-specific dict. See each scorer module's docstring
                     for the expected payload shape.
            threshold: Score threshold for threshold_crossed. Default 0.5.

        Returns:
            NoveltyScore — always deterministic.

        Raises:
            NotImplementedError: For REGIME/STRUCTURAL/VOLATILITY/BEHAVIORAL stubs.
        """
        scorer = self._dispatch[dimension]
        return scorer(payload, history_provider=self._history, threshold=threshold)

    def register_dimension(self, dimension: NoveltyDimensions, scorer: Callable) -> None:
        """Override the scorer for a dimension (for testing / future V2 plug-in).

        This allows Phase 66 emitter authors to slot in a real scorer without
        patching the module. Prefer sub-classing or dependency injection.
        """
        self._dispatch[dimension] = scorer

    # ── Config-driven thresholds (Phase 66 checker WARNING 2) ────────────────
    # Restored 2026-07-27: the Phase 83-08 "V1" rewrite dropped these accessors
    # while the DISCOVERIES composer
    # (emitters/intelligence_feed_discoveries_composer.py) still calls
    # get_discoveries_threshold() at __init__ — every /intelligence_feed/
    # discoveries request was raising AttributeError. Thresholds load from the
    # shared novelty_config.yaml; NEVER hardcode them at a call site (WARNING 2).

    # Documented defaults — used ONLY if novelty_config.yaml can't be located.
    _DEFAULT_NARRATIVE_THRESHOLD = 0.7
    _DEFAULT_DISCOVERIES_THRESHOLD = 0.85

    @staticmethod
    def _find_novelty_config() -> Optional[Any]:
        """Locate novelty_config.yaml. engine.py lives at
        <app_root>/lib/novelty_engine/engine.py, so the canonical config is at
        <app_root>/emitters/novelty_config.yaml (66-02)."""
        from pathlib import Path

        here = Path(__file__).resolve()
        app_root = here.parents[2]
        candidates = [
            here.parent / "novelty_config.yaml",             # colocated (future-proof)
            app_root / "emitters" / "novelty_config.yaml",   # canonical (66-02)
            app_root / "services" / "novelty_config.yaml",   # services copy
        ]
        for c in candidates:
            if c.is_file():
                return c
        return None

    def _load_thresholds(self) -> None:
        """Lazily load + cache narrative/discoveries thresholds from config.

        Falls back to documented defaults (0.7 / 0.85) only if the config file
        cannot be found or parsed — a downstream composer must never crash just
        because config discovery failed."""
        if getattr(self, "_thresholds_loaded", False):
            return
        narrative = self._DEFAULT_NARRATIVE_THRESHOLD
        discoveries = self._DEFAULT_DISCOVERIES_THRESHOLD
        cfg_path = self._find_novelty_config()
        if cfg_path is not None:
            try:
                import yaml

                with open(cfg_path) as fh:
                    cfg = yaml.safe_load(fh) or {}
                narrative = float(
                    cfg.get("narrative_threshold", cfg.get("threshold", narrative))
                )
                discoveries = float(cfg.get("discoveries_threshold", discoveries))
            except Exception:  # noqa: BLE001 — defensive; keep defaults on any error
                pass
        self._narrative_threshold = narrative
        self._discoveries_threshold = discoveries
        self._thresholds_loaded = True

    def get_narrative_threshold(self) -> float:
        """Narrative novelty gate (config-driven, WARNING 2). Default 0.7."""
        self._load_thresholds()
        return self._narrative_threshold

    def get_discoveries_threshold(self) -> float:
        """Stricter DISCOVERIES novelty gate (config-driven, WARNING 2). Default
        0.85. MUST be > narrative_threshold (CONTEXT.md §4 lock) so discoveries
        stay rare and meaningful."""
        self._load_thresholds()
        return self._discoveries_threshold

    def get_threshold(self) -> float:
        """Backward-compat alias for get_narrative_threshold() (Plan 66-01)."""
        return self.get_narrative_threshold()
