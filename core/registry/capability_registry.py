"""CapabilityRegistry singleton — boot-time-frozen cognition compiler.

Boot path (VM107 initialize.py or entrypoint):
    import os
    from pathlib import Path
    from core.registry.capability_registry import CapabilityRegistry

    CapabilityRegistry.initialize(Path(os.environ["CAPABILITY_REGISTRY_ROOT"]))

After boot, any module can:
    from core.registry.capability_registry import CapabilityRegistry
    reg = CapabilityRegistry.get()
    summary = reg.lookup("get_trade_quality_score")

LD-2: Runtime reload is REJECTED. Once initialized, the registry is frozen.
LD-3: Hash computed over semantic fields only (not YAML bytes or timestamps).
LD-4: get_index_for_profile returns profile-scoped slice of real capabilities.
LD-5: list() ordering: (type, -impact_rank, id) for stable agent cognition.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Optional

from fingpt_core.contracts.capability_registry import (
    CapabilityRegistrySnapshot,
    CapabilitySnapshotEntry,
    CapabilityStatus,
    CapabilitySummary,
    CapabilityType,
    ImpactLevel,
    RegistryValidationError,
)

from .index import get_index_for_profile as _get_index_for_profile
from .loader import load_all_yamls
from .snapshot import build_snapshot
from .validation import (
    validate_contract_resolution,
    validate_cross_type_linkage,
    validate_dependency_graph,
    validate_identity_uniqueness,
    validate_schemas,
    validate_scope_references,
    validate_yaml_syntax,
)

# Impact level -> numeric rank for LD-5 ordering
_IMPACT_RANK = {
    ImpactLevel.HIGH: 3,
    ImpactLevel.MEDIUM: 2,
    ImpactLevel.LOW: 1,
}


class CapabilityRegistry:
    """Singleton registry of all 155 capability YAMLs.

    Lifecycle:
        1. Call CapabilityRegistry.initialize(root) ONCE at boot.
        2. Call CapabilityRegistry.get() everywhere else.
        3. Calling initialize() again raises RuntimeError (LD-2 reload rejection).

    The registry is immutable after initialization. No per-call YAML re-reads.
    """

    _instance: ClassVar[Optional["CapabilityRegistry"]] = None

    def __init__(
        self,
        snapshot: CapabilityRegistrySnapshot,
        descriptions: dict[str, str],
        full_meta: dict[str, dict],
    ) -> None:
        """Internal constructor. Use CapabilityRegistry.initialize() instead."""
        self._snapshot = snapshot
        self._descriptions: dict[str, str] = descriptions
        # Side-channel: full raw YAML dict per capability id for CapabilitySummary
        self._full_meta: dict[str, dict] = full_meta
        # Build O(1) lookup index
        self._by_id: dict[str, CapabilitySnapshotEntry] = {
            e.id: e for e in snapshot.entries
        }

    # ------------------------------------------------------------------
    # Class methods (singleton lifecycle)
    # ------------------------------------------------------------------

    @classmethod
    def initialize(cls, registry_root: Path) -> "CapabilityRegistry":
        """Load and validate all YAMLs under registry_root, freeze the snapshot.

        Args:
            registry_root: Path to the registry directory containing type subdirs.

        Returns:
            The initialized CapabilityRegistry instance.

        Raises:
            RuntimeError: If called more than once (LD-2 runtime reload rejected).
            RegistryValidationError: If any of the 7 validation stages fail.
        """
        if cls._instance is not None:
            raise RuntimeError(
                "CapabilityRegistry already initialized; "
                "runtime reload is REJECTED per CONTEXT.md LD-2. "
                "The registry is boot-time-frozen. "
                "Restart the VM107 process to reload."
            )

        # Load all YAMLs (stage 1 errors raised here)
        raw_entries = load_all_yamls(registry_root)

        # Stage 1: passthrough (syntax errors already raised by loader)
        validate_yaml_syntax(raw_entries)

        # Stage 2: Pydantic schema validation -> CapabilitySnapshotEntry list
        entries = validate_schemas(raw_entries)

        # Stage 3: identity uniqueness
        validate_identity_uniqueness(entries)

        # Stage 4: dependency graph
        validate_dependency_graph(entries)

        # Stage 5: scope references
        validate_scope_references(entries)

        # Stage 6: contract resolution — repo_root is two levels up from registry
        # (VM107/registry -> VM107 -> FinGPT root)
        repo_root = registry_root.parent
        validate_contract_resolution(entries, repo_root)

        # Stage 7: cross-type linkage — needs raw YAML data for extra fields
        raw_map = {raw.get("id", path.stem): raw for path, raw in raw_entries}
        validate_cross_type_linkage(entries, raw_map)

        # Build side channels for rich CapabilitySummary lookups
        descriptions: dict[str, str] = {}
        full_meta: dict[str, dict] = {}
        for path, raw in raw_entries:
            cap_id = raw.get("id", path.stem)
            # Prefer explicit short_description or description field
            descriptions[cap_id] = raw.get("short_description") or raw.get("description") or ""
            full_meta[cap_id] = raw

        # Build and freeze snapshot
        snapshot = build_snapshot(entries)

        cls._instance = cls(snapshot, descriptions, full_meta)
        return cls._instance

    @classmethod
    def get(cls) -> "CapabilityRegistry":
        """Return the initialized registry instance.

        Raises:
            RuntimeError: If initialize() has not been called yet.
        """
        if cls._instance is None:
            raise RuntimeError(
                "CapabilityRegistry not initialized. "
                "Call CapabilityRegistry.initialize() in VM107 boot path "
                "BEFORE any agent dispatch."
            )
        return cls._instance

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def snapshot(self) -> CapabilityRegistrySnapshot:
        """The frozen registry snapshot."""
        return self._snapshot

    @property
    def snapshot_hash(self) -> str:
        """The 64-char SHA-256 hex hash of the canonical registry payload."""
        return self._snapshot.snapshot_hash

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def lookup(self, id: str) -> Optional[CapabilitySummary]:
        """Look up a capability by id and return a full CapabilitySummary DTO.

        Returns None if the id is not registered (the lookup_capability tool
        wraps this into a not_available envelope — Plan 03).
        """
        entry = self._by_id.get(id)
        if entry is None:
            return None

        raw = self._full_meta.get(id, {})

        # Build location dict from raw YAML
        location_raw = raw.get("location", {})
        if isinstance(location_raw, dict):
            location = location_raw
        else:
            location = {"source": str(location_raw)}

        return CapabilitySummary(
            id=entry.id,
            type=entry.type,
            status=entry.status,
            short_description=self._descriptions.get(id, ""),
            long_description=raw.get("long_description") or raw.get("description") or "",
            contracts={
                "request": entry.contracts_request,
                "response": entry.contracts_response,
            },
            impact_on_decision=entry.impact_on_decision,
            allowed_agent_profiles=entry.allowed_agent_profiles,
            dependencies=entry.dependencies,
            related_capabilities=entry.related_capabilities,
            deprecated=entry.deprecated,
            tags=entry.tags,
            api_structure=raw.get("api_structure", ""),
            location=location,
            unblocks_when=tuple(raw.get("unblocks_when", [])),
            last_changed=str(raw.get("last_changed", "") or ""),
        )

    def list(
        self,
        *,
        type: Optional[CapabilityType] = None,
        status: Optional[CapabilityStatus] = None,
        tags: Optional[list[str]] = None,
        allowed_profile: Optional[str] = None,
        impact: Optional[ImpactLevel] = None,
    ) -> list[CapabilitySummary]:
        """Return capabilities matching the given filters.

        Ordering: (type.value, -impact_rank, id) per LD-5 for stable cognition.
        All filters are optional; unset filters do not restrict results.
        """
        results: list[CapabilitySummary] = []

        for entry in self._snapshot.entries:
            if type is not None and entry.type != type:
                continue
            if status is not None and entry.status != status:
                continue
            if impact is not None and entry.impact_on_decision != impact:
                continue
            if tags is not None:
                entry_tags = set(entry.tags)
                if not all(t in entry_tags for t in tags):
                    continue
            if allowed_profile is not None:
                if not self.is_capability_in_scope(allowed_profile, entry.id):
                    continue

            summary = self.lookup(entry.id)
            if summary is not None:
                results.append(summary)

        # LD-5 ordering: (type, -impact_rank, id)
        return sorted(
            results,
            key=lambda s: (
                s.type.value,
                -_IMPACT_RANK.get(s.impact_on_decision, 0),
                s.id,
            ),
        )

    def get_index_for_profile(self, profile_id: str) -> list[dict]:
        """Return LD-4 profile-scoped index slice.

        Only real, non-deprecated, profile-allowed entries.
        Each item: {"id": ..., "short_description": ..., "impact_on_decision": ...}
        """
        return _get_index_for_profile(self._snapshot, profile_id, self._descriptions)

    def is_capability_in_scope(self, profile: str, capability_id: str) -> bool:
        """Return True if profile is listed in the capability's allowed_agent_profiles.

        Sub-profile handling:
          - If hard_scoped=True: exact match required (no base-profile fallback).
          - If hard_scoped=False: profile base-id matches sub-profile slot.
        """
        entry = self._by_id.get(capability_id)
        if entry is None:
            return False

        allowed = entry.allowed_agent_profiles
        if not allowed:
            # Empty allowed_agent_profiles means no profile-level restriction
            # (only non-tool types use this; tools must explicitly list profiles)
            # Per plan: return False if profile is not listed
            return False

        if entry.hard_scoped:
            # Exact match only
            return profile in allowed

        # Soft-scoped: exact match OR base-id match
        base_caller = profile.split(".")[0]
        for listed in allowed:
            if listed == profile:
                return True
            base_listed = listed.split(".")[0]
            if base_listed == base_caller:
                return True

        return False

    def closest_ids(self, id: str, *, limit: int = 3) -> list[str]:
        """Return top-N Levenshtein-closest capability ids to the given string.

        Uses rapidfuzz for fast approximate string matching.
        Falls back to difflib.get_close_matches if rapidfuzz unavailable.
        """
        all_ids = [e.id for e in self._snapshot.entries]

        try:
            from rapidfuzz.distance import Levenshtein

            # Score: lower edit distance is better
            scored = sorted(
                all_ids,
                key=lambda candidate: Levenshtein.distance(id, candidate),
            )
        except ImportError:
            import difflib

            # difflib returns closest matches by similarity ratio
            scored = difflib.get_close_matches(id, all_ids, n=limit, cutoff=0.0)
            return scored[:limit]

        return scored[:limit]
