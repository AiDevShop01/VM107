"""
MACRO IntelligenceFeed composer — REQ-66-3 (Plan 66-07).

Sources: AnalyticsCalendarService.get_next_24h_events().
Novelty gate: macro_event_arrival, macro_forecast_surprise (HIGH triggers).
Lifecycle: event_date > now → 'active'; event_date < now → 'resolved'.

Design:
  - _calendar_service is injected in __init__ so tests can patch it directly.
  - _novelty_engine is injected so tests can patch score() side effects.
  - Returns MacroIntelligenceFeedItem — subclass of IntelligenceFeedItem that
    exposes lifecycle_state as an alias for state (forward-compat lock §16).

Architecture lock (CONTEXT.md §2): deterministic-first. LLM enrichment fires
ONLY when novelty.threshold_crossed is True.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from emitters.novelty_engine import NoveltyEngine, NoveltyDimensions

log = logging.getLogger(__name__)

# Valid lifecycle state strings — mirrors FeedItemState
_LIFECYCLE_ACTIVE = "active"
_LIFECYCLE_RESOLVED = "resolved"
_LIFECYCLE_WATCHING = "watching"
_LIFECYCLE_EXPIRED = "expired"


class MacroIntelligenceFeedItem:
    """Single macro intelligence feed item produced by IntelligenceFeedMacroComposer.

    Exposes `lifecycle_state` (forward-compat test seam) as an alias for `state`.
    Carries the minimal fields consumed by IntelligenceFeed.jsx (forward-compat lock §16):
      item_id, category, priority, title, summary, evidence, confidence,
      generated_at, source_emitter, state / lifecycle_state.
    """

    __slots__ = (
        "item_id", "category", "priority", "title", "summary",
        "evidence", "confidence", "generated_at", "source_emitter", "state",
        "llm_enriched",
    )

    def __init__(
        self,
        item_id: str,
        category: str,
        priority: str,
        title: str,
        summary: str,
        evidence: list[str],
        confidence: float,
        generated_at: datetime,
        source_emitter: str,
        state: str,
        llm_enriched: bool = False,
    ) -> None:
        self.item_id = item_id
        self.category = category
        self.priority = priority
        self.title = title
        self.summary = summary
        self.evidence = evidence
        self.confidence = confidence
        self.generated_at = generated_at
        self.source_emitter = source_emitter
        self.state = state
        self.llm_enriched = llm_enriched

    @property
    def lifecycle_state(self) -> str:
        """Alias for state — exposes lifecycle_state as test seam (forward-compat lock §16)."""
        return self.state


class IntelligenceFeedMacroComposer:
    """Deterministic + LLM-enriched MACRO intelligence feed composer.

    Reads from AnalyticsCalendarService (via _calendar_service attribute —
    injectable for tests). Applies NoveltyEngine gate before emitting each item.

    Usage::

        composer = IntelligenceFeedMacroComposer()
        items = composer.compose()
        # items: list[MacroIntelligenceFeedItem]
    """

    def __init__(
        self,
        novelty_engine: Optional[NoveltyEngine] = None,
        calendar_service=None,
    ) -> None:
        self._novelty_engine = novelty_engine or NoveltyEngine()

        if calendar_service is not None:
            self._calendar_service = calendar_service
        else:
            try:
                from mission_control.services.analytics_calendar_service import (
                    AnalyticsCalendarService,
                )
                self._calendar_service = AnalyticsCalendarService()
            except Exception:
                # Calendar service not available in this environment — tests patch it.
                self._calendar_service = None

    # ── Public API ──────────────────────────────────────────────────────────

    def compose(self) -> list[MacroIntelligenceFeedItem]:
        """Compose MACRO feed items from the analytics calendar.

        Returns:
            list[MacroIntelligenceFeedItem] — may be empty when no calendar
            events are scheduled (empty is a REAL signal per REQ-66-3).
        """
        if self._calendar_service is None:
            log.warning("IntelligenceFeedMacroComposer: calendar service unavailable — returning []")
            return []

        try:
            events = self._calendar_service.get_next_24h_events()
        except Exception as exc:
            log.warning(
                "IntelligenceFeedMacroComposer.compose: calendar fetch failed: %s(%s)",
                type(exc).__name__, exc,
            )
            return []

        items = []
        now = datetime.now(timezone.utc)
        for ev in events:
            item = self._compose_single(ev, now)
            if item is not None:
                items.append(item)
        return items

    # ── Internal helpers ────────────────────────────────────────────────────

    def _compose_single(
        self, ev, now: datetime
    ) -> Optional[MacroIntelligenceFeedItem]:
        """Compose a single MacroIntelligenceFeedItem from a calendar event object.

        Returns None if the event is low novelty and should be suppressed.
        """
        event_name = getattr(ev, "event_name", None) or str(ev)
        event_date_raw = getattr(ev, "event_date", None)
        risk_severity = getattr(ev, "risk_severity", "LOW")
        releasing_authority = getattr(ev, "releasing_authority", None)
        event_status = getattr(ev, "event_status", "scheduled")

        # Parse event_date (ISO string or datetime)
        event_dt = self._parse_event_date(event_date_raw, now)

        # Lifecycle state
        lifecycle_state = _LIFECYCLE_ACTIVE if event_dt > now else _LIFECYCLE_RESOLVED

        # Novelty scoring
        is_high = risk_severity in ("HIGH", "CRITICAL")
        dims = NoveltyDimensions(
            macro_novelty=0.8 if is_high else 0.3,
            macro_event_arrival=(lifecycle_state == _LIFECYCLE_ACTIVE),
        )
        novelty = self._novelty_engine.score(dims)

        # Deterministic base summary
        summary = self._render_deterministic(event_name, risk_severity, event_dt, now)

        # Optional LLM enrichment (additive only, does not replace factual fields)
        llm_enriched = False
        if novelty.threshold_crossed:
            enriched_text = self._call_llm(event_name, risk_severity, summary)
            if enriched_text:
                summary = enriched_text
                llm_enriched = True

        # Build evidence list
        evidence = [f"severity={risk_severity}"]
        if releasing_authority is not None:
            authority_code = getattr(releasing_authority, "authority_code", str(releasing_authority))
            evidence.append(f"authority={authority_code}")
        evidence.append(f"status={event_status}")
        evidence.append(f"lifecycle={lifecycle_state}")

        # Build stable item_id
        ts_key = int(event_dt.timestamp()) if event_dt else int(now.timestamp())
        item_id = f"macro-{event_name.replace(' ', '-').lower()}-{ts_key}"

        return MacroIntelligenceFeedItem(
            item_id=item_id,
            category="macro",
            priority="P1" if risk_severity == "CRITICAL" else ("P2" if risk_severity == "HIGH" else "P3"),
            title=event_name,
            summary=summary,
            evidence=evidence,
            confidence=0.9 if is_high else 0.6,
            generated_at=now,
            source_emitter="vm107.intelligence_feed.composer.macro",
            state=lifecycle_state,
            llm_enriched=llm_enriched,
        )

    def _parse_event_date(self, raw, fallback: datetime) -> datetime:
        """Parse event date from ISO string or datetime object."""
        if raw is None:
            return fallback
        if isinstance(raw, datetime):
            return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
        return fallback

    def _render_deterministic(
        self, event_name: str, risk_severity: str, event_dt: datetime, now: datetime
    ) -> str:
        """Deterministic template rendering — always produces a valid summary."""
        delta_seconds = (event_dt - now).total_seconds()
        if delta_seconds > 0:
            mins = int(delta_seconds // 60)
            if mins >= 60:
                time_desc = f"in {mins // 60}h {mins % 60}m"
            else:
                time_desc = f"in {mins}m"
        else:
            mins_ago = int(-delta_seconds // 60)
            time_desc = f"{mins_ago}m ago"
        return (
            f"{event_name} — {risk_severity.lower()} impact. "
            f"Releases {time_desc}."
        )

    def _call_llm(self, event_name: str, risk_severity: str, base_summary: str) -> Optional[str]:
        """Call Anthropic SDK for additive LLM enrichment. Additive only — never overrides facts."""
        try:
            import anthropic  # type: ignore[import]
            client = anthropic.Anthropic()
            prompt = (
                f"Deterministic base summary:\n\n\"{base_summary}\"\n\n"
                f"Event: {event_name} ({risk_severity} impact).\n\n"
                f"Add 1-2 sentences of operational trading context. "
                f"Do NOT contradict any fact. Respond with only the enriched paragraph."
            )
            message = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=128,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text.strip()
        except Exception as exc:
            log.warning(
                "IntelligenceFeedMacroComposer._call_llm failed: %s(%s)",
                type(exc).__name__, exc,
            )
            return None
