"""Phase 94-06 — Central Bank Summariser agent.

Per §K.1: this agent triggers ONLY on ``EventType.CENTRAL_BANK`` events.
Firing any other event family (macro_release, regime_change, …) is a
no-op. The agent reads the event payload (rate decision, statement
summary, stance) and emits a :class:`CentralBankSection`.

Wave 3b uses template-based summarisation. 94-07 may wire LLM completion
behind the same contract surface.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from contracts.economic_intelligence.base_section import SectionStatus
from contracts.economic_intelligence.central_bank import (
    CentralBankSection,
    CentralBankStance,
    CentralBankStatement,
)
from contracts.economic_intelligence.events import EconomicEvent, EventType
from contracts.economic_intelligence.provenance import ProvenanceObject

logger = logging.getLogger(__name__)


# Default stance mapping for unknown payloads.
_STANCE_FALLBACK = CentralBankStance.NEUTRAL


class CentralBankSummariser:
    """Fires only on EventType.CENTRAL_BANK; emits CentralBankSection."""

    AGENT_ID = "vm107.central_bank_summariser"
    SECTION_ID = "central_bank"

    def __init__(self) -> None:
        # country -> latest section.
        self._cache: dict[str, CentralBankSection] = {}

    def subscribed_event_types(self) -> tuple[EventType, ...]:
        """Per §K.1 — ONLY CENTRAL_BANK events."""
        return (EventType.CENTRAL_BANK,)

    def on_event(self, event: EconomicEvent) -> CentralBankSection | None:
        if event.event_type is not EventType.CENTRAL_BANK:
            logger.debug(
                "central_bank_summariser: ignoring event type %s (§K.1 requires CENTRAL_BANK)",
                event.event_type,
            )
            return None
        section = self._compose(event)
        self._cache[event.country] = section
        return section

    def invoke(self, country: str) -> CentralBankSection | None:
        """Return cached section (or ``None`` if no CENTRAL_BANK event yet)."""
        return self._cache.get(country)

    # ---------------------------------------------------------------- internals
    def _compose(self, event: EconomicEvent) -> CentralBankSection:
        payload = event.payload or {}
        bank = payload.get("bank", _country_to_bank(event.country))
        stance = _coerce_stance(payload.get("stance"))
        policy_rate = float(payload.get("policy_rate", 0.0))
        balance_sheet = payload.get("balance_sheet_usd_bn")
        balance_sheet = float(balance_sheet) if balance_sheet is not None else None

        statement = None
        if payload.get("statement_summary") or payload.get("statement_title"):
            statement = CentralBankStatement(
                statement_id=payload.get("statement_id", event.event_id),
                issued_at=event.occurred_at,
                title=payload.get("statement_title", f"{bank} statement"),
                summary=payload.get(
                    "statement_summary",
                    f"{bank} statement at {event.occurred_at.isoformat()}",
                ),
                citations=[f"ref:event:{event.event_id}"],
            )

        previous = self._cache.get(event.country)
        prev_version = previous.version if previous else 0

        return CentralBankSection(
            section_id=self.SECTION_ID,
            version=prev_version + 1,
            generated_at=datetime.now(timezone.utc),
            snapshot_id=f"central_bank:{event.country}",
            freshness_seconds=0,
            confidence=0.85,
            status=SectionStatus.READY,
            agent=self.AGENT_ID,
            execution_time_ms=1,
            citations=[f"ref:event:{event.event_id}"],
            limitations=[],
            depends_on=["event_bus"],
            provenance=ProvenanceObject(
                source_event_ids=[event.event_id],
                weights_version="na",
                model_version="template-1",
                prompt_version="central_bank_v1",
                upstream_sections=[],
                data_versions={},
            ),
            bank=bank,
            stance=stance,
            policy_rate=policy_rate,
            balance_sheet_usd_bn=balance_sheet,
            latest_statement=statement,
        )


# ─────────────────────────────────────────────────────────── helpers


def _country_to_bank(country: str) -> str:
    """Best-effort country → bank id mapping for the §A.6 tier-1 set."""
    return {
        "US": "FED",
        "EU": "ECB",
        "GB": "BOE",
        "JP": "BOJ",
        "AU": "RBA",
        "CN": "PBOC",
    }.get(country, country)


def _coerce_stance(raw) -> CentralBankStance:
    if raw is None:
        return _STANCE_FALLBACK
    if isinstance(raw, CentralBankStance):
        return raw
    try:
        return CentralBankStance(str(raw).upper())
    except ValueError:
        return _STANCE_FALLBACK


__all__ = ["CentralBankSummariser"]
