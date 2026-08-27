"""Phase 168 Plan 05 — per-facet composers for the EvidencePackAssembler.

Each composer takes the assembler's ``AssemblyContext`` and returns a typed
``tiers.FacetOutcome`` (a populated pack sub-model on success, or a typed
FacetIntegrity failure — NEVER a raise). Composers reach VM102 data ONLY through
typed client seams (G10): never a raw parquet/DB store, never ``compute_domain``.

``reuse_composers()`` returns the four reuse/typed facets (domain_state /
state_diff / contribution / contradiction) the assembler registers over its
deferred-placeholder defaults. The net-new signal_importance /
historical_context / prior_assessment facets land in 168-06.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

__all__ = [
    "reuse_composers",
    "netnew_composers",
    "bounded",
    "parse_dt",
    "to_iso",
    "is_latest_only_lookahead",
]

# A live run stamps knowledge_time ~ now; a small tolerance keeps sub-second
# clock skew from being mistaken for a historical (look-ahead) replay. Mirrors
# core/evidence/tools/quant_tools.py::_LOOKAHEAD_TOLERANCE.
LOOKAHEAD_TOLERANCE = timedelta(seconds=5)


def bounded(value: Any, lo: float, hi: float) -> float | None:
    """Coerce to a float clamped into [lo, hi]; ``None`` stays ``None`` (honest)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, f))


def parse_dt(value: Any) -> datetime | None:
    """Best-effort ISO-8601 -> datetime; never raises (returns None on failure)."""
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def is_latest_only_lookahead(knowledge_time: datetime, *, latest_only: bool = True) -> bool:
    """Constitution 18: a latest-only read served for a MATERIALLY-PAST as-of is
    a look-ahead. A live run (kt ~ now) is not flagged."""
    if not latest_only:
        return False
    now = datetime.now(timezone.utc)
    kt = knowledge_time
    if kt.tzinfo is None:
        kt = kt.replace(tzinfo=timezone.utc)
    return kt < now - LOOKAHEAD_TOLERANCE


def reuse_composers() -> dict[str, Callable]:
    """Return the reuse/typed facet composers to register on the assembler.

    Lazy imports avoid an import cycle (submodules import shared helpers from
    this package). The assembler registers these over its honest UNAVAILABLE
    defaults for the four reuse facets.
    """
    from core.evidence.facets.contradiction import compose_contradiction
    from core.evidence.facets.contribution import compose_contribution
    from core.evidence.facets.domain_state import compose_domain_state
    from core.evidence.facets.state_diff import compose_state_diff

    return {
        "domain_state": compose_domain_state,
        "state_diff": compose_state_diff,
        "contribution": compose_contribution,
        "contradiction": compose_contradiction,
    }


def netnew_composers() -> dict[str, Callable]:
    """Return the 168-06 NET-NEW facet composers (D-01) to register on the
    assembler over its 168-05 deferred-placeholder slots.

    Each real composer degrades gracefully when its concrete reader seam is
    absent (169 wiring): signal_importance -> deferred (non-downgrading);
    historical_context / prior_assessment (evidence ranking) -> ENRICHMENT
    omit-with-reason. Lazy imports avoid an import cycle.
    """
    from core.evidence.facets.signal_importance import compose_signal_importance

    composers: dict[str, Callable] = {
        "signal_importance": compose_signal_importance,
    }
    # historical_context + prior_assessment (evidence ranking) land in Task 2;
    # wired-as-available so Task 1 stays green standalone.
    try:
        from core.evidence.facets.evidence_ranking import compose_evidence_ranking
        from core.evidence.facets.historical_context import compose_historical_context

        composers["historical_context"] = compose_historical_context
        composers["prior_assessment"] = compose_evidence_ranking
    except Exception:  # pragma: no cover - Task 1 standalone: modules not yet present
        pass
    return composers
