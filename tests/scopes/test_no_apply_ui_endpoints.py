"""Phase 62-06 Task 3 — test_no_apply_ui_endpoints.py

Apply-UI regression sweep: verifies no VM107 tool, agent profile, or test file
touches apply-UI endpoints or UI-facing recommendation surfaces.

CTX-DEC-15: SHADOW_ONLY V1 invariant — recommendations are advisory observations.
    Phase 62 does NOT have an apply UI. No tool, agent, or test should reference
    apply-tier endpoint paths, frontend route patterns, or UI-facing apply surfaces.

RG-11: Envelope flag enforcement at tool layer — confirmed via source scan.

Doctrine:
    Phase 62 does NOT optimize. It proposes adaptive hypotheses.
    Humans authorize epistemic change.
    Adaptive outputs are advisory cognition artifacts. Never canonical trading truth.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# ---------------------------------------------------------------------------
# Forbidden patterns — none of these should appear in VM107 source/tests
# ---------------------------------------------------------------------------

# Endpoint paths that would imply a live-apply pipeline in Phase 62
_FORBIDDEN_ENDPOINT_FRAGMENTS = [
    "/apply-recommendation",
    "/apply_recommendation",
    "/recommendations/apply",
    "/adaptive/apply",
    "/weight-version/apply",
    "/weight_version/apply",
]

# Frontend route patterns that would imply apply UI
_FORBIDDEN_FRONTEND_PATTERNS = [
    "apply_threshold",
    "apply_weight",
    "ApplyRecommendation",
    "applyRecommendation",
    "approve_recommendation",
    "approveRecommendation",
]

# Tool field names for apply tier (must NOT be set in any tool call)
_FORBIDDEN_APPLY_TIER_FIELDS = [
    '"applied_threshold"',
    '"applied_by"',
    '"applied_at"',
    "applied_threshold=",
    "applied_by=",
    "applied_at=",
]

# Files to exclude from scan (external libs, __pycache__, etc.)
_EXCLUDE_DIRS = {"__pycache__", ".git", ".mypy_cache", "node_modules"}


def _collect_vm107_source_files() -> list[Path]:
    """Return all .py files under VM107 tools/, agents/, helpers/, tests/.

    Excludes this test file itself — which contains forbidden patterns as
    string constants for inspection purposes.
    """
    candidate_dirs = [
        _VM107_ROOT / "tools",
        _VM107_ROOT / "agents",
        _VM107_ROOT / "helpers",
        _VM107_ROOT / "tests",
    ]
    # This file contains the forbidden patterns as constants — exclude self
    _self = Path(__file__).resolve()
    files = []
    for parent in candidate_dirs:
        if not parent.is_dir():
            continue
        for f in parent.rglob("*.py"):
            if not any(excl in f.parts for excl in _EXCLUDE_DIRS):
                if f.resolve() != _self:
                    files.append(f)
    return files


# ---------------------------------------------------------------------------
# No apply-UI endpoint paths in VM107 source
# ---------------------------------------------------------------------------


def test_no_apply_ui_endpoint_paths_in_vm107_tools():
    """No VM107 tool file references apply-tier endpoint paths (CTX-DEC-15).

    Phase 62 is SHADOW_ONLY V1. No tool should call an /apply-recommendation
    or equivalent endpoint. All recommendations are advisory only.
    """
    tool_dir = _VM107_ROOT / "tools"
    if not tool_dir.is_dir():
        pytest.skip(f"tools/ dir missing at {tool_dir}")

    violations = []
    for py_file in tool_dir.rglob("*.py"):
        if any(excl in py_file.parts for excl in _EXCLUDE_DIRS):
            continue
        content = py_file.read_text(encoding="utf-8")
        for forbidden in _FORBIDDEN_ENDPOINT_FRAGMENTS:
            if forbidden in content:
                violations.append(f"{py_file.relative_to(_VM107_ROOT)}: contains {forbidden!r}")

    assert not violations, (
        "CTX-DEC-15 violation: VM107 tool files reference apply-tier endpoints. "
        "Phase 62 is SHADOW_ONLY — no apply pipeline exists.\n"
        + "\n".join(violations)
    )


def test_no_apply_ui_endpoint_paths_in_vm107_agents():
    """No VM107 agent file references apply-tier endpoint paths (CTX-DEC-15)."""
    agent_dir = _VM107_ROOT / "agents"
    if not agent_dir.is_dir():
        pytest.skip(f"agents/ dir missing at {agent_dir}")

    violations = []
    for py_file in agent_dir.rglob("*.py"):
        if any(excl in py_file.parts for excl in _EXCLUDE_DIRS):
            continue
        content = py_file.read_text(encoding="utf-8")
        for forbidden in _FORBIDDEN_ENDPOINT_FRAGMENTS:
            if forbidden in content:
                violations.append(f"{py_file.relative_to(_VM107_ROOT)}: contains {forbidden!r}")

    assert not violations, (
        "CTX-DEC-15 violation: VM107 agent files reference apply-tier endpoints.\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# No apply-UI frontend patterns in VM107 source
# ---------------------------------------------------------------------------


def test_no_apply_ui_frontend_patterns_in_vm107():
    """No VM107 source references apply-tier frontend patterns (CTX-DEC-15).

    Pattern names like ApplyRecommendation, apply_threshold imply a live-apply
    UI surface that does not exist in Phase 62.
    """
    source_files = _collect_vm107_source_files()
    violations = []
    for py_file in source_files:
        content = py_file.read_text(encoding="utf-8")
        for pattern in _FORBIDDEN_FRONTEND_PATTERNS:
            if pattern in content:
                violations.append(
                    f"{py_file.relative_to(_VM107_ROOT)}: contains {pattern!r}"
                )

    assert not violations, (
        "CTX-DEC-15 violation: VM107 source references apply-tier UI patterns. "
        "Phase 62 is SHADOW_ONLY — no apply UI exists.\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# No apply-tier field assignments in VM107 tools
# ---------------------------------------------------------------------------


def test_no_apply_tier_field_assignments_in_vm107_tools():
    """No VM107 adaptive tool sets applied_threshold, applied_by, or applied_at (CTX-DEC-5).

    The applied_* tier is schema-only in Phase 62 V1. Tools must NOT write or pass
    these fields. DB CHECK constraint enforces NULL at persistence layer — this test
    adds defense-in-depth at code layer.
    """
    adaptive_tool_dir = _VM107_ROOT / "tools" / "adaptive"
    if not adaptive_tool_dir.is_dir():
        pytest.skip(f"tools/adaptive/ missing at {adaptive_tool_dir}")

    violations = []
    for py_file in adaptive_tool_dir.rglob("*.py"):
        if any(excl in py_file.parts for excl in _EXCLUDE_DIRS):
            continue
        lines = py_file.read_text(encoding="utf-8").splitlines()
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            # Skip comments
            if stripped.startswith("#"):
                continue
            for forbidden in _FORBIDDEN_APPLY_TIER_FIELDS:
                if forbidden in line:
                    violations.append(
                        f"{py_file.relative_to(_VM107_ROOT)}:{line_num}: "
                        f"contains {forbidden!r}"
                    )

    assert not violations, (
        "CTX-DEC-5 violation: VM107 adaptive tools reference apply-tier fields. "
        "applied_threshold/applied_by/applied_at must remain NULL in Phase 62 V1.\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Adaptive tools have _shadow_only envelope check in source
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_file", [
    "get_adaptive_recommendations.py",
    "get_regime_adaptation_candidates.py",
])
def test_adaptive_tools_have_shadow_only_envelope_check(tool_file):
    """Phase 62-06 tools enforce _shadow_only envelope at call layer (RG-11).

    Both get_adaptive_recommendations and get_regime_adaptation_candidates must
    contain source code that raises on missing/False _shadow_only flag.
    """
    tool_path = _VM107_ROOT / "tools" / "adaptive" / tool_file
    if not tool_path.exists():
        pytest.skip(f"Tool not yet created: {tool_path}")

    content = tool_path.read_text(encoding="utf-8")

    assert "_shadow_only" in content, (
        f"{tool_file}: must check _shadow_only envelope field (RG-11 / CTX-DEC-15)"
    )
    assert "ToolError" in content, (
        f"{tool_file}: must define and raise ToolError for missing SHADOW_ONLY (RG-11)"
    )
    assert "SHADOW_ONLY" in content, (
        f"{tool_file}: ToolError message must contain SHADOW_ONLY framing (CTX-DEC-15)"
    )


# ---------------------------------------------------------------------------
# Registry YAMLs for Phase 62-06 are present
# ---------------------------------------------------------------------------


def test_phase_62_06_capability_yamls_present():
    """All 4 Phase 62-06 capability YAMLs are present in the registry.

    Phase 47.6 registry lock: all capabilities must have a registry entry.
    Phase 62-06 ships: signal/adaptive_recommendation_signal.yaml,
    tool/get_adaptive_recommendations.yaml, tool/get_regime_adaptation_candidates.yaml,
    service/adaptive_pipeline_orchestrator.yaml.
    """
    expected = [
        _VM107_ROOT / "registry" / "signal" / "adaptive_recommendation_signal.yaml",
        _VM107_ROOT / "registry" / "tool" / "get_adaptive_recommendations.yaml",
        _VM107_ROOT / "registry" / "tool" / "get_regime_adaptation_candidates.yaml",
        _VM107_ROOT / "registry" / "service" / "adaptive_pipeline_orchestrator.yaml",
    ]
    missing = [str(p) for p in expected if not p.exists()]
    assert not missing, (
        "Phase 47.6 registry lock violation: missing Phase 62-06 capability YAMLs:\n"
        + "\n".join(missing)
    )
