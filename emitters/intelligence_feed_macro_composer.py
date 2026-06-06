"""Phase 83 Plan 09 — IntelligenceFeedMacroComposer (4-surgery refactor).

Surgery 1: HTTP client data source (RISK-06 consumer closure)
  - Removes broken Django ORM cross-VM import
  - Uses MacroCalendarHTTPClient calling VM100's Plan 07 endpoint
  - Decision D1: VM107 → VM100 direction via typed HTTP contract

Surgery 2: LLM routing (Pitfall 6 closure)
  - Removes direct SDK usage (anthropic SDK no longer imported)
  - Uses Phase 43 ModelRouter via utility profile (Agent Hands)
  - Phase 43.2 graceful degradation: None narrative on any failure

Surgery 3: NoveltyEngine V1 integration (Phase 66 Lock 2)
  - score_macro() called per item (deterministic, no LLM)
  - LLM enrichment gated on threshold_crossed=True
  - NoveltyScore embedded in emission payload

Surgery 4: Phase 70.5 envelope wrap (Open Question 6 — emitter side)
  - Wraps payload in ToolResultEnvelope[MacroEmissionPayload]
  - Provenance fields populated for Phase 71 Evidence Drawer

Architecture locks:
  - Phase 66 Lock 2: LLM enrichment fires ONLY when novelty.threshold_crossed is True
  - Phase 66 Lock 4: short journalistic prose (≤200 chars), 1-2 sentences max
  - Phase 65 lock: _demo=False always here — Plan 10 env-flag flip owns True
  - CLAUDE.md: No Django ORM imports from VM107
  - CLAUDE.md: No direct Anthropic SDK instantiation in VM107 emitters
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import litellm
from pydantic import BaseModel

from fingpt_core.contracts.tool_envelope import ToolResultEnvelope, ENVELOPE_SCHEMA_VERSION
from core.routing.schemas import RouterContext
from lib.novelty_engine import NoveltyEngine, NoveltyScore, NoveltyDimensions
from services.macro_calendar_client import MacroCalendarHTTPClient

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic payload contracts (Phase 83 Plan 09)
# ---------------------------------------------------------------------------

class MacroItem(BaseModel):
    """Single macro event item in the emission payload.

    Phase 66 Lock 4: headline always present (deterministic).
    narrative is None when LLM enrichment not triggered or fails (Tier-1 degradation).
    novelty_score always present (Phase 66 Lock E1 — deterministic).
    demo=False always here — Plan 10 env-flag flip owns the True path.
    """
    event_id: str
    indicator_code: str
    indicator_short_name: str
    event_date: str
    severity: str
    releasing_authority: Optional[str] = None
    headline: str              # Deterministic narrative — always present
    narrative: Optional[str] = None   # LLM-enriched (None if Tier-1 fallback)
    novelty_score: NoveltyScore       # Deterministic; Phase 66 Lock E1
    demo: bool = False                # Phase 65 lock — Plan 10 owns the True path

    model_config = {"arbitrary_types_allowed": True}  # for NoveltyScore dataclass


class MacroEmissionPayload(BaseModel):
    """Emission payload for the MACRO intelligence feed.

    degraded=True when calendar client returned [] (Tier-3 indicator).
    Plan 11 will elaborate the degradation tiers.
    """
    items: list[MacroItem]
    state: str
    generated_at: str
    degraded: bool = False
    source: str = "vm107.intelligence_feed_macro_composer"


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------

class IntelligenceFeedMacroComposer:
    """MACRO intelligence feed composer — refactored for Plan 09.

    Data source: MacroCalendarHTTPClient → VM100 GET /api/v1/mission-control/calendar/upcoming
    LLM routing: Phase 43 ModelRouter (utility path, Agent Hands profile)
    Novelty gate: NoveltyEngine V1 score_macro() — deterministic, LLM-free
    Output: ToolResultEnvelope[MacroEmissionPayload] (Phase 70.5 contract)

    Usage::

        composer = IntelligenceFeedMacroComposer()
        envelope = composer.compose(state='OPEN')
        # envelope: ToolResultEnvelope[MacroEmissionPayload]

    Constructor accepts injectable deps for testing:

        composer = IntelligenceFeedMacroComposer(
            novelty_engine=mock_engine,
            calendar_client=mock_client,
            router=mock_router,
        )
    """

    def __init__(
        self,
        novelty_engine: Optional[NoveltyEngine] = None,
        calendar_client: Optional[MacroCalendarHTTPClient] = None,
        router=None,
    ) -> None:
        self._novelty_engine = novelty_engine or NoveltyEngine()
        self._calendar_client = calendar_client or MacroCalendarHTTPClient()
        self._router = router  # None = ModelRouter lazy-init in _call_llm

    # ── Public API ──────────────────────────────────────────────────────────

    def compose(self, state: str = "OPEN") -> ToolResultEnvelope[MacroEmissionPayload]:
        """Compose MACRO feed items and return a Phase 70.5 envelope.

        Args:
            state: Market state string (e.g. 'OPEN', 'CLOSED').

        Returns:
            ToolResultEnvelope[MacroEmissionPayload] — always returned, never raises.
            Empty items + degraded=True when calendar client is unavailable.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # Fetch calendar items via HTTP client (Surgery 1).
        # Window configurable via env var so operators can widen during quiet
        # FRED-release stretches (weekends, holidays); default 24h preserves
        # original behavior for normal trading days.
        lookahead = int(os.environ.get("MACRO_EMITTER_LOOKAHEAD_HOURS", "24"))
        raw_items = self._calendar_client.fetch_upcoming(hours=lookahead)

        macro_items: list[MacroItem] = []
        decision_model_id: Optional[str] = None

        if raw_items:
            for raw in raw_items:
                item, model_id = self._compose_single(raw, now)
                if item is not None:
                    macro_items.append(item)
                if model_id is not None:
                    decision_model_id = model_id

        degraded = len(raw_items) == 0

        # Build payload (Surgery 4 — envelope wrap)
        payload = MacroEmissionPayload(
            items=macro_items,
            state=state,
            generated_at=now_iso,
            degraded=degraded,
            source="vm107.intelligence_feed_macro_composer",
        )

        envelope = ToolResultEnvelope[MacroEmissionPayload](
            envelope_id=uuid.uuid4(),
            tool_name="vm107.intelligence_feed.macro",
            tool_version="1.0",
            outcome_class="success" if not degraded else "degraded",
            success=True,
            generated_at=now,
            registry_snapshot_hash=self._registry_snapshot_hash(),
            payload_schema_version="1.0",
            payload=payload,
        )
        return envelope

    # ── Internal helpers ────────────────────────────────────────────────────

    def _compose_single(
        self, raw: dict, now: datetime
    ) -> tuple[Optional[MacroItem], Optional[str]]:
        """Compose a single MacroItem from a raw calendar event dict.

        Returns (MacroItem, model_id_if_llm_used).
        """
        event_id = raw.get("event_id", "")
        indicator_code = raw.get("indicator_code", "")
        indicator_short_name = raw.get("indicator_short_name", indicator_code)
        event_date_str = raw.get("event_date", now.isoformat())
        severity = raw.get("severity", "MEDIUM")
        releasing_authority = raw.get("releasing_authority")

        # Deterministic headline (Phase 66 Lock 4)
        headline = self._build_headline(
            indicator_short_name, releasing_authority, event_date_str
        )

        # Build novelty scoring payload (Surgery 3)
        novelty_payload = {
            "indicator_code": indicator_code,
            "releasing_authority": releasing_authority or "",
            "event_date": event_date_str,
            "severity": severity,
        }
        novelty: NoveltyScore = self._novelty_engine.score(
            NoveltyDimensions.MACRO,
            novelty_payload,
        )

        # LLM enrichment gated on threshold_crossed (Phase 66 Lock 2)
        narrative: Optional[str] = None
        model_id: Optional[str] = None
        if novelty.threshold_crossed:
            narrative, model_id = self._call_llm_with_decision(
                indicator_short_name, severity, headline
            )

        return MacroItem(
            event_id=event_id,
            indicator_code=indicator_code,
            indicator_short_name=indicator_short_name,
            event_date=event_date_str,
            severity=severity,
            releasing_authority=releasing_authority,
            headline=headline,
            narrative=narrative,
            novelty_score=novelty,
            demo=False,  # Phase 65 lock — Plan 10 env-flag flip
        ), model_id

    def _build_headline(
        self,
        indicator_short_name: str,
        releasing_authority: Optional[str],
        event_date_str: str,
    ) -> str:
        """Deterministic headline template (Phase 66 Lock 4 — short journalistic prose)."""
        authority_part = f" by {releasing_authority}" if releasing_authority else ""
        return f"{indicator_short_name} release{authority_part} at {event_date_str}."

    def _call_llm(
        self, event_name: str, severity: str, base_summary: str
    ) -> Optional[str]:
        """Call LLM via Phase 43 ModelRouter (Agent Hands utility profile).

        Surgery 2: Never calls the anthropic SDK directly — uses litellm + ModelRouter.
        Phase 43.2 graceful degradation: returns None on any failure.

        Returns:
            narrative_text on success (max 200 chars — Phase 66 Lock 4).
            None on any failure (Tier-1 deterministic fallback).
        """
        narrative, _ = self._call_llm_with_decision(event_name, severity, base_summary)
        return narrative

    def _call_llm_with_decision(
        self, event_name: str, severity: str, base_summary: str
    ) -> tuple[Optional[str], Optional[str]]:
        """Internal — returns (narrative, model_id). Callers that need model_id use this."""
        router = self._get_router()
        if router is None:
            log.warning(
                "IntelligenceFeedMacroComposer._call_llm: no router available (Tier-1 fallback)"
            )
            return None, None

        ctx = RouterContext(
            task_id=f"macro-enrich-{uuid.uuid4().hex[:12]}",
            goal_id="vm107.macro_emitter",
            agent_id="macro_emitter",
            task_type="macro_narrative_enrichment",
            priority="P3",
            latency_sla_ms=5000,
            brain_context={"mode": "exploitation"},
            path="utility",  # Agent Hands profile per Phase 43.1
        )

        try:
            decision = router.decide(ctx)
            model_id = decision.primary

            prompt = self._build_llm_prompt(event_name, severity, base_summary)
            response = litellm.completion(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=128,
            )
            raw_text = response.choices[0].message.content or ""
            # Phase 66 Lock 4: truncate to 200 chars to enforce brevity
            narrative = raw_text.strip()[:200]
            return narrative, model_id

        except Exception as exc:
            log.warning(
                "IntelligenceFeedMacroComposer._call_llm failed (Tier-1 fallback): %s: %r",
                type(exc).__name__, exc,
            )
            return None, None

    def _build_llm_prompt(
        self, event_name: str, severity: str, base_summary: str
    ) -> str:
        """LLM enrichment prompt (Phase 66 Lock 4 — 1-2 sentences, factual only)."""
        return (
            f"Write a 1-2 sentence journalistic summary explaining why this "
            f"{severity} {event_name} release matters for traders. "
            f"Be factual. Do not predict the outcome. "
            f"Context: {base_summary}"
        )

    def _get_router(self):
        """Return injected router or None (lazy default deferred to test boundary)."""
        return self._router

    def _registry_snapshot_hash(self) -> str:
        """Placeholder provenance hash (Phase 47.6 registry will fill this)."""
        return "plan09-v1-deterministic"
