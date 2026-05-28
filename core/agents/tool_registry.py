"""Phase 70.5 Plan 02 — typed view over CapabilityRegistrySnapshot for tool dispatch.

Decision 15 lock: this is NOT a hand-maintained Dict[str, Callable]. The registry
YAMLs are the declarative truth (Phase 47.6 lock); this module is the typed runtime
accessor.

The registry is boot-frozen (LD-2). load_tool_entries() caches its result for the
lifetime of the process — calling it twice returns the same list instance.

Companion module: tool_resolver.py (callable binding + invocation).

Public API:
    ToolEntry            — frozen dataclass: runtime-friendly projection of a tool entry
    ResolverError        — base exception class for registry/resolver errors
    load_tool_entries()  — boot-frozen list of all tool-type entries from the registry
    get_tool_entry(id)   — return ToolEntry by id or raise KeyError
    _get_registry()      — internal accessor; patched in tests to inject mock registry

Facade tool detection:
    Tool IDs with a cross-VM prefix (vm100.*, vm101.*, vm102.*, vm107.*) are facade
    registrations. They do not have a local Python implementation in VM107/tools/.
    Plan 07 ships proxy modules for them; until then tool_resolver.py raises
    CapabilityRefusedError(reason="facade_not_yet_implemented") for those entries.

Source module parsing:
    YAML `location.source: VM107/tools/get_trade_context.py`
    → importable string: `tools.get_trade_context`

    Algorithm:
    1. Strip the `VM107/` prefix (all local tool paths start with this).
    2. Strip the `.py` suffix.
    3. Replace `/` with `.`.
    Returns None for facade YAMLs that have no `location.source` referencing a
    local VM107 file.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.registry.capability_registry import CapabilityRegistry as _CapabilityRegistry


class ResolverError(Exception):
    """Base error for tool_registry / tool_resolver."""


# Prefixes that identify cross-VM facade registrations.
# These tools have no local Python implementation — they will be wired via
# proxy modules in Plan 07. Until then, the resolver refuses them cleanly.
_FACADE_PREFIXES: frozenset[str] = frozenset({"vm100", "vm101", "vm102", "vm107"})

# The filesystem prefix all local VM107 tool source paths carry.
# e.g. "VM107/tools/get_trade_context.py" → strip this prefix first.
_VM107_PREFIX = "VM107/"


@dataclass(frozen=True)
class ToolEntry:
    """Runtime-friendly projection of a tool CapabilitySnapshotEntry.

    Carries the resolver-relevant subset of fields — typed, frozen, replay-safe.

    Fields:
        id                       — registry id (e.g. "get_trade_context")
        status                   — "stub" | "experimental" | "real" | "deprecated"
        source_module            — importable module string (e.g. "tools.get_trade_context");
                                   None for facade tools without a local implementation
        typical_confidence       — registry YAML typical_confidence or None
        expected_freshness_seconds — registry YAML expected_freshness_seconds or None
        is_deterministic         — registry YAML is_deterministic or None
        version                  — registry YAML version or None
        is_facade                — True when id prefix is in _FACADE_PREFIXES
    """
    id: str
    status: str                          # "stub" | "experimental" | "real" | "deprecated"
    source_module: str | None            # e.g. "tools.get_trade_context"; None for facades
    typical_confidence: float | None
    expected_freshness_seconds: int | None
    is_deterministic: bool | None
    version: str | None
    is_facade: bool                      # True when id prefix matches a cross-VM namespace


def _parse_source_module(source: str | None) -> str | None:
    """Convert YAML `location.source: VM107/tools/foo.py` → `"tools.foo"`.

    Returns None when:
    - source is None or empty (facade YAMLs without a local implementation file)
    - source does not start with VM107/ (unexpected format; treated as None)

    Examples:
        "VM107/tools/get_trade_context.py"   → "tools.get_trade_context"
        "VM107/tools/behavioral_analysis.py" → "tools.behavioral_analysis"
        None                                 → None
        "VM100/tools/foo.py"                 → None  (not a VM107-local module)
    """
    if not source:
        return None
    if not source.startswith(_VM107_PREFIX):
        # Cross-VM path or unexpected format — not importable from VM107 root
        return None
    # Strip "VM107/" prefix and ".py" suffix, then convert path separators to dots
    relative = source[len(_VM107_PREFIX):]          # e.g. "tools/get_trade_context.py"
    if relative.endswith(".py"):
        relative = relative[:-3]                     # e.g. "tools/get_trade_context"
    return relative.replace("/", ".")                # e.g. "tools.get_trade_context"


def _is_facade(tool_id: str) -> bool:
    """Return True if tool_id has a cross-VM prefix (vm100, vm101, vm102, vm107)."""
    prefix = tool_id.split(".", 1)[0]
    return prefix in _FACADE_PREFIXES


# Boot-frozen cache — populated on first call to load_tool_entries()
_CACHE: list[ToolEntry] | None = None


def _get_registry() -> "_CapabilityRegistry":
    """Return the initialized CapabilityRegistry singleton.

    Extracted as a named function (not inlined) so tests can patch it cleanly:
        with patch("core.agents.tool_registry._get_registry", return_value=mock_reg):
            entries = load_tool_entries()

    In production this is equivalent to `CapabilityRegistry.get()` which raises
    RuntimeError if called before initialize(). That hard-fail is intentional.
    """
    from core.registry.capability_registry import CapabilityRegistry
    return CapabilityRegistry.get()


def load_tool_entries() -> list[ToolEntry]:
    """Return the boot-frozen list of all tool-type entries from the active registry.

    First call builds and caches the list. Every subsequent call returns the same
    list instance (identity test via `is` will pass).

    The registry is itself boot-frozen (Phase 47.6 LD-2); caching here mirrors
    that immutability — the tool entry list cannot change within a process lifetime.

    Raises:
        RuntimeError: If CapabilityRegistry has not been initialized yet.
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    reg = _get_registry()
    entries: list[ToolEntry] = []

    from fingpt_core.contracts.capability_registry import CapabilityType

    for snapshot_entry in reg.snapshot.entries:
        # Only tool-type entries are relevant to the dispatcher
        if snapshot_entry.type != CapabilityType.TOOL:
            continue

        cap_id = snapshot_entry.id
        raw = reg._full_meta.get(cap_id, {})

        # Extract location.source from the raw YAML data
        location = raw.get("location", {})
        if isinstance(location, dict):
            source_str = location.get("source")
        elif isinstance(location, str):
            source_str = location
        else:
            source_str = None

        # Extract Phase 70.5 provenance fields (may be None if YAMLs not yet migrated)
        typical_confidence = snapshot_entry.typical_confidence  # type: ignore[attr-defined]
        expected_freshness_seconds = snapshot_entry.expected_freshness_seconds  # type: ignore[attr-defined]
        is_deterministic = snapshot_entry.is_deterministic  # type: ignore[attr-defined]
        version = snapshot_entry.version  # type: ignore[attr-defined]

        facade = _is_facade(cap_id)
        source_module = _parse_source_module(source_str) if not facade else None

        entries.append(ToolEntry(
            id=cap_id,
            status=snapshot_entry.status.value,
            source_module=source_module,
            typical_confidence=typical_confidence,
            expected_freshness_seconds=expected_freshness_seconds,
            is_deterministic=is_deterministic,
            version=version,
            is_facade=facade,
        ))

    _CACHE = entries
    return _CACHE


def get_tool_entry(tool_id: str) -> ToolEntry:
    """Return the ToolEntry for the given tool_id.

    Args:
        tool_id: The capability id to look up (must match registry id exactly).

    Returns:
        The matching ToolEntry.

    Raises:
        KeyError: If tool_id is not registered as a tool-type capability.
    """
    for entry in load_tool_entries():
        if entry.id == tool_id:
            return entry
    raise KeyError(f"Tool not registered: {tool_id!r}")
