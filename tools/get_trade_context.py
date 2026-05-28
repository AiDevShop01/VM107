"""get_trade_context — fetch curated trade journal data via VM100 API.

Phase 47.2 Tier-2 real tool. Idempotent + stateless (CONTEXT lock).

Phase 58.1 amendment (REQ-58.1-F4):
  - Accepts EITHER ``trade_id`` (Execution UUID or ``api.Trade.id`` int) OR
    ``journal_id`` (``TradeJournal.id`` UUID) — strict exactly-one enforced
    by ``GetTradeContextRequest.exactly_one_id`` validator.
  - Resolves identity via VM100 ``GET /api/journal/internal/resolve-trade-identity``
    BEFORE fetching trade detail — replaces the silent-swallow path
    (``except Exception: trade = {}``) that Phase 47.2 shipped with.
  - Returns the canonical 6-field ``NotAvailableResponse`` envelope on
    unresolved IDs (Phase 47.2 lock: never fake unavailable intelligence).
    Six fields: ``status, planned_phase, tool, would_provide,
    impact_on_decision, unblocks_when``. NO ``reason`` field — the unblock
    reason is encoded into the human-readable ``unblocks_when[0]`` string.

Phase 70.5 Plan 06 amendment (Decision 5 + Pitfall 9):
  - Returns ``GetTradeContextPayload`` (renamed from GetTradeContextResponse)
    with a populated ``provenance: ToolProvenance`` field on the success path.
  - The dispatcher (Plan 03) extracts provenance to build the RICH envelope.
  - RICH citations: trade EvidenceCitation(kind="trade", opaque_id=trade_id)
    + VM100 resolver citation(kind="dataset", opaque_id=resolver_endpoint).
  - RICH assumptions: 2 pilot assumption strings (timezone + fills coverage).
  - Backward compat: ``GetTradeContextResponse = GetTradeContextPayload`` alias.

Returns the canonical journal payload for a single trade — instrument,
direction, strategy_id, entry/SL/TP, notes, timeframe, checklist snapshot,
and (when available) the last formal evaluation summary.

VM100Client has no ``get_trade(trade_id)`` method (Phase 39 client surface
only ships ``get_recent_trades`` and ``create_pre_trade_entry``); we therefore
go through the generic BaseVMClient ``.get(path)`` against
``GET /api/v1/trades/{trade_id}`` after the resolver returns a numeric
``trade_id``.
"""
from __future__ import annotations

from typing import Any

from fingpt_core.clients import RetryProfile, VM100Client
from fingpt_core.contracts.agents.not_available import NotAvailableResponse
from fingpt_core.contracts.agents.trade_context import (
    GetTradeContextPayload,
    GetTradeContextRequest,
    GetTradeContextResponse,  # backward compat — same as GetTradeContextPayload
)
from fingpt_core.contracts.base import BaseContract
from fingpt_core.contracts.errors import ContractValidationError
from fingpt_core.contracts.evidence import EvidenceCitation
from fingpt_core.contracts.failure_modes import FailureMode, FailureModeCode
from fingpt_core.contracts.tool_envelope import ToolProvenance

from tools.vm_contracts.base import ContractTool


# VM100 identity resolver endpoint — single canonical reference for provenance citations.
# Phase 70.5: used as the "dataset" citation opaque_id in RICH provenance.
_RESOLVER_ENDPOINT_CITATION = "vm100/api/journal/internal/resolve-trade-identity"

# Locked list of fields the tool WOULD provide if the input ID resolved.
# Used by the NotAvailableResponse envelope. Matches GetTradeContextPayload
# Optional field set (excluding the echoed trade_id).
_WOULD_PROVIDE = [
    "instrument",
    "direction",
    "strategy_id",
    "entry_price",
    "stop_loss_price",
    "take_profit_price",
    "notes",
    "timeframe",
    "checklist_snapshot_text",
    "last_evaluation",
]


def _not_available(*, unblock_reason: str) -> dict:
    """Construct the canonical 6-field NotAvailableResponse payload.

    Returns the ``.model_dump(mode="python")`` dict so the tool's
    ``_validate_response`` can re-parse it via ``NotAvailableResponse(**data)``.
    The 6 fields lock matches ``fingpt_core.contracts.agents.not_available``
    — adding a ``reason`` field would break the contract (Phase 58.1 RESEARCH
    correction #2).
    """
    return NotAvailableResponse(
        status="not_available",
        planned_phase="58.1",
        tool="get_trade_context",
        would_provide=list(_WOULD_PROVIDE),
        impact_on_decision="MEDIUM",
        unblocks_when=[
            "Caller passes a valid trade_id/journal_id/execution_id "
            f"(reason={unblock_reason})"
        ],
    ).model_dump(mode="python")


class GetTradeContext(ContractTool):
    """LLM-callable: get_trade_context(trade_id=... | journal_id=...)."""

    def _validate_request(self, args: dict) -> BaseContract:
        try:
            return GetTradeContextRequest(**args)
        except Exception as e:  # noqa: BLE001 — contract path
            raise ContractValidationError(errors=[str(e)], message=str(e))

    async def _call_vm(self, request: GetTradeContextRequest) -> dict:
        client = VM100Client(profile=RetryProfile.FAST_FAIL)
        input_id = request.trade_id or request.journal_id

        # Step 1 — RESOLVE IDENTITY (replaces silent-swallow).
        # The resolver returns 200 with a typed triple on success, or 404
        # with a tried[] list on miss. BaseVMClient.get raises on non-2xx
        # (httpx.HTTPStatusError), so a 404 lands in the except block.
        # Use the endpoint path from _RESOLVER_ENDPOINT_CITATION (strips the vm100/ prefix
        # since VM100Client.get takes the path without the scheme/host prefix).
        _resolver_path = _RESOLVER_ENDPOINT_CITATION.removeprefix("vm100/")
        try:
            identity = await client.get(
                _resolver_path,
                params={"id": str(input_id)},
            )
        except Exception:
            # Resolver missed (404) OR resolver unreachable. In either case
            # the LLM should know — honest miss, NOT empty payload.
            return _not_available(unblock_reason="id_unresolved")

        if not identity.get("found"):
            # Defensive: resolver returned 200 but flagged not-found. Same
            # NotAvailable outcome.
            return _not_available(unblock_reason="id_unresolved")

        # Step 2 — fetch trade detail via resolved integer trade_id.
        # If the resolver returned a journal_id only (DRAFT journal with no
        # Execution / no api.Trade row yet), we don't have an integer to
        # fetch /api/v1/trades/{int} against. Return the journal-shaped
        # context with the resolved identity but None for trade fields.
        trade_id_int = identity.get("trade_id")
        if trade_id_int is None:
            return self._draft_journal_response(request, identity)

        try:
            trade = await client.get(f"api/v1/trades/{trade_id_int}")
        except Exception:
            # Trade fetch failed (trade row deleted? hypertable gap?). The
            # resolver said the trade exists; the read endpoint disagrees.
            # Honest miss is still the right answer.
            return _not_available(unblock_reason="trade_fetch_failed")

        return self._build_response(request, trade, identity)

    def _build_response(
        self,
        request: GetTradeContextRequest,
        trade: dict[str, Any],
        identity: dict[str, Any],
    ) -> dict:
        """Build a GetTradeContextPayload-shaped dict from a resolved trade.

        Phase 70.5 Plan 06: now includes a populated ``provenance`` field
        with RICH citations + assumptions (Decision 5).
        """
        # GetTradeContextPayload requires trade_id (str). Use the input
        # echo so caller sees back what they passed; the resolver's
        # numeric trade_id is also available via identity.trade_id.
        echoed_id = request.trade_id or request.journal_id or str(
            identity.get("trade_id") or identity.get("journal_id") or ""
        )
        echoed_id_str = str(echoed_id)

        # Phase 70.5 RICH provenance — Decision 5
        provenance = ToolProvenance(
            citations=(
                EvidenceCitation(
                    citation_kind="trade",
                    opaque_id=echoed_id_str,
                    human_label=f"Trade {echoed_id_str}",
                ),
                EvidenceCitation(
                    citation_kind="dataset",
                    opaque_id=_RESOLVER_ENDPOINT_CITATION,
                    human_label="VM100 identity resolver",
                ),
            ),
            assumptions=(
                "assumes user's local timezone is account timezone",
                "assumes no broker fills missed in the lookback window",
            ),
        )

        return {
            "trade_id": echoed_id_str,
            "instrument": trade.get("instrument"),
            "direction": trade.get("direction"),
            "strategy_id": trade.get("strategy_id"),
            "entry_price": trade.get("entry_price"),
            "stop_loss_price": trade.get("stop_loss_price"),
            "take_profit_price": trade.get("take_profit_price"),
            "notes": trade.get("notes"),
            "timeframe": trade.get("timeframe"),
            "checklist_snapshot_text": trade.get("checklist_snapshot_text"),
            # Plan 07 Tier-1 builder owns evaluation summary fetch (CONTEXT.md
            # OQ-1 / OQ-2). Phase 58.1 leaves this null on the tool side.
            "last_evaluation": None,
            "provenance": provenance,
        }

    def _draft_journal_response(
        self,
        request: GetTradeContextRequest,
        identity: dict[str, Any],
    ) -> dict:
        """Resolved to a DRAFT journal with no trade row → fields null but
        trade_id echoes the input so the LLM has a stable handle.

        Phase 70.5: populates provenance with trade citation + assumptions
        even on the draft path (journal_id is still a valid evidence source).
        """
        echoed_id = request.trade_id or request.journal_id or str(
            identity.get("journal_id") or ""
        )
        echoed_id_str = str(echoed_id)

        provenance = ToolProvenance(
            citations=(
                EvidenceCitation(
                    citation_kind="trade",
                    opaque_id=echoed_id_str,
                    human_label=f"Trade {echoed_id_str} (DRAFT journal)",
                ),
                EvidenceCitation(
                    citation_kind="dataset",
                    opaque_id=_RESOLVER_ENDPOINT_CITATION,
                    human_label="VM100 identity resolver",
                ),
            ),
            assumptions=(
                "assumes user's local timezone is account timezone",
                "assumes no broker fills missed in the lookback window",
            ),
        )

        return {
            "trade_id": echoed_id_str,
            "instrument": None,
            "direction": None,
            "strategy_id": None,
            "entry_price": None,
            "stop_loss_price": None,
            "take_profit_price": None,
            "notes": None,
            "timeframe": None,
            "checklist_snapshot_text": None,
            "last_evaluation": None,
            "provenance": provenance,
        }

    def _validate_response(self, data: dict) -> BaseContract:
        # Union return: NotAvailableResponse on honest miss, else
        # GetTradeContextPayload on resolved hit (or DRAFT pass-through).
        # GetTradeContextResponse is a backward-compat alias — same class.
        try:
            if data.get("status") == "not_available":
                return NotAvailableResponse(**data)
            return GetTradeContextPayload(**data)
        except Exception as e:  # noqa: BLE001 — contract path
            raise ContractValidationError(errors=[str(e)], message=str(e))
