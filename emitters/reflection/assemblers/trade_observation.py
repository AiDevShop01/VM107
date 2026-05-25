"""Stage 1: TradeObservationAssembler — Phase 67 Plan 07 (REQ-67-4).

Pulls observable trade evidence from VM100's Phase 47.4 trade_outcomes
service. Pure concrete behaviors only — no interpretation, no patterns.

VM100 client method:
    vm100_client.get_trade_outcomes_for_session(account_id, session_date)
    → list[dict] with keys:
        trade_id, symbol, entry_at, exit_at, pnl_r, regime, behavioral_tags

The assembler degrades gracefully — VM100 down ⇒ empty observation list
+ ``missing_sources.add("vm100")``. The synthesizer treats observations
as REQUIRED evidence (no observations ⇒ no eligible prompts), so a
DEGRADED upstream surfaces as zero prompts rather than spurious content.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TradeObservation:
    """One observable trade — Phase 47.4 trade_outcomes row → frozen dataclass.

    behavioral_tags is a tuple (frozen-compatible) of strings such as
    ``"premature_entry"`` / ``"size_violation"`` / etc; tags themselves
    are NOT discipline flags (those come from Stage 2's mentor narrative
    layer) — they are surface signals attached to the trade outcome row.
    """

    trade_id: str
    symbol: str
    entry_at: datetime
    exit_at: datetime
    pnl_r: float
    regime: str
    behavioral_tags: tuple[str, ...] = field(default_factory=tuple)


def _parse_dt(value: Any) -> datetime:
    """Best-effort ISO-8601 parse — accepts datetime or string."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # Normalize trailing Z → +00:00 for fromisoformat
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Cannot parse datetime from {type(value).__name__}: {value!r}")


class TradeObservationAssembler:
    """Stage 1: Concrete trade evidence from VM100.

    Usage::

        assembler = TradeObservationAssembler(vm100_client=client)
        obs = assembler.assemble(account_id=42, session_date=date(2026, 5, 25))
        # obs is list[TradeObservation]
        if assembler.missing_sources:
            # degraded upstream — synthesizer should account for this
            ...
    """

    def __init__(self, vm100_client: Any | None = None) -> None:
        self._vm100 = vm100_client
        self.missing_sources: set[str] = set()

    def assemble(
        self, account_id: int, session_date: date
    ) -> list[TradeObservation]:
        """Return list[TradeObservation] for the session.

        Empty list when no trades or when VM100 unavailable.
        """
        if self._vm100 is None:
            # No client injected → return empty (test / offline path).
            return []

        try:
            raw_rows = self._vm100.get_trade_outcomes_for_session(
                account_id, session_date
            ) or []
        except Exception as exc:
            log.warning(
                "trade_observation_assembler_vm100_unavailable: %s(%s)",
                type(exc).__name__,
                exc,
            )
            self.missing_sources.add("vm100")
            return []

        out: list[TradeObservation] = []
        for row in raw_rows:
            try:
                out.append(
                    TradeObservation(
                        trade_id=str(row["trade_id"]),
                        symbol=str(row["symbol"]),
                        entry_at=_parse_dt(row["entry_at"]),
                        exit_at=_parse_dt(row["exit_at"]),
                        pnl_r=float(row["pnl_r"]),
                        regime=str(row.get("regime", "UNKNOWN")),
                        behavioral_tags=tuple(row.get("behavioral_tags") or ()),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                # One bad row should not blow up the whole assemble pass;
                # log and continue. The pipeline reports degraded shape via
                # missing_sources on TOTAL failure, not per-row.
                log.warning(
                    "trade_observation_row_skipped: %s(%s) row=%r",
                    type(exc).__name__,
                    exc,
                    row,
                )
        return out
