"""Phase 87 Wave 2 — macro_transmission_analyst event-driven agent.

Lifecycle (per Phase 36 AgentRunner pattern, mirrors Phase 85's
macro_release_analyst structure):

  1. Wake on Phase 83 econ_release event (via Phase 85's listener service +
     Brain task type `transmission_analysis`).
  2. Walk the VM105 Neo4j macro graph via vm105.neo4j_macro_graph_walker
     (HTTPX → VM100 internal endpoint per Phase 39 typed-API lock).
  3. Query B6 episodic memory (Wave-2 stub returns empty; Wave-4 Plan 87-07
     wires the real EpisodicMemoryService without changing this call site).
  4. Narrate hop-by-hop via TransmissionNarrationSkill (Phase 43 router
     + hard-assertion regex retry-once-degrade gate).
  5. Persist Phase 70.5 envelope + Brain B1 reasoning artifact +
     macro_transmission_analysis row.
  6. Publish ``macro.transmission.<indicator_id>.updated`` WS topic
     (thin-invalidation contract; no payload).
  7. Terminate (single-emit-terminate; no background loop).

REQ-87-2: End-to-end within 60s of the release event.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from tools.neo4j_macro_graph_walker import Hop, Neo4jMacroGraphWalker

from .skill_transmission_narration import (
    NarrationFailedAfterRetry,
    TransmissionNarrationSkill,
)

logger = logging.getLogger(__name__)


@dataclass
class TransmissionAnalysisResult:
    """Outcome of a single ``MacroTransmissionAnalyst.run()`` invocation.

    Attributes:
        analysis_id:    PK of the macro_transmission_analysis row.
        event_id:       UUID of the source economic_event (Phase 85).
        indicator_id:   FRED-style id (e.g. "CPIAUCSL").
        chain:          Ordered hops from the walker (AFFECTS first, DRIVES last).
        narrative_text: LLM narrative (or degraded Markdown fallback).
        envelope_id:    Phase 70.5 envelope row id.
        b1_artifact_id: Brain B1 reasoning artifact id.
        degraded:       True if the LLM narrative failed regex gate twice.
    """

    analysis_id: uuid.UUID
    event_id: uuid.UUID
    indicator_id: str
    chain: list[Hop]
    narrative_text: str
    envelope_id: uuid.UUID
    b1_artifact_id: uuid.UUID
    degraded: bool = False


class MacroTransmissionAnalyst:
    """Event-driven graph-walking transmission analyst.

    Collaborators are injected via the constructor to keep the agent
    testable in isolation (see test_transmission_analyst_walk.py). The
    Phase 36 AgentRunner wires them up at task-dispatch time.
    """

    agent_id = "vm107.macro_transmission_analyst"

    def __init__(
        self,
        walker: Neo4jMacroGraphWalker,
        episodic_memory_service: Any,  # B6 stub in Wave 2; real client in Wave 4
        narration_skill: TransmissionNarrationSkill,
        envelope_repo: Any,            # Phase 70.5 envelope writer
        b1_repo: Any,                  # Brain B1 reasoning artifact writer
        persist_repo: Any,             # macro_transmission_analysis DAL
        ws_publisher: Any,             # macro.transmission.<id>.updated publisher
    ) -> None:
        self._walker = walker
        self._memory = episodic_memory_service
        self._narration = narration_skill
        self._envelope_repo = envelope_repo
        self._b1_repo = b1_repo
        self._persist = persist_repo
        self._ws = ws_publisher

    def run(self, release_event: dict) -> TransmissionAnalysisResult:
        """Execute one full transmission-analysis cycle.

        Args:
            release_event: Phase 83 econ_release payload (see fixtures/
              cpi_release_synthetic.json for the canonical shape). MUST
              contain ``indicator_id`` and ``release_id``.

        Returns:
            TransmissionAnalysisResult with the chain, narrative,
            envelope/B1 ids and degraded flag.
        """
        indicator_id = release_event["indicator_id"]
        event_id = self._extract_event_id(release_event)

        # 1. Walk the graph
        chain = self._walker.walk(indicator_id, max_hops=5)
        if not chain:
            logger.warning({
                "event": "transmission_chain_empty",
                "indicator_id": indicator_id,
                "note": "Wave-1 seed missing for this indicator or graph empty",
            })

        # 2. B6 episodic memory (Wave-2 stub returns empty)
        memory_response = self._memory.query({
            "query_text": (
                f"{indicator_id} release surprise "
                f"{release_event.get('surprise', '?')}"
            ),
            "scope": {"collection": "macro_episode"},
            "top_k": 5,
        })
        episodes = memory_response.get("memories_retrieved", [])

        # 3. Narrate with hard-assertion retry-once-degrade gate
        try:
            narrative_text, degraded = self._narration.narrate(
                indicator_id=indicator_id,
                release=release_event,
                chain=chain,
                episodes=episodes,
            )
        except NarrationFailedAfterRetry:
            logger.warning({
                "event": "transmission_narration_degraded",
                "indicator_id": indicator_id,
                "reason": "regex_gate_failed_twice",
            })
            narrative_text = self._narration.degraded_fallback(chain)
            degraded = True

        # Empty-chain is also a degraded outcome — the narrative may pass
        # the regex (LLM hallucinates over zero edges) but the envelope is
        # not trustworthy. Mark degraded explicitly.
        if not chain:
            degraded = True
            narrative_text = self._narration.degraded_fallback(chain)

        # 4. Persist envelope + B1
        chain_json = [self._hop_to_dict(h) for h in chain]
        envelope_id = self._envelope_repo.persist(
            analysis_kind="macro_transmission_analysis",
            payload={
                "indicator_id": indicator_id,
                "chain": chain_json,
                "narrative": narrative_text,
                "degraded": degraded,
            },
        )
        b1_id = self._b1_repo.persist(
            profile=self.agent_id,
            trace={
                "event": release_event,
                "chain_len": len(chain),
                "narrative_len": len(narrative_text),
                "degraded": degraded,
            },
        )

        # 5. Persist macro_transmission_analysis row
        analysis_id = self._persist.create(
            event_id=event_id,
            indicator_id=indicator_id,
            chain_json=chain_json,
            narrative_text=narrative_text,
            envelope_id=envelope_id,
            b1_artifact_id=b1_id,
            degraded=degraded,
            generated_at=datetime.now(tz=timezone.utc),
        )

        # 6. Thin-invalidation WS topic publish (no payload by contract)
        self._ws.publish(
            f"macro.transmission.{indicator_id}.updated", payload=None
        )

        return TransmissionAnalysisResult(
            analysis_id=analysis_id,
            event_id=event_id,
            indicator_id=indicator_id,
            chain=chain,
            narrative_text=narrative_text,
            envelope_id=envelope_id,
            b1_artifact_id=b1_id,
            degraded=degraded,
        )

    # ---- helpers ------------------------------------------------------

    @staticmethod
    def _extract_event_id(release_event: dict) -> uuid.UUID:
        """Extract or derive a UUID event_id from a Phase 83 payload.

        Phase 83 contract uses ``release_id`` (uuid string). Some
        producers may include a separate ``event_id`` field; prefer it
        when present (forward-compat with Phase 85 listener).
        """
        candidate = release_event.get("event_id") or release_event.get("release_id")
        if candidate is None:
            # Defensive: synthesise one if neither is present
            return uuid.uuid4()
        if isinstance(candidate, uuid.UUID):
            return candidate
        try:
            return uuid.UUID(str(candidate))
        except (ValueError, TypeError):
            # Non-UUID strings (e.g. "CPIAUCSL:2026-06-15") get hashed
            return uuid.uuid5(uuid.NAMESPACE_URL, str(candidate))

    @staticmethod
    def _hop_to_dict(hop: Hop) -> dict:
        return {
            "source": hop.source,
            "target": hop.target,
            "relationship_type": hop.relationship_type,
            "strength": hop.strength,
            "confidence": hop.confidence,
            "sample_size": hop.sample_size,
            "evidence_period": hop.evidence_period,
            "hop_order": hop.hop_order,
        }
