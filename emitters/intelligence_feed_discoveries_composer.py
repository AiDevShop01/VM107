"""
DISCOVERIES IntelligenceFeed composer — REQ-66-3 (Plan 66-07).

Three internal source domains:
  - PATTERN     : Phase 54 cross-trade patterns (CrossTradePatternsService)
  - BEHAVIORAL  : Phase 60 review_narrative table entries
  - EMERGENT    : VM107 novelty-surfaced signals (scaffolded empty in v1)

Per checker WARNING 2 (2026-05-23): The DISCOVERIES novelty threshold is LOADED
from NoveltyEngine.get_discoveries_threshold() — reads `discoveries_threshold` key
from VM107/emitters/novelty_config.yaml. NEVER define a module-level
DISCOVERIES_NOVELTY_THRESHOLD constant here. Phase 73 tunes via YAML.

Architecture lock (CONTEXT.md §2): deterministic-first.
"""
from __future__ import annotations

import enum
import logging
from datetime import datetime, timezone
from typing import Optional

from emitters.novelty_engine import NoveltyEngine

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Discovery category enum — locked per CONTEXT.md §4
# ─────────────────────────────────────────────────────────────────────────────


class DiscoveryCategory(str, enum.Enum):
    """Categories for discovery items. Values are uppercase strings."""
    PATTERN = "PATTERN"
    BEHAVIORAL = "BEHAVIORAL"
    EMERGENT = "EMERGENT"
    SYSTEMIC = "SYSTEMIC"
    CORRELATIONAL = "CORRELATIONAL"


# ─────────────────────────────────────────────────────────────────────────────
# Discovery item — lightweight carrier
# ─────────────────────────────────────────────────────────────────────────────


class DiscoveryFeedItem:
    """Single discovery item produced by IntelligenceFeedDiscoveriesComposer.

    Carries: item_id, category, priority, title, summary, evidence,
    confidence, generated_at, source_emitter, state.
    """

    __slots__ = (
        "item_id", "category", "priority", "title", "summary",
        "evidence", "confidence", "generated_at", "source_emitter", "state",
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
        state: str = "active",
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


# ─────────────────────────────────────────────────────────────────────────────
# Composer
# ─────────────────────────────────────────────────────────────────────────────


class IntelligenceFeedDiscoveriesComposer:
    """DISCOVERIES feed composer — Phase 54 patterns + Phase 60 narratives + emergent.

    Per WARNING 2 (2026-05-23): threshold loaded from NoveltyEngine.get_discoveries_threshold().
    Never hardcoded at module level.

    Usage::

        composer = IntelligenceFeedDiscoveriesComposer()
        items = composer.compose(account_id=42, state="mid")
    """

    def __init__(self, novelty_engine: Optional[NoveltyEngine] = None) -> None:
        self._novelty_engine = novelty_engine or NoveltyEngine()
        # Per WARNING 2 — threshold loaded from shared config, NOT a module constant.
        # Do NOT introduce DISCOVERIES_NOVELTY_THRESHOLD = <float literal> anywhere here.
        self._discoveries_threshold: float = self._novelty_engine.get_discoveries_threshold()

    def get_novelty_threshold(self) -> float:
        """Return the discoveries novelty threshold (loaded from shared config).

        Per WARNING 2: BOTH this value and the narrative threshold come from config.
        DISCOVERIESComposer carries a stricter gate than the global narrative emitter.
        """
        return self._discoveries_threshold

    # ── Public API ──────────────────────────────────────────────────────────

    def compose(self, account_id: int, state: str) -> list[DiscoveryFeedItem]:
        """Compose discovery items from three source domains.

        Applies stricter novelty filter: only items with confidence >=
        _discoveries_threshold pass (threshold loaded from shared NoveltyEngine config
        per WARNING 2 — not hardcoded here).

        Returns:
            list[DiscoveryFeedItem] — may be empty if no discoveries pass the threshold.
        """
        items: list[DiscoveryFeedItem] = []

        # 1. PATTERN — Phase 54 cross-trade patterns
        try:
            phase54 = self._fetch_phase54_patterns(account_id=account_id, state=state)
            items.extend(self._convert_phase54(phase54))
        except Exception as exc:
            log.warning(
                "IntelligenceFeedDiscoveriesComposer: phase54 fetch failed: %s(%s)",
                type(exc).__name__, exc,
            )

        # 2. BEHAVIORAL — Phase 60 review_narrative
        try:
            phase60 = self._fetch_phase60_narratives(account_id=account_id, state=state)
            items.extend(self._convert_phase60(phase60))
        except Exception as exc:
            log.warning(
                "IntelligenceFeedDiscoveriesComposer: phase60 fetch failed: %s(%s)",
                type(exc).__name__, exc,
            )

        # 3. EMERGENT — VM107 novelty surfacing (v1: scaffolded, empty)
        try:
            emergent = self._fetch_emergent_signals(account_id=account_id, state=state)
            items.extend(self._convert_emergent(emergent))
        except Exception as exc:
            log.warning(
                "IntelligenceFeedDiscoveriesComposer: emergent fetch failed: %s(%s)",
                type(exc).__name__, exc,
            )

        # Apply stricter discoveries filter — threshold from shared NoveltyEngine config
        # (per WARNING 2 — no hardcoded float literals on either side of the comparison)
        return [item for item in items if item.confidence >= self._discoveries_threshold]

    # ── Source fetchers (injectable for tests) ──────────────────────────────

    def _fetch_phase54_patterns(self, account_id: int, state: str) -> list:
        """Fetch Phase 54 cross-trade patterns.

        Calls CrossTradePatternsService.get_patterns via direct import (NOT HTTP
        self-call — per RESEARCH Pitfall 5 and Phase 65 pattern).

        Returns list of pattern objects/dicts; empty list on unavailability.
        """
        try:
            from journal.services.cross_trade_patterns_service import (  # type: ignore[import]
                CrossTradePatternsService,
            )
            service = CrossTradePatternsService()
            return list(service.get_patterns(
                account_id=str(account_id),
                scope=None,
                window_days=30,
            ) or [])
        except Exception as exc:
            log.debug(
                "_fetch_phase54_patterns: CrossTradePatternsService unavailable: %s(%s)",
                type(exc).__name__, exc,
            )
            return []

    def _fetch_phase60_narratives(self, account_id: int, state: str) -> list:
        """Fetch Phase 60 behavioral narratives from the review_narrative table.

        Returns list of narrative objects/dicts; empty list on unavailability.
        """
        try:
            # Phase 60 review_narrative is a Django model
            from journal.models import ReviewNarrative  # type: ignore[import]
            rows = list(
                ReviewNarrative.objects.filter(account_id=account_id).order_by(
                    "-created_at"
                )[:20]
            )
            return rows
        except Exception as exc:
            log.debug(
                "_fetch_phase60_narratives: review_narrative unavailable: %s(%s)",
                type(exc).__name__, exc,
            )
            return []

    def _fetch_emergent_signals(self, account_id: int, state: str) -> list:
        """Fetch VM107 novelty-surfaced emergent signals.

        Phase 66 v1: emergent layer is scaffolded but empty — detectors land in
        a future phase. Returns empty list.
        """
        return []

    # ── Converters ───────────────────────────────────────────────────────────

    def _convert_phase54(self, patterns: list) -> list[DiscoveryFeedItem]:
        """Convert Phase 54 pattern objects to DiscoveryFeedItem list."""
        now = datetime.now(timezone.utc)
        items = []
        for p in patterns:
            pattern_name = getattr(p, "pattern_name", None) or (
                p.get("pattern_name") if isinstance(p, dict) else "behavioral_pattern"
            )
            frequency = getattr(p, "frequency", None) or (
                p.get("frequency", 1) if isinstance(p, dict) else 1
            )
            if not pattern_name:
                continue
            frequency = int(frequency) if frequency else 1
            title = str(pattern_name).replace("_", " ").title()
            summary = f"Cross-trade pattern '{title}' observed {frequency} time(s) in recent trades."
            # Confidence scales with frequency — high-frequency patterns are more trustworthy
            confidence = min(0.5 + frequency * 0.05, 0.95)
            items.append(DiscoveryFeedItem(
                item_id=f"disc-pattern-{str(pattern_name).lower().replace(' ', '-')}",
                category=DiscoveryCategory.PATTERN.value,
                priority="P2" if frequency >= 3 else "P3",
                title=title,
                summary=summary,
                evidence=[f"frequency={frequency}", "source=phase54"],
                confidence=confidence,
                generated_at=now,
                source_emitter="vm107.intelligence_feed.composer.discoveries.pattern",
                state="active",
            ))
        return items

    def _convert_phase60(self, narratives: list) -> list[DiscoveryFeedItem]:
        """Convert Phase 60 review_narrative objects to DiscoveryFeedItem list."""
        now = datetime.now(timezone.utc)
        items = []
        for n in narratives:
            narrative_id = getattr(n, "narrative_id", None) or (
                n.get("narrative_id") if isinstance(n, dict) else None
            ) or "behavioral"
            summary_text = getattr(n, "summary", None) or (
                n.get("summary", "Behavioral pattern detected") if isinstance(n, dict) else "Behavioral pattern detected"
            )
            items.append(DiscoveryFeedItem(
                item_id=f"disc-behavioral-{str(narrative_id)}",
                category=DiscoveryCategory.BEHAVIORAL.value,
                priority="P3",
                title="Behavioral Pattern",
                summary=str(summary_text)[:200],
                evidence=["source=phase60_review_narrative"],
                confidence=0.75,
                generated_at=now,
                source_emitter="vm107.intelligence_feed.composer.discoveries.behavioral",
                state="active",
            ))
        return items

    def _convert_emergent(self, signals: list) -> list[DiscoveryFeedItem]:
        """Convert emergent signal objects to DiscoveryFeedItem list.

        Phase 66 v1: empty — detectors land in a future phase.
        """
        now = datetime.now(timezone.utc)
        items = []
        for sig in signals:
            novelty_score = getattr(sig, "novelty_score", 0.5)
            items.append(DiscoveryFeedItem(
                item_id=f"disc-emergent-{int(now.timestamp())}",
                category=DiscoveryCategory.EMERGENT.value,
                priority="P2",
                title="Emergent Signal",
                summary="VM107 novelty engine surfaced an emergent pattern.",
                evidence=[f"novelty_score={novelty_score}"],
                confidence=float(novelty_score),
                generated_at=now,
                source_emitter="vm107.intelligence_feed.composer.discoveries.emergent",
                state="active",
            ))
        return items
