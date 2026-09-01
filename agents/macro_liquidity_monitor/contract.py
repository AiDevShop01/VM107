"""Phase 173 Plan 04 (D-08) — LiquidityScore typed output contract.

Promotes ``macro_liquidity_monitor`` from a bare ``float | None`` return to a
typed Pydantic boundary so consumers receive provenance + an explicit
``degraded`` flag instead of an ambiguous nullable float.

House honest-null semantics are PRESERVED at the type level: ``score`` and
``tier`` are nullable and ``degraded`` makes the null explicit — the wrapper
(``agent.score_liquidity``) NEVER coerces a ``None`` score to a neutral 0.

Mirrors the Pydantic v2 conventions of ``core/counterfactual/output_contract.py``
(``from __future__ import annotations``, provenance fields, honest-null via
nullable fields + an explicit flag). Does NOT touch the deterministic scorer,
the thresholds, or the ``emit_alert_candidate`` fan-out.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LiquidityScore(BaseModel):
    """Typed output boundary for the deterministic global-liquidity scorer.

    Attributes:
        score: 0..100 global_liquidity_score, or ``None`` when the substrate is
            empty / no recognised signal contributed (honest-null — never 0).
        tier: Threshold tier derived from ``score`` — ``"blocking"`` when
            ``score < _BLOCKING_THRESHOLD``, ``"warning"`` when
            ``score < _WARNING_THRESHOLD``, else ``"normal"``. ``None`` mirrors a
            ``None`` score (no tier asserted on degraded substrate).
        substrate_keys_present: Provenance — the substrate keys that actually
            contributed to the score (empty when degraded).
        computed_at: When the wrapper produced this contract (UTC).
        producer_agent_id: Stable producer id (``"vm107.macro_liquidity_monitor"``).
        degraded: ``True`` exactly when ``score is None`` — the explicit
            honest-degradation flag consumers gate on.
    """

    score: float | None
    tier: Literal["normal", "warning", "blocking"] | None = None
    substrate_keys_present: list[str] = Field(default_factory=list)
    computed_at: datetime
    producer_agent_id: str = "vm107.macro_liquidity_monitor"
    degraded: bool


__all__ = ["LiquidityScore"]
