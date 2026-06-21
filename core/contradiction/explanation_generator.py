"""Phase 89 Wave 3 — Contradiction explanation candidate generator.

Generates ≥1 candidate narratives for warning + blocking severity contradictions.
For info severity, returns an empty list (not surfaced to UI).

Uses:
  - Phase 87 Neo4j macro graph (vm105.neo4j_macro_graph_walker) to find
    confounding events in the divergence time window.
  - Phase 86 cross-asset correlations to find assets that moved opposite
    to the prediction's expectation.

Per project locks:
  - No hardcoded URLs — graph + correlation callers are injected (testable).
  - env-driven: any URL env vars are resolved at call time, not at import.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Return type ───────────────────────────────────────────────────────────────

@dataclass
class ExplanationCandidate:
    """A single explanation candidate for a contradiction.

    Attributes:
        narrative: Human-readable explanation of why the contradiction may
                   have occurred (e.g. "Treasury auction demand offset inflation concerns").
        confounder_event_ids: IDs of confounding events from Phase 87 graph that
                              may explain the divergence.
        supporting_correlations: Cross-asset correlations (from Phase 86) that
                                 support this explanation.
        confidence: Float [0.0, 1.0] — how confident the generator is in this candidate.
    """

    narrative: str
    confounder_event_ids: list[str] = field(default_factory=list)
    supporting_correlations: list[dict] = field(default_factory=list)
    confidence: float = 0.5


# ── Core function ─────────────────────────────────────────────────────────────

def generate_candidates(
    contradiction: Any,  # ContradictionArtifact — typed loosely to avoid circular import
    neo4j_graph: Any,  # vm105.neo4j_macro_graph_walker double or live client
    cross_asset_correlations: list[dict] | None = None,
    k: int = 2,
) -> list[ExplanationCandidate]:
    """Generate up to k explanation candidates for a contradiction artifact.

    For 'info' severity contradictions, returns an empty list (not surfaced to UI).
    For 'warning' and 'blocking', emits ≥1 candidate.

    Args:
        contradiction: ContradictionArtifact with indicator_id, severity,
                       divergence_sigma, asset_keys.
        neo4j_graph: Phase 87 macro graph walker. Must support .walk(indicator_id)
                     returning list of graph node dicts with 'relationship_type',
                     'source', 'target', 'strength', 'confidence'.
        cross_asset_correlations: Optional list of cross-asset correlation dicts
                                  from Phase 86. Each: {asset, corr, direction, lag_days}.
                                  If None, skips correlation-based candidates.
        k: Max number of candidates to generate.

    Returns:
        List of ExplanationCandidate objects (empty for 'info' severity).
    """
    severity = getattr(contradiction, "severity", None)
    if severity == "info":
        logger.debug({
            "event": "explanation_generator_skipped",
            "reason": "info severity — no explanation needed",
            "indicator_id": getattr(contradiction, "indicator_id", "unknown"),
        })
        return []

    indicator_id = getattr(contradiction, "indicator_id", "unknown")
    divergence_sigma = getattr(contradiction, "divergence_sigma", {})
    candidates: list[ExplanationCandidate] = []

    # ── Step 1: Query Phase 87 graph for confounders ─────────────────────
    confounder_events: list[dict] = []
    try:
        graph_nodes = neo4j_graph.walk(indicator_id)
        confounder_events = [
            node for node in graph_nodes
            if node.get("confounder_event_type") or node.get("relationship_type") == "CONFOUNDS"
        ]
    except Exception as exc:
        logger.warning({
            "event": "explanation_generator_graph_error",
            "indicator_id": indicator_id,
            "error": str(exc),
        })

    # ── Step 2: Build graph-based narrative ──────────────────────────────
    diverging_assets = [
        asset for asset, sigma in divergence_sigma.items()
        if isinstance(sigma, (int, float)) and sigma > 0.5
    ]

    if graph_nodes := (confounder_events or _extract_graph_nodes(neo4j_graph, indicator_id)):
        # Use the graph edges to synthesise a narrative about what may have offset
        top_node = graph_nodes[0] if graph_nodes else {}
        target = top_node.get("target") or top_node.get("source", "related asset")
        rel_type = top_node.get("confounder_event_type") or top_node.get("relationship_type", "demand")
        asset_str = ", ".join(diverging_assets) if diverging_assets else "market reaction"

        narrative = (
            f"{rel_type.replace('_', ' ').title()} dynamics appear to have "
            f"offset the expected {indicator_id} transmission to {asset_str}. "
            f"The Phase 87 macro graph shows a {target}—{indicator_id} pathway "
            f"that may have absorbed or inverted the standard shock propagation."
        )
        confounder_ids = [
            str(node.get("id") or node.get("source", ""))
            for node in graph_nodes[:3]
            if node
        ]
        candidates.append(
            ExplanationCandidate(
                narrative=narrative,
                confounder_event_ids=[cid for cid in confounder_ids if cid],
                supporting_correlations=[],
                confidence=min(0.5 + 0.1 * len(graph_nodes), 0.85),
            )
        )

    # ── Step 3: Cross-asset correlation candidate ─────────────────────────
    if cross_asset_correlations and len(candidates) < k:
        inverse_movers = [
            c for c in cross_asset_correlations
            if c.get("direction") == "inverse" or (c.get("corr", 0.0) or 0.0) < -0.3
        ]
        if inverse_movers:
            top_mover = inverse_movers[0]
            asset = top_mover.get("asset", "a correlated asset")
            corr = top_mover.get("corr", 0.0) or 0.0
            narrative = (
                f"Phase 86 cross-asset analysis shows {asset} moved inversely "
                f"to the expected {indicator_id} reaction (r={corr:.2f}). "
                f"This offsetting move may reflect independent demand factors "
                f"or a regime shift suppressing the standard transmission channel."
            )
            candidates.append(
                ExplanationCandidate(
                    narrative=narrative,
                    confounder_event_ids=[],
                    supporting_correlations=inverse_movers[:3],
                    confidence=0.45,
                )
            )

    # ── Step 4: Fallback narrative if no candidates yet ──────────────────
    if not candidates:
        # Generic fallback — always emits ≥1 for warning/blocking
        asset_str = ", ".join(diverging_assets[:2]) if diverging_assets else "observed assets"
        narrative = (
            f"The actual market reaction for {asset_str} diverged "
            f"significantly from the Phase 87 transmission engine prediction for {indicator_id}. "
            f"The divergence may indicate a regime shift, an omitted confounder, "
            f"or a structural break in the indicator–asset transmission channel."
        )
        candidates.append(
            ExplanationCandidate(
                narrative=narrative,
                confounder_event_ids=[],
                supporting_correlations=[],
                confidence=0.30,
            )
        )

    logger.info({
        "event": "explanation_candidates_generated",
        "indicator_id": indicator_id,
        "severity": severity,
        "candidate_count": len(candidates),
    })
    return candidates[:k]


def _extract_graph_nodes(neo4j_graph: Any, indicator_id: str) -> list[dict]:
    """Safe wrapper around neo4j_graph.walk() — returns empty list on error."""
    try:
        return neo4j_graph.walk(indicator_id) or []
    except Exception:
        return []
