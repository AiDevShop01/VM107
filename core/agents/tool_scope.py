"""Phase 47.6 Wave 4: pure registry projection. LEGACY_NON_AUTHORITATIVE constants preserved.

The discovery authority for tool scope is now CapabilityRegistry.get().is_capability_in_scope().
HARD_ALLOWED_TOOLS, SENSITIVE_TOOLS, and PROFILE_TO_AGENT_ID are POPULATED PROJECTIONS
(M15 — chose populated over empty shim; empty shim risks runtime breakage in any old
consumer that hasn't migrated to is_capability_in_scope yet).

Full deletion of the legacy constants is deferred to a follow-up cleanup phase per
CONTEXT.md decision LD-8. Until then, reads against these constants get a snapshot
of registry truth at module-import time.

NOTE: The legacy constants may return empty dicts/frozensets if the registry is not
yet initialized at import time (test contexts, scripts). This is intentional —
old consumers reading HARD_ALLOWED_TOOLS get empty maps, but any scope CHECK still
goes through is_tool_allowed() → is_capability_in_scope() which consults the live
registry directly.

Public API (unchanged):
    UnauthorizedToolError           — raised by denial stubs and check_tool_scope
    is_tool_allowed()               — returns bool (now projects registry truth)
    check_tool_scope()              — raises UnauthorizedToolError on denial
    resolve_agent_id_from_profile() — bridge profile name → agent_id (uses registry)

    SENSITIVE_TOOLS       — LEGACY_NON_AUTHORITATIVE populated projection
    HARD_ALLOWED_TOOLS    — LEGACY_NON_AUTHORITATIVE populated projection
    PROFILE_TO_AGENT_ID   — LEGACY_NON_AUTHORITATIVE populated projection
"""
from __future__ import annotations

from typing import Final


class UnauthorizedToolError(PermissionError):
    """Raised when an agent attempts to invoke a HARD-scoped tool not in its allow-list."""

    def __init__(self, agent_id: str, tool_name: str) -> None:
        self.agent_id = agent_id
        self.tool_name = tool_name
        super().__init__(
            f"Agent '{agent_id}' is not authorized to use tool '{tool_name}'. "
            f"Tool is HARD-scoped (Phase 47.6 registry projection)."
        )


# ── Public API — registry-projected ─────────────────────────────────────────


def is_tool_allowed(agent_id: str, tool_name: str) -> bool:
    """Return True if agent_id may invoke tool_name.

    REG-05: pure projection over registry truth (Phase 47.6 Wave 4).
    Previously: checked HARD_ALLOWED_TOOLS dict for SENSITIVE_TOOLS;
                returned True unconditionally for all other tools.
    Now: delegates to CapabilityRegistry.is_capability_in_scope for
         any tool registered in the registry; returns True for unknown
         tools (preserves soft-scope behavior for legacy tools not yet
         registered, maintaining backward-compatible permissive default).
    """
    from core.registry.capability_registry import CapabilityRegistry

    try:
        reg = CapabilityRegistry.get()
    except RuntimeError:
        # Registry not yet initialized (boot race or test context).
        # Fall back to permissive default to avoid blocking unrelated code.
        return True

    # If the tool is not in the registry, treat as soft-scoped (allow all agents).
    # This preserves the pre-Phase-47.6 behavior for legacy tools not yet registered.
    entry = reg._by_id.get(tool_name)
    if entry is None:
        return True  # unknown tool — soft-scope default

    return reg.is_capability_in_scope(profile=agent_id, capability_id=tool_name)


def check_tool_scope(agent_id: str, tool_name: str) -> None:
    """Raise UnauthorizedToolError if agent_id is not allowed to use tool_name.

    Soft-scoped tools (not in registry or no profile restriction) never raise.
    Used by denial stubs and extension hooks to enforce HARD scoping.
    """
    if not is_tool_allowed(agent_id, tool_name):
        raise UnauthorizedToolError(agent_id, tool_name)


def resolve_agent_id_from_profile(profile: str) -> str:
    """Bridge agent.config.profile (filesystem name) to router agent_id.

    Preserves the legacy 'agent0' -> 'agent_zero' mapping for backward
    compatibility. For all other profiles, identity mapping (key == value).
    """
    return PROFILE_TO_AGENT_ID.get(profile, profile)


# ── LEGACY_NON_AUTHORITATIVE projections ────────────────────────────────────
# These exist for backward compatibility with consumers that still import the
# dict/frozenset shape (e.g., tests/registry/test_yaml_normalization.py,
# scripts/curate_task2.py). They are NOT the discovery authority.
#
# Reads against these constants are snapshots of registry truth at module-import
# time. If the registry is not yet initialized (test contexts, scripts), the
# projections return empty containers — callers should use is_tool_allowed()
# or is_capability_in_scope() directly for accurate runtime checks.
#
# Full deletion deferred per CONTEXT.md LD-8.


def _legacy_hard_allowed_tools_projection() -> dict[str, frozenset[str]]:
    """Build {agent_id: frozenset[tool_ids]} from registry — mirrors old HARD_ALLOWED_TOOLS."""
    try:
        from core.registry.capability_registry import CapabilityRegistry
        reg = CapabilityRegistry.get()
    except (RuntimeError, ImportError):
        return {}  # registry not yet initialized; consumers fall through to is_tool_allowed

    # Invert: for each TOOL entry with hard_scoped=True, for each allowed_profile,
    # add the tool_id to that profile's frozenset.
    # Only type=tool entries — non-tool types (services, skills, etc.) may also be
    # hard_scoped but are not relevant to the tool-scope allow-list.
    from fingpt_core.contracts.capability_registry import CapabilityType
    mapping: dict[str, set[str]] = {}
    for entry in reg.snapshot.entries:
        if entry.hard_scoped and entry.type == CapabilityType.TOOL:
            for profile in entry.allowed_agent_profiles:
                mapping.setdefault(profile, set()).add(entry.id)

    # Ensure all known profiles appear (even those with no hard-scoped tools)
    for profile_id in _legacy_profile_to_agent_id_projection().values():
        mapping.setdefault(profile_id, set())

    return {k: frozenset(v) for k, v in mapping.items()}


def _legacy_sensitive_tools_projection() -> frozenset[str]:
    """Build frozenset of hard-scoped TOOL ids — mirrors old SENSITIVE_TOOLS.

    Only type=tool entries with hard_scoped=True are included. Other capability
    types (services, skills, patterns, etc.) may also be hard_scoped but are
    NOT tools and should not appear in SENSITIVE_TOOLS.
    """
    try:
        from core.registry.capability_registry import CapabilityRegistry
        from fingpt_core.contracts.capability_registry import CapabilityType
        reg = CapabilityRegistry.get()
    except (RuntimeError, ImportError):
        return frozenset()

    return frozenset(
        entry.id
        for entry in reg.snapshot.entries
        if entry.hard_scoped and entry.type == CapabilityType.TOOL
    )


def _legacy_profile_to_agent_id_projection() -> dict[str, str]:
    """Build {profile_name: agent_id} — mirrors old PROFILE_TO_AGENT_ID.

    For all agent_profile entries in the registry, key == value (dotted ids
    are their own agent_ids). The legacy 'agent0' -> 'agent_zero' filesystem
    alias is preserved explicitly since it's a well-known mapping.
    """
    try:
        from core.registry.capability_registry import CapabilityRegistry
        from fingpt_core.contracts.capability_registry import CapabilityType
        reg = CapabilityRegistry.get()
    except (RuntimeError, ImportError):
        return {}

    mapping: dict[str, str] = {}
    for entry in reg.snapshot.entries:
        if entry.type == CapabilityType.AGENT_PROFILE:
            mapping[entry.id] = entry.id

    # Legacy filesystem alias: 'agent0' (on-disk profile dir) -> 'agent_zero' (agent_id)
    if "agent_zero" in mapping:
        mapping["agent0"] = "agent_zero"

    return mapping


# Module-level projection constants (LEGACY_NON_AUTHORITATIVE)
# These are populated at import time if the registry is already initialized.
# If not, they are empty containers — use is_tool_allowed() for runtime checks.
HARD_ALLOWED_TOOLS: Final[dict] = _legacy_hard_allowed_tools_projection()  # LEGACY_NON_AUTHORITATIVE
SENSITIVE_TOOLS: Final[frozenset] = _legacy_sensitive_tools_projection()  # LEGACY_NON_AUTHORITATIVE
PROFILE_TO_AGENT_ID: Final[dict] = _legacy_profile_to_agent_id_projection()  # LEGACY_NON_AUTHORITATIVE
