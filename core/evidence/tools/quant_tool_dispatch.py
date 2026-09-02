"""Phase 172 Plan 02 Task 1 (SC-3) — reader-bound dispatch wrappers for the
L0-L4 progressive-disclosure quant tools.

The budgeted quant tools in :mod:`core.evidence.tools.quant_tools`
(``historical_percentile`` / ``change_point`` / ``surprise_score`` /
``lead_lag_correlation``) each require a ``reader: QuantReader`` keyword — a typed
VM102 read seam (G10). ``dispatch_tool`` (core/agents/tool_dispatcher.py) spreads
a tool's ``kwargs`` straight to the resolved callable and CANNOT supply ``reader=``
blind (RESEARCH Pitfall 4). This module is the thin reader-BINDING layer between
the registry and the raw tool functions: each wrapper here resolves the active
:class:`~core.evidence.tools.quant_tools.QuantReader` internally and delegates to
the underlying tool, so a caller (dispatch or an agent) need never pass ``reader=``.

Reader binding (honest, additive — the concrete VM102-backed reader is a 169 /
assembler wiring dependency, OUT of SC-3's standalone-registration scope):

- A concrete ``QuantReader`` is injected once at wiring time via
  :func:`set_quant_reader` (the assembler / registry wiring, or a test). The
  wrappers then bind that reader on every call.
- If no reader has been injected, :func:`active_reader` raises
  :class:`QuantReaderNotConfigured` — a LOUD failure, never a fabricated read.
  SC-3 registers + budget-proofs these tools; they are NOT invoked on the live
  ``assess()`` path this phase (RESEARCH Priority Q2), so the fail-loud default is
  never reached in production. Wiring a VM102Client-backed reader (RetryProfile
  ``FAST_FAIL``) is the 169 follow-up.

Snapshot hash: ``quant_tools`` made ``registry_snapshot_hash`` keyword-REQUIRED
(the ``_UNREGISTERED_SNAPSHOT`` sentinel was removed). Each wrapper supplies the
LIVE registry snapshot hash via :func:`current_snapshot_hash` (resolved lazily
from the capability registry; a caller may still override it explicitly).

Host-clean: stdlib + the pure ``quant_tools`` module. No import-time network,
registry, or VM102 dependency — every seam is resolved lazily at call time.
"""
from __future__ import annotations

from fingpt_core.contracts.invocation_context import InvocationContext
from fingpt_core.contracts.tool_envelope import ToolResultEnvelope

from core.evidence.tools import quant_tools
from core.evidence.tools.quant_tools import (
    CorrelationPayload,
    PercentilePayload,
    ChangePointPayload,
    QuantReader,
    SurprisePayload,
)

__all__ = [
    "historical_percentile",
    "change_point",
    "surprise_score",
    "lead_lag_correlation",
    "set_quant_reader",
    "reset_quant_reader",
    "active_reader",
    "current_snapshot_hash",
    "QuantReaderNotConfigured",
]


class QuantReaderNotConfigured(RuntimeError):
    """Raised when a quant tool is invoked before a concrete QuantReader is wired.

    Fail-loud by design (honest degradation): a quant tool NEVER fabricates a read
    to paper over a missing reader. Wire one with :func:`set_quant_reader` — the
    169 / assembler wiring injects a VM102Client-backed reader; tests inject a fake.
    """


# The process-wide bound reader. ``None`` until the assembler / registry wiring
# (or a test) injects a concrete QuantReader. Deliberately module-level so a
# single wiring call binds it for every wrapper on the dispatch path.
_bound_reader: QuantReader | None = None


def set_quant_reader(reader: QuantReader) -> None:
    """Bind the concrete ``QuantReader`` the dispatch wrappers read through (G10).

    Called by the assembler / registry wiring (169) with a VM102Client-backed
    reader, or by a test with a fake. Idempotent — the last binding wins.
    """
    global _bound_reader
    _bound_reader = reader


def reset_quant_reader() -> None:
    """Clear the bound reader (test-hygiene helper)."""
    global _bound_reader
    _bound_reader = None


def active_reader() -> QuantReader:
    """Return the bound ``QuantReader`` or fail loud if none is wired.

    Raises:
        QuantReaderNotConfigured: no concrete reader has been injected. Never
            silently substitutes a fabricated read (no-mocks-in-production).
    """
    if _bound_reader is None:
        raise QuantReaderNotConfigured(
            "No QuantReader is wired — call quant_tool_dispatch.set_quant_reader() "
            "at assembler/registry wiring time (169) with a VM102Client-backed "
            "reader, or in a test with a fake. SC-3 registers these tools; they are "
            "not invoked on the live assess() path this phase."
        )
    return _bound_reader


def current_snapshot_hash() -> str:
    """Resolve the LIVE capability-registry snapshot hash (lazy, best-effort).

    ``quant_tools`` made ``registry_snapshot_hash`` keyword-required; the wrappers
    supply this so a real registration always stamps the real hash. If the registry
    has not been initialised (e.g. an early call), a clearly-labelled runtime
    sentinel is returned rather than raising — the envelope stays well-formed.
    """
    try:
        from core.registry.capability_registry import CapabilityRegistry

        return CapabilityRegistry.get().snapshot_hash
    except Exception:
        return "sha-runtime-unresolved-quant"


# ---------------------------------------------------------------------------
# Reader-bound wrappers — one per L0-L4 tool. Dispatch-compatible: every argument
# except ``reader`` is accepted (dispatch spreads kwargs); ``reader`` is bound
# internally (Pitfall 4 closed structurally).
# ---------------------------------------------------------------------------


def historical_percentile(
    ctx: InvocationContext,
    series_id: str,
    *,
    detail_level: str = "COMPACT",
    profile_cap: int | None = None,
    registry_snapshot_hash: str | None = None,
) -> ToolResultEnvelope[PercentilePayload]:
    """Reader-bound ``historical_percentile`` — binds the active QuantReader."""
    return quant_tools.historical_percentile(
        ctx,
        series_id,
        reader=active_reader(),
        detail_level=detail_level,
        profile_cap=profile_cap,
        registry_snapshot_hash=registry_snapshot_hash or current_snapshot_hash(),
    )


def change_point(
    ctx: InvocationContext,
    series_id: str,
    *,
    detail_level: str = "COMPACT",
    profile_cap: int | None = None,
    registry_snapshot_hash: str | None = None,
) -> ToolResultEnvelope[ChangePointPayload]:
    """Reader-bound ``change_point`` — binds the active QuantReader."""
    return quant_tools.change_point(
        ctx,
        series_id,
        reader=active_reader(),
        detail_level=detail_level,
        profile_cap=profile_cap,
        registry_snapshot_hash=registry_snapshot_hash or current_snapshot_hash(),
    )


def surprise_score(
    ctx: InvocationContext,
    event_id: str,
    *,
    detail_level: str = "COMPACT",
    profile_cap: int | None = None,
    registry_snapshot_hash: str | None = None,
) -> ToolResultEnvelope[SurprisePayload]:
    """Reader-bound ``surprise_score`` — binds the active QuantReader."""
    return quant_tools.surprise_score(
        ctx,
        event_id,
        reader=active_reader(),
        detail_level=detail_level,
        profile_cap=profile_cap,
        registry_snapshot_hash=registry_snapshot_hash or current_snapshot_hash(),
    )


def lead_lag_correlation(
    ctx: InvocationContext,
    series_a: str,
    series_b: str,
    *,
    detail_level: str = "COMPACT",
    profile_cap: int | None = None,
    registry_snapshot_hash: str | None = None,
) -> ToolResultEnvelope[CorrelationPayload]:
    """Reader-bound ``lead_lag_correlation`` — binds the active QuantReader."""
    return quant_tools.lead_lag_correlation(
        ctx,
        series_a,
        series_b,
        reader=active_reader(),
        detail_level=detail_level,
        profile_cap=profile_cap,
        registry_snapshot_hash=registry_snapshot_hash or current_snapshot_hash(),
    )
