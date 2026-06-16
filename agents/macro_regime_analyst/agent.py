"""Phase 87 Plan 06 (Wave 3) — macro_regime_analyst event-driven agent.

Lifecycle (per Phase 36 AgentRunner pattern, mirrors Plan 87-04's
macro_transmission_analyst structure):

  1. Wake on Phase 83 econ_release event (via Phase 85's listener service +
     Brain task type ``regime_assessment``).
  2. Extract anchor indicator directions (CPI / UNRATE / GDP).
  3. Read the most-recent persisted regime (cold start → ``expansion``).
  4. Classify via the deterministic LOCK-10 27-entry table.
  5. Compute Wave-3 deterministic transition_probability (0.0 / 1.0).
  6. Query BeliefStore (Wave-3 STUB — flat 0.5; Wave-5 Plan 87-09 swaps
     in real B9 without changing this call site).
  7. Retrieve top-3 historical analogues via Phase 86 ``/event-study``.
  8. Narrate via RegimeNarrationSkill (Phase 43 router + hard-assertion
     regex retry-once-degrade gate). On gate failure → degraded fallback.
  9. Persist Phase 70.5 envelope + Brain B1 reasoning artifact +
     ``macro_regime_classification`` row.
 10. Publish ``macro.regime.<indicator_id>.updated`` WS topic
     (thin-invalidation contract; no payload).
 11. Terminate (single-emit-terminate; no background loop).

REQ-87-3: End-to-end within 60s of the release event; envelope names
one of the 7 LOCK-2 regimes with ≥1 historical analogue citation and
≥3 anchor indicator citations in supporting_evidence.

Plan 87-10 (Wave 5b) stub-swap notice
-------------------------------------
The ``belief_store_client`` constructor argument receives the REAL
``core.belief.belief_store.BeliefStore`` (Plan 87-09) in production /
deploy wiring. No code change is required at the agent call site —
``self._beliefs.query(subject_type=..., subject_id=...)`` returns the
same shape (``{"probability": float, "confidence": float, ...}``) from
both the Wave-3 ``belief_store_stub`` fixture and the Wave-5 real
client. DI swap happens at construction time only.

The Wave-3 unit tests continue to use the ``belief_store_stub`` fixture
in ``tests/phase87/conftest.py`` (flat probability=0.5, confidence=0.5,
``propose()`` raises AttributeError so Wave-3 tests cannot accidentally
write beliefs). Production wires ``BeliefStore()`` from
``core.belief.belief_store`` — env-driven fail-fast on
``BELIEF_STORE_POSTGRES_URL`` + ``BELIEF_STORE_MONGO_URL``.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .historical_analogue_client import EventStudyAnalogueClient, HistoricalAnalogue
from .skill_regime_classifier import (
    Regime,
    classify_regime,
    transition_probability_v1,
)
from .skill_regime_narration import (
    NarrationFailedAfterRetry,
    RegimeNarrationSkill,
)

logger = logging.getLogger(__name__)


# Cold-start default — used only when persist_repo.last_regime() returns
# None (no prior macro_regime_classification rows exist yet). LOCK-2
# treats expansion as the neutral baseline regime.
_COLD_START_DEFAULT_REGIME: Regime = "expansion"


@dataclass
class RegimeClassificationResult:
    """Outcome of a single ``MacroRegimeAnalyst.run()`` invocation.

    Attributes:
        classification_id:     PK of the macro_regime_classification row.
        event_id:              UUID of the source economic_event.
        current_regime:        Classifier output (one of 7 LOCK-2 regimes).
        prior_regime:          Most-recent persisted regime (or cold-start
                               default 'expansion').
        transition_probability: 0.0 (no flip / carry_prior) or 1.0 (flip).
                               Wave 5 Plan 87-09 swaps for Bayesian posterior.
        confidence:            BeliefStore confidence (0.5 stub in Wave 3).
        narrative_text:        LLM narrative (or degraded fallback).
        supporting_evidence:   List of citation dicts (analogue + anchor).
        envelope_id:           Phase 70.5 envelope row id.
        b1_artifact_id:        Brain B1 reasoning artifact id.
        degraded:              True if narrative fell back OR analogues empty.
    """

    classification_id: uuid.UUID
    event_id: uuid.UUID
    indicator_id: str
    current_regime: str
    prior_regime: str
    transition_probability: float
    confidence: float
    narrative_text: str
    supporting_evidence: list[dict]
    envelope_id: uuid.UUID
    b1_artifact_id: uuid.UUID
    degraded: bool = False


class MacroRegimeAnalyst:
    """Event-driven 7-regime classifier agent.

    Collaborators are injected via the constructor (Phase 36 AgentRunner
    pattern) to keep the agent testable in isolation. The Phase 36
    runtime wires them at task-dispatch time.
    """

    agent_id = "vm107.macro_regime_analyst"

    def __init__(
        self,
        *,
        anchor_direction_provider: Any,   # extracts (cpi_dir, unrate_dir, gdp_dir)
        analogue_client: EventStudyAnalogueClient,
        belief_store_client: Any,         # Wave-3 stub; Wave-5 real B9 (Plan 87-10 swap)
        narration_skill: RegimeNarrationSkill,
        envelope_repo: Any,               # Phase 70.5 envelope writer
        b1_repo: Any,                     # Brain B1 reasoning artifact writer
        persist_repo: Any,                # macro_regime_classification DAL
        ws_publisher: Any,                # macro.regime.<id>.updated publisher
        cold_start_default_regime: Regime = _COLD_START_DEFAULT_REGIME,
    ) -> None:
        self._directions = anchor_direction_provider
        self._analogues_client = analogue_client
        self._beliefs = belief_store_client
        self._narration = narration_skill
        self._envelope_repo = envelope_repo
        self._b1_repo = b1_repo
        self._persist = persist_repo
        self._ws = ws_publisher
        self._cold_start: Regime = cold_start_default_regime

    def run(self, release_event: dict) -> RegimeClassificationResult:
        """Execute one full regime-classification cycle.

        Args:
            release_event: Phase 83 econ_release payload. MUST contain
              ``indicator_id`` and ``release_id``.

        Returns:
            RegimeClassificationResult with the regime, transition
            probability, supporting evidence, envelope/B1 ids, and
            degraded flag.
        """
        indicator_id = release_event["indicator_id"]
        event_id = self._extract_event_id(release_event)

        # 1. Anchor directions (CPI / UNRATE / GDP)
        cpi_dir, unrate_dir, gdp_dir = self._directions.directions_at(release_event)

        # 2. Prior regime (cold start → expansion)
        prior_regime: Regime = self._read_prior_regime()

        # 3. Classify (LOCK-10 deterministic 27-entry table)
        current_regime, flipped = classify_regime(
            cpi_dir=cpi_dir,
            unrate_dir=unrate_dir,
            gdp_dir=gdp_dir,
            prior_regime=prior_regime,
        )
        decision_is_carry_prior = (current_regime == prior_regime) and not flipped
        transition_prob = transition_probability_v1(
            flipped=flipped,
            decision_is_carry_prior=decision_is_carry_prior,
        )

        # 4. BeliefStore stub call (Wave 3) — Plan 87-09 swaps real B9.
        # The agent profile YAML lists belief_store.query in allowed_tools;
        # the call site does NOT change in Wave 5.
        belief = self._beliefs.query(
            subject_type="regime", subject_id=current_regime,
        )
        confidence = float(belief.get("confidence", 0.5))

        # 5. Historical analogues (Phase 86 event-study; degrades to []).
        try:
            surprise = float(release_event.get("surprise", 0.0))
        except (TypeError, ValueError):
            surprise = 0.0
        analogues = self._analogues_client.find_analogues(
            indicator_id=indicator_id,
            surprise=surprise,
        )

        # 6. Narrate with retry-once-degrade gate.
        try:
            narrative_text, degraded = self._narration.narrate(
                indicator_id=indicator_id,
                release=release_event,
                current_regime=current_regime,
                prior_regime=prior_regime,
                transition_probability=transition_prob,
                analogues=analogues,
            )
        except NarrationFailedAfterRetry:
            logger.warning(
                {
                    "event": "regime_narration_degraded",
                    "indicator_id": indicator_id,
                    "reason": "regex_gate_failed_twice",
                }
            )
            narrative_text = self._narration.degraded_fallback(
                current_regime=current_regime,
                prior_regime=prior_regime,
                transition_probability=transition_prob,
                analogues=analogues,
            )
            degraded = True

        # If analogue retrieval degraded (empty list), mark the envelope
        # degraded so downstream consumers know the analogue layer was
        # missing — even when the LLM happened to satisfy the regex gate.
        if not analogues:
            degraded = True

        # 7. Build supporting_evidence (analogue citations + 3 anchors).
        supporting_evidence = self._build_supporting_evidence(
            analogues=analogues,
            cpi_dir=cpi_dir,
            unrate_dir=unrate_dir,
            gdp_dir=gdp_dir,
        )

        # 8. Persist envelope + B1.
        envelope_id = self._envelope_repo.persist(
            analysis_kind="macro_regime_classification",
            payload={
                "current_regime": current_regime,
                "prior_regime": prior_regime,
                "transition_probability": transition_prob,
                "confidence": confidence,
                "supporting_evidence": supporting_evidence,
                "narrative": narrative_text,
                "degraded": degraded,
            },
        )
        b1_id = self._b1_repo.persist(
            profile=self.agent_id,
            trace={
                "event": release_event,
                "directions": [cpi_dir, unrate_dir, gdp_dir],
                "current_regime": current_regime,
                "prior_regime": prior_regime,
                "flipped": flipped,
                "decision_is_carry_prior": decision_is_carry_prior,
                "transition_probability": transition_prob,
                "confidence": confidence,
                "analogue_count": len(analogues),
                "degraded": degraded,
            },
        )

        # 9. Persist macro_regime_classification row.
        classification_id = self._persist.create(
            event_id=event_id,
            indicator_id=indicator_id,
            current_regime=current_regime,
            prior_regime=prior_regime,
            transition_probability=transition_prob,
            confidence=confidence,
            supporting_evidence=supporting_evidence,
            envelope_id=envelope_id,
            b1_artifact_id=b1_id,
            degraded=degraded,
            generated_at=datetime.now(tz=timezone.utc),
        )

        # 10. Thin-invalidation WS topic publish (no payload by contract).
        self._ws.publish(
            f"macro.regime.{indicator_id}.updated", payload=None,
        )

        return RegimeClassificationResult(
            classification_id=classification_id,
            event_id=event_id,
            indicator_id=indicator_id,
            current_regime=current_regime,
            prior_regime=prior_regime,
            transition_probability=transition_prob,
            confidence=confidence,
            narrative_text=narrative_text,
            supporting_evidence=supporting_evidence,
            envelope_id=envelope_id,
            b1_artifact_id=b1_id,
            degraded=degraded,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_prior_regime(self) -> Regime:
        """Read the most-recent persisted regime; fall back to cold-start.

        ``persist_repo.last_regime()`` returns ``None`` or the prior regime
        as a string. Cold-start default is 'expansion' (LOCK-2 neutral).
        """
        try:
            prior = self._persist.last_regime()
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                {
                    "event": "regime_prior_read_failed",
                    "error": str(exc),
                    "fallback": self._cold_start,
                }
            )
            return self._cold_start
        if not prior:
            return self._cold_start
        return prior  # type: ignore[return-value]

    @staticmethod
    def _build_supporting_evidence(
        *,
        analogues: list[HistoricalAnalogue],
        cpi_dir: int,
        unrate_dir: int,
        gdp_dir: int,
    ) -> list[dict]:
        """Construct the supporting_evidence list (analogues + 3 anchors).

        Schema is consumed by the Phase 71 evidence drawer + Plan 87-11
        VM100 backend. Plan 87-12 frontend filters on ``kind``.

        REQ-87-3 acceptance: at least 1 analogue + 3 anchor citations.
        """
        citations: list[dict] = []
        for a in analogues:
            citations.append(
                {
                    "kind": "analogue",
                    "release_id": a.release_id,
                    "release_date": a.release_date,
                    "indicator_id": a.indicator_id,
                    "surprise": a.surprise,
                    "sample_size": a.sample_size,
                    "evidence_period": a.evidence_period,
                }
            )
        citations.extend(
            [
                {"kind": "anchor", "indicator_id": "CPIAUCSL", "direction": int(cpi_dir)},
                {"kind": "anchor", "indicator_id": "UNRATE", "direction": int(unrate_dir)},
                {"kind": "anchor", "indicator_id": "GDP", "direction": int(gdp_dir)},
            ]
        )
        return citations

    @staticmethod
    def _extract_event_id(release_event: dict) -> uuid.UUID:
        """Extract or derive a UUID event_id from a Phase 83 payload.

        Mirrors Plan 87-04's MacroTransmissionAnalyst._extract_event_id —
        same input contract, same fallback semantics.
        """
        candidate = release_event.get("event_id") or release_event.get("release_id")
        if candidate is None:
            return uuid.uuid4()
        if isinstance(candidate, uuid.UUID):
            return candidate
        try:
            return uuid.UUID(str(candidate))
        except (ValueError, TypeError):
            return uuid.uuid5(uuid.NAMESPACE_URL, str(candidate))
