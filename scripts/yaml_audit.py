"""
yaml_audit.py — Read-only audit of the VM107 capability registry YAML files.

Walks CAPABILITY_REGISTRY_ROOT (must be set in env — no fallback per project rule).
For each YAML, checks schema-drift fields against the LD-3 locked schema.

Usage:
    CAPABILITY_REGISTRY_ROOT=/path/to/registry python -m scripts.yaml_audit
    CAPABILITY_REGISTRY_ROOT=/path/to/registry python -m scripts.yaml_audit --csv

Exit code: 0 always (read-only audit).

LD-3 locked status enum: stub | experimental | real | deprecated
Legacy values that need remap: shipped, reserved_for_future, planned, beta
"""

from __future__ import annotations

import csv
import os
import pathlib
import sys
from typing import Any

import yaml

# LD-3 locked status enum (CONTEXT.md decision #3, RESEARCH Pitfall 2)
LOCKED_STATUS: frozenset[str] = frozenset({"stub", "experimental", "real", "deprecated"})
LOCKED_IMPACT: frozenset[str] = frozenset({"HIGH", "MEDIUM", "LOW"})

# Legacy status values that must be remapped
LEGACY_STATUS_REMAP: dict[str, str] = {
    "shipped": "real",
    "reserved_for_future": "stub",
    "planned": "stub",
    "beta": "experimental",
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


def load_first_document(path: pathlib.Path) -> tuple[dict[str, Any] | None, str | None]:
    """Load the first YAML document from path. Returns (data, error_msg).

    Some YAMLs have a trailing '---' which causes yaml.safe_load to raise
    (multi-document stream). We handle that by using safe_load_all and taking
    only the first document.
    """
    raw = path.read_text(encoding="utf-8")
    try:
        docs = list(yaml.safe_load_all(raw))
        first = next((d for d in docs if d is not None), None)
        if first is None:
            return None, "empty_document"
        if not isinstance(first, dict):
            return None, f"not_a_mapping: {type(first).__name__}"
        return first, None
    except yaml.YAMLError as exc:
        return None, f"yaml_error: {exc}"


def audit_yaml(path: pathlib.Path, registry_root: pathlib.Path) -> dict[str, Any]:
    """Audit a single YAML file against LD-3 schema requirements."""
    rel = path.relative_to(registry_root)
    parts = rel.parts
    type_folder = parts[0] if len(parts) >= 2 else "unknown"

    row: dict[str, Any] = {
        "path": str(rel),
        "type_folder": type_folder,
        "id": None,
        "status_raw": None,
        "status_needs_remap": False,
        "status_in_locked_enum": False,
        "impact_on_decision_present": False,
        "impact_on_decision_value": None,
        "impact_valid": False,
        "allowed_agent_profiles_present": False,
        "allowed_agent_profiles_count": 0,
        "dependencies_present": False,
        "related_capabilities_present": False,
        "tags_freeform_count": 0,
        "contracts_request_present": False,
        "contracts_response_present": False,
        "hard_scoped_present": False,
        "deprecated_present": False,
        "skill_md_path_present_if_skill": None,
        "skill_md_path_resolves": None,
        "parse_error": None,
    }

    data, err = load_first_document(path)
    if err:
        row["parse_error"] = err
        return row

    row["id"] = data.get("id")
    status_raw = data.get("status")
    row["status_raw"] = status_raw
    row["status_needs_remap"] = status_raw in LEGACY_STATUS_REMAP
    row["status_in_locked_enum"] = status_raw in LOCKED_STATUS

    impact = data.get("impact_on_decision")
    row["impact_on_decision_present"] = "impact_on_decision" in data
    row["impact_on_decision_value"] = impact
    row["impact_valid"] = impact in LOCKED_IMPACT

    row["allowed_agent_profiles_present"] = "allowed_agent_profiles" in data
    profiles = data.get("allowed_agent_profiles") or []
    row["allowed_agent_profiles_count"] = len(profiles) if isinstance(profiles, list) else 0

    row["dependencies_present"] = "dependencies" in data
    row["related_capabilities_present"] = "related_capabilities" in data

    tags = data.get("tags") or []
    row["tags_freeform_count"] = len(tags) if isinstance(tags, list) else 0

    # contracts may be nested under location.contracts or at top level
    loc = data.get("location") or {}
    contracts = loc.get("contracts") if isinstance(loc, dict) else {}
    if not contracts:
        contracts = data.get("contracts") or {}
    row["contracts_request_present"] = bool(
        contracts.get("request") if isinstance(contracts, dict) else False
    )
    row["contracts_response_present"] = bool(
        contracts.get("response") if isinstance(contracts, dict) else False
    )

    row["hard_scoped_present"] = "hard_scoped" in data
    row["deprecated_present"] = "deprecated" in data

    # Skill-specific: skill_md_path
    if type_folder == "skill":
        has_path = "skill_md_path" in data
        row["skill_md_path_present_if_skill"] = has_path
        if has_path:
            skill_path = data.get("skill_md_path")
            if skill_path:
                # Resolve relative to VM107 root (parent of registry root's parent)
                vm107_root = registry_root.parent
                resolved = vm107_root / skill_path
                row["skill_md_path_resolves"] = resolved.exists()
            else:
                row["skill_md_path_resolves"] = False
        else:
            row["skill_md_path_resolves"] = False

    return row


def run_audit(registry_root: pathlib.Path, csv_output: bool = False) -> int:
    """Walk registry, audit all YAMLs, print results. Returns exit code (always 0)."""
    yaml_paths = sorted(registry_root.rglob("*.yaml"))

    if not yaml_paths:
        print("WARNING: No YAML files found under CAPABILITY_REGISTRY_ROOT.", file=sys.stderr)
        return 0

    rows = [audit_yaml(p, registry_root) for p in yaml_paths]

    if csv_output:
        fieldnames = list(rows[0].keys()) if rows else []
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    else:
        # Human-readable tabular output
        col_width = 55
        header = (
            f"{'path':<{col_width}} {'status_raw':<22} {'remap?':<8} "
            f"{'impact_ok?':<12} {'profiles?':<10} {'parse_err?':<30}"
        )
        print(header)
        print("-" * len(header))
        for row in rows:
            path_str = row["path"]
            if len(path_str) > col_width:
                path_str = "..." + path_str[-(col_width - 3):]
            remap = "YES" if row["status_needs_remap"] else "no"
            impact_ok = "YES" if row["impact_valid"] else ("todo" if row["impact_on_decision_value"] == "TODO" else "MISSING")
            profiles = "YES" if row["allowed_agent_profiles_present"] else "MISSING"
            parse_err = row["parse_error"] or ""
            if len(parse_err) > 28:
                parse_err = parse_err[:28] + ".."
            print(
                f"{path_str:<{col_width}} {str(row['status_raw']):<22} {remap:<8} "
                f"{impact_ok:<12} {profiles:<10} {parse_err:<30}"
            )

    # Summary counts
    total = len(rows)
    parse_errors = sum(1 for r in rows if r["parse_error"])
    remap_status = sum(1 for r in rows if r["status_needs_remap"])
    missing_impact = sum(1 for r in rows if not r["impact_valid"])
    missing_allowed_profiles = sum(1 for r in rows if not r["allowed_agent_profiles_present"])
    missing_deprecated = sum(1 for r in rows if not r["deprecated_present"])
    missing_hard_scoped = sum(1 for r in rows if not r["hard_scoped_present"])
    skill_rows = [r for r in rows if r["type_folder"] == "skill"]
    missing_skill_md = sum(1 for r in skill_rows if not r["skill_md_path_present_if_skill"])
    unresolvable_skill_md = sum(
        1 for r in skill_rows
        if r["skill_md_path_present_if_skill"] and not r["skill_md_path_resolves"]
    )

    print()
    print(f"Total: {total}")
    print(f"  parse_errors:              {parse_errors}")
    print(f"  remap_status:              {remap_status}  (legacy: shipped/reserved_for_future/planned/beta)")
    print(f"  missing_impact:            {missing_impact}  (missing or invalid impact_on_decision)")
    print(f"  missing_allowed_profiles:  {missing_allowed_profiles}  (key absent entirely)")
    print(f"  missing_deprecated:        {missing_deprecated}")
    print(f"  missing_hard_scoped:       {missing_hard_scoped}")
    if skill_rows:
        print(f"  skills total:              {len(skill_rows)}")
        print(f"  missing_skill_md_path:     {missing_skill_md}")
        print(f"  unresolvable_skill_md:     {unresolvable_skill_md}")

    return 0


def main() -> None:
    args = sys.argv[1:]
    csv_output = "--csv" in args

    registry_root = get_registry_root()
    sys.exit(run_audit(registry_root, csv_output=csv_output))


if __name__ == "__main__":
    main()
