"""Phase 48 Plan 07 — orchestrator is the SOLE EMITTER of refinement events.

CONTEXT § Decision 18 (LOCKED): "Orchestrator is the SOLE EMITTER of
refinement lifecycle events. Agents emit cognition artifacts; orchestrator
emits lifecycle authority. Strict separation."

AST-level invariant guards:
  1. NO agent profile module under ``VM107/agents/`` may import any helper
     or payload model from ``core.events.refinement_events``.
  2. The ``refinement_orchestrator`` package is permitted to import the
     module (Plan 08b wires the helpers into the main loop; until then
     this guard rail is in place to prevent agent-side regressions).

REQ-48-D18.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# The exact module path that callers (orchestrator) import. Any agent profile
# that references this string violates the sole-emitter invariant.
_GUARDED_MODULE = "core.events.refinement_events"


def _module_imports_target(py_path: Path, target_module: str) -> bool:
    """Walk ``py_path``'s AST and return True iff it imports ``target_module``.

    Detects both ``import core.events.refinement_events`` and
    ``from core.events.refinement_events import ...`` shapes.
    """
    try:
        tree = ast.parse(py_path.read_text())
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == target_module or name.startswith(target_module + "."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == target_module or mod.startswith(target_module + "."):
                return True
    return False


def _iter_agent_profile_py_files():
    """Iterate every .py file under VM107/agents/ (agent profile dirs)."""
    agents_root = _VM107_ROOT / "agents"
    if not agents_root.exists():
        return
    for path in sorted(agents_root.rglob("*.py")):
        # Skip __pycache__ defensively (rglob already filters to *.py).
        if "__pycache__" in path.parts:
            continue
        # Skip Agent Zero example profile (vendored / non-shipped).
        if "/_example/" in str(path):
            continue
        yield path


def _iter_orchestrator_py_files():
    """Iterate every .py file under VM107/core/agents/refinement_orchestrator/."""
    orch_dir = _VM107_ROOT / "core" / "agents" / "refinement_orchestrator"
    if not orch_dir.exists():
        return
    for path in sorted(orch_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def test_no_agent_profile_module_imports_refinement_events():
    """No file under VM107/agents/ may import core.events.refinement_events.

    Agent profiles emit cognition artifacts (envelopes, narratives, verdicts)
    via their existing emission paths. They MUST NOT emit Phase 48 lifecycle
    events directly. Orchestrator is the sole emitter.
    """
    offenders: list[str] = []
    for path in _iter_agent_profile_py_files():
        if _module_imports_target(path, _GUARDED_MODULE):
            offenders.append(str(path.relative_to(_VM107_ROOT)))

    assert not offenders, (
        "Agent profile modules MUST NOT import core.events.refinement_events "
        "(sole-emitter invariant; CONTEXT § Decision 18). Offenders:\n  - "
        + "\n  - ".join(offenders)
    )


def test_orchestrator_package_is_authorized_to_import_refinement_events():
    """``refinement_orchestrator/`` package is permitted to import the module.

    This test is a positive surface check — it asserts the module IS the
    sole permitted importer. Until Plan 08b wires the helpers into the main
    loop, the package itself may not yet import them; this test therefore
    does NOT REQUIRE an import — it only asserts the negative invariant
    (agents do not import) and that, when an importer eventually exists,
    it lives under ``core/agents/refinement_orchestrator/``.
    """
    # Sole-emitter invariant: the only authorized importers live under
    # ``core/agents/refinement_orchestrator/``. We assert no OTHER importer
    # exists outside the orchestrator package (excluding tests + the
    # refinement_events module itself).
    other_importers: list[str] = []
    for path in sorted((_VM107_ROOT / "core").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(_VM107_ROOT)
        rel_str = str(rel)
        # Allow the module itself + tests + the orchestrator package.
        if rel_str == "core/events/refinement_events.py":
            continue
        if rel_str.startswith("core/agents/refinement_orchestrator/"):
            continue
        if _module_imports_target(path, _GUARDED_MODULE):
            other_importers.append(rel_str)

    assert not other_importers, (
        "Only core/agents/refinement_orchestrator/ modules may import "
        "core.events.refinement_events. Found unauthorized importer(s):\n  - "
        + "\n  - ".join(other_importers)
    )


def test_refinement_events_module_is_present_and_importable():
    """Sanity: the guarded module exists on disk and is importable."""
    p = _VM107_ROOT / "core" / "events" / "refinement_events.py"
    assert p.exists(), f"core.events.refinement_events missing at {p}"

    import importlib
    mod = importlib.import_module(_GUARDED_MODULE)
    # Confirm the 10 helper attribute surface exists.
    expected_helpers = (
        "emit_refinement_loop_started",
        "emit_iteration_started",
        "emit_critic_verdict_received",
        "emit_hard_veto_triggered",
        "emit_identity_drift_detected",
        "emit_convergence_stall_detected",
        "emit_budget_exceeded",
        "emit_strategy_accepted",
        "emit_strategy_rejected",
        "emit_loop_terminated",
    )
    missing = [h for h in expected_helpers if not callable(getattr(mod, h, None))]
    assert not missing, (
        f"core.events.refinement_events missing helper attrs: {missing}"
    )


def test_strategy_refinement_critic_profile_does_not_import_refinement_events():
    """Explicit check: the Phase 48 Critic profile must NOT import the module.

    The Critic emits cognition artifacts (CriticVerdict) via the agent
    response path. Lifecycle authority belongs to the orchestrator.
    """
    critic_dir = _VM107_ROOT / "agents" / "strategy_refinement_critic"
    if not critic_dir.exists():
        # Plan 06 ships this dir; if absent, surface the missing dir.
        # Soft-skip rather than false-pass.
        import pytest
        pytest.skip(f"strategy_refinement_critic profile dir not present at {critic_dir}")

    offenders: list[str] = []
    for path in sorted(critic_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if _module_imports_target(path, _GUARDED_MODULE):
            offenders.append(str(path.relative_to(_VM107_ROOT)))

    assert not offenders, (
        "strategy_refinement_critic profile MUST NOT import "
        "core.events.refinement_events (Critic emits cognition; orchestrator "
        "emits lifecycle). Offenders:\n  - " + "\n  - ".join(offenders)
    )
