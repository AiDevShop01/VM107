"""
yaml_normalize.py — Deterministic bulk-edit of VM107 capability registry YAMLs.

Walks CAPABILITY_REGISTRY_ROOT (must be set in env — no fallback per project rule).
For each YAML, applies the LD-3 normalization pass:

  1. Status rename:
       shipped            -> real
       reserved_for_future-> stub
       planned            -> stub
       beta               -> experimental
     (Unknown values raise ValueError listing the file)

  2. Add impact_on_decision: TODO  (if missing)
     NOTE: "TODO" is a human-curation marker per CONTEXT.md / RESEARCH §Pitfall 2.
     Hand-curated HIGH/MEDIUM/LOW values are set in Task 2 — NOT auto-generated.

  3. Add allowed_agent_profiles: []  (if key absent)

  4. Add deprecated: false  (if key absent)

  5. Add hard_scoped: false  (if key absent)

  6. Add tags: []  (if key absent)

Usage:
    CAPABILITY_REGISTRY_ROOT=... python -m scripts.yaml_normalize          # dry-run
    CAPABILITY_REGISTRY_ROOT=... python -m scripts.yaml_normalize --apply  # write changes

Exit code: 0 on success; 1 if any YAML has an unrecognised status (requires human triage).

Formatting: Uses ruamel.yaml if available (preserves comments + key order best-effort),
falls back to yaml.safe_dump with sort_keys=False.
"""

from __future__ import annotations

import os
import pathlib
import sys
from typing import Any

# Try ruamel.yaml for comment-preserving round-trip
try:
    from ruamel.yaml import YAML as RuamelYAML  # type: ignore[import]
    from ruamel.yaml.comments import CommentedMap  # type: ignore[import]
    _HAS_RUAMEL = True
except ImportError:
    _HAS_RUAMEL = False

import yaml


# LD-3 locked status enum (CONTEXT.md decision #3)
LOCKED_STATUS: frozenset[str] = frozenset({"stub", "experimental", "real", "deprecated"})

# Legacy -> locked remap (RESEARCH Pitfall 2)
STATUS_REMAP: dict[str, str] = {
    "shipped": "real",
    "reserved_for_future": "stub",
    "planned": "stub",
    "beta": "experimental",
}

# Fields to default-add if absent
DEFAULT_FIELDS: dict[str, Any] = {
    "impact_on_decision": "TODO",
    "allowed_agent_profiles": [],
    "deprecated": False,
    "hard_scoped": False,
    "tags": [],
}


def get_registry_root() -> pathlib.Path:
    """Return registry root from env. Fails fast if not set (no fallback per project rule)."""
    raw = os.environ.get("CAPABILITY_REGISTRY_ROOT")
    if not raw:
        print(
            "ERROR: CAPABILITY_REGISTRY_ROOT environment variable is not set. "
            "Set it to the path of the registry directory (e.g., /path/to/VM107/registry). "
            "No fallback default per project convention.",
            file=sys.stderr,
        )
        sys.exit(1)
    root = pathlib.Path(raw)
    if not root.is_dir():
        print(
            f"ERROR: CAPABILITY_REGISTRY_ROOT={raw!r} is not an existing directory.",
            file=sys.stderr,
        )
        sys.exit(1)
    return root


def _load_ruamel(path: pathlib.Path):
    """Load with ruamel.yaml (comment-preserving). Returns (data, ryaml_instance)."""
    ryaml = RuamelYAML()
    ryaml.preserve_quotes = True
    # Use safe_load_all equivalent: read first document only
    # ruamel.yaml handles multi-doc via load_all
    docs = list(ryaml.load_all(path))
    first = next((d for d in docs if d is not None), None)
    return first, ryaml


def _dump_ruamel(data, path: pathlib.Path, ryaml) -> str:
    """Dump with ruamel.yaml to string. Returns serialized text."""
    import io
    buf = io.StringIO()
    ryaml.dump(data, buf)
    return buf.getvalue()


def _load_plain(path: pathlib.Path) -> dict[str, Any] | None:
    """Load first document with yaml.safe_load_all."""
    raw = path.read_text(encoding="utf-8")
    try:
        docs = list(yaml.safe_load_all(raw))
        first = next((d for d in docs if d is not None), None)
        return first
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML parse error in {path}: {exc}") from exc


def _dump_plain(data: dict[str, Any]) -> str:
    """Dump with yaml.safe_dump (no comment preservation)."""
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)


def normalize_data(
    data: dict[str, Any],
    path: pathlib.Path,
) -> tuple[dict[str, Any], list[str]]:
    """Apply LD-3 normalization to data dict. Returns (updated_data, list_of_changes).

    Raises ValueError if status is unrecognised (not in locked enum and not in remap map).
    """
    changes: list[str] = []

    # 1. Status rename
    status_raw = data.get("status")
    if status_raw in STATUS_REMAP:
        new_status = STATUS_REMAP[status_raw]
        data["status"] = new_status
        changes.append(f"status: {status_raw!r} -> {new_status!r}")
    elif status_raw in LOCKED_STATUS:
        pass  # already correct
    elif status_raw is None:
        # Missing status — default to stub
        data["status"] = "stub"
        changes.append("status: None -> 'stub' (was missing)")
    else:
        raise ValueError(
            f"Unrecognised status value {status_raw!r} in {path}. "
            f"Allowed locked values: {sorted(LOCKED_STATUS)}. "
            f"Legacy values that auto-remap: {sorted(STATUS_REMAP)}. "
            f"Human triage required."
        )

    # 2. Add missing fields
    for field, default_val in DEFAULT_FIELDS.items():
        if field not in data:
            data[field] = default_val
            changes.append(f"added {field}: {default_val!r}")

    return data, changes


def normalize_file(
    path: pathlib.Path,
    apply: bool,
    errors: list[tuple[pathlib.Path, str]],
) -> list[str]:
    """Normalize one YAML file. Returns list of changes (empty = no changes).

    On --apply, writes atomically (write to .tmp, then os.replace).
    """
    changes: list[str] = []

    # Prefer ruamel for comment preservation; fall back to plain yaml
    if _HAS_RUAMEL:
        try:
            data, ryaml = _load_ruamel(path)
        except Exception as exc:
            errors.append((path, f"load_error: {exc}"))
            return []
        if data is None:
            errors.append((path, "empty_document"))
            return []
        if not hasattr(data, "__setitem__"):
            errors.append((path, f"not_a_mapping: {type(data).__name__}"))
            return []
        try:
            data, changes = normalize_data(data, path)
        except ValueError as exc:
            errors.append((path, str(exc)))
            return []
        if changes and apply:
            tmp = path.with_suffix(".yaml.tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    ryaml.dump(data, f)
                os.replace(tmp, path)
            except Exception as exc:
                errors.append((path, f"write_error: {exc}"))
                if tmp.exists():
                    tmp.unlink()
    else:
        try:
            data = _load_plain(path)
        except ValueError as exc:
            errors.append((path, str(exc)))
            return []
        if data is None:
            errors.append((path, "empty_document"))
            return []
        if not isinstance(data, dict):
            errors.append((path, f"not_a_mapping: {type(data).__name__}"))
            return []
        try:
            data, changes = normalize_data(data, path)
        except ValueError as exc:
            errors.append((path, str(exc)))
            return []
        if changes and apply:
            serialized = _dump_plain(data)
            tmp = path.with_suffix(".yaml.tmp")
            try:
                tmp.write_text(serialized, encoding="utf-8")
                os.replace(tmp, path)
            except Exception as exc:
                errors.append((path, f"write_error: {exc}"))
                if tmp.exists():
                    tmp.unlink()

    return changes


def run_normalize(registry_root: pathlib.Path, apply: bool = False) -> int:
    """Walk registry and normalize all YAMLs. Returns exit code (0 on success, 1 on errors)."""
    yaml_paths = sorted(registry_root.rglob("*.yaml"))

    if not yaml_paths:
        print("WARNING: No YAML files found under CAPABILITY_REGISTRY_ROOT.", file=sys.stderr)
        return 0

    mode_label = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode_label}] Scanning {len(yaml_paths)} YAMLs under {registry_root}")
    if not apply:
        print("         Run with --apply to write changes atomically.\n")

    errors: list[tuple[pathlib.Path, str]] = []
    changed: list[tuple[pathlib.Path, list[str]]] = []
    unchanged: list[pathlib.Path] = []

    for path in yaml_paths:
        changes = normalize_file(path, apply=apply, errors=errors)
        rel = path.relative_to(registry_root)
        if changes:
            changed.append((rel, changes))
            verb = "WROTE" if apply else "WOULD CHANGE"
            print(f"  {verb}: {rel}")
            for c in changes:
                print(f"         - {c}")
        else:
            unchanged.append(rel)

    print()
    print(f"Summary ({mode_label}):")
    print(f"  Total YAMLs scanned: {len(yaml_paths)}")
    print(f"  Files changed:       {len(changed)}")
    print(f"  Files unchanged:     {len(unchanged)}")
    print(f"  Errors:              {len(errors)}")

    if errors:
        print("\nErrors (require human triage):")
        for p, msg in errors:
            print(f"  {p}: {msg}")
        return 1

    return 0


def main() -> None:
    args = sys.argv[1:]
    apply = "--apply" in args

    registry_root = get_registry_root()
    sys.exit(run_normalize(registry_root, apply=apply))


if __name__ == "__main__":
    main()
