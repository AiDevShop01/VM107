"""Phase 168 Plan 03 Task 2 — budgeted quant tool wrappers (AGV-07 / D-04).

Exposes the reuse-first VM102 quant substrate to agents as a budgeted,
progressively-disclosed tool surface. Each wrapper returns a
``ToolResultEnvelope[T]`` whose payload is a SCALAR/STRUCT — a number back, never
the underlying series (Constitution 17; agent-catalogue/11 §3 "a number back,
never the series"). The series stays server-side on VM102.

Design (why a reader seam, not a direct VM102 call here):
- G10 (typed-API lock): a tool NEVER touches raw parquet/DB and NEVER calls the
  VM102 compute functions directly (they take raw ``pl.Series``). It reaches its
  data through a typed read that returns a scalar/struct.
- The concrete typed reads for the quant library (percentile / change-point /
  surprise / lead-lag) are exposed by VM102 endpoints + ``VM102Client`` methods;
  the assembler (168-05/06) and the agent-registry wiring (169) inject a concrete
  reader. Here the wrappers take a :class:`QuantReader` seam (dependency
  injection / patchable) so the *budgeted surface* is complete and testable
  without a live VM102 — mirroring analogue_retrieval.py's patchable-seam pattern.
- Every tool, once registered, flows through ``dispatch_tool`` and inherits
  ``ctx.knowledge_time`` automatically (168-07). These wrappers read that as-of
  off ``ctx`` and stamp it onto the envelope + set the latest-only look-ahead flag.

The reuse-first VM102 homes each read wraps (verified 2026-08-27; A1/A5):
- percentile / zscore : ``analytics/distribution.py`` ``percentile_of_latest`` (-> int)
                        / ``zscore_of_latest`` (-> float)
- change-point        : ``analytics/forecast/regime/change_point.py``
                        ``detect_change_points`` (-> list[int] of indices)
- surprise            : ``feature_pipeline/models.py`` ``get_surprise_category`` (-> str)
                        + ``standardized_surprise`` / ``raw_surprise`` fields
- correlation/lead-lag: ``analytics/{correlations,rolling_correlation,lead_lag}.py``
                        (``lead_lag.fixed_table`` -> DataFrame; the tool returns the
                        best-lag SCALAR, never the table)

Host-clean: fingpt_core contracts + core.evidence.tools.budget + stdlib only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from fingpt_core.contracts.tool_envelope import ToolResultEnvelope
from fingpt_core.contracts.invocation_context import InvocationContext

from core.evidence.tools import budget

# Phase 172-02 (SC-3): the L0-L4 quant tools are now registered in the LIVE
# capability registry and invoked through the reader-bound wrappers in
# ``core.evidence.tools.quant_tool_dispatch``. ``registry_snapshot_hash`` is a
# keyword-REQUIRED argument on every tool below (no sentinel default): a caller —
# the dispatch-path wrapper, or a direct assembler call — MUST supply the live
# registry snapshot hash. The former ``_UNREGISTERED_SNAPSHOT`` sentinel was
# removed so a missing registration can no longer be masked by a fallback hash.
_PAYLOAD_SCHEMA_VERSION: str = "1.0"

# A live run stamps knowledge_time ~ now; a small tolerance keeps sub-second clock
# skew from being mistaken for a historical (look-ahead) replay.
_LOOKAHEAD_TOLERANCE = timedelta(seconds=5)


# ---------------------------------------------------------------------------
# Typed read structs (scalar/struct — NEVER a series). These are what the typed
# VM102 read returns; the tool projects a per-detail-level subset onto its payload.
# ---------------------------------------------------------------------------


class _QuantRead(BaseModel):
    """Base for a typed quant read: carries look-ahead honesty + provenance time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # True when the underlying VM102 service is latest-only (no point-in-time
    # store) — the tool escalates this to is_latest_only_flagged when the run's
    # as-of predates now (Constitution 18).
    latest_only: bool = False
    source_generated_at: datetime | None = None


class PercentileRead(_QuantRead):
    percentile: float
    zscore: float | None = None
    n_observations: int | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    # small struct (percentile markers), NOT the underlying series
    distribution_summary: dict | None = None


class ChangePointRead(_QuantRead):
    change_point_count: int
    last_change_index: int | None = None
    last_change_at: datetime | None = None
    recent_change: bool | None = None
    change_indices: tuple[int, ...] | None = None


class SurpriseRead(_QuantRead):
    category: str
    standardized_surprise: float | None = None
    raw_surprise: float | None = None
    reaction_strength: str | None = None


class CorrelationRead(_QuantRead):
    correlation: float
    best_lag: int | None = None
    best_lag_correlation: float | None = None
    direction: str | None = None


# ---------------------------------------------------------------------------
# Reader seam — the typed VM102 quant path (G10). Injected / patchable.
# ---------------------------------------------------------------------------


@runtime_checkable
class QuantReader(Protocol):
    """Typed read seam over the VM102 quant substrate (G10).

    A concrete implementation (backed by ``VM102Client`` + the quant endpoints)
    is injected by the assembler / registry wiring (168-05/06, 169). It returns
    scalar/struct reads — NEVER a series. ``knowledge_time`` is forwarded so the
    read can declare whether it honored the as-of (latest_only).
    """

    def historical_percentile(self, series_id: str, *, knowledge_time: datetime | None = None) -> PercentileRead: ...

    def change_point(self, series_id: str, *, knowledge_time: datetime | None = None) -> ChangePointRead: ...

    def surprise(self, event_id: str, *, knowledge_time: datetime | None = None) -> SurpriseRead: ...

    def lead_lag(self, series_a: str, series_b: str, *, knowledge_time: datetime | None = None) -> CorrelationRead: ...


# ---------------------------------------------------------------------------
# Payload models — Optional fields so a narrow level populates only the headline
# and each wider level adds strictly more (progressive disclosure D-04).
# ---------------------------------------------------------------------------


class PercentilePayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    percentile: float  # headline (COMPACT)
    zscore: float | None = None
    n_observations: int | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    distribution_summary: dict | None = None


class ChangePointPayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    change_point_count: int  # headline (COMPACT)
    recent_change: bool | None = None
    last_change_index: int | None = None
    last_change_at: datetime | None = None
    change_indices: tuple[int, ...] | None = None


class SurprisePayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    category: str  # headline (COMPACT)
    standardized_surprise: float | None = None
    reaction_strength: str | None = None
    raw_surprise: float | None = None


class CorrelationPayload(BaseModel):
    model_config = ConfigDict(frozen=True)
    correlation: float  # headline (COMPACT)
    best_lag: int | None = None
    direction: str | None = None
    best_lag_correlation: float | None = None


# ---------------------------------------------------------------------------
# Shared envelope builder
# ---------------------------------------------------------------------------


def _is_latest_only_lookahead(read: _QuantRead, ctx: InvocationContext) -> bool:
    """Look-ahead honesty (Constitution 18): flag a latest-only read served for a
    PAST as-of. A tolerance guards the ``knowledge_time == now`` live case from a
    sub-second clock skew being mistaken for a historical replay.
    """
    if not read.latest_only:
        return False
    now = datetime.now(timezone.utc)
    kt = ctx.knowledge_time
    # Only a materially-past as-of is a look-ahead; live runs (kt ~ now) are fine.
    return kt < now - _LOOKAHEAD_TOLERANCE


def _build_envelope(
    *,
    tool_name: str,
    ctx: InvocationContext,
    payload: BaseModel,
    read: _QuantRead,
    detail_level: str,
    profile_cap: int | None,
    registry_snapshot_hash: str,
) -> ToolResultEnvelope:
    """Construct a budgeted ToolResultEnvelope following the dispatcher convention.

    - envelope_id / knowledge_time inherited from ``ctx``;
    - detail_level + next_detail_levels populate the progressive-disclosure surface;
    - enforce_budget resolves the effective cap (min of tier + profile) and marks
      outcome_class "partial" if the payload would exceed it (never a silent drop);
    - is_latest_only_flagged set per the look-ahead rule.
    """
    decision = budget.enforce_budget(payload, detail_level, profile_cap=profile_cap)
    return ToolResultEnvelope(
        envelope_id=ctx.envelope_id,
        parent_envelope_id=ctx.parent_envelope_id,
        tool_name=tool_name,
        tool_version="1.0",
        outcome_class=decision.outcome_class,
        success=decision.outcome_class == "success",
        generated_at=datetime.now(timezone.utc),
        source_generated_at=read.source_generated_at,
        registry_snapshot_hash=registry_snapshot_hash,
        payload_schema_version=_PAYLOAD_SCHEMA_VERSION,
        knowledge_time=ctx.knowledge_time,
        is_latest_only_flagged=_is_latest_only_lookahead(read, ctx),
        detail_level=detail_level,  # type: ignore[arg-type]
        next_detail_levels=budget.next_detail_levels(detail_level),
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Budgeted quant tools
# ---------------------------------------------------------------------------


def historical_percentile(
    ctx: InvocationContext,
    series_id: str,
    *,
    reader: QuantReader,
    detail_level: str = "COMPACT",
    profile_cap: int | None = None,
    registry_snapshot_hash: str,
) -> ToolResultEnvelope[PercentilePayload]:
    """``historical_percentile(series="US_CORE_CPI") -> 71.4`` — the scalar, not the series."""
    read = reader.historical_percentile(series_id, knowledge_time=ctx.knowledge_time)
    fields_by_tier = {
        "COMPACT": {"percentile": read.percentile},
        "STANDARD": {"zscore": read.zscore, "n_observations": read.n_observations},
        "DETAILED": {"window_start": read.window_start, "window_end": read.window_end},
        "RAW": {"distribution_summary": read.distribution_summary},
    }
    payload = PercentilePayload(**budget.merge_detail_fields(fields_by_tier, detail_level))
    return _build_envelope(
        tool_name="historical_percentile",
        ctx=ctx,
        payload=payload,
        read=read,
        detail_level=detail_level,
        profile_cap=profile_cap,
        registry_snapshot_hash=registry_snapshot_hash,
    )


def change_point(
    ctx: InvocationContext,
    series_id: str,
    *,
    reader: QuantReader,
    detail_level: str = "COMPACT",
    profile_cap: int | None = None,
    registry_snapshot_hash: str,
) -> ToolResultEnvelope[ChangePointPayload]:
    """Change-point summary: a count + recency struct, never the change-index series."""
    read = reader.change_point(series_id, knowledge_time=ctx.knowledge_time)
    fields_by_tier = {
        "COMPACT": {"change_point_count": read.change_point_count},
        "STANDARD": {"recent_change": read.recent_change, "last_change_index": read.last_change_index},
        "DETAILED": {"last_change_at": read.last_change_at},
        "RAW": {"change_indices": read.change_indices},
    }
    payload = ChangePointPayload(**budget.merge_detail_fields(fields_by_tier, detail_level))
    return _build_envelope(
        tool_name="change_point",
        ctx=ctx,
        payload=payload,
        read=read,
        detail_level=detail_level,
        profile_cap=profile_cap,
        registry_snapshot_hash=registry_snapshot_hash,
    )


def surprise_score(
    ctx: InvocationContext,
    event_id: str,
    *,
    reader: QuantReader,
    detail_level: str = "COMPACT",
    profile_cap: int | None = None,
    registry_snapshot_hash: str,
) -> ToolResultEnvelope[SurprisePayload]:
    """Economic-surprise category (INLINE/MILD/MODERATE/LARGE/EXTREME) + z-score struct."""
    read = reader.surprise(event_id, knowledge_time=ctx.knowledge_time)
    fields_by_tier = {
        "COMPACT": {"category": read.category},
        "STANDARD": {"standardized_surprise": read.standardized_surprise, "reaction_strength": read.reaction_strength},
        "DETAILED": {"raw_surprise": read.raw_surprise},
        "RAW": {},
    }
    payload = SurprisePayload(**budget.merge_detail_fields(fields_by_tier, detail_level))
    return _build_envelope(
        tool_name="surprise_score",
        ctx=ctx,
        payload=payload,
        read=read,
        detail_level=detail_level,
        profile_cap=profile_cap,
        registry_snapshot_hash=registry_snapshot_hash,
    )


def lead_lag_correlation(
    ctx: InvocationContext,
    series_a: str,
    series_b: str,
    *,
    reader: QuantReader,
    detail_level: str = "COMPACT",
    profile_cap: int | None = None,
    registry_snapshot_hash: str,
) -> ToolResultEnvelope[CorrelationPayload]:
    """Lead-lag: the best-lag correlation SCALAR + direction, never the lag table."""
    read = reader.lead_lag(series_a, series_b, knowledge_time=ctx.knowledge_time)
    fields_by_tier = {
        "COMPACT": {"correlation": read.correlation},
        "STANDARD": {"best_lag": read.best_lag, "direction": read.direction},
        "DETAILED": {"best_lag_correlation": read.best_lag_correlation},
        "RAW": {},
    }
    payload = CorrelationPayload(**budget.merge_detail_fields(fields_by_tier, detail_level))
    return _build_envelope(
        tool_name="lead_lag_correlation",
        ctx=ctx,
        payload=payload,
        read=read,
        detail_level=detail_level,
        profile_cap=profile_cap,
        registry_snapshot_hash=registry_snapshot_hash,
    )
