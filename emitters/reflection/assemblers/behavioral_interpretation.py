"""Stage 2: BehavioralInterpretationAssembler — Phase 67 Plan 07 (REQ-67-4).

Layers Phase 60 mentor_pipeline_writer output onto each observation:
discipline_flags + mentor_narrative_summary + confidence.

VM100 chokepoint method:
    vm100_client.get_mentor_narrative_for_trade(account_id, trade_id)
    → dict with keys: discipline_flags / narrative_summary / confidence

Per Phase 47.6 + load-bearing constraint #10: VM107 emitters call VM100
clients (chokepoint pattern) even when the underlying service lives on
the SAME VM (VM107). The exception is when the upstream IS a VM107
in-process module — Plan 07's emitter, however, treats Phase 60 mentor
output as a typed CONTRACT consumed via the VM100-facing client wrapper
so the cross-plan dependency surface stays uniform.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from emitters.reflection.assemblers.trade_observation import TradeObservation

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BehavioralInterpretation:
    """One trade + Phase 60 mentor narrative interpretation."""

    trade_id: str
    discipline_flags: tuple[str, ...] = field(default_factory=tuple)
    mentor_narrative_summary: str = ""
    confidence: float = 0.0


class BehavioralInterpretationAssembler:
    """Stage 2: Layer Phase 60 mentor narrative on each observation."""

    def __init__(self, vm100_client: Any | None = None) -> None:
        self._vm100 = vm100_client
        self.missing_sources: set[str] = set()

    def assemble(
        self,
        account_id: int,
        session_date: date,
        observations: list[TradeObservation],
    ) -> list[BehavioralInterpretation]:
        """Return list[BehavioralInterpretation] one-per-observation.

        On per-trade narrative failure → degraded interpretation kept
        (so the trade is still present in the pipeline) AND
        ``missing_sources.add("mentor_narrative")``.
        """
        if not observations:
            return []

        out: list[BehavioralInterpretation] = []
        any_failure = False

        for obs in observations:
            if self._vm100 is None:
                # Test / offline path → empty interpretation
                out.append(
                    BehavioralInterpretation(
                        trade_id=obs.trade_id,
                        discipline_flags=tuple(obs.behavioral_tags),
                        mentor_narrative_summary="",
                        confidence=0.0,
                    )
                )
                continue

            try:
                narrative = self._vm100.get_mentor_narrative_for_trade(
                    account_id, obs.trade_id
                ) or {}
                flags = tuple(narrative.get("discipline_flags") or ())
                summary = str(narrative.get("narrative_summary") or "")
                confidence = float(narrative.get("confidence") or 0.0)
                out.append(
                    BehavioralInterpretation(
                        trade_id=obs.trade_id,
                        discipline_flags=flags,
                        mentor_narrative_summary=summary,
                        confidence=confidence,
                    )
                )
            except Exception as exc:
                log.warning(
                    "mentor_narrative_unavailable for trade=%s: %s(%s)",
                    obs.trade_id,
                    type(exc).__name__,
                    exc,
                )
                any_failure = True
                # Degraded interpretation — keep the trade in the pipeline.
                out.append(
                    BehavioralInterpretation(
                        trade_id=obs.trade_id,
                        discipline_flags=(),
                        mentor_narrative_summary="",
                        confidence=0.0,
                    )
                )

        if any_failure:
            self.missing_sources.add("mentor_narrative")

        return out
