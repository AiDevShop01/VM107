"""Stage 3: PatternContextAssembler — Phase 67 Plan 07 (REQ-67-4).

Pulls cross-trade patterns SCOPED TO THE SESSION (Pitfall 3 fix).

VM100 chokepoint method:
    vm100_client.get_session_patterns(account_id, session_date)
    → list[dict] with keys:
        pattern_id, pattern_name, supporting_trade_ids, severity

CRITICAL: This stage MUST call ``get_session_patterns`` (Pitfall 3 fix
shipped in same plan) and NOT the legacy 30-day ``get_patterns`` method.
A 30-day window inflates the perceived pattern severity by including
historical noise, contaminating the SAME-SESSION reflection prompt.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from emitters.reflection.assemblers.behavioral_interpretation import (
    BehavioralInterpretation,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PatternContext:
    """One session-scoped cross-trade pattern (Phase 54 :EXHIBITS edge cluster)."""

    pattern_id: str
    pattern_name: str
    supporting_trade_ids: tuple[str, ...] = field(default_factory=tuple)
    severity: float = 0.0


class PatternContextAssembler:
    """Stage 3: Session-scoped cross-trade patterns."""

    def __init__(self, vm100_client: Any | None = None) -> None:
        self._vm100 = vm100_client
        self.missing_sources: set[str] = set()

    def assemble(
        self,
        account_id: int,
        session_date: date,
        interpretations: list[BehavioralInterpretation],
    ) -> list[PatternContext]:
        """Return list[PatternContext] for the session window.

        Pitfall 3 fix: invokes ``get_session_patterns`` (not the 30-day
        ``get_patterns``). The new method was added to
        ``CrossTradePatternsService`` in the same plan.
        """
        if self._vm100 is None:
            return []

        try:
            raw_rows = self._vm100.get_session_patterns(
                account_id, session_date
            ) or []
        except Exception as exc:
            log.warning(
                "session_patterns_unavailable: %s(%s)",
                type(exc).__name__,
                exc,
            )
            self.missing_sources.add("cross_trade_patterns")
            return []

        out: list[PatternContext] = []
        for row in raw_rows:
            try:
                out.append(
                    PatternContext(
                        pattern_id=str(row.get("pattern_id") or row.get("pattern_name")),
                        pattern_name=str(row["pattern_name"]),
                        supporting_trade_ids=tuple(
                            str(t) for t in (row.get("supporting_trade_ids") or ())
                        ),
                        severity=float(row.get("severity") or row.get("frequency") or 0.0),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                log.warning(
                    "pattern_context_row_skipped: %s(%s) row=%r",
                    type(exc).__name__,
                    exc,
                    row,
                )
        return out
