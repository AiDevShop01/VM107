"""Phase 94 §H — MacroThemeEngine (deterministic, LLM-free).

The MacroThemeEngine evaluates a curated catalog of themes against an
evidence provider and persists :class:`Theme` objects. The strength score
is computed via DETERMINISTIC weighted evidence accumulation; the state
machine in :mod:`core.theme_engine.state_machine` derives the
:class:`ThemeState`. NO LLM anywhere on the score path (§H.3 lock).

Catalog layout: ``themes/catalog/<theme_id>.yaml`` (see
``themes/catalog/_schema.yaml``). Adding a theme = adding a YAML; no
engine code changes required.

Ranking on the dashboard uses ``Strength × Confidence`` per §H.4 — never
``Strength`` alone.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from contracts.economic_intelligence.themes import Theme, ThemeState
from core.theme_engine.state_machine import derive_next_state

logger = logging.getLogger(__name__)

CATALOG_DIR = Path(__file__).resolve().parent / "themes" / "catalog"

_TRIGGER_KEYS = ("indicator", "event_type", "forecast")


def _rule_signal_key(rule: dict[str, Any]) -> str:
    """Canonical signal key for a single evidence_rule.

    Mirrors the test helper — evidence providers emit signals using the
    same ``<trigger_key>:<value>`` format so matching is structural.
    """
    for key in _TRIGGER_KEYS:
        if key in rule:
            return f"{key}:{rule[key]}"
    raise ValueError(f"rule missing trigger key (expected one of {_TRIGGER_KEYS}): {rule}")


class MacroThemeEngine:
    """Deterministic theme engine — strength + state, no LLM.

    Construction loads the catalog from ``themes/catalog/*.yaml`` (excluding
    ``_schema.yaml``). Pass ``catalog_dir`` to override (e.g. tests).
    """

    def __init__(self, catalog_dir: Path | None = None) -> None:
        self._catalog_dir = catalog_dir if catalog_dir is not None else CATALOG_DIR
        self._catalog: dict[str, dict[str, Any]] = self._load_catalog(self._catalog_dir)

    # ------------------------------------------------------------------ API
    @property
    def catalog(self) -> dict[str, dict[str, Any]]:
        """Return the loaded catalog keyed by theme_id (read-only view)."""
        return self._catalog

    def compute_strength(
        self,
        theme_id: str,
        satisfied_rule_signals: Iterable[str],
    ) -> int:
        """Deterministic weighted accumulation.

        Each evidence_rule contributes its weight when its canonical signal
        is in ``satisfied_rule_signals``. Result is capped at 100.
        """
        spec = self._catalog[theme_id]
        satisfied = set(satisfied_rule_signals)
        total = 0
        for rule in spec["evidence_rules"]:
            key = _rule_signal_key(rule)
            if key in satisfied:
                total += int(rule["weight"])
        return min(100, max(0, total))

    def evaluate_theme(
        self,
        *,
        theme_id: str,
        satisfied_rule_signals: Iterable[str],
        previous_state: ThemeState | None = None,
        ticks_in_current_state: int = 0,
        confidence: float = 0.8,
        first_seen: str | None = None,
        now: datetime | None = None,
    ) -> Theme:
        """Compute strength + next state and return a typed :class:`Theme`.

        Confidence is supplied by the caller (typically from upstream
        evidence quality scoring). Ranking uses ``strength × confidence``
        per §H.4; this method does NOT apply that multiplication — it
        returns the raw strength on the Theme contract.
        """
        spec = self._catalog[theme_id]
        strength = self.compute_strength(theme_id, satisfied_rule_signals)

        current = previous_state if previous_state is not None else ThemeState.CANDIDATE
        next_state = derive_next_state(
            current_state=current,
            strength=strength,
            thresholds=spec["state_thresholds"],
            ticks_in_current_state=ticks_in_current_state,
        )

        ts_now = (now or datetime.now(tz=timezone.utc)).isoformat()
        first_seen_ts = first_seen or ts_now

        drivers = self._extract_drivers(spec)

        return Theme(
            theme_id=spec["theme_id"],
            label=spec.get("title", spec["theme_id"]),
            strength=float(strength),
            state=next_state,
            drivers=drivers,
            first_seen=first_seen_ts,
            last_changed=ts_now,
        )

    def evaluate_all(
        self,
        *,
        evidence_provider,
        previous_states: dict[str, ThemeState] | None = None,
        ticks: dict[str, int] | None = None,
        confidences: dict[str, float] | None = None,
        now: datetime | None = None,
    ) -> list[Theme]:
        """Evaluate every catalogued theme using ``evidence_provider``.

        ``evidence_provider`` is any callable accepting ``theme_id`` and
        returning an iterable of canonical rule-signal strings; in
        production the SnapshotCoordinator (94-07) wires it to live
        indicator/event data.
        """
        previous_states = previous_states or {}
        ticks = ticks or {}
        confidences = confidences or {}
        themes: list[Theme] = []
        for theme_id in self._catalog:
            try:
                signals = list(evidence_provider(theme_id))
            except Exception as exc:  # noqa: BLE001 — keep loop alive
                logger.warning(
                    "evidence_provider raised for %s: %s — using empty signal set",
                    theme_id,
                    exc,
                )
                signals = []
            themes.append(
                self.evaluate_theme(
                    theme_id=theme_id,
                    satisfied_rule_signals=signals,
                    previous_state=previous_states.get(theme_id),
                    ticks_in_current_state=ticks.get(theme_id, 0),
                    confidence=confidences.get(theme_id, 0.8),
                    now=now,
                )
            )
        return themes

    @staticmethod
    def rank_themes(themes: Iterable[dict[str, Any] | Theme]) -> list[dict[str, Any]]:
        """Sort themes by Strength × Confidence (§H.4).

        Accepts dicts (with 'strength' + 'confidence' keys) or Theme
        objects (confidence defaulted to 1.0 when not supplied separately).
        Returns the input as a list sorted descending by rank score.
        """
        out: list[dict[str, Any]] = []
        for t in themes:
            if isinstance(t, Theme):
                out.append({
                    "theme_id": t.theme_id,
                    "strength": float(t.strength),
                    "confidence": 1.0,
                })
            else:
                out.append(dict(t))
        out.sort(
            key=lambda d: float(d.get("strength", 0.0)) * float(d.get("confidence", 1.0)),
            reverse=True,
        )
        return out

    # --------------------------------------------------------- internals
    @staticmethod
    def _load_catalog(catalog_dir: Path) -> dict[str, dict[str, Any]]:
        if not catalog_dir.exists():
            raise FileNotFoundError(
                f"theme catalog directory not found: {catalog_dir}"
            )
        catalog: dict[str, dict[str, Any]] = {}
        for path in sorted(catalog_dir.glob("*.yaml")):
            if path.name == "_schema.yaml":
                continue
            with path.open() as f:
                spec = yaml.safe_load(f)
            if not isinstance(spec, dict) or "theme_id" not in spec:
                raise ValueError(f"invalid theme YAML (no theme_id): {path}")
            theme_id = spec["theme_id"]
            if theme_id in catalog:
                raise ValueError(f"duplicate theme_id {theme_id!r} in catalog")
            catalog[theme_id] = spec
        return catalog

    @staticmethod
    def _extract_drivers(spec: dict[str, Any]) -> list[str]:
        """Collect indicator IDs + event_type identifiers as drivers."""
        drivers: list[str] = []
        for rule in spec.get("evidence_rules", []):
            for key in _TRIGGER_KEYS:
                if key in rule:
                    drivers.append(f"{key}:{rule[key]}")
                    break
        # Append explicit supporting indicators (de-duplicated, preserving order).
        seen = set(drivers)
        for ind in spec.get("supporting_indicators", []):
            tag = f"indicator:{ind}"
            if tag not in seen:
                drivers.append(tag)
                seen.add(tag)
        return drivers


__all__ = ["MacroThemeEngine", "CATALOG_DIR"]
