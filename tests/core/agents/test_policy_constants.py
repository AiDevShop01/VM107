"""Phase 48 Plan 48-04 Task 4.1 — policy_constants.py single source of truth.

Implements REQ-48-D8 + REQ-48-D9 (deterministic policy substrate).

CONTEXT § Decision 2 mandate: "All policy constants (MAX_ITERATIONS=3,
IDENTITY_THRESHOLDS, HARD_VETOES, ACCEPT_FLOORS, BUDGET_CAPS) live in
orchestrator config — single source of truth, auditable, replayable."

These assertions lock the planner-locked numeric values and the
no-redefinition discipline. If a future plan re-binds any of these constants
at module level in another refinement_orchestrator/*.py file, the
test_no_other_module_redefines_constants assertion fires immediately.
"""
from __future__ import annotations

import ast
import pathlib


# ---------------------------------------------------------------------------
# Locked numeric values (CONTEXT § Decisions 8 + 9 + Phase 46 ROADMAP).
# ---------------------------------------------------------------------------


def test_max_iterations_is_three():
    from core.agents.refinement_orchestrator.policy_constants import MAX_ITERATIONS

    assert MAX_ITERATIONS == 3


def test_accept_floors_match_phase46_roadmap_numbers():
    """CONTEXT § Decision 8 — Phase 46 ROADMAP V1 floor numbers."""
    from core.agents.refinement_orchestrator.policy_constants import ACCEPT_FLOORS

    assert ACCEPT_FLOORS == {
        "sample_size": 200,
        "win_rate": 0.45,
        "max_drawdown": 0.20,
        "profit_factor": 1.2,
    }


def test_accept_floor_breach_threshold_is_twenty_percent():
    """Planner-locked severity policy: >20% breach -> HARD_REJECT; <=20% -> REFINABLE."""
    from core.agents.refinement_orchestrator.policy_constants import (
        ACCEPT_FLOOR_BREACH_THRESHOLD,
    )

    assert ACCEPT_FLOOR_BREACH_THRESHOLD == 0.20


def test_hard_vetoes_match_decision_9_locked_values():
    """CONTEXT § Decision 9 — 4 catastrophic-only vetoes (family-agnostic)."""
    from core.agents.refinement_orchestrator.policy_constants import HARD_VETOES

    assert HARD_VETOES == {
        "max_drawdown": {"op": ">", "value": 0.35},
        "win_rate": {"op": "<", "value": 0.30},
        "consecutive_losses": {"op": ">", "value": 10},
        "regime_coverage": {"op": "<", "value": 0.20},
    }


def test_identity_thresholds_tighten_across_iterations():
    """CONTEXT § Decision 10 — iter -> min_similarity ratchet."""
    from core.agents.refinement_orchestrator.policy_constants import IDENTITY_THRESHOLDS

    assert IDENTITY_THRESHOLDS == {1: 0.70, 2: 0.80, 3: 0.90}


def test_budget_caps_usd_per_iteration_and_per_loop():
    from core.agents.refinement_orchestrator.policy_constants import BUDGET_CAPS_USD

    assert BUDGET_CAPS_USD == {"per_iteration": 1.50, "per_loop": 5.00}


def test_budget_caps_wall_time_per_iteration_and_per_loop():
    """20-min per iteration, 60-min per loop (in ms)."""
    from core.agents.refinement_orchestrator.policy_constants import (
        BUDGET_CAPS_WALL_TIME_MS,
    )

    assert BUDGET_CAPS_WALL_TIME_MS == {
        "per_iteration": 20 * 60 * 1000,
        "per_loop": 60 * 60 * 1000,
    }


# ---------------------------------------------------------------------------
# Single-source-of-truth discipline: no other refinement_orchestrator/*.py
# may rebind these constants at module level.
# ---------------------------------------------------------------------------


_FORBIDDEN_REBINDS = {
    "MAX_ITERATIONS",
    "ACCEPT_FLOORS",
    "ACCEPT_FLOOR_BREACH_THRESHOLD",
    "HARD_VETOES",
    "IDENTITY_THRESHOLDS",
    "BUDGET_CAPS_USD",
    "BUDGET_CAPS_WALL_TIME_MS",
}


def _module_level_assignment_names(source: str) -> set[str]:
    """Return the set of names bound by module-level Assign nodes."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in tree.body:  # only top-level statements
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_no_other_module_redefines_policy_constants():
    """Walk refinement_orchestrator/*.py and assert no sibling rebinds these names."""
    pkg_dir = pathlib.Path(
        "/Volumes/ HardDrive/FinGPT/VM107/core/agents/refinement_orchestrator"
    )
    assert pkg_dir.is_dir(), pkg_dir

    offenders: list[tuple[str, str]] = []
    for path in pkg_dir.glob("*.py"):
        if path.name == "policy_constants.py":
            continue  # the canonical source -- allowed
        source = path.read_text()
        names = _module_level_assignment_names(source)
        for forbidden in _FORBIDDEN_REBINDS:
            if forbidden in names:
                offenders.append((path.name, forbidden))

    assert not offenders, (
        "policy constants must live ONLY in policy_constants.py; "
        f"sibling redefinitions found: {offenders}"
    )


def test_constants_are_typed_with_final():
    """Locked discipline: constants module uses typing.Final annotations."""
    src = pathlib.Path(
        "/Volumes/ HardDrive/FinGPT/VM107/core/agents/refinement_orchestrator/policy_constants.py"
    ).read_text()
    assert "from typing import Final" in src or "Final[" in src, (
        "policy_constants.py must import and use typing.Final"
    )
