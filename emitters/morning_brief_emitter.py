"""MorningBriefEmitter — Phase 67 Plan 06 (REQ-67-3).

Mirrors the Phase 66 ``global_narrative_emitter.py`` 5-step pipeline verbatim:

    1. Health-registry clear (skip emit if upstream sources unhealthy)
    2. Context assembly from typed VM APIs (NEVER filesystem — load-bearing
       constraint #2 from MEMORY.md)
    3. Degradation tier classification (FULL / PARTIAL / DEGRADED)
    4. Deterministic base summary (ALWAYS produced regardless of novelty)
    5. Novelty scoring (shared NoveltyEngine instance — Phase 66 lock)
    6. _demo flip (DEGRADED → _demo=True)
    7. Optional LLM enrichment (additive only — never replaces deterministic base)
    8. Return typed MorningBriefContract → VM100 client

Snapshot-before-publish ordering (REQ-66-5 lock) preserved in
``persist_and_publish()``: ``transaction.atomic()`` wraps the publish so
downstream Redis invalidation fires only AFTER the (future) snapshot row
commits.  No SnapshotModel ships in Phase 67 v1 — the wiring is in place
for Plan 13 to add when WS replay requirements demand it.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from emitters.contracts.morning_brief import MorningBriefContract
from emitters.degradation_policy_engine import (
    DegradationPolicyEngine,
    DegradationTier,
)
from emitters.novelty_engine import NoveltyDimensions, NoveltyEngine
from emitters.source_health_registry import SourceHealthRegistry

log = logging.getLogger(__name__)

# Source IDs reported into the health registry during context assembly.
# Plan 13 sensor / scheduler can read these to gate emit cycles.
_CONTEXT_SOURCES = ("vm100", "vm102")


# Tier → confidence_score map (CONTEXT.md §2 + Plan 67-02 4-tier policy).
_TIER_CONFIDENCE: dict[str, float] = {
    "FULL": 0.95,
    "PARTIAL": 0.65,
    "DEGRADED": 0.30,
}


def _classify_tier(missing_count: int) -> str:
    """0 missing → FULL; 1 → PARTIAL; 2+ → DEGRADED (per plan behavior block)."""
    if missing_count == 0:
        return "FULL"
    if missing_count == 1:
        return "PARTIAL"
    return "DEGRADED"


class MorningBriefEmitter:
    """Pre-market AI briefing assembled from market + macro + behavioral context.

    Mirror of GlobalNarrativeEmitter pattern — same 5-step pipeline shape,
    same shared engine usage, same snapshot-before-publish ordering.

    Dependencies are injected to support unit-test isolation:
        novelty_engine      — NoveltyEngine instance (SHARED — Phase 66 lock)
        health_registry     — SourceHealthRegistry instance (SHARED)
        degradation_engine  — DegradationPolicyEngine instance
        vm100_client        — Optional VM100 chokepoint client for context assembly

    Usage::

        emitter = MorningBriefEmitter()
        brief = emitter.get_morning_brief(account_id=42)
        # brief is a MorningBriefContract
    """

    def __init__(
        self,
        novelty_engine: NoveltyEngine | None = None,
        health_registry: SourceHealthRegistry | None = None,
        degradation_engine: DegradationPolicyEngine | None = None,
        vm100_client: Any | None = None,
    ) -> None:
        # SHARED instances (Phase 66 lock — never instantiate new ones here
        # when the caller didn't inject; defer to the singleton accessor).
        self._novelty = novelty_engine or NoveltyEngine.get_shared_instance()
        self._health = health_registry or SourceHealthRegistry.get_shared_instance()
        self._degradation = degradation_engine or DegradationPolicyEngine()
        self._vm100 = vm100_client

    # ── Public API ─────────────────────────────────────────────────────────

    def get_morning_brief(self, account_id: int) -> MorningBriefContract:
        """Build a MorningBriefContract for the given account.

        Pipeline:
          1. Clear per-cycle health state.
          2. Assemble context from typed VM APIs (graceful on failure).
          3. Classify degradation tier from missing sources.
          4. Build deterministic base (headline / body / catalysts / risks).
          5. Score novelty via the SHARED NoveltyEngine.
          6. Flip _demo when tier == DEGRADED.
          7. If novelty crossed AND not demo, request LLM enrichment.
          8. Build + return MorningBriefContract.
        """
        # 1. Health clear (per-cycle isolation).
        self._health.clear()

        # 2. Context assembly — graceful degradation on any exception.
        ctx: dict[str, Any] = {}
        ctx_failed = False
        try:
            ctx = self._assemble_context(account_id)
        except Exception as exc:
            log.warning(
                "morning_brief_context_assembly_failed: %s(%s)",
                type(exc).__name__,
                exc,
            )
            ctx_failed = True
            for src_id in _CONTEXT_SOURCES:
                self._health.report(src_id, available=False, failure_reason=str(exc))

        # 3. Degradation tier — derived from health snapshot.
        health_snapshot = self._health.snapshot()
        missing_sources = [
            sid for sid, h in health_snapshot.items() if not h.available
        ]
        tier = _classify_tier(len(missing_sources))

        # 4. Deterministic base summary (ALWAYS produced).
        base = self._build_base_summary(ctx, tier)

        # 5. Novelty scoring via SHARED engine.
        dims = self._compute_novelty_dims(ctx)
        novelty = self._novelty.score(dims)

        # 6. _demo flip — Tier 3 / DEGRADED + ctx_failed both flip.
        demo = (tier == "DEGRADED") or ctx_failed

        # 7. Optional LLM enrichment.
        enriched_headline: str | None = None
        enriched_body: str | None = None
        if getattr(novelty, "threshold_crossed", False) and not demo:
            enriched_headline, enriched_body = self._call_llm(base, ctx, novelty)

        # 8. Return typed contract.
        return MorningBriefContract(
            brief_id=f"mb-{uuid.uuid4().hex[:12]}",
            account_id=account_id,
            generated_at=datetime.now(timezone.utc),
            headline=base["headline"],
            body=base["body"],
            top_catalysts=base["catalysts"][:3],
            risk_alerts=base["risks"][:3],
            llm_enriched_headline=enriched_headline,
            llm_enriched_body=enriched_body,
            confidence_score=_TIER_CONFIDENCE[tier],
            confidence_tier=tier,  # type: ignore[arg-type]
            missing_sources=missing_sources,
            _demo=demo,
            novelty_score=float(getattr(novelty, "score", 0.0)),
            novelty_crossed=bool(getattr(novelty, "threshold_crossed", False)),
        )

    # ── Snapshot-before-publish hook (REQ-66-5 lock) ─────────────────────────

    def persist_and_publish(
        self,
        brief: MorningBriefContract,
        invalidation_reason: str = "SCHEDULED",
    ) -> None:
        """Persist (future model) + publish snapshot invalidation.

        Snapshot-before-publish ordering preserved via ``transaction.atomic()``
        + ``publish_after_commit`` — Redis invalidation fires only AFTER
        the DB row commits.  Plan 13 may add MorningBriefSnapshot ORM.

        No-op if Django / publisher unavailable (test / offline mode).
        """
        # Phase 136 / SC-2 / D-01: the historic Django-import early-return guard that
        # silently no-op'd this path in the Django-less VM107 runtime is removed. The
        # publish attempt is resolved directly against the VM107-local Django-free
        # publisher and fired immediately (no transaction.atomic()).
        try:
            from mission_control.services.snapshot_invalidation_publisher import (
                SnapshotInvalidationPublisher,
            )
        except ImportError:
            try:
                from services.snapshot_invalidation_publisher import (  # type: ignore[import]
                    SnapshotInvalidationPublisher,
                )
            except ImportError:
                log.warning(
                    "morning_brief_emitter.persist_and_publish: "
                    "SnapshotInvalidationPublisher not available — skipping publish"
                )
                return

        publisher = SnapshotInvalidationPublisher()
        # VM107 has no Django DB transaction — publish IMMEDIATELY (fire-and-forget).
        publisher.publish_after_commit(
            topic="mission_control.pre.morning_brief",
            snapshot_id=brief.brief_id,
            account_id=brief.account_id,
            invalidation_reason=invalidation_reason,
        )

    # ── Internal helpers ───────────────────────────────────────────────────

    def _assemble_context(self, account_id: int) -> dict:
        """Assemble morning-brief context via typed VM APIs.

        Calls VM100 (market + macro) + VM102 (risk) via injected chokepoint
        client when present.  Otherwise reports both sources as available
        with placeholder shapes — Plan 13 wires the actual clients in
        production.  NEVER reads the filesystem.
        """
        ctx: dict[str, Any] = {
            "account_id": account_id,
            "ribbon": {},
            "macro_events": [],
            "risk_metrics": {},
            "behavioral_baseline": {},
        }

        if self._vm100 is not None:
            # Production path — call VM100 chokepoint helpers (each method on
            # the injected client returns its own typed payload, errors are
            # caught per-source so a single VM failure stays Tier PARTIAL).
            try:
                ctx["ribbon"] = self._vm100.get_ribbon(account_id) or {}
                self._health.report("vm100", available=True)
            except Exception as exc:
                self._health.report(
                    "vm100", available=False, failure_reason=str(exc)
                )

            try:
                ctx["risk_metrics"] = self._vm100.get_risk_metrics(account_id) or {}
                self._health.report("vm102", available=True)
            except Exception as exc:
                self._health.report(
                    "vm102", available=False, failure_reason=str(exc)
                )
        else:
            # Test / offline path — assume both healthy with empty context.
            self._health.report("vm100", available=True)
            self._health.report("vm102", available=True)

        return ctx

    def _build_base_summary(self, ctx: dict, tier: str) -> dict:
        """Deterministic base (ALWAYS produced — no LLM, no novelty gating).

        Returns a dict with keys: headline / body / catalysts / risks.
        Plan 13 may swap to a richer template; the shape is stable.
        """
        macro_events = ctx.get("macro_events") or []
        catalysts = [e.get("title", "Unnamed event") for e in macro_events[:3]]
        if not catalysts:
            catalysts = ["No high-impact macro events scheduled"]

        risk_metrics = ctx.get("risk_metrics") or {}
        risks: list[str] = []
        if risk_metrics.get("var95_breach"):
            risks.append("Portfolio VaR95 breached overnight")
        if risk_metrics.get("concentration_risk"):
            risks.append("Concentration risk elevated in top position")
        if risk_metrics.get("correlation_risk"):
            risks.append("Cross-asset correlations have shifted")

        if tier == "DEGRADED":
            headline = "Morning brief operating in degraded mode"
            body = (
                "Upstream data sources are unavailable; the morning brief is "
                "rendered from cached baselines only. Treat as informational."
            )
        elif tier == "PARTIAL":
            headline = "Morning brief — partial data context"
            body = (
                "Some context sources are unavailable; the brief is built from "
                "the remaining healthy sources. Confidence is reduced."
            )
        else:  # FULL
            headline = "Morning brief — full context assembled"
            body = (
                "Pre-market context assembled from market, macro, and risk "
                "sources. Review the catalyst list and risk alerts below."
            )

        return {
            "headline": headline,
            "body": body,
            "catalysts": catalysts,
            "risks": risks,
        }

    def _compute_novelty_dims(self, ctx: dict) -> NoveltyDimensions:
        """Map assembled context → NoveltyDimensions deterministically."""
        macro_events = ctx.get("macro_events") or []
        risk_metrics = ctx.get("risk_metrics") or {}
        return NoveltyDimensions(
            macro_novelty=min(1.0, len(macro_events) * 0.25),
            regime_novelty=float(risk_metrics.get("regime_shift_score", 0.0)),
            structural_novelty=0.0,
            volatility_novelty=float(risk_metrics.get("vol_expansion_score", 0.0)),
            behavioral_novelty=0.0,
            macro_event_arrival=any(
                e.get("severity") in ("HIGH", "EXTREME") for e in macro_events
            ),
            risk_escalation=bool(risk_metrics.get("var95_breach")),
        )

    def _call_llm(
        self,
        base: dict,
        ctx: dict,
        novelty: Any,
    ) -> tuple[str | None, str | None]:
        """Optional LLM enrichment — returns (enriched_headline, enriched_body).

        Mock-seam for tests:
            patch.object(emitter, '_call_llm', return_value=('H', 'B'))

        Returns (None, None) on any error — engine survives without LLM.
        """
        try:
            import anthropic  # type: ignore[import]

            client = anthropic.Anthropic()
            novelty_codes = getattr(novelty, "reason_codes", [])
            prompt = (
                f"Given this deterministic morning-brief base:\n\n"
                f"Headline: {base['headline']}\n"
                f"Body: {base['body']}\n\n"
                f"And these novelty signals: {', '.join(novelty_codes) or 'none'}.\n\n"
                f"Rewrite the headline as a single tight sentence and add one "
                f"paragraph of operational insight for a trader. Do NOT "
                f"contradict any fact in the base. Respond in this exact JSON "
                f"shape: {{\"headline\": \"...\", \"body\": \"...\"}}."
            )
            message = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            import json

            payload = json.loads(message.content[0].text.strip())
            return payload.get("headline"), payload.get("body")
        except Exception as exc:
            log.warning(
                "morning_brief_llm_enrichment_failed: %s(%s)",
                type(exc).__name__,
                exc,
            )
            return None, None
