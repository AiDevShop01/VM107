"""lookup_capability — meta-tool for capability registry introspection.

Phase 47.6 Plan 03 — sole declarant of the lookup_capability capability (LD-7).

REGISTER_CAPABILITY:
  type: tool
  id: lookup_capability
  path: VM107/registry/tool/lookup_capability.yaml
  status: real
  impact: HIGH

Agents call this tool when:
- Uncertain about a known capability (use lookup(id)).
- Performing explicit category enumeration (use list()).

This tool is soft-scoped on ALL registered agent profiles.
It returns typed LookupResult / ListResult — never raw YAML dicts.

Stub/experimental capabilities are DISCOVERABLE via lookup/list.
They are NOT invokable per Phase 47.6 LD-6c. Refusal cascade is the
caller's (tool_dispatcher) responsibility — this tool does NOT refuse.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel

from core.registry.capability_registry import CapabilityRegistry
from fingpt_core.contracts.capability_registry import (
    CapabilityIntrospectionEvent,
    CapabilitySummary,
    CapabilityStatus,
    CapabilityType,
    ImpactLevel,
)


# ---------------------------------------------------------------------------
# Return-type models
# ---------------------------------------------------------------------------


class LookupResult(BaseModel):
    """Typed result envelope for a single-id lookup.

    status="ok"           → capability field is populated
    status="not_available" → capability is None; meta carries the id attempted
                            and closest_matches list (Pitfall 4: no exception)
    """

    status: Literal["ok", "not_available"]
    capability: Optional[CapabilitySummary] = None
    meta: dict = {}


class ListResult(BaseModel):
    """Typed result envelope for a filtered list query."""

    status: Literal["ok"]
    capabilities: list[CapabilitySummary]
    registry_snapshot_hash: str
    returned_count: int


# ---------------------------------------------------------------------------
# Internal helper: introspection event logging
# ---------------------------------------------------------------------------


def _log_introspection(
    *,
    capability_id: Optional[str],
    lookup_type: Literal["lookup", "list"],
    registry_snapshot_hash: str,
    returned_status: Optional[str],
    returned_count: Optional[int],
    filters: Optional[dict],
    discovery_reason: Optional[str],
    reasoning_context_id: str = "unknown",  # overridden by env.envelope_id when envelope active
) -> Optional[CapabilityIntrospectionEvent]:
    """Build a CapabilityIntrospectionEvent and append it to the active envelope.

    Phase 47.6 Plan 06 (Wave 3 — LD-6d wired):
    Reads the current_envelope contextvar and appends an immutable
    CapabilityIntrospectionEvent to envelope.capability_introspection_log.

    CLI/dev safety: if no envelope is active (current_envelope returns None),
    silently skips — never crashes.

    B2 invariant: This function ONLY writes to capability_introspection_log.
    It NEVER writes to capability_refusal_log. That log is the sole domain
    of tool_dispatcher.py (invocation attempts only, per CONTEXT.md #6c).
    """
    from core.agents.envelope_context import current_envelope

    env = current_envelope.get()
    if env is None:
        # CLI / dev context — no active envelope; skip silently
        return None

    event = CapabilityIntrospectionEvent(
        capability_id=capability_id,
        lookup_type=lookup_type,
        registry_snapshot_hash=registry_snapshot_hash,
        returned_status=returned_status,
        returned_count=returned_count,
        filters=filters,
        discovery_reason=discovery_reason,
        occurred_at=datetime.now(tz=timezone.utc),
        reasoning_context_id=str(getattr(env, "envelope_id", "unknown") or "unknown"),
    )
    # LD-6d: append-only log — NEVER mutate existing entries
    env.capability_introspection_log.append(event)
    # NOTE (B2): intentionally NOT writing to capability_refusal_log here.
    # Introspection of a stub is NOT a refusal. Refusal is invocation-attempt
    # only — handled by tool_dispatcher.py (Task 2).
    return event


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def lookup(
    id: str,
    *,
    discovery_reason: Optional[str] = None,
    registry_snapshot_hash: Optional[str] = None,
) -> LookupResult:
    """Look up a capability by id. Returns a typed LookupResult envelope.

    Never raises an exception for unknown ids — returns a not_available envelope
    with closest_matches for typo recovery (Pitfall 4).

    Args:
        id: The capability id to look up.
        discovery_reason: Optional free-text reason for the lookup (logged to
            the introspection trace when inside an active agent envelope).
        registry_snapshot_hash: If provided and different from the current
            snapshot hash, raises NotImplementedError (V1 = current-only;
            frozen-snapshot replay is deferred per Phase 47.6 Deferred Ideas).

    Returns:
        LookupResult with status="ok" and populated capability, or
        LookupResult with status="not_available" and closest_matches in meta.
    """
    reg = CapabilityRegistry.get()

    # V1 frozen-snapshot replay guard
    if registry_snapshot_hash is not None and registry_snapshot_hash != reg.snapshot_hash:
        raise NotImplementedError(
            "Frozen-snapshot replay queries are deferred to a future phase. "
            f"Requested hash {registry_snapshot_hash!r} differs from current "
            f"snapshot hash {reg.snapshot_hash!r}. V1 supports current-only queries."
        )

    summary = reg.lookup(id)

    if summary is None:
        closest = reg.closest_ids(id, limit=3)
        _log_introspection(
            capability_id=id,
            lookup_type="lookup",
            registry_snapshot_hash=reg.snapshot_hash,
            returned_status="not_available",
            returned_count=None,
            filters=None,
            discovery_reason=discovery_reason,
            reasoning_context_id="unknown",
        )
        return LookupResult(
            status="not_available",
            capability=None,
            meta={
                "capability_id_attempted": id,
                "closest_matches": closest,
            },
        )

    _log_introspection(
        capability_id=id,
        lookup_type="lookup",
        registry_snapshot_hash=reg.snapshot_hash,
        returned_status=summary.status.value,
        returned_count=1,
        filters=None,
        discovery_reason=discovery_reason,
        reasoning_context_id="unknown",
    )
    return LookupResult(status="ok", capability=summary, meta={})


def list_capabilities(
    *,
    type: Optional[str] = None,
    status: Optional[str] = None,
    tags: Optional[list[str]] = None,
    allowed_profile: Optional[str] = None,
    impact: Optional[str] = None,
    discovery_reason: Optional[str] = None,
    registry_snapshot_hash: Optional[str] = None,
) -> ListResult:
    """Return a filtered, stably-ordered list of capability summaries.

    Filters compose (AND logic). All filters are optional.
    Order: (type, impact DESC, id) — LD-5 stable ordering from CapabilityRegistry.list().

    Args:
        type: Filter by capability type string (e.g. "tool", "signal").
        status: Filter by status string (e.g. "real", "stub").
        tags: Return only capabilities that have ALL of these tags.
        allowed_profile: Return only capabilities allowed for this profile id.
        impact: Filter by impact_on_decision string (e.g. "HIGH", "MEDIUM").
        discovery_reason: Logged to introspection trace when inside an envelope.
        registry_snapshot_hash: See lookup() — V1 raises if differs from current.

    Returns:
        ListResult with status="ok", capabilities list, snapshot hash, and count.
    """
    reg = CapabilityRegistry.get()

    # V1 frozen-snapshot replay guard
    if registry_snapshot_hash is not None and registry_snapshot_hash != reg.snapshot_hash:
        raise NotImplementedError(
            "Frozen-snapshot replay queries are deferred to a future phase. "
            f"Requested hash {registry_snapshot_hash!r} differs from current "
            f"snapshot hash {reg.snapshot_hash!r}. V1 supports current-only queries."
        )

    # Convert string filter args to enum values for CapabilityRegistry.list()
    type_filter: Optional[CapabilityType] = None
    if type is not None:
        try:
            type_filter = CapabilityType(type)
        except ValueError:
            # Unknown type → return empty list (no matching capabilities)
            return ListResult(
                status="ok",
                capabilities=[],
                registry_snapshot_hash=reg.snapshot_hash,
                returned_count=0,
            )

    status_filter: Optional[CapabilityStatus] = None
    if status is not None:
        try:
            status_filter = CapabilityStatus(status)
        except ValueError:
            return ListResult(
                status="ok",
                capabilities=[],
                registry_snapshot_hash=reg.snapshot_hash,
                returned_count=0,
            )

    impact_filter: Optional[ImpactLevel] = None
    if impact is not None:
        try:
            impact_filter = ImpactLevel(impact)
        except ValueError:
            return ListResult(
                status="ok",
                capabilities=[],
                registry_snapshot_hash=reg.snapshot_hash,
                returned_count=0,
            )

    results = reg.list(
        type=type_filter,
        status=status_filter,
        tags=tags,
        allowed_profile=allowed_profile,
        impact=impact_filter,
    )

    _log_introspection(
        capability_id=None,
        lookup_type="list",
        registry_snapshot_hash=reg.snapshot_hash,
        returned_status=None,
        returned_count=len(results),
        filters={
            "type": type,
            "status": status,
            "tags": tags,
            "allowed_profile": allowed_profile,
            "impact": impact,
        },
        discovery_reason=discovery_reason,
        reasoning_context_id="unknown",
    )

    return ListResult(
        status="ok",
        capabilities=results,
        registry_snapshot_hash=reg.snapshot_hash,
        returned_count=len(results),
    )
