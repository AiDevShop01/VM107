"""Registry YAML loader — pure reading, no validation logic.

Reads every *.yaml file under registry_root (recursively, sorted order for
LD-2 determinism) and returns raw Python dicts paired with their source paths.

Raises RegistryValidationError(stage=1) on YAML parse errors so the caller
treats parse failures consistently as stage-1 failures.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from fingpt_core.contracts.capability_registry import RegistryValidationError


def load_all_yamls(registry_root: Path) -> list[tuple[Path, dict]]:
    """Load every *.yaml under registry_root, sorted for determinism.

    Args:
        registry_root: Root directory containing capability YAML files.

    Returns:
        Sorted list of (path, raw_dict) tuples.

    Raises:
        RegistryValidationError(stage=1): If any file contains invalid YAML.
    """
    results: list[tuple[Path, dict]] = []

    # Meta/navigation files — not capability entries; must not be validated by Stage 2.
    # registry_index.yaml is a human-navigation index (created Phase 89 Plan 08).
    # _schema.yaml files are schema documentation, not registered capabilities.
    _META_FILENAMES: frozenset[str] = frozenset({"registry_index.yaml", "_schema.yaml"})

    for yaml_path in sorted(registry_root.rglob("*.yaml")):
        # Skip _reserved subdirectories — they are namespace claims, not registered
        # capabilities. Their type field (e.g., event_type_reserved_namespace) is
        # intentionally outside the 16 locked CapabilityType values.
        if "_reserved" in yaml_path.parts:
            continue

        # Skip meta/navigation files that live at the registry root but are not
        # capability entries. These files do not carry id/type/status/impact_on_decision
        # fields and must not be passed to Stage 2 Pydantic validation.
        # Added Phase 89 Plan 09: registry_index.yaml (created in Plan 08) was being
        # picked up by the rglob and failing Stage 2 with "field 'id' — Field required".
        if yaml_path.name in _META_FILENAMES:
            continue

        # Skip leading-underscore scaffold/template files (e.g. _TEMPLATE.yaml,
        # landed 168-03). By documented convention these are grammar-by-example
        # scaffolds, NOT live capabilities — the file's own header states "It is
        # NOT loaded as a live profile (leading-underscore filename)" and Plan
        # 169-05 established the same `_`-prefix skip in the initialize.py boot
        # validator. Without this skip, _TEMPLATE.yaml's non-enum `status: template`
        # fails Stage 2 and bricks CapabilityRegistry.initialize() at boot. Fix
        # applied Phase 169 Plan 06 (Rule-3 blocking; closes the latent boot-brick).
        if yaml_path.name.startswith("_"):
            continue
        try:
            with yaml_path.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise RegistryValidationError(
                stage=1,
                type="yaml_syntax_error",
                capability_id=yaml_path.stem,
                missing_ref=str(yaml_path),
                message=f"YAML parse error in {yaml_path}: {exc}",
            ) from exc

        # safe_load returns None for empty files — skip them
        if raw is None:
            continue

        if not isinstance(raw, dict):
            raise RegistryValidationError(
                stage=1,
                type="yaml_not_mapping",
                capability_id=yaml_path.stem,
                missing_ref=str(yaml_path),
                message=f"YAML root must be a mapping (dict), got {type(raw).__name__} in {yaml_path}",
            )

        results.append((yaml_path, raw))

    return results
