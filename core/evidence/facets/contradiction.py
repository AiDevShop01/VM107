"""Phase 168 Plan 05 Task 2 — Contradiction facet composer (ENRICHMENT).

Wraps the existing ``core/contradiction/ContradictionEngine`` WIRE-AS-IS
(``detect_divergence`` + ``grade_severity``) and maps the per-asset divergence
into the ``contradictions`` tuple of ``ContradictionFacet``. Contradiction is
ENRICHMENT: any failure (engine down, missing inputs) OMITS the facet with a
recorded reason — it NEVER raises out and NEVER sinks the pack (07 §1 Mode 3:
opposing evidence is surfaced, never averaged away).

The engine + its detection inputs (predicted / actual / sigma_historical from
the transmission engine + VM101, per B13) are injected on ``ctx.deps``; concrete
input plumbing is a 169 dependency. When either is absent the facet omits
honestly.
"""

from __future__ import annotations

from typing import Any

from fingpt_core.contracts.evidence_pack import ContradictionFacet, FacetIntegrity

from core.evidence import tiers
from core.evidence.facets import bounded

# 5-sigma divergence maps to maximum (1.0) contradiction severity.
_SIGMA_FULL_SCALE = 5.0


def _severity_from_sigma(sigma: float) -> float:
    val = bounded(abs(sigma) / _SIGMA_FULL_SCALE, 0.0, 1.0)
    return val if val is not None else 0.0


def _to_contradiction_facets(divergence: dict, inputs: dict) -> tuple[ContradictionFacet, ...]:
    predicted = inputs.get("predicted_per_asset") or {}
    actual = inputs.get("actual_per_asset") or {}
    indicator = inputs.get("indicator_id") or "indicator"
    out: list[ContradictionFacet] = []
    for asset, sigma in (divergence or {}).items():
        try:
            sigma_f = float(sigma)
        except (TypeError, ValueError):
            continue
        if sigma_f <= 0.0:
            continue  # no divergence => not a contradiction
        pred = predicted.get(asset)
        act = actual.get(asset)
        out.append(
            ContradictionFacet(
                claim_a=f"{indicator} predicted {asset} reaction={pred}",
                claim_b=f"{indicator} observed {asset} reaction={act}",
                severity=_severity_from_sigma(sigma_f),
            )
        )
    return tuple(out)


def compose_contradiction(ctx) -> tiers.FacetOutcome:
    engine = getattr(ctx.deps, "contradiction_engine", None)
    inputs: dict[str, Any] | None = getattr(ctx.deps, "contradiction_inputs", None)
    if engine is None:
        return tiers.FacetOutcome(
            name="contradiction",
            ok=False,
            integrity=FacetIntegrity.UNAVAILABLE,
            reason="no contradiction_engine configured",
        )
    if not inputs:
        return tiers.FacetOutcome(
            name="contradiction",
            ok=False,
            integrity=FacetIntegrity.UNKNOWN,
            reason="no contradiction inputs (predicted/actual/sigma — 169 wiring)",
        )

    try:
        divergence = engine.detect_divergence(
            inputs.get("indicator_id"),
            inputs.get("predicted_per_asset") or {},
            inputs.get("actual_per_asset") or {},
            inputs.get("sigma_historical") or {},
        )
        # grade_severity is wired-as-is; its result enriches downstream but the
        # facet severity is derived from the normalized divergence sigma.
        engine.grade_severity(divergence, inputs.get("active_beliefs") or [])
    except Exception as exc:  # ENRICHMENT: omit honestly, never propagate.
        return tiers.FacetOutcome(
            name="contradiction",
            ok=False,
            integrity=FacetIntegrity.PROVIDER_FAILURE,
            reason=f"contradiction engine failed: {type(exc).__name__}: {exc}",
        )

    facets = _to_contradiction_facets(divergence, inputs)
    if not facets:
        return tiers.FacetOutcome(
            name="contradiction",
            ok=False,
            integrity=FacetIntegrity.NEUTRAL,
            reason="no material divergence — no contradictions surfaced",
        )
    return tiers.FacetOutcome(
        name="contradiction", ok=True, integrity=FacetIntegrity.NEUTRAL, value=facets
    )
