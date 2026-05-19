"""Phase 48 Plan 48-09 — REQ-48-REG: every Phase 48 capability has a
REGISTER_CAPABILITY directive declared somewhere in the codebase.

Per Phase 47.6 plan-checker discipline: every new capability shipped under
a Phase 48 plan MUST declare a REGISTER_CAPABILITY directive somewhere in
the codebase — either in:
  - The plan text itself (.planning/phases/48-*/48-NN-PLAN.md)
  - A source file (.py) at the path it lives at
  - A YAML file (.yaml) at the path it lives at
  - A SUMMARY file (.planning/phases/48-*/48-NN-SUMMARY.md)

This meta-test parses every Phase 48 deliverable on disk (the YAML registry
+ in-source REGISTER_CAPABILITY directives) and asserts that for each new
YAML in registry/<type>/<id>.yaml with phase=48, at least one
REGISTER_CAPABILITY directive declaring (type, id) appears somewhere in:
  - .planning/phases/48-idea-to-strategy-to-code-pipeline/48-*-PLAN.md
  - .planning/phases/48-idea-to-strategy-to-code-pipeline/48-*-SUMMARY.md
  - VM107/**/*.py (excluding tests + __pycache__)
  - VM107/registry/**/*.yaml

This is the planner-side counterpart to test_phase48_register_capability_
completeness.py (which audits registry contents vs source declarations).
The two tests together prove the declaration discipline is closed-loop.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
import pytest


_DIRECTIVE_RE = re.compile(
    r"REGISTER_CAPABILITY:\s*type=(\w+),\s*id=([\w_/-]+)"
)

# Where to look for REGISTER_CAPABILITY directive declarations.
_REPO_ROOT = Path(__file__).resolve().parents[2]  # tests/planning -> tests -> VM107
_DAGSTER_PLANNING = (
    _REPO_ROOT.parent
    / "Dagster"
    / ".planning"
    / "phases"
    / "48-idea-to-strategy-to-code-pipeline"
)


def _collect_declared_directives() -> set[tuple[str, str]]:
    """Walk all eligible files and collect (type, id) tuples from
    REGISTER_CAPABILITY directives."""
    declared: set[tuple[str, str]] = set()

    # 1. Phase 48 plans + summaries.
    if _DAGSTER_PLANNING.is_dir():
        for pattern in ("48-*-PLAN.md", "48-*-SUMMARY.md"):
            for p in _DAGSTER_PLANNING.glob(pattern):
                try:
                    text = p.read_text()
                except Exception:
                    continue
                for m in _DIRECTIVE_RE.finditer(text):
                    declared.add((m.group(1), m.group(2)))

    # 2. VM107 source files (.py + .yaml).
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
    """Walk VM107/registry/<type>/<id>.yaml and collect phase=48 entries."""
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


def test_every_phase48_yaml_has_register_capability_directive() -> None:
    """For every Phase 48 YAML on disk, at least one REGISTER_CAPABILITY
    directive declaring (type, id) must appear somewhere in plans, summaries,
    source files, or the YAML headers themselves."""
    declared = _collect_declared_directives()
    on_disk = _collect_phase48_yamls()

    missing = on_disk - declared
    assert not missing, (
        f"Phase 48 YAMLs on disk with NO REGISTER_CAPABILITY directive "
        f"anywhere in plans/summaries/source/yaml headers: {sorted(missing)}. "
        "Phase 47.6 plan-checker discipline requires every capability to be "
        "declared via REGISTER_CAPABILITY: type=X, id=Y, path=... directive."
    )


def test_register_capability_directive_count_floor() -> None:
    """Phase 48 ships at least 27 capabilities (CONTEXT § plan-09 inventory).

    Floor: 27. Actual may be higher (additional internal services declared in
    source). The test asserts the lower bound — Phase 48 doesn't regress below
    the planned inventory.
    """
    declared = _collect_declared_directives()
    phase48_yamls = _collect_phase48_yamls()
    # Phase 48 inventory must be at least 27 (plan-09 lock).
    assert len(phase48_yamls) >= 27, (
        f"Phase 48 inventory regressed below 27 capabilities — got "
        f"{len(phase48_yamls)} YAMLs on disk."
    )
    # And every Phase 48 capability declared somewhere.
    assert phase48_yamls.issubset(declared), (
        f"Phase 48 capabilities on disk not declared anywhere: "
        f"{sorted(phase48_yamls - declared)}"
    )
