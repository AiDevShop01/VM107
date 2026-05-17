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

    for yaml_path in sorted(registry_root.rglob("*.yaml")):
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
