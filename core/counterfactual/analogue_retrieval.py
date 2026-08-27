"""Phase 89 Wave 2 — counterfactual analogue retrieval helper.

Queries Phase 87 Neo4j macro graph for historical analogue releases of a given
indicator that had a surprise value close to the hypothetical_surprise.

Per project locks:
  - All cross-VM URLs from env vars (no hardcoded URLs, no fallback defaults)
  - vm105.neo4j_macro_graph_walker called through the registry capability;
    this module provides a testable pure-logic layer with a patchable seam
    (_call_neo4j_query_analogues) that tests can mock without network access

Decision 2 note: analogue_retrieval returns whatever count the graph returns,
including partial results below k_analogues_minimum. The CALLER (counterfactual
engine) checks the count and refuses if < 5. This keeps the retrieval helper
reusable and the refusal policy in one place.
"""
from __future__ import annotations

import logging
import os
from datetime import date

logger = logging.getLogger(__name__)

# Hard-coded k_analogues_minimum per Decision 2 — NEVER change without
# updating the agent profile YAML and the architecture doc.
K_ANALOGUES_MINIMUM = 5

# VM105 analogue endpoint timeout — short so a dev-unreachable graph fails fast
# and the ENRICHMENT HistoricalContext facet omits the analogue path promptly.
_ANALOGUE_TIMEOUT_S = 0.5


# ─── Analogue data structure ─────────────────────────────────────────────────

class AnalogueRelease:
    """Analogue release data returned by query_analogues.

    Attributes:
        release_id: Unique ID for this release event.
        release_date: Date the release occurred.
        indicator_surprise: How much the actual beat/missed expectations.
        regime_at_time: Phase 87 regime classification at time of release.
    """
    __slots__ = ("release_id", "release_date", "indicator_surprise", "regime_at_time")

    def __init__(
        self,
        *,
        release_id: str,
        release_date: date,
        indicator_surprise: float,
        regime_at_time: str,
    ) -> None:
        self.release_id = release_id
        self.release_date = release_date
        self.indicator_surprise = indicator_surprise
        self.regime_at_time = regime_at_time

    def __repr__(self) -> str:
        return (
            f"AnalogueRelease(release_id={self.release_id!r}, "
            f"date={self.release_date}, "
            f"surprise={self.indicator_surprise:.3f}, "
            f"regime={self.regime_at_time!r})"
        )


# ─── Patchable seam (tests mock this, not the full Neo4j client) ─────────────

def _call_neo4j_query_analogues(
    indicator: str,
    surprise_range: tuple[float, float],
    k: int,
    current_regime: str | None,
) -> list[dict]:
    """Call vm105.neo4j_macro_graph_walker.query_analogues.

    This function is the ONLY patchable seam between analogue_retrieval and
    the Neo4j graph. Tests patch `core.counterfactual.analogue_retrieval._call_neo4j_query_analogues`
    (the binding site, not the walker import site).

    Args:
        indicator: FRED indicator ID (e.g. "CPIAUCSL").
        surprise_range: (low, high) bounds for the surprise neighbourhood search.
        k: Maximum analogues to return.
        current_regime: If set, passed to the walker for regime-filtered results.

    Returns:
        List of raw analogue dicts from the Neo4j walker. Each dict must have:
            release_id, release_date (date or ISO string), indicator_surprise,
            regime_at_time.

    Raises:
        RuntimeError: If VM105_NEO4J_URL env var not set (fail-fast per project lock).
    """
    neo4j_url = os.environ.get("VM105_NEO4J_URL")
    if not neo4j_url:
        raise RuntimeError(
            "analogue_retrieval: VM105_NEO4J_URL environment variable not set. "
            "Cannot query Phase 87 Neo4j graph. "
            "Set VM105_NEO4J_URL=<url> (no fallback per project lock)."
        )

    # Phase 168 Plan 06 (D-01) — de-stub. Per the Phase 39 typed-API lock VM107
    # never bolt://s Neo4j directly: it queries the VM105-hosted analogue endpoint
    # over HTTP (env-driven base URL, NO fallback). Any connection / HTTP / parse
    # error propagates to the CALLER (the HistoricalContext facet), which — as an
    # ENRICHMENT sub-facet — catches it and omits the analogue path with a reason.
    # The env lock means this is inert until VM105_NEO4J_URL is set in dev/prod.
    import httpx  # local import: keep the pure-logic layer import-light

    base = neo4j_url.rstrip("/")
    low, high = surprise_range
    params = {
        "indicator": indicator,
        "surprise_low": low,
        "surprise_high": high,
        "k": k,
    }
    if current_regime:
        params["current_regime"] = current_regime

    with httpx.Client(timeout=_ANALOGUE_TIMEOUT_S) as client:
        resp = client.get(f"{base}/api/macro/internal/query-analogues", params=params)
        resp.raise_for_status()
        payload = resp.json()

    analogues = payload.get("analogues", payload if isinstance(payload, list) else [])
    return list(analogues)


# ─── Public API ──────────────────────────────────────────────────────────────

def query_analogues(
    indicator: str,
    hypothetical_surprise: float,
    k: int = 20,
    current_regime: str | None = None,
    tolerance: float = 0.001,
) -> list[dict]:
    """Query Phase 87 Neo4j graph for historical analogue releases.

    Finds releases of `indicator` whose surprise was within `tolerance` of
    `hypothetical_surprise`. Optionally filters to analogues whose Phase 87
    regime classification matches `current_regime`.

    Decision 2 note: this function returns whatever count the graph returns
    (may be fewer than k). The CALLER must check `len(result) < K_ANALOGUES_MINIMUM`
    and return an InsufficientAnaloguesResponse if so.

    Args:
        indicator: FRED indicator ID (e.g. "CPIAUCSL").
        hypothetical_surprise: The user's "what if" surprise value (e.g. -0.3).
        k: Maximum number of analogues to return (default 20 per agent profile).
        current_regime: If set, filter to analogues whose regime_at_time matches.
            Non-matching analogues are still returned but flagged in regime_alignment.
        tolerance: Half-width of the surprise neighbourhood search (default 0.001).

    Returns:
        List of analogue dicts: [{release_id, release_date, indicator_surprise,
        regime_at_time}, ...]. May be empty or fewer than k if graph has fewer
        matching releases.

    Raises:
        RuntimeError: If VM105_NEO4J_URL env var not set (fail-fast per project lock).
    """
    surprise_range = (hypothetical_surprise - tolerance, hypothetical_surprise + tolerance)

    logger.debug(
        "analogue_retrieval.query",
        extra={
            "indicator": indicator,
            "hypothetical_surprise": hypothetical_surprise,
            "surprise_range": surprise_range,
            "k": k,
            "current_regime": current_regime,
        },
    )

    raw_results = _call_neo4j_query_analogues(
        indicator=indicator,
        surprise_range=surprise_range,
        k=k,
        current_regime=current_regime,
    )

    logger.info(
        "analogue_retrieval.done",
        extra={
            "indicator": indicator,
            "count_returned": len(raw_results),
            "k_requested": k,
            "below_minimum": len(raw_results) < K_ANALOGUES_MINIMUM,
        },
    )

    return raw_results


def compute_regime_alignment(
    analogues: list[dict],
    current_regime: str | None,
) -> str:
    """Compute regime_alignment from the analogue set vs current regime.

    Args:
        analogues: List of analogue dicts with regime_at_time field.
        current_regime: Phase 87 regime at the time of the hypothetical.

    Returns:
        "aligned" if ≥75% of analogues match current_regime,
        "partial" if 25-74% match,
        "divergent" if <25% match (or current_regime is None).
    """
    if not current_regime or not analogues:
        return "partial"

    matching = sum(
        1 for a in analogues
        if a.get("regime_at_time") == current_regime
    )
    ratio = matching / len(analogues)

    if ratio >= 0.75:
        return "aligned"
    elif ratio >= 0.25:
        return "partial"
    else:
        return "divergent"
