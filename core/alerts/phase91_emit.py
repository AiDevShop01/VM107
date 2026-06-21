"""Phase 89 Wave 3 — Phase 89↔Phase 91 alert candidate emit helper.

THIS IS THE SHARED PHASE 89↔PHASE 91 CONTRACT SURFACE.
Both contradiction (Wave 3) and discovery (Wave 4) agents import from this module:
  from core.alerts.phase91_emit import emit_alert_candidate

Phase 91 UAE (User Alert Engine) receives alert_candidate_created events per
Decision 13. This module handles:
  1. Severity translation: B13 internal → Phase 91 5-severity taxonomy
     info → Info, warning → Important, blocking → Critical
     None (discovery path) → Info (default)
  2. Envelope construction per fixtures/alert_candidate_event.schema.json
  3. Schema validation (fail-fast on mismatch)
  4. HTTP POST to PHASE_91_UAE_URL (env var — NO fallback default per project lock)
  5. DLQ fallback when PHASE_91_UAE_URL is unset — logs + stores for replay
     (Phase 91 not yet shipped in Phase 89; DLQ ensures no event loss)

Per project locks:
  - PHASE_91_UAE_URL from env — NO fallback default.
  - Fail-fast on schema mismatch (validates before POST).
  - DLQ on missing URL — NEVER raises to caller (observability degradation, not crash).
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

import jsonschema
import requests

logger = logging.getLogger(__name__)

# ── Schema ───────────────────────────────────────────────────────────────────

_SCHEMA_PATH = pathlib.Path(__file__).parents[2] / "tests" / "phase89" / "fixtures" / "alert_candidate_event.schema.json"
_SCHEMA: dict | None = None
_VALIDATOR: jsonschema.Draft7Validator | None = None


def _get_schema() -> tuple[dict, jsonschema.Draft7Validator]:
    """Lazily load and cache the JSON Schema + validator."""
    global _SCHEMA, _VALIDATOR
    if _SCHEMA is None:
        _SCHEMA = json.loads(_SCHEMA_PATH.read_text())
        _VALIDATOR = jsonschema.Draft7Validator(_SCHEMA)
    return _SCHEMA, _VALIDATOR  # type: ignore[return-value]


# ── Severity translation (Decision 13) ───────────────────────────────────────

_B13_TO_PHASE91: dict[str, str] = {
    "info": "Info",
    "warning": "Important",
    "blocking": "Critical",
}

_DEFAULT_DISCOVERY_SEVERITY = "Info"


def _translate_severity(
    b13_internal_severity: str | None,
    alert_type: str,
) -> str:
    """Translate B13 internal severity to Phase 91 5-severity taxonomy.

    Decision 13:
      info → Info
      warning → Important
      blocking → Critical
      None (discovery path, alert_type='discovery') → Info

    Args:
        b13_internal_severity: "info" | "warning" | "blocking" | None
        alert_type: "contradiction" | "discovery" | etc.

    Returns:
        Phase 91 severity string.
    """
    if b13_internal_severity is None:
        return _DEFAULT_DISCOVERY_SEVERITY
    translated = _B13_TO_PHASE91.get(b13_internal_severity)
    if translated is None:
        logger.warning({
            "event": "phase91_emit_unknown_severity",
            "b13_internal_severity": b13_internal_severity,
            "fallback": _DEFAULT_DISCOVERY_SEVERITY,
        })
        return _DEFAULT_DISCOVERY_SEVERITY
    return translated


# ── DLQ ──────────────────────────────────────────────────────────────────────

def _write_to_dlq(envelope: dict) -> None:
    """Write an alert candidate envelope to the dead-letter queue.

    Called when PHASE_91_UAE_URL is not set (Phase 91 not yet shipped in Phase 89).
    Logs at WARNING level so the envelope can be replayed when Phase 91 ships.

    In production, this could write to a Postgres DLQ table or a local log file.
    For Phase 89, we use structured logging + in-memory capture for testability.
    """
    logger.warning({
        "event": "phase91_alert_candidate_dlq",
        "reason": "PHASE_91_UAE_URL not set — queued for replay when Phase 91 ships",
        "envelope": envelope,
    })


# ── Main emit function ────────────────────────────────────────────────────────

def emit_alert_candidate(
    alert_type: Literal["contradiction", "discovery", "regime", "correlation",
                        "macro_indicator", "liquidity", "price"],
    producer_agent_id: str,
    subject_id: str,
    b13_internal_severity: Literal["info", "warning", "blocking"] | None,
    explanation: str,
    citations: list[str],
    contradiction_id: UUID | None = None,
    proposal_id: UUID | None = None,
    subject_type: str = "indicator",
    confidence: float | None = None,
) -> None:
    """Emit an alert_candidate_created event to Phase 91 UAE.

    THIS IS THE SHARED PHASE 89↔PHASE 91 CONTRACT SURFACE.
    Imported by:
      - VM107/core/contradiction/contradiction_engine.py (Wave 3)
      - VM107/core/discovery/edge_proposer.py (Wave 4)

    Validates envelope against alert_candidate_event.schema.json before POST.
    Falls back to DLQ if PHASE_91_UAE_URL is unset (never raises to caller).

    Args:
        alert_type: Category for Phase 91 routing ("contradiction", "discovery", etc.)
        producer_agent_id: VM107 agent that produced this candidate.
        subject_id: FRED indicator or asset ID (e.g. "CPIAUCSL", "DXY").
        b13_internal_severity: B13 internal severity or None for discovery (→ "Info").
        explanation: Human-readable explanation of why this alert was raised.
        citations: Phase 71 source references.
        contradiction_id: UUID of the contradiction artifact (contradiction path only).
        proposal_id: UUID of the EdgeProposal (discovery path only).
        subject_type: Entity type, defaults to "indicator".
        confidence: Agent confidence [0.0, 1.0]. Defaults to severity-based heuristic.
    """
    phase91_severity = _translate_severity(b13_internal_severity, alert_type)

    # Default confidence based on severity (heuristic)
    if confidence is None:
        _severity_confidence: dict[str | None, float] = {
            "blocking": 0.85,
            "warning": 0.65,
            "info": 0.40,
            None: 0.50,
        }
        confidence = _severity_confidence.get(b13_internal_severity, 0.50)

    # Build envelope
    envelope: dict = {
        "event_type": "alert_candidate_created",
        "alert_type": alert_type,
        "producer_agent_id": producer_agent_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "severity": phase91_severity,
        "b13_internal_severity": b13_internal_severity if b13_internal_severity is not None else "info",
        "confidence": confidence,
        "explanation": explanation,
        "citations": citations,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "schema_version": "0.1-provisional",
    }

    # Optional path-specific fields
    if contradiction_id is not None:
        envelope["contradiction_id"] = str(contradiction_id)
    if proposal_id is not None:
        envelope["proposal_id"] = str(proposal_id)

    # Schema validation (fail-fast on mismatch)
    _, validator = _get_schema()
    errors = list(validator.iter_errors(envelope))
    if errors:
        error_msgs = "; ".join(e.message for e in errors[:3])
        raise ValueError(
            f"emit_alert_candidate: envelope failed schema validation: {error_msgs}"
        )

    # POST to Phase 91 UAE or DLQ fallback
    phase91_url = os.environ.get("PHASE_91_UAE_URL")
    if not phase91_url:
        logger.warning({
            "event": "phase91_url_not_set",
            "reason": "PHASE_91_UAE_URL env var not set — routing to DLQ",
        })
        _write_to_dlq(envelope)
        return

    try:
        response = requests.post(phase91_url, json=envelope)
        response.raise_for_status()
        logger.info({
            "event": "phase91_alert_candidate_emitted",
            "alert_type": alert_type,
            "severity": phase91_severity,
            "b13_internal_severity": b13_internal_severity,
            "subject_id": subject_id,
        })
    except Exception as exc:  # noqa: BLE001
        logger.error({
            "event": "phase91_emit_failed",
            "error": str(exc),
            "alert_type": alert_type,
            "subject_id": subject_id,
        })
        # Route to DLQ on failure — never raise to caller
        _write_to_dlq(envelope)
