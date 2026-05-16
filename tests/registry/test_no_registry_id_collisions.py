"""Phase 62-03 Task 2 — test_no_registry_id_collisions.py

Regression guard for Pitfall 9 (namespace collision): no duplicate registry `id`
values across any two YAML files in different subdirs of registry/.

Walks all VM107/registry/*/*.yaml files, extracts their `id` fields,
and asserts no two files have the same `id` (regardless of subdir).

This test MUST remain green after every new registry YAML is added.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

REGISTRY_ROOT = _VM107_ROOT / "registry"


def test_no_registry_id_collisions():
    """No two registry YAML files have the same 'id' field (Pitfall 9 regression guard, RG-13).

    Walks all registry/*/*.yaml files and asserts that each `id` appears exactly once.
    """
    assert REGISTRY_ROOT.is_dir(), f"registry/ dir missing at {REGISTRY_ROOT}"

    id_to_files: dict[str, list[Path]] = {}

    for subdir in sorted(REGISTRY_ROOT.iterdir()):
        if not subdir.is_dir():
            continue
        for yaml_file in sorted(subdir.glob("*.yaml")):
            try:
                data = yaml.safe_load(yaml_file.read_text())
            except yaml.YAMLError:
                continue  # Malformed YAML — registry YAML tests catch these
            if not isinstance(data, dict):
                continue
            registry_id = data.get("id")
            if registry_id is None:
                continue
            registry_id = str(registry_id)
            id_to_files.setdefault(registry_id, []).append(yaml_file)

    # Build collision report
    collisions = {
        rid: files
        for rid, files in id_to_files.items()
        if len(files) > 1
    }

    if collisions:
        collision_report = "\n".join(
            f"  id={rid!r} appears in:\n" + "\n".join(f"    {f}" for f in files)
            for rid, files in sorted(collisions.items())
        )
        raise AssertionError(
            f"Registry ID collisions detected (Pitfall 9 — must be unique across all subdirs):\n"
            f"{collision_report}\n\n"
            f"Fix: ensure each registry YAML has a globally unique 'id' field."
        )
