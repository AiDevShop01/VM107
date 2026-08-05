"""ReflectionPromptEmitter — Phase 67 Plan 07 (REQ-67-4) facade.

Top-level entry point for the 5-stage progressive enrichment pipeline.
Composes the 4 assemblers + ReflectionPromptSynthesizer behind a single
``get_reflection_prompts(account_id, session_date)`` call.

Architecture:
  * Stage 1: TradeObservationAssembler
  * Stage 2: BehavioralInterpretationAssembler
  * Stage 3: PatternContextAssembler (uses VM100.get_session_patterns — Pitfall 3 fix)
  * Stage 4: LongitudinalContextAssembler (Phase 62 evolution + adaptive)
  * Stage 5: ReflectionPromptSynthesizer (score → diversify → coherence → LLM)

Returns ``ReflectionPromptSetContract`` (Pydantic v2 frozen):
  - selected_prompts (≤4) with base + optional LLM-enriched text
  - rejected_candidates persisted for Phase 62 tuning gold
  - reflection_set_coherence_score
  - dominant_session_theme (optional override)

``persist_and_publish()`` wraps SnapshotInvalidationPublisher in
``transaction.atomic()`` (REQ-66-5 lock — snapshot-before-publish
ordering). Publishes on ``mission_control.close.journal_prompts``
(CLOSE state center, NOT a PRE topic — REQ-67-4).

When Plan 13 ships ReflectionPromptSnapshot ORM, the model `.create()`
slots into the existing atomic block without restructure.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from emitters.contracts.reflection_prompt import ReflectionPromptSetContract
from emitters.novelty_engine import NoveltyEngine
from emitters.reflection.assemblers.behavioral_interpretation import (
    BehavioralInterpretationAssembler,
)
from emitters.reflection.assemblers.longitudinal_context import (
    LongitudinalContextAssembler,
)
from emitters.reflection.assemblers.pattern_context import (
    PatternContextAssembler,
)
from emitters.reflection.assemblers.trade_observation import (
    TradeObservationAssembler,
)
from emitters.reflection.synthesizer import ReflectionPromptSynthesizer

log = logging.getLogger(__name__)


# Topic — locked: CLOSE state journal_prompts namespace (not a PRE topic).
RFLP_PUBLISH_TOPIC = "mission_control.close.journal_prompts"


class ReflectionPromptEmitter:
    """5-stage progressive enrichment reflection prompt emitter."""

    def __init__(
        self,
        novelty_engine: NoveltyEngine | None = None,
        vm100_client: Any | None = None,
        synthesizer: ReflectionPromptSynthesizer | None = None,
    ) -> None:
        # SHARED NoveltyEngine — Phase 66 lock; fall back to singleton when
        # caller did not inject (tests inject an isolated engine).
        self._novelty = novelty_engine or NoveltyEngine.get_shared_instance()
        self._vm100 = vm100_client
        self._synthesizer = synthesizer or ReflectionPromptSynthesizer()

    # ── Public API ─────────────────────────────────────────────────────────

    def get_reflection_prompts(
        self, account_id: int, session_date: date
    ) -> ReflectionPromptSetContract:
        """Run the 5-stage pipeline for a session.

        Returns a ReflectionPromptSetContract:
          * selected_prompts (≤4) — base_prompt + optional llm_enriched_prompt
          * rejected_candidates — Phase 62 tuning substrate
          * reflection_set_coherence_score in [0, 1]
          * dominant_session_theme — locked category name OR None
        """
        # Stage 1: TradeObservations
        obs_asm = TradeObservationAssembler(vm100_client=self._vm100)
        observations = obs_asm.assemble(account_id, session_date)

        # Stage 2: BehavioralInterpretations
        bi_asm = BehavioralInterpretationAssembler(vm100_client=self._vm100)
        interpretations = bi_asm.assemble(account_id, session_date, observations)

        # Stage 3: PatternContexts (session-scoped per Pitfall 3 fix)
        pc_asm = PatternContextAssembler(vm100_client=self._vm100)
        patterns = pc_asm.assemble(account_id, session_date, interpretations)

        # Stage 4: LongitudinalContext (Phase 62)
        lc_asm = LongitudinalContextAssembler(vm100_client=self._vm100)
        longitudinal = lc_asm.assemble(account_id, session_date, patterns)

        # Stage 5: Synthesize (score → diversify → coherence → LLM)
        return self._synthesizer.synthesize(
            account_id=account_id,
            observations=observations,
            interpretations=interpretations,
            patterns=patterns,
            longitudinal=longitudinal,
            novelty_engine=self._novelty,
        )

    # ── Snapshot-before-publish hook (REQ-66-5 lock) ───────────────────────

    def persist_and_publish(
        self,
        set_contract: ReflectionPromptSetContract,
        invalidation_reason: str = "reflection_prompts_generated",
    ) -> None:
        """Persist (future snapshot) + publish on CLOSE journal_prompts topic.

        Snapshot-before-publish ordering preserved via ``transaction.atomic()``
        + ``publish_after_commit`` — Redis invalidation fires only AFTER any
        future DB row commits. Plan 13 may add ReflectionPromptSnapshot ORM.

        No-op when Django / publisher unavailable (test / offline mode).
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
                    "reflection_prompt_emitter.persist_and_publish: "
                    "SnapshotInvalidationPublisher not available — skipping publish"
                )
                return

        publisher = SnapshotInvalidationPublisher()
        # VM107 has no Django DB transaction — publish IMMEDIATELY (fire-and-forget).
        publisher.publish_after_commit(
            topic=RFLP_PUBLISH_TOPIC,
            snapshot_id=set_contract.set_id,
            account_id=set_contract.account_id,
            invalidation_reason=invalidation_reason,
        )
