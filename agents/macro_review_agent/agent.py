"""Phase 91 Plan 6 — MacroReviewAgent.

Synchronous review agent invoked by VM100 when a high-severity macro alert
fires (liquidity_critical, regime_change). Cross-checks the payload against
Phase 87 regime_state + Phase 89 correlation data, synthesizes a findings
string, and may emit FOLLOW-UP alert_candidate envelopes (alert_type !=
liquidity / regime — never itself, per denied_dispatch_targets).

Initial impl is DETERMINISTIC — no Phase 43 LLM router integration. The
LLM enrichment is post-91 backlog; deterministic logic ships first so the
agent loop closes end-to-end. Cross-VM cross-checks use the existing typed
clients (regime_state_reader / correlation_data_reader) — agent never
filesystem-reads other VMs (per feedback_no_cross_vm_filesystem lock).

Invocation contract (matches VM100/backend/notifications/channels/agent_webhook_channel.py):

    POST /api/v1/agents/macro_review_agent/invoke
    Authorization: Bearer ${VM107_API_TOKEN}
    Body: {
      profile_id: str,                # 'macro_review_agent'
      alert_trigger_id: int,          # VM100 AlertTrigger.pk
      alert_type: str,                # 'liquidity' or 'regime'
      severity: str,                  # 'critical' or 'regime_change'
      subject_id: str,
      payload: dict,                  # original VM107 envelope payload
      agent_chain_depth: int,         # 1..3 (loop_safety_guard sets this)
      parent_dispatch_id: int | None, # AgentDispatchLog.pk that triggered us
      event_id: str,                  # idempotency key
    }

Returns: {
  status: 'ok' | 'noop',
  findings: str,
  follow_up_count: int,
  follow_up_alert_types: list[str],   # for caller's audit
}
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


_PRODUCER_AGENT_ID = "vm107.macro_review_agent"

# Self-loop ban — REINFORCED at the agent-code layer alongside the
# profile.yaml denied_dispatch_targets entry. If macro_review_agent's findings
# include language that would trigger another macro_review_agent dispatch
# (alert_type='liquidity' + severity='critical' OR alert_type='regime' +
# severity='regime_change'), the agent emits with a downgraded alert_type
# ('discovery') so the VM100 router doesn't loop back.
_BANNED_FOLLOW_UP_ALERT_TYPES_FOR_SELF_LOOP = {"liquidity", "regime"}


def _cross_check_regime(subject_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Read Phase 87 regime_state for context.

    Returns a dict with 'regime', 'accelerating' booleans + 'available' flag.
    Degraded-mode safe: if Phase 87 unreachable returns 'available': False
    so the agent silently downshifts to lower-confidence findings.
    """
    try:
        # Lazy import — keeps Phase 87 client optional in test environments.
        from clients.phase87_regime_client import get_current_regime  # type: ignore[import-not-found]
    except ImportError:
        logger.info({
            "event": "macro_review_phase87_client_unavailable",
            "subject_id": subject_id,
        })
        return {"available": False, "regime": None, "accelerating": False}

    try:
        regime = get_current_regime(dimension="inflation")
        return {
            "available": True,
            "regime": regime,
            "accelerating": "accelerating" in (regime or "").lower(),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning({
            "event": "macro_review_regime_lookup_failed",
            "error": str(exc),
        })
        return {"available": False, "regime": None, "accelerating": False}


def _cross_check_correlations(subject_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Read Phase 89 correlation data for indicator linkages.

    Returns a dict with 'correlation_breaks' (list[str]) + 'available' flag.
    """
    try:
        from clients.phase89_correlation_client import (  # type: ignore[import-not-found]
            get_recent_correlation_breaks,
        )
    except ImportError:
        logger.info({
            "event": "macro_review_phase89_client_unavailable",
            "subject_id": subject_id,
        })
        return {"available": False, "correlation_breaks": []}

    try:
        breaks = get_recent_correlation_breaks(subject_id=subject_id)
        return {"available": True, "correlation_breaks": list(breaks or [])}
    except Exception as exc:  # noqa: BLE001
        logger.warning({
            "event": "macro_review_correlation_lookup_failed",
            "error": str(exc),
        })
        return {"available": False, "correlation_breaks": []}


def _synthesize_findings(
    alert_type: str,
    severity: str,
    subject_id: str,
    payload: dict[str, Any],
    regime_ctx: dict[str, Any],
    corr_ctx: dict[str, Any],
) -> str:
    """Compose a one-paragraph human-readable findings string.

    The output is plain text (not Markdown) so VM100 can embed it in
    notification body / agent_dispatch_log.response_body_excerpt without
    rendering concerns.
    """
    parts: list[str] = []
    parts.append(
        f"macro_review_agent review of {alert_type}/{severity} alert on {subject_id}:"
    )

    if alert_type == "liquidity":
        score = payload.get("liquidity_score")
        prev = payload.get("prev_liquidity_score")
        if isinstance(score, (int, float)):
            if isinstance(prev, (int, float)) and prev > score:
                parts.append(
                    f"liquidity_score dropped to {score} from {prev} "
                    f"(Δ={prev - score:.1f})."
                )
            else:
                parts.append(f"liquidity_score at {score}.")

    if regime_ctx.get("available") and regime_ctx.get("regime"):
        parts.append(f"Phase 87 regime: {regime_ctx['regime']}.")
        if regime_ctx.get("accelerating"):
            parts.append(
                "Regime is accelerating — heightened risk of macro pivot."
            )

    if corr_ctx.get("available") and corr_ctx.get("correlation_breaks"):
        breaks = corr_ctx["correlation_breaks"]
        if breaks:
            parts.append(
                f"Phase 89 correlation breaks active: {', '.join(breaks[:3])}."
            )

    # Heuristic — if liquidity + regime accelerating + correlation breaks,
    # flag potential macro pivot.
    pivot_signal = (
        alert_type == "liquidity"
        and severity == "critical"
        and regime_ctx.get("accelerating")
        and bool(corr_ctx.get("correlation_breaks"))
    )
    if pivot_signal:
        parts.append("Conditions suggest potential macro pivot.")

    return " ".join(parts)


def _should_emit_follow_up(findings: str) -> bool:
    """Trigger a follow-up alert_candidate when findings include pivot signal."""
    return "potential macro pivot" in findings.lower()


def review_alert(
    *,
    alert_trigger_id: int,
    alert_type: str,
    severity: str,
    subject_id: str,
    payload: dict[str, Any],
    agent_chain_depth: int = 1,
    parent_dispatch_id: int | None = None,
    event_id: str = "",
) -> dict[str, Any]:
    """Synchronous review entry point.

    Returns a dict with status + findings + follow_up_count. NEVER raises;
    failures land in the 'status': 'error' path so the VM100 caller sees
    a structured response.
    """
    try:
        regime_ctx = _cross_check_regime(subject_id, payload)
        corr_ctx = _cross_check_correlations(subject_id, payload)
        findings = _synthesize_findings(
            alert_type=alert_type,
            severity=severity,
            subject_id=subject_id,
            payload=payload,
            regime_ctx=regime_ctx,
            corr_ctx=corr_ctx,
        )

        follow_up_alert_types: list[str] = []
        follow_up_count = 0

        if _should_emit_follow_up(findings):
            # Emit a 'discovery' alert — NOT 'liquidity'/'regime' (those would
            # loop back to macro_review_agent and trigger LoopBreakerError).
            follow_up_alert_type = "discovery"
            assert follow_up_alert_type not in _BANNED_FOLLOW_UP_ALERT_TYPES_FOR_SELF_LOOP, (
                f"macro_review_agent attempted to emit self-loop alert_type="
                f"{follow_up_alert_type!r} — denied at code layer."
            )
            try:
                from core.alerts.phase91_emit import emit_alert_candidate

                emit_alert_candidate(
                    alert_type=follow_up_alert_type,
                    producer_agent_id=_PRODUCER_AGENT_ID,
                    subject_id=subject_id,
                    b13_internal_severity="warning",  # discovery → 'Important'
                    explanation=findings,
                    citations=payload.get("citations", []),
                )
                follow_up_count = 1
                follow_up_alert_types.append(follow_up_alert_type)
            except Exception as exc:  # noqa: BLE001
                logger.exception({
                    "event": "macro_review_follow_up_emit_failed",
                    "error": str(exc),
                })

        result = {
            "status": "ok",
            "agent_id": _PRODUCER_AGENT_ID,
            "alert_trigger_id": alert_trigger_id,
            "findings": findings,
            "follow_up_count": follow_up_count,
            "follow_up_alert_types": follow_up_alert_types,
            "agent_chain_depth": agent_chain_depth,
            "event_id": event_id,
            "reviewed_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        logger.info({
            "event": "macro_review_completed",
            "alert_trigger_id": alert_trigger_id,
            "alert_type": alert_type,
            "follow_up_count": follow_up_count,
            "agent_chain_depth": agent_chain_depth,
        })
        return result

    except Exception as exc:  # noqa: BLE001
        logger.exception({
            "event": "macro_review_failed",
            "error": str(exc),
            "alert_trigger_id": alert_trigger_id,
        })
        return {
            "status": "error",
            "agent_id": _PRODUCER_AGENT_ID,
            "alert_trigger_id": alert_trigger_id,
            "error": str(exc),
            "findings": "",
            "follow_up_count": 0,
            "follow_up_alert_types": [],
        }


class MacroReviewAgent:
    """Class facade for VM107 agent registry compatibility.

    The function-style ``review_alert`` is the primary entry point; this
    class wraps it for sites that prefer an OO surface (e.g. agent dispatch
    runners that instantiate an agent class).
    """

    agent_id: str = _PRODUCER_AGENT_ID

    def review_alert(self, **kwargs: Any) -> dict[str, Any]:
        return review_alert(**kwargs)
