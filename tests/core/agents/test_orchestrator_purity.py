"""Phase 48 Plan 48-03 Task 3.2 — orchestrator skeleton is pure Python.

Implements REQ-48-D2.

CONTEXT § Decision 2: orchestrator is a workflow compiler, NOT an agent.
"No prompts, no LLM, no agent.yaml, no role.md, no specifics.md, no affinity
routing, no reasoning loop, no cognition."

AST inspection asserts NO module in
``VM107/core/agents/refinement_orchestrator/`` imports any LLM client or
agent-profile loader.
"""
from __future__ import annotations

import ast
import pathlib

import pytest


_PROHIBITED_PREFIXES = (
    "langchain",
    "openai",
    "anthropic",
    "agent_zero",
    "agents.idea_agent",
    "agents.strategy_agent",
    "agents.code_agent",
    "agents.backtester_agent",
    "agents.strategy_refinement_critic",
    "core.agents.agent_zero",
)


def _iter_orchestrator_py_files():
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    orch_dir = repo_root / "core" / "agents" / "refinement_orchestrator"
    assert orch_dir.exists(), f"orchestrator dir missing: {orch_dir}"
    for path in sorted(orch_dir.glob("*.py")):
        yield path


def test_orchestrator_modules_import_no_llm_clients_or_agent_profiles():
    offenders: list[tuple[str, str, int]] = []
    for path in _iter_orchestrator_py_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    for forbidden in _PROHIBITED_PREFIXES:
                        if name == forbidden or name.startswith(forbidden + "."):
                            offenders.append((path.name, name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for forbidden in _PROHIBITED_PREFIXES:
                    if mod == forbidden or mod.startswith(forbidden + "."):
                        offenders.append((path.name, mod, node.lineno))

    assert not offenders, (
        "orchestrator modules must not import LLM clients or agent profiles: "
        + "; ".join(f"{f}:{l} imports {m}" for (f, m, l) in offenders)
    )


def test_orchestrator_modules_do_not_load_agent_yaml_files():
    """No module under refinement_orchestrator/ may read agent.yaml / role.md."""
    forbidden_substrings = ("agent.yaml", "role.md", "specifics.md", "prompts/")
    offenders: list[tuple[str, str]] = []
    for path in _iter_orchestrator_py_files():
        src = path.read_text()
        for sub in forbidden_substrings:
            if sub in src:
                offenders.append((path.name, sub))
    assert not offenders, (
        "orchestrator modules must not reference agent-profile files: "
        + "; ".join(f"{f} references {s}" for (f, s) in offenders)
    )
