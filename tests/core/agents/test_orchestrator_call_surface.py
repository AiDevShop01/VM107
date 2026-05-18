"""Phase 48 Plan 48-03 Task 3.2 — orchestrator only imports the approved surface.

Implements REQ-48-D2.

CONTEXT § Decision 2: orchestrator calls typed wrappers ONLY:
``run_idea_agent``, ``run_strategy_agent``, ``run_code_agent``, ``run_build``,
``run_backtest``, ``run_critic``. NEVER calls tools directly.

AST inspection asserts every top-level import in the orchestrator skeleton
resolves to one of the approved import roots:
  - core.agents.invocation
  - core.contracts.*
  - core.registry.capability_registry
  - core.events.phase56_client
  - helpers.mongo
  - stdlib (datetime, uuid, logging, typing, __future__, etc.)
"""
from __future__ import annotations

import ast
import pathlib
import sys


_APPROVED_ROOTS = {
    "core.agents.invocation",
    "core.contracts",
    "core.registry.capability_registry",
    "core.registry.strategy_yaml_emitter",  # Plan 08a: acceptance_path auto-emits YAML
    "core.events.phase56_client",
    "core.events",  # re-export package
    "core.events.refinement_events",  # Plan 08a: acceptance/rejection paths emit lifecycle events
    "helpers.mongo",
    "core.agents.refinement_orchestrator",  # internal cross-import
}

_STDLIB_OK = set(sys.stdlib_module_names) | {"__future__"}


def _is_approved(module_name: str) -> bool:
    # Stdlib top-level OK.
    top = module_name.split(".")[0]
    if top in _STDLIB_OK:
        return True
    # Internal cross-imports relative-style (handled at ImportFrom level via
    # absolute-form already in this codebase — see envelope_writer).
    for root in _APPROVED_ROOTS:
        if module_name == root or module_name.startswith(root + "."):
            return True
    return False


def _iter_orchestrator_py_files():
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    orch_dir = repo_root / "core" / "agents" / "refinement_orchestrator"
    assert orch_dir.exists()
    for path in sorted(orch_dir.glob("*.py")):
        yield path


def test_orchestrator_imports_only_from_approved_call_surface():
    offenders: list[tuple[str, str, int]] = []
    for path in _iter_orchestrator_py_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not _is_approved(alias.name):
                        offenders.append((path.name, alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    # Relative import — only allowed within the package.
                    continue
                mod = node.module or ""
                if not _is_approved(mod):
                    offenders.append((path.name, mod, node.lineno))

    assert not offenders, (
        "orchestrator may only import from the approved call surface: "
        + "; ".join(f"{f}:{l} imports {m}" for (f, m, l) in offenders)
    )
