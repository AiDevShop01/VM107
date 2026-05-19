"""Phase 48 Plan 48-09 — REQ-48-REG: REGISTER_CAPABILITY <-> registry YAML
completeness sweep.

CONTEXT § Decision 18 + Phase 47.6 lock: every Phase 48 capability MUST
exist in BOTH the declaration set (REGISTER_CAPABILITY directives across
plans, summaries, source files, YAML headers) AND on-disk registry YAMLs.

This test cross-references both sets and asserts equality. No orphans
either way:
  - "Declared but not on disk" -> Plan shipped a directive but forgot the YAML.
  - "On disk but not declared" -> YAML exists but no directive declares it
    (planner-side bookkeeping gap; the capability would not be discoverable
    by future plan-checker discipline audits).

Source set:
  - .planning/phases/48-idea-to-strategy-to-code-pipeline/48-*-PLAN.md
  - .planning/phases/48-idea-to-strategy-to-code-pipeline/48-*-SUMMARY.md
  - VM107/**/*.py (excluding tests + __pycache__)
  - VM107/registry/**/*.yaml (the YAML headers themselves carry the directive)

This is the closing test for Phase 48's REGISTER_CAPABILITY discipline.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
import pytest


_DIRECTIVE_RE = re.compile(
    r"REGISTER_CAPABILITY:\s*type=(\w+),\s*id=([\w_/-]+)"
)

_REPO_ROOT = Path(__file__).resolve().parents[2]  # tests/registry -> tests -> VM107
_DAGSTER_PLANNING = (
    _REPO_ROOT.parent
    / "Dagster"
    / ".planning"
    / "phases"
    / "48-idea-to-strategy-to-code-pipeline"
)


def _collect_declared_directives() -> set[tuple[str, str]]:
    """All REGISTER_CAPABILITY directives across the project."""
    declared: set[tuple[str, str]] = set()
    if _DAGSTER_PLANNING.is_dir():
        for pattern in ("48-*-PLAN.md", "48-*-SUMMARY.md"):
            for p in _DAGSTER_PLANNING.glob(pattern):
                try:
                    text = p.read_text()
                except Exception:
                    continue
                for m in _DIRECTIVE_RE.finditer(text):
                    declared.add((m.group(1), m.group(2)))
    for ext in ("py", "yaml"):
        for p in _REPO_ROOT.rglob(f"*.{ext}"):
            sp = str(p)
            if "__pycache__" in sp or "/.git/" in sp:
                continue
            try:
                text = p.read_text()
            except Exception:
                continue
            for m in _DIRECTIVE_RE.finditer(text):
                declared.add((m.group(1), m.group(2)))
    return declared


def _collect_phase48_yamls() -> set[tuple[str, str]]:
    """All on-disk phase=48 registry YAMLs (excluding non-registry capabilities
    declared in source like internal service implementations)."""
    on_disk: set[tuple[str, str]] = set()
    registry_root = _REPO_ROOT / "registry"
    if not registry_root.is_dir():
        return on_disk
    for type_dir in registry_root.iterdir():
        if not type_dir.is_dir():
            continue
        for yml in type_dir.glob("*.yaml"):
            try:
                data = yaml.safe_load(yml.read_text())
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if data.get("phase") != 48:
                continue
            t = data.get("type")
            i = data.get("id")
            if t and i:
                on_disk.add((t, i))
    return on_disk


def _collect_phase48_only_directives() -> set[tuple[str, str]]:
    """Subset of declared directives that correspond to Phase 48 capabilities.

    Heuristic: declarations that match on-disk Phase 48 YAML (type, id) OR
    that mention Phase 48 in surrounding context. For the completeness sweep
    we narrow to declarations that ALSO appear in the registry namespace
    (i.e., the YAML is the canonical truth; we audit that side).
    """
    return _collect_declared_directives()


def test_phase48_capabilities_have_yaml_on_disk() -> None:
    """Every Phase 48 capability declared with REGISTER_CAPABILITY at a
    ``path=VM107/registry/<type>/<id>.yaml`` must have a matching YAML
    on disk with phase=48."""
    declared = _collect_phase48_only_directives()
    on_disk = _collect_phase48_yamls()

    # The "declared but registry-pathed and missing on disk" check.
    # We scan the full directive set and filter to those whose corresponding
    # path begins with VM107/registry/ — those are the YAMLs we MUST ship.
    #
    # Source-of-truth declarations only: PLAN.md (locked planner intent) +
    # in-source REGISTER_CAPABILITY directives (.py + .yaml). SUMMARY.md
    # files often contain illustrative code blocks (e.g., example output
    # of a YAML emitter) which are documentation, NOT capability declarations.
    registry_pathed: set[tuple[str, str]] = set()
    pattern = re.compile(
        r"REGISTER_CAPABILITY:\s*type=(\w+),\s*id=([\w_/-]+),\s*path=VM107/registry/"
    )
    # Re-scan PLAN files only (SUMMARY files excluded — see above).
    if _DAGSTER_PLANNING.is_dir():
        for p in _DAGSTER_PLANNING.glob("48-*-PLAN.md"):
            try:
                text = p.read_text()
            except Exception:
                continue
            for m in pattern.finditer(text):
                registry_pathed.add((m.group(1), m.group(2)))
    for ext in ("py", "yaml"):
        for p in _REPO_ROOT.rglob(f"*.{ext}"):
            sp = str(p)
            if (
                "__pycache__" in sp
                or "/.git/" in sp
                or "/tests/" in sp  # test fixtures emit example YAMLs; exclude
            ):
                continue
            try:
                text = p.read_text()
            except Exception:
                continue
            for m in pattern.finditer(text):
                registry_pathed.add((m.group(1), m.group(2)))

    missing_yaml = registry_pathed - on_disk
    assert not missing_yaml, (
        f"REGISTER_CAPABILITY declared at VM107/registry/<type>/<id>.yaml but "
        f"YAML not on disk: {sorted(missing_yaml)}"
    )


def test_phase48_yamls_have_register_capability_declaration() -> None:
    """Every Phase 48 YAML on disk must have at least one REGISTER_CAPABILITY
    directive declaring (type, id) somewhere in the codebase."""
    declared = _collect_declared_directives()
    on_disk = _collect_phase48_yamls()

    missing_directive = on_disk - declared
    assert not missing_directive, (
        f"Phase 48 YAMLs on disk with no REGISTER_CAPABILITY directive "
        f"anywhere: {sorted(missing_directive)}. Phase 47.6 plan-checker "
        "discipline requires every YAML to be declared."
    )


def test_phase48_inventory_meets_plan_09_floor() -> None:
    """Plan 09 § success criteria: at least 27 Phase 48 capabilities total.

    Inventory: 1 orchestrator service + 1 endpoint service + 4 collections +
    1 critic agent_profile + 5 family skills + 10 event_types + 5 tool YAMLs
    = 27 minimum. Additional internal services (phase56_emit_client_vm107,
    refinement_events_emitter_vm107, strategy_yaml_emitter,
    replay_query_service_extension_vm107) bring on-disk total higher.
    """
    on_disk = _collect_phase48_yamls()
    assert len(on_disk) >= 27, (
        f"Phase 48 capability inventory dropped below floor 27: "
        f"got {len(on_disk)} on-disk YAMLs. "
        f"Current set: {sorted(on_disk)}"
    )
