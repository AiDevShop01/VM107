"""Phase 91 Plan 3 Task 2 — alert_emit_hook for macro_relationship_discovery.

SIDECAR module — does NOT refactor MacroRelationshipDiscovery's core scan
loop. Provides one-line emit helpers for two flows:

  * emit_discovery_alert(proposal) — invoke from the existing EdgeProposer
    acceptance path inside MacroRelationshipDiscovery.run (one line after
    ``proposer.propose(candidate)`` succeeds). LD-91-8 always-emit-info
    pattern: every accepted EdgeProposal becomes an info-severity alert
    candidate; user subscriptions filter via condition_yaml DSL.

  * emit_correlation_break_alert(breakdown) — invoke from the correlation
    breakdown branch when a 30d correlation drops > 0.5 absolute over the
    scan window. Plan 86 has not shipped a dedicated correlation-breakdown
    agent; this stub ships the routing surface so user subscriptions on
    alert_type='correlation' can flow end-to-end via UAE. When Phase 86
    ships, replace this with a dedicated emitter agent_profile.

Both helpers use the shared ``core/alerts/phase91_emit.py`` shim — same
contract surface as macro_regime_monitor and macro_indicator_alert_emitter.

Envelope shapes:
  discovery:
    - subject_type    : 'edge_proposal'
    - subject_id      : proposal['proposal_id']
    - b13_severity    : 'info' → 'Info' user-facing (LD-91-8)
    - extra_payload   : {discovery_text, agent_confidence, source_indicators,
                         source_assets, edge_proposal_id}

  correlation:
    - subject_type    : 'asset_pair'
    - subject_id      : breakdown['asset_pair'] (e.g. 'DXY-Gold')
    - b13_severity    : 'warning' → 'Important' user-facing
    - extra_payload   : {correlation_30d, prev_correlation_30d,
                         n_observations, asset_pair, delta_abs}
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from core.alerts.phase91_emit import emit_alert_candidate

logger = logging.getLogger(__name__)


_PRODUCER_AGENT_ID = "vm107.macro_relationship_discovery"


def _event_id_for(*parts: str) -> str:
    raw = "|".join(parts).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


# ── Discovery alert (LD-91-8 always-emit-info) ──────────────────────────────


def emit_discovery_alert(proposal: dict[str, Any]) -> None:
    """Emit a discovery alert envelope for an accepted EdgeProposal.

    Args:
        proposal: Dict carrying the EdgeProposal-flavoured fields:
            - proposal_id        : str (UUID)
            - discovery_text     : str
            - agent_confidence   : float [0..1]
            - source_indicators  : list[str] (optional)
            - source_assets      : list[str] (optional)
            - from_node / to_node: graph endpoints (optional, for context)
    """
    proposal_id = str(proposal.get("proposal_id") or "")
    discovery_text = (
        proposal.get("discovery_text")
        or proposal.get("explanation")
        or "Discovery proposal accepted"
    )
    confidence = float(proposal.get("agent_confidence") or proposal.get("confidence") or 0.5)

    payload: dict[str, Any] = {
        "discovery_text": discovery_text,
        "agent_confidence": confidence,
        "source_indicators": list(proposal.get("source_indicators") or []),
        "source_assets": list(proposal.get("source_assets") or []),
        "edge_proposal_id": proposal_id,
    }

    citations: list[str] = []
    if proposal_id:
        citations.append(f"vm107://discovery/edge_proposal/{proposal_id}")

    event_id = _event_id_for(_PRODUCER_AGENT_ID, "discovery", proposal_id)

    try:
        emit_alert_candidate(
            alert_type="discovery",
            producer_agent_id=_PRODUCER_AGENT_ID,
            subject_type="edge_proposal",
            subject_id=proposal_id or "unknown",
            b13_internal_severity="info",  # LD-91-8 always-emit-info
            explanation=discovery_text,
            citations=citations,
            confidence=confidence,
            event_id=event_id,
            extra_payload=payload,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error({
            "event": "discovery_alert_emit_failed",
            "proposal_id": proposal_id,
            "error": str(exc),
        })


# ── Correlation break alert (Phase 86 stub) ─────────────────────────────────


def emit_correlation_break_alert(breakdown: dict[str, Any]) -> None:
    """Emit a correlation-breakdown alert envelope.

    STUB for Phase 86 — Plan 86 has not shipped a dedicated correlation-
    breakdown agent. This emit point lives inside macro_relationship_discovery's
    correlation analysis path so user subscriptions on alert_type='correlation'
    flow end-to-end via the UAE substrate immediately. When Phase 86 lands
    its dedicated agent, replace this with that agent's emit helper and
    update VM107/registry/event_type/correlation_break_alert.yaml's producers
    list.

    Args:
        breakdown: Dict carrying the correlation breakdown payload:
            - asset_pair             : str (e.g. 'DXY-Gold')
            - correlation_30d        : float
            - prev_correlation_30d   : float (optional)
            - n_observations         : int (optional)
            - delta_abs              : float (optional — |curr - prev|)
            - explanation            : str (optional)
    """
    asset_pair = breakdown.get("asset_pair") or "unknown_pair"
    curr_corr = breakdown.get("correlation_30d")
    prev_corr = breakdown.get("prev_correlation_30d")

    payload: dict[str, Any] = {
        "correlation_30d": curr_corr,
        "prev_correlation_30d": prev_corr,
        "n_observations": breakdown.get("n_observations"),
        "asset_pair": asset_pair,
        "delta_abs": breakdown.get("delta_abs"),
    }

    explanation = breakdown.get("explanation") or (
        f"{asset_pair} 30d correlation breakdown: {curr_corr} (was {prev_corr})"
    )

    event_id = _event_id_for(
        _PRODUCER_AGENT_ID,
        "correlation",
        asset_pair,
        str(curr_corr),
        str(prev_corr),
    )

    try:
        emit_alert_candidate(
            alert_type="correlation",
            producer_agent_id=_PRODUCER_AGENT_ID,
            subject_type="asset_pair",
            subject_id=asset_pair,
            b13_internal_severity="warning",  # → 'Important'
            explanation=explanation,
            citations=[],
            confidence=0.7,
            event_id=event_id,
            extra_payload=payload,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error({
            "event": "correlation_break_alert_emit_failed",
            "asset_pair": asset_pair,
            "error": str(exc),
        })


__all__ = ["emit_discovery_alert", "emit_correlation_break_alert"]
