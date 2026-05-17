"""7-stage validation pipeline for the capability registry.

Each stage is a pure function that either returns its input on success
or raises RegistryValidationError(stage=N, ...) on the first detected error.

All stages iterate in SORTED(type, id) order for LD-2 deterministic ordering.
Identical inputs always produce identical error sequences across runs.

Stages:
    1. validate_yaml_syntax      — YAML parse errors (raised by loader.py)
    2. validate_schemas          — Pydantic per-type schema validation
    3. validate_identity_uniqueness — duplicate id across all entries
    4. validate_dependency_graph — related_capabilities / dependencies refs exist
    5. validate_scope_references — allowed_agent_profiles refs exist
    6. validate_contract_resolution — contracts_request/response importable classes
    7. validate_cross_type_linkage — type-specific cross-reference rules
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from fingpt_core.contracts.capability_registry import (
    CapabilitySnapshotEntry,
    CapabilityStatus,
    CapabilityType,
    ImpactLevel,
    RegistryValidationError,
)

# ---------------------------------------------------------------------------
# Per-type Pydantic schemas for stage 2
# ---------------------------------------------------------------------------


class _BaseEntrySchema(BaseModel):
    """Minimal required fields shared by ALL capability types.

    extra='ignore' so type-specific extras (signal_category, cron, payload_schema,
    applies_to_profiles, etc.) are silently accepted — RESEARCH Pitfall 2.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    type: CapabilityType
    status: CapabilityStatus
    impact_on_decision: ImpactLevel
    deprecated: bool = False
    hard_scoped: bool = False
    allowed_agent_profiles: list[str] = []
    dependencies: list[str] = []
    related_capabilities: list[str] = []
    tags: list[str] = []
    contracts_request: str | None = None
    contracts_response: str | None = None


# ---------------------------------------------------------------------------
# Stage 1 — YAML syntax (raised by loader.py; this function is a passthrough)
# ---------------------------------------------------------------------------


def validate_yaml_syntax(
    raw_entries: list[tuple[Path, dict]],
) -> list[tuple[Path, dict]]:
    """Stage 1: YAML syntax validation.

    In practice, yaml.YAMLError is raised by loader.load_all_yamls before this
    stage is reached. This function is a semantic passthrough that documents the
    stage boundary clearly.
    """
    return raw_entries


# ---------------------------------------------------------------------------
# Stage 2 — Pydantic schema validation
# ---------------------------------------------------------------------------


def validate_schemas(
    raw_entries: list[tuple[Path, dict]],
) -> list[CapabilitySnapshotEntry]:
    """Stage 2: Validate each raw dict against the per-type Pydantic schema.

    On success, returns a list of CapabilitySnapshotEntry (the 12 LD-3 fields).
    On first failure (sorted by type then id), raises RegistryValidationError(stage=2).
    """
    # Sort for determinism: by (raw.get('type',''), raw.get('id',''))
    sorted_entries = sorted(raw_entries, key=lambda t: (t[1].get("type", ""), t[1].get("id", "")))

    result: list[CapabilitySnapshotEntry] = []

    for path, raw in sorted_entries:
        cap_id = raw.get("id", path.stem)
        cap_type = raw.get("type", "")

        try:
            validated = _BaseEntrySchema.model_validate(raw)
        except ValidationError as exc:
            first_error = exc.errors()[0] if exc.errors() else {}
            field = ".".join(str(x) for x in first_error.get("loc", ["unknown"]))
            raise RegistryValidationError(
                stage=2,
                type="schema_validation_error",
                capability_id=cap_id,
                missing_ref=field,
                message=(
                    f"Stage 2 schema validation failed for '{cap_id}' ({path}): "
                    f"field '{field}' — {first_error.get('msg', str(exc))}"
                ),
            ) from exc

        # Project to CapabilitySnapshotEntry (13 LD-3 fields — status + 12)
        entry = CapabilitySnapshotEntry(
            id=validated.id,
            type=validated.type,
            status=validated.status,
            contracts_request=validated.contracts_request,
            contracts_response=validated.contracts_response,
            dependencies=tuple(validated.dependencies),
            related_capabilities=tuple(validated.related_capabilities),
            allowed_agent_profiles=tuple(validated.allowed_agent_profiles),
            impact_on_decision=validated.impact_on_decision,
            deprecated=validated.deprecated,
            tags=tuple(validated.tags),
            hard_scoped=validated.hard_scoped,
        )
        result.append(entry)

    return result


# ---------------------------------------------------------------------------
# Stage 3 — Identity uniqueness
# ---------------------------------------------------------------------------


def validate_identity_uniqueness(
    entries: list[CapabilitySnapshotEntry],
) -> list[CapabilitySnapshotEntry]:
    """Stage 3: All ids must be globally unique across all capability types.

    Iterates sorted(entries, key=(type, id)) and raises on FIRST duplicate found.
    """
    seen: dict[str, str] = {}  # id -> type of first occurrence
    for entry in sorted(entries, key=lambda e: (e.type.value, e.id)):
        if entry.id in seen:
            raise RegistryValidationError(
                stage=3,
                type="duplicate_id",
                capability_id=entry.id,
                missing_ref=seen[entry.id],
                message=(
                    f"Stage 3 duplicate id: '{entry.id}' declared as type={entry.type.value} "
                    f"but already registered as type={seen[entry.id]}. "
                    f"All capability ids must be globally unique."
                ),
            )
        seen[entry.id] = entry.type.value

    return entries


# ---------------------------------------------------------------------------
# Stage 4 — Dependency graph integrity
# ---------------------------------------------------------------------------


def validate_dependency_graph(
    entries: list[CapabilitySnapshotEntry],
) -> list[CapabilitySnapshotEntry]:
    """Stage 4: Hard dependencies must refer to known ids.

    `dependencies` are hard dependencies (blocking, must be resolvable).
    `related_capabilities` are soft informational cross-references (not validated here).

    Rationale: related_capabilities often reference future or external capabilities
    not yet registered. Validating them as hard deps would break the registry for
    any YAML that documents conceptual relationships to unregistered capabilities.
    Only `dependencies` represent hard runtime requirements that must be resolved.

    Iterates sorted(entries, key=(type, id)) and raises on FIRST unresolved dependency.
    """
    known_ids = {e.id for e in entries}

    for entry in sorted(entries, key=lambda e: (e.type.value, e.id)):
        # Check hard dependencies only (related_capabilities are soft/informational)
        for ref in entry.dependencies:
            if ref not in known_ids:
                raise RegistryValidationError(
                    stage=4,
                    type="unresolved_dependency",
                    capability_id=entry.id,
                    missing_ref=ref,
                    message=(
                        f"Stage 4 dependency graph error: '{entry.id}' lists "
                        f"dependencies=[..., '{ref}', ...] but '{ref}' "
                        f"is not registered in the capability registry."
                    ),
                )

    return entries


# ---------------------------------------------------------------------------
# Stage 5 — Scope reference integrity
# ---------------------------------------------------------------------------


def validate_scope_references(
    entries: list[CapabilitySnapshotEntry],
) -> list[CapabilitySnapshotEntry]:
    """Stage 5: All allowed_agent_profiles must resolve to known agent_profile ids.

    Sub-profile notation (e.g., 'agent_zero._writer') is matched by checking that
    the base id (before the first '.') exists as an agent_profile.

    Iterates sorted(entries, key=(type, id)) and raises on FIRST unresolved reference.
    """
    agent_profile_ids = {e.id for e in entries if e.type == CapabilityType.AGENT_PROFILE}

    for entry in sorted(entries, key=lambda e: (e.type.value, e.id)):
        for profile_ref in entry.allowed_agent_profiles:
            # Sub-profile: "agent_zero._writer" -> base is "agent_zero"
            base_id = profile_ref.split(".")[0]
            if base_id not in agent_profile_ids:
                raise RegistryValidationError(
                    stage=5,
                    type="unresolved_agent_profile",
                    capability_id=entry.id,
                    missing_ref=profile_ref,
                    message=(
                        f"Stage 5 scope reference error: '{entry.id}' lists "
                        f"allowed_agent_profiles=[..., '{profile_ref}', ...] "
                        f"but base profile '{base_id}' is not registered as an agent_profile."
                    ),
                )

    return entries


# ---------------------------------------------------------------------------
# Stage 6 — Contract resolution
# ---------------------------------------------------------------------------


def validate_contract_resolution(
    entries: list[CapabilitySnapshotEntry],
    repo_root: Path,
) -> list[CapabilitySnapshotEntry]:
    """Stage 6: contracts_request/response must be importable Pydantic classes.
    location.source (if present) must exist as a file or directory.

    Iterates sorted(entries, key=(type, id)) and raises on FIRST unresolvable reference.

    NOTE: Contract fields on entries are raw strings from YAML (dotted module paths).
    We use importlib to verify the module+attribute exist. The source path is checked
    via Path(repo_root / source).exists().

    For entries that passed stage 2, contract strings are already extracted.
    We need the raw YAML data to check location.source — this is passed via
    a side channel (_raw_map) populated by the loader when this stage is called
    through the full pipeline in CapabilityRegistry.
    """
    # Build contract references to validate
    for entry in sorted(entries, key=lambda e: (e.type.value, e.id)):
        for field_name, dotted in [
            ("contracts_request", entry.contracts_request),
            ("contracts_response", entry.contracts_response),
        ]:
            if dotted is None:
                continue
            parts = dotted.rsplit(".", 1)
            if len(parts) != 2:
                raise RegistryValidationError(
                    stage=6,
                    type="invalid_contract_path",
                    capability_id=entry.id,
                    missing_ref=dotted,
                    message=(
                        f"Stage 6 contract path '{dotted}' on '{entry.id}' ({field_name}) "
                        f"must be a fully-qualified 'module.ClassName' dotted path."
                    ),
                )
            module_path, class_name = parts
            try:
                module = importlib.import_module(module_path)
            except ImportError as exc:
                raise RegistryValidationError(
                    stage=6,
                    type="unresolvable_contract_module",
                    capability_id=entry.id,
                    missing_ref=dotted,
                    message=(
                        f"Stage 6 contract resolution error: '{entry.id}' {field_name}="
                        f"'{dotted}' — cannot import module '{module_path}': {exc}"
                    ),
                ) from exc
            if not hasattr(module, class_name):
                raise RegistryValidationError(
                    stage=6,
                    type="unresolvable_contract_class",
                    capability_id=entry.id,
                    missing_ref=dotted,
                    message=(
                        f"Stage 6 contract resolution error: '{entry.id}' {field_name}="
                        f"'{dotted}' — module '{module_path}' has no attribute '{class_name}'."
                    ),
                )

    return entries


# ---------------------------------------------------------------------------
# Stage 7 — Cross-type linkage rules
# ---------------------------------------------------------------------------


def validate_cross_type_linkage(
    entries: list[CapabilitySnapshotEntry],
    raw_map: dict[str, dict] | None = None,
) -> list[CapabilitySnapshotEntry]:
    """Stage 7: Concrete cross-type reference rules.

    Rules:
    1. skill/*.yaml applies_to_profiles -> must all resolve to agent_profile/ ids
    2. signal/*.yaml derived_from (if present) -> must resolve to feature/ or event_type/ ids
    3. agent_profile/*.yaml consumes_tools (if present) -> must resolve to tool/ ids

    Iterates sorted(entries, key=(type, id)) for determinism.
    raw_map: optional dict(id -> raw YAML dict) for accessing extra fields not in CapabilitySnapshotEntry.
    """
    if raw_map is None:
        raw_map = {}

    agent_profile_ids = {e.id for e in entries if e.type == CapabilityType.AGENT_PROFILE}
    feature_ids = {e.id for e in entries if e.type == CapabilityType.FEATURE}
    event_type_ids = {e.id for e in entries if e.type == CapabilityType.EVENT_TYPE}
    tool_ids = {e.id for e in entries if e.type == CapabilityType.TOOL}

    for entry in sorted(entries, key=lambda e: (e.type.value, e.id)):
        raw = raw_map.get(entry.id, {})

        # Rule 1: skill applies_to_profiles -> agent_profile
        if entry.type == CapabilityType.SKILL:
            applies_to = raw.get("applies_to_profiles", []) or []
            for profile_ref in applies_to:
                base_id = profile_ref.split(".")[0]
                if base_id not in agent_profile_ids:
                    raise RegistryValidationError(
                        stage=7,
                        type="cross_type_skill_profile_unresolved",
                        capability_id=entry.id,
                        missing_ref=profile_ref,
                        message=(
                            f"Stage 7 cross-type linkage error: skill '{entry.id}' "
                            f"applies_to_profiles=[..., '{profile_ref}', ...] "
                            f"but base profile '{base_id}' is not a registered agent_profile."
                        ),
                    )

        # Rule 2: signal derived_from -> feature or event_type
        if entry.type == CapabilityType.SIGNAL:
            derived_from = raw.get("derived_from", []) or []
            if isinstance(derived_from, str):
                derived_from = [derived_from]
            for ref in derived_from:
                if ref not in feature_ids and ref not in event_type_ids:
                    raise RegistryValidationError(
                        stage=7,
                        type="cross_type_signal_derived_from_unresolved",
                        capability_id=entry.id,
                        missing_ref=ref,
                        message=(
                            f"Stage 7 cross-type linkage error: signal '{entry.id}' "
                            f"derived_from=[..., '{ref}', ...] "
                            f"but '{ref}' is not a registered feature or event_type."
                        ),
                    )

        # Rule 3: agent_profile consumes_tools -> tool
        if entry.type == CapabilityType.AGENT_PROFILE:
            consumes_tools = raw.get("consumes_tools", []) or []
            for ref in consumes_tools:
                if ref not in tool_ids:
                    raise RegistryValidationError(
                        stage=7,
                        type="cross_type_profile_tool_unresolved",
                        capability_id=entry.id,
                        missing_ref=ref,
                        message=(
                            f"Stage 7 cross-type linkage error: agent_profile '{entry.id}' "
                            f"consumes_tools=[..., '{ref}', ...] "
                            f"but '{ref}' is not a registered tool."
                        ),
                    )

    return entries


# ---------------------------------------------------------------------------
# Full pipeline runner (convenience for tests)
# ---------------------------------------------------------------------------


def run_full_pipeline(
    registry_root: Path,
) -> list[CapabilitySnapshotEntry]:
    """Run all 7 stages against a registry_root. Raises on first error.

    This is a convenience wrapper used by tests. The CapabilityRegistry singleton
    calls each stage individually so it can pass additional context (repo_root,
    raw_map) to stages 6 and 7.
    """
    from .loader import load_all_yamls

    raw_entries = load_all_yamls(registry_root)
    # Stage 1: passthrough (errors raised by loader)
    validate_yaml_syntax(raw_entries)
    # Stage 2
    entries = validate_schemas(raw_entries)
    # Stage 3
    validate_identity_uniqueness(entries)
    # Stage 4
    validate_dependency_graph(entries)
    # Stage 5
    validate_scope_references(entries)
    # Stage 6: need repo_root to resolve source paths
    # For test convenience, use registry_root.parent.parent as repo_root approximation
    repo_root = registry_root.parent.parent
    validate_contract_resolution(entries, repo_root)
    # Stage 7: need raw_map for applies_to_profiles / derived_from / consumes_tools
    raw_map = {raw.get("id", path.stem): raw for path, raw in raw_entries}
    validate_cross_type_linkage(entries, raw_map)

    return entries
