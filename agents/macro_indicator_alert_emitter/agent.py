"""Phase 91 Plan 2 Task 2 — MacroIndicatorAlertEmitter agent.

Watches FRED release ingestion events and emits ``alert_candidate_created``
envelopes (alert_type='macro_indicator') for the Phase 91 Universal Alert
Engine. Subscription-side DSL evaluation happens on VM100; the emitter is
responsible for surfacing every notable release per indicator's default
condition catalog so user subscriptions with custom thresholds can match.

Architecture:

    Dagster macro_release_alert_sensor
        → POST VM107 /api/v1/agents/macro_indicator_alert_emitter/invoke
        → MacroIndicatorAlertEmitter.emit_for_release(release_event)
        → for each matching condition (or always-on info):
            emit_alert_candidate(alert_type='macro_indicator', ...)
              → POST PHASE_91_UAE_URL /api/mission-control/internal/alert-candidate-created
        → VM100 alert_candidate_intake.receive_alert_candidate runs evaluator
          → AlertTrigger row + Phase 74 dispatch

Stateless by design — INDICATOR_DEFAULT_CONDITIONS is a Python dict (not a
DB table) so deployments + tests get deterministic behaviour.

Pattern mirrors ``agents.macro_regime_monitor.MacroRegimeMonitor`` for the
agent surface; the actual fan-out uses core/alerts/phase91_emit.py (shared
with the contradiction + discovery emitters per the Phase 89 Wave 3 lock).

Tests: tests/agents/test_macro_indicator_alert_emitter.py.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from simpleeval import simple_eval

from agents.macro_indicator_alert_emitter.conditions import (
    INDICATOR_DEFAULT_CONDITIONS,
    RELEASE_LANDED_INFO_CONDITION,
)
from core.alerts.phase91_emit import emit_alert_candidate


logger = logging.getLogger(__name__)


# Short-name aliases — mirrors
# VM100/backend/mission_control/services/macro_release_intake.INDICATOR_SHORT_NAMES.
# Pinned here for stateless emit-side templating; the VM100 evaluator namespace
# uses the same aliases so the same DSL condition matches at both ends.
_INDICATOR_SHORT_NAMES: dict[str, str] = {
    "CPIAUCSL": "CPI",
    "PAYEMS": "NFP",
    "UNRATE": "UNRATE",
    "FEDFUNDS": "FEDFUNDS",
    "PPIACO": "PPI",
}

_EPSILON = 1e-6


def _short_name(indicator_id: str) -> str:
    return _INDICATOR_SHORT_NAMES.get(indicator_id, indicator_id)


def _build_namespace(release_event: dict[str, Any]) -> dict[str, Any]:
    """Build the emit-side DSL namespace for a release event.

    Mirrors VM100 macro_release_intake.build_macro_namespace so the
    emitter's local condition evaluation produces identical truth values to
    the VM100-side subscription evaluator. Keeps templating values consistent
    with what user-side DSL operates on.
    """
    indicator_id = release_event.get("indicator_id")
    if not indicator_id:
        return {"True": True, "False": False, "None": None}

    short = _short_name(indicator_id)

    ns: dict[str, Any] = {
        "True": True,
        "False": False,
        "None": None,
        "short_name": short,
    }

    value = release_event.get("value")
    prev_value = release_event.get("prev_value")
    consensus = release_event.get("consensus")

    # Place value + prev_value under both short and indicator_id keys
    for prefix, v in (("", value), ("prev_", prev_value)):
        ns[f"{prefix}{indicator_id}"] = v
        if short != indicator_id:
            ns[f"{prefix}{short}"] = v

    # Direct payload references for templating (not used by DSL operators)
    ns["value"] = value
    ns["prev_value"] = prev_value
    ns["consensus"] = consensus

    # surprise — (value - consensus) / max(|consensus|, epsilon)
    if value is not None and consensus is not None:
        surprise = (float(value) - float(consensus)) / max(abs(float(consensus)), _EPSILON)
        ns[f"surprise_{indicator_id}"] = surprise
        if short != indicator_id:
            ns[f"surprise_{short}"] = surprise
    else:
        ns[f"surprise_{indicator_id}"] = None
        if short != indicator_id:
            ns[f"surprise_{short}"] = None

    return ns


def _event_id_for(indicator_id: str, release_date: str, condition_id: str) -> str:
    """sha256-derived 16-char hex event_id keyed on the per-condition tuple.

    Idempotency contract — Plan 1 schema v1.0 requires event_id; VM100
    alert_trigger.event_id is UNIQUE so duplicate POSTs return 409 instead
    of double-firing. Per-condition keying means the same release fires
    each tier exactly once across replays.
    """
    raw = f"{indicator_id}|{release_date}|{condition_id}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _evaluate_condition_local(expr: str, namespace: dict[str, Any]) -> bool:
    """Evaluate a condition's DSL expression locally on the emitter side.

    The emitter pre-filters which tiers fire so we don't spray dozens of
    info-severity envelopes on every release. VM100-side subscription
    evaluator still runs the user's DSL on the resulting envelope's payload.

    Conservative on error: simpleeval failure → False (don't emit on a
    busted condition string; surfacing via DLQ would be misleading).
    """
    try:
        return bool(simple_eval(expr, names=namespace, functions={"abs": abs}))
    except Exception as exc:  # noqa: BLE001
        logger.warning({
            "event": "macro_emitter_condition_eval_failed",
            "expr": expr,
            "error": str(exc),
        })
        return False


def _format_template(template: str, namespace: dict[str, Any]) -> str:
    """Format a condition's template string with the namespace.

    Missing keys → fall back to the raw template (don't crash an emit on
    bad templating).
    """
    try:
        return template.format(**namespace)
    except (KeyError, IndexError, ValueError) as exc:
        logger.warning({
            "event": "macro_emitter_template_format_failed",
            "template": template,
            "error": str(exc),
        })
        return template


def _citation_for(indicator_id: str, release_date: str) -> str:
    """Per-Phase 71 citation grammar: fred://<indicator_id>/<release_date>."""
    return f"fred://{indicator_id}/{release_date}"


class MacroIndicatorAlertEmitter:
    """Emit alert_candidate_created envelopes for FRED release events.

    Stateless — every call to emit_for_release reads the static
    INDICATOR_DEFAULT_CONDITIONS catalog + the always-on info-tier
    RELEASE_LANDED_INFO_CONDITION.

    Args:
        agent_id: Override the producer_agent_id used in the envelope.
            Tests can pin this to a deterministic value.
    """

    agent_id: str = "vm107.macro_indicator_alert_emitter"

    def __init__(self, *, agent_id: str | None = None) -> None:
        if agent_id is not None:
            self.agent_id = agent_id

    def emit_for_release(self, release_event: dict[str, Any]) -> dict[str, Any]:
        """Emit envelopes for every matching default condition.

        Args:
            release_event: Dict with at minimum ``indicator_id``,
                ``release_date``, ``value``. Optional: ``prev_value``,
                ``consensus``, ``history_30y`` (history forwarded in the
                envelope payload for VM100-side percentile use).

        Returns:
            Dict with:
              - indicator_id (echo)
              - release_date (echo)
              - emitted_count (int — number of envelopes POSTed)
              - matched_condition_ids (list[str] — id of each emitted tier)
              - skipped_no_indicator (bool — True if indicator_id was missing)
        """
        indicator_id = release_event.get("indicator_id")
        release_date = release_event.get("release_date") or ""

        if not indicator_id:
            logger.warning({
                "event": "macro_emitter_missing_indicator_id",
                "release_event_keys": sorted(release_event.keys()),
            })
            return {
                "indicator_id": None,
                "release_date": release_date,
                "emitted_count": 0,
                "matched_condition_ids": [],
                "skipped_no_indicator": True,
            }

        namespace = _build_namespace(release_event)
        tiers = list(INDICATOR_DEFAULT_CONDITIONS.get(indicator_id, []))
        # Always include the info-tier always-fire so subscriptions with
        # custom DSL get a chance to evaluate (else releases with no tier
        # hit would be silently dropped at the emitter).
        tiers.append(RELEASE_LANDED_INFO_CONDITION)

        matched_ids: list[str] = []
        for condition in tiers:
            condition_id = condition["id"]
            if not _evaluate_condition_local(condition["expr"], namespace):
                continue

            explanation = _format_template(condition["template"], namespace)
            event_id = _event_id_for(indicator_id, release_date, condition_id)

            # The envelope's payload sub-dict carries the full FRED release
            # state so VM100's build_macro_namespace can rebuild the
            # subscription-evaluator namespace verbatim.
            payload = {
                "indicator_id": indicator_id,
                "release_date": release_date,
                "value": release_event.get("value"),
                "prev_value": release_event.get("prev_value"),
                "consensus": release_event.get("consensus"),
                "history_30y": release_event.get("history_30y"),
                "condition_id": condition_id,
            }

            try:
                emit_alert_candidate(
                    alert_type="macro_indicator",
                    producer_agent_id=self.agent_id,
                    subject_type="indicator",
                    subject_id=indicator_id,
                    b13_internal_severity=condition["severity"],
                    explanation=explanation,
                    citations=[_citation_for(indicator_id, release_date)],
                    confidence=1.0,  # release values are deterministic
                    event_id=event_id,
                    extra_payload=payload,
                )
                matched_ids.append(condition_id)
            except Exception as exc:  # noqa: BLE001
                logger.error({
                    "event": "macro_emitter_emit_failed",
                    "indicator_id": indicator_id,
                    "condition_id": condition_id,
                    "error": str(exc),
                })

        logger.info({
            "event": "macro_emitter_release_processed",
            "indicator_id": indicator_id,
            "release_date": release_date,
            "matched_condition_ids": matched_ids,
            "emitted_count": len(matched_ids),
        })
        return {
            "indicator_id": indicator_id,
            "release_date": release_date,
            "emitted_count": len(matched_ids),
            "matched_condition_ids": matched_ids,
            "skipped_no_indicator": False,
        }


# Module-level shim so the Dagster asset (or external caller) can fire without
# instantiating the class.
def emit_for_release(release_event: dict[str, Any]) -> dict[str, Any]:
    """Module-level convenience wrapper — MacroIndicatorAlertEmitter().emit_for_release."""
    return MacroIndicatorAlertEmitter().emit_for_release(release_event)


__all__ = ["MacroIndicatorAlertEmitter", "emit_for_release"]
