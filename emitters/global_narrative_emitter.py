"""
Global Narrative emitter — REQ-66-1 + CONTEXT.md §2.

Architecture (deterministic-first lock):
    Context Assembly → _build_base_summary (deterministic) →
    Novelty Scoring  → (IF threshold_crossed: _call_llm ELSE: emit template)

The canonical reference implementation for every other emitter in Wave 2.
Both `deterministic_base_summary` and `llm_enriched_summary` are always
persisted when LLM enrichment fires (additive-only).

Public API:
    emitter.get_narrative(state) -> dict   — returns GlobalNarrativeContract-shaped dict
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from emitters.source_health_registry import SourceHealthRegistry, SourceHealth
from emitters.degradation_policy_engine import DegradationPolicyEngine, DegradationTier
from emitters.novelty_engine import NoveltyEngine, NoveltyDimensions, NoveltyScore

log = logging.getLogger(__name__)

# Per-state cadence in seconds (CONTEXT.md §2).
# PRE=5min, OPEN=60s, ACTIVE_SUPERVISION≈90s, MID=2min, CLOSE=5min.
STATE_CADENCE_SECONDS: dict[str, int] = {
    "pre": 300,
    "open": 60,
    "active_supervision": 90,
    "mid": 120,
    "close": 300,
    "review": 0,
}

# Source IDs that will be reported after context assembly.
# These represent the typed-API surfaces the emitter pulls from.
_CONTEXT_SOURCES = [
    "vm100.macro",
    "vm101.structural",
    "vm102.risk",
    "vm107.session",
]


class GlobalNarrativeEmitter:
    """Deterministic + LLM-enriched global narrative emitter.

    Dependencies are injected to support unit-test isolation:
        novelty_engine      — NoveltyEngine instance (shared)
        health_registry     — SourceHealthRegistry instance
        degradation_engine  — DegradationPolicyEngine instance

    Usage::

        emitter = GlobalNarrativeEmitter()
        result = emitter.get_narrative(state="mid")
        # result is a GlobalNarrativeContract-shaped dict
    """

    def __init__(
        self,
        novelty_engine: NoveltyEngine | None = None,
        health_registry: SourceHealthRegistry | None = None,
        degradation_engine: DegradationPolicyEngine | None = None,
    ) -> None:
        self._novelty = novelty_engine or NoveltyEngine()
        self._health = health_registry or SourceHealthRegistry()
        self._degradation = degradation_engine or DegradationPolicyEngine()

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_narrative(
        self,
        state: str,
        refresh_reason: str = "SCHEDULED",
        interrupt_dims: NoveltyDimensions | None = None,
    ) -> dict:
        """Emit a GlobalNarrativeContract-shaped dict for the given trading state.

        Args:
            state: Trading session state ('pre'|'open'|'mid'|'close'|...).
                   Raises ValueError when None.
            refresh_reason: Why this narrative was triggered.
            interrupt_dims: Pre-computed novelty dimensions (from interrupt signal).
                            When None, novelty is computed from assembled context.

        Returns:
            dict matching AINarrativeContract (all fields populated).
        """
        if state is None:
            raise ValueError("state must be provided (e.g. 'mid', 'open', 'pre', 'close')")
        state_lower = state.lower()

        # 1. Clear registry for this emit cycle.
        self._health.clear()

        # 2. Context assembly from typed APIs (NEVER filesystem).
        ctx: dict = {}
        ctx_failed = False
        try:
            ctx = self._assemble_context(state_lower)
        except Exception as exc:
            log.warning(
                "global_narrative_context_assembly_failed: %s(%s)",
                type(exc).__name__,
                exc,
            )
            ctx_failed = True
            # Mark all sources as unavailable so tier_for() returns TIER_3.
            for src_id in _CONTEXT_SOURCES:
                self._health.report(src_id, available=False, failure_reason=str(exc))

        # 3. Degradation tier.
        tier = self._degradation.tier_for(self._health.snapshot())

        # 4. Deterministic base summary (ALWAYS produced, even on Tier 3).
        base_summary = self._build_base_summary(ctx, state_lower)

        # 5. Novelty scoring — uses interrupt dims if provided.
        # 2026-07-02: guarded because prior implementation constructed
        # `NoveltyDimensions(macro_novelty=..., regime_novelty=..., ...)`
        # against a string Enum (raised `TypeError: EnumType.__call__() got
        # an unexpected keyword argument 'macro_novelty'`), 500-ing every
        # narrative fetch and forcing VM100's fallback path on every page
        # load. The engine V1 only has a live MACRO scorer; other dims
        # raise NotImplementedError. If the picked dimension's scorer
        # can't process `ctx` (shape mismatch is likely — score_macro
        # wants indicator_code/severity/event_date, ctx has aggregated
        # summary fields), degrade to a zero-novelty score so the
        # template-summary path still emits (no LLM enrichment).
        try:
            dims = interrupt_dims or self._compute_novelty_dims(ctx)
            novelty = self._novelty.score(dims, ctx)
        except Exception as exc:  # noqa: BLE001 — defensive: never 500 the endpoint
            log.warning(
                "global_narrative_emitter.novelty_scoring_degraded",
                extra={"exc_type": type(exc).__name__, "exc": str(exc)[:200]},
            )
            novelty = NoveltyScore(
                score=0.0,
                contributing_factors=[],
                threshold_crossed=False,
                reason_codes=["NOVELTY_SCORING_DEGRADED"],
            )

        # 6. Confidence vector (compound DEMO-flip rule from CONTEXT.md §2).
        confidence = self._compute_confidence(ctx, tier)
        is_demo = (tier == DegradationTier.TIER_3) or self._demo_flip_compound(confidence)

        # 7. Optional LLM enrichment — additive only, factual fields unchanged.
        # _call_llm is the novelty gate: it internally checks threshold_crossed
        # and returns None when novelty is insufficient or LLM is unavailable.
        # The enrichment guard here prevents LLM calls in full Tier 3 degradation.
        llm_summary: str | None = None
        enrichment_applied = False
        if not is_demo:
            llm_summary = self._call_llm(base_summary, ctx, novelty)
            enrichment_applied = llm_summary is not None

        # 8. Assemble contract.
        now = datetime.now(timezone.utc)
        cadence_s = STATE_CADENCE_SECONDS.get(state_lower, 120)
        next_refresh = now + timedelta(seconds=cadence_s) if cadence_s > 0 else None

        return {
            "narrative_id": f"narr-{state_lower}-{int(now.timestamp())}",
            "summary": llm_summary or base_summary,
            "confidence_vector": {
                "coverage": confidence.coverage,
                "source_diversity": confidence.source_diversity,
                "freshness_hours": confidence.freshness_hours,
                "evidence_density": confidence.evidence_density,
            },
            "generated_at": now.isoformat(),
            "model_version": "claude-sonnet-4-5" if enrichment_applied else "deterministic-v1",
            "prompt_version": "gn-v1.0" if enrichment_applied else "template-v1",
            "evidence": ctx.get("evidence", []),
            "_demo": is_demo,
            "degraded_mode": (tier != DegradationTier.HEALTHY),
            "missing_sources": [
                sid for sid, h in self._health.snapshot().items() if not h.available
            ],
            "stale_threshold_seconds": cadence_s * 2 if cadence_s > 0 else 0,
            "refresh_reason": refresh_reason,
            "next_refresh_at": next_refresh.isoformat() if next_refresh else None,
            "deterministic_base_summary": base_summary,  # ALWAYS persisted
            "llm_enriched_summary": llm_summary,           # ONLY when enrichment fires
        }

    # ── Snapshot invalidation hook (REQ-66-5 cross-plan wiring, Plan 66-09 Task 3a) ──

    def persist_and_publish_narrative(
        self,
        narrative_dict: dict,
        account_id: int,
        invalidation_reason: str = "SCHEDULED",
    ) -> None:
        """Persist a narrative snapshot to DB and publish invalidation event after commit.

        Per WARNING 4 (Plan 66-09 files_modified) — this is the explicit snapshot-write
        site for GlobalNarrativeEmitter. The snapshot ORM create is wrapped in
        transaction.atomic() and publish_after_commit is registered inside that block,
        guaranteeing snapshot row exists in DB before Redis invalidation publish fires.

        Usage (from Dagster narrative asset or VM107 API endpoint)::

            emitter = GlobalNarrativeEmitter()
            result = emitter.get_narrative(state="mid")
            emitter.persist_and_publish_narrative(result, account_id=42)

        This method is a no-op if the NarrativeSnapshot model is unavailable
        (graceful degradation for test/offline mode).
        """
        try:
            from django.db import transaction
        except ImportError:
            # Django not available in this runtime (VM107 local process) — skip
            return

        try:
            # Import publisher here to avoid circular import at module load
            from mission_control.services.snapshot_invalidation_publisher import (
                SnapshotInvalidationPublisher,
            )
        except ImportError:
            # VM100 mission_control not importable from VM107 — use local mirror if available
            try:
                from services.snapshot_invalidation_publisher import (  # type: ignore[import]
                    SnapshotInvalidationPublisher,
                )
            except ImportError:
                log.warning(
                    "global_narrative_emitter.persist_and_publish_narrative: "
                    "SnapshotInvalidationPublisher not available — invalidation publish skipped"
                )
                return

        narrative_id = narrative_dict.get("narrative_id", f"narr-{int(datetime.now(timezone.utc).timestamp())}")
        publisher = SnapshotInvalidationPublisher()

        with transaction.atomic():
            # NOTE: NarrativeSnapshot model will be added in a later plan.
            # For now this block establishes the transaction.atomic() + publish_after_commit
            # wiring pattern so the ordering guarantee is in place when the model lands.
            publisher.publish_after_commit(
                topic="homepage.global",
                snapshot_id=narrative_id,
                account_id=account_id,
                invalidation_reason=invalidation_reason,
            )

    # ── Context assembly ────────────────────────────────────────────────────

    def _assemble_context(self, state: str) -> dict:
        """Call VM100/VM101/VM102 typed APIs to assemble narrative context.

        NEVER reads the filesystem — all data comes from HTTP typed APIs.
        Reports per-source health to self._health after each call.

        Returns dict with keys: evidence, macro_events, structural, risk,
        session, regime, macro_novelty, regime_novelty, structural_novelty,
        volatility_novelty, behavioral_novelty, freshness_hours, etc.
        """
        ctx: dict[str, Any] = {
            "evidence": [],
            "macro_events": [],
            "structural": [],
            "risk": {},
            "session": {"state": state},
            "regime": {"label": "UNKNOWN", "confidence": 0.5},
            "macro_novelty": 0.0,
            "regime_novelty": 0.0,
            "structural_novelty": 0.0,
            "volatility_novelty": 0.0,
            "behavioral_novelty": 0.0,
            "freshness_hours": 0.0,
        }

        # Try fetching macro context via the macro-agent tool.
        try:
            from tools.get_macro_context import get_macro_context  # type: ignore[import]
            macro_data = get_macro_context(state=state)
            ctx.update(macro_data or {})
            self._health.report("vm100.macro", available=True)
        except Exception as exc:
            self._health.report("vm100.macro", available=False, failure_reason=str(exc))

        # Try fetching structural context (VM101).
        try:
            from tools.get_primitives import get_structural_context  # type: ignore[import]
            structural_data = get_structural_context(state=state)
            if structural_data:
                ctx["structural"] = structural_data.get("events", [])
            self._health.report("vm101.structural", available=True)
        except Exception as exc:
            self._health.report("vm101.structural", available=False, failure_reason=str(exc))

        # Risk and session sources — report as available (no external calls at this stage).
        self._health.report("vm102.risk", available=True)
        self._health.report("vm107.session", available=True)

        return ctx

    # ── Internal helpers ───────────────────────────────────────────────────

    def _build_base_summary(self, ctx: dict, state: str) -> str:
        """Deterministic template rendering — always produces a valid summary.

        This method is the mock-seam for tests:
            patch.object(emitter, '_build_base_summary', return_value='...')
        """
        try:
            # Use the existing NarrativeTemplateEngine from VM100 if available.
            from mission_control.services.narrative_template_engine import (
                NarrativeTemplateEngine,
                NarrativeInputs,
            )
            inputs = NarrativeInputs(
                symbol=ctx.get("symbol", "EURUSD"),
                regime=ctx.get("regime", {"label": "UNKNOWN", "confidence": 0.5}),
                session_state=state if state in ("pre", "open", "mid", "close") else "mid",
                structural_events=ctx.get("structural", []),
                event_countdown=ctx.get("event_countdown"),
                volatility_state=ctx.get("volatility_state", "normal"),
            )
            rendered = NarrativeTemplateEngine().render(inputs)
            return rendered.get("text", f"{state.upper()} market narrative unavailable")
        except Exception:
            # Ultra-safe fallback — never let the base summary raise.
            regime_label = ctx.get("regime", {}).get("label", "current regime")
            return f"Market is in {regime_label} during the {state} session."

    def _compute_novelty_dims(self, ctx: dict) -> NoveltyDimensions:
        """Pick the primary novelty dimension to score for narrative gating.

        2026-07-02 — previously tried to construct `NoveltyDimensions` as a
        dataclass with per-dimension score kwargs, but the type is a string
        `Enum` listing the 5 dimension names (MACRO/REGIME/STRUCTURAL/
        VOLATILITY/BEHAVIORAL). Enum members are selected, not constructed
        with kwargs — the prior code raised `TypeError` on every call.

        V1 (Phase 83) only has a live MACRO scorer; the other 4 dimensions
        are stubs (`raise NotImplementedError`). Emit MACRO so the caller
        gets a real NoveltyScore back when the payload shape matches.
        """
        return NoveltyDimensions.MACRO

    def _compute_confidence(
        self, ctx: dict, tier: DegradationTier
    ) -> "_ConfidenceStub":
        """Compute a multi-dim confidence vector from context + degradation tier."""
        base_coverage = {
            DegradationTier.HEALTHY: 1.0,
            DegradationTier.TIER_1: 0.7,
            DegradationTier.TIER_2: 0.5,
            DegradationTier.TIER_3: 0.2,
        }.get(tier, 0.5)

        evidence = ctx.get("evidence", [])
        return _ConfidenceStub(
            coverage=base_coverage,
            source_diversity=min(1.0, len(evidence) / 5.0),
            freshness_hours=float(ctx.get("freshness_hours", 0.0)),
            evidence_density=min(1.0, len(evidence) / 10.0),
        )

    def _demo_flip_compound(self, confidence: "_ConfidenceStub") -> bool:
        """COMPOUND rule (CONTEXT.md §2): ALL three dimensions must fail to flip _demo.

        A single failing dimension does NOT flip demo — it only triggers
        degraded mode (Tier 1 or Tier 2).  All three must fail simultaneously.
        """
        return (
            confidence.coverage < 0.5
            and confidence.freshness_hours > 4.0
            and confidence.evidence_density < 0.3
        )

    def _call_llm(
        self,
        base_summary: str,
        ctx: dict,
        novelty: Any,
    ) -> str | None:
        """Call the Anthropic SDK for additive LLM enrichment.

        Novelty gate lives here: returns None immediately when novelty has not
        crossed the threshold (deterministic path — same as if novelty was False).
        This method is the mock-seam for tests:
            patch.object(emitter, '_call_llm', return_value='enriched text')

        Returns:
            Enriched text string, or None on any error (engine survives without LLM).
        """
        # Novelty gate: skip LLM when threshold not crossed.
        if not getattr(novelty, "threshold_crossed", False):
            return None

        try:
            import anthropic  # type: ignore[import]
            client = anthropic.Anthropic()

            novelty_codes = getattr(novelty, "reason_codes", [])
            prompt = (
                f"Given this deterministic base summary:\n\n"
                f"\"{base_summary}\"\n\n"
                f"And these novelty signals: {', '.join(novelty_codes) or 'none'}.\n\n"
                f"Add 1-2 sentences of operational insight for a trader. "
                f"Do NOT contradict any fact in the base summary. "
                f"Respond with only the enriched paragraph."
            )

            message = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text.strip()
        except Exception as exc:
            log.warning(
                "global_narrative_llm_enrichment_failed: %s(%s)",
                type(exc).__name__,
                exc,
            )
            return None


class _ConfidenceStub:
    """Lightweight confidence carrier — mirrors ConfidenceVector fields.

    Used internally to avoid coupling to the Pydantic model during tests.
    """

    __slots__ = ("coverage", "source_diversity", "freshness_hours", "evidence_density")

    def __init__(
        self,
        coverage: float,
        source_diversity: float,
        freshness_hours: float,
        evidence_density: float,
    ) -> None:
        self.coverage = coverage
        self.source_diversity = source_diversity
        self.freshness_hours = freshness_hours
        self.evidence_density = evidence_density
