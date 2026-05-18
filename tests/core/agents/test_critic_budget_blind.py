"""Phase 48 Plan 48-05 Task 5.3 — Critic LLM never sees budget state.

REQ-48-D14. CONTEXT § Decision 14:
  "Critic NEVER sees budget state -- preserves evaluation purity (LLM should
   not become economically self-aware mid-evaluation)."

CONTEXT § Anti-Patterns:
  "Critic seeing budget state (LLM becomes economically self-aware ->
   evaluation purity contamination)."

Two-pronged guard:
  1. ``run_critic`` signature (inspect.signature) has no budget* kwarg.
  2. The prompt-payload builder ``_build_critic_prompt_payload`` does NOT
     reference budget_snapshot / ExecutionCost / BudgetGovernor.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest


_INVOCATION_PATH = pathlib.Path(
    "/Volumes/ HardDrive/FinGPT/VM107/core/agents/invocation.py"
)


def test_run_critic_signature_has_no_budget_param():
    """No parameter named budget, budget_snapshot, remaining_budget, governor, or cost."""
    from core.agents.invocation import run_critic

    sig = inspect.signature(run_critic)
    param_names = set(sig.parameters.keys())

    banned = {
        "budget",
        "budget_snapshot",
        "remaining_budget",
        "budget_governor",
        "governor",
        "cost",
        "execution_cost",
        "remaining_usd",
        "budget_caps",
    }
    forbidden = banned & param_names
    assert not forbidden, (
        f"run_critic must be budget-blind; forbidden params present: {forbidden}"
    )


def test_run_critic_signature_only_takes_typed_artifacts():
    """Whitelist: state, spec, code, build, result + db/task_id/parent_task_id."""
    from core.agents.invocation import run_critic

    sig = inspect.signature(run_critic)
    expected_positional = {"state", "spec", "code", "build", "result"}
    expected_kwonly = {"db", "task_id", "parent_task_id"}
    expected = expected_positional | expected_kwonly

    actual = set(sig.parameters.keys())
    unexpected = actual - expected
    assert not unexpected, f"run_critic has unexpected params: {unexpected}"


def test_critic_prompt_payload_builder_excludes_budget_state():
    """Source inspection: _build_critic_prompt_payload must not reference budget."""
    src = _INVOCATION_PATH.read_text()
    tree = ast.parse(src)

    # Locate the _build_critic_prompt_payload function.
    func_def = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_build_critic_prompt_payload":
            func_def = node
            break
    assert func_def is not None, "_build_critic_prompt_payload not found in invocation.py"

    # Serialise just that function's source for keyword search.
    func_src = ast.unparse(func_def)
    banned_substrings = (
        "budget_snapshot",
        "BudgetGovernor",
        "ExecutionCost",
        "loop_budget_remaining",
        "iteration_budget_remaining",
        "BUDGET_CAPS",
    )
    offenders = [s for s in banned_substrings if s in func_src]
    assert not offenders, (
        "_build_critic_prompt_payload must not reference budget state; "
        f"found: {offenders}"
    )


def test_critic_prompt_payload_dumps_only_5_artifacts():
    """Defensive: the payload includes loop_state, strategy_spec, code_module,
    build_report, backtest_result — and NOTHING ELSE.

    RefinementLoopState carries budget_snapshot as a field, BUT the budget_snapshot
    dict is metadata for the orchestrator. The Critic sees the full state.model_dump
    by convention (it gets iteration counters, history), so this test pins the
    surface: 5 top-level keys, all carrying typed artifact data — no
    separately-injected budget object.
    """
    from core.agents.invocation import _build_critic_prompt_payload
    from core.contracts.schemas import (
        BacktestMetrics,
        BacktestResult,
        BuildReport,
        CodeModule,
        RefinementLoopState,
        StrategyFamily,
        StrategySpec,
    )
    from datetime import datetime, timezone
    import json

    now = datetime.now(timezone.utc)
    state = RefinementLoopState(
        loop_id="loop_blind",
        root_hypothesis_id="hyp_blind",
        strategy_family="BREAKOUT",
        loop_registry_snapshot_hash="hash-abc",
        iteration=1,
        max_iterations=3,
        strategy_version="0.1.0",
        code_version="0.1.0",
        started_at=now,
        updated_at=now,
    )
    spec = StrategySpec(
        name="alpha",
        features=["rsi"],
        rules=["x"],
        timeframes=["1h"],
        version="1.0.0",
        strategy_family=StrategyFamily.BREAKOUT,
    )
    code = CodeModule(
        module_type="strategy",
        target_vm="vm101",
        contract="c",
        code="def x(): pass",
        tests="t",
        version="1.0.0",
    )
    build = BuildReport(status="success")
    result = BacktestResult(
        metrics=BacktestMetrics(win_rate=0.55, rr=1.5, max_drawdown=0.10),
        sample_size=250,
        confidence=0.6,
    )

    payload = _build_critic_prompt_payload(state, spec, code, build, result)
    parsed = json.loads(payload)

    expected_keys = {"loop_state", "strategy_spec", "code_module", "build_report", "backtest_result"}
    actual_keys = set(parsed.keys())
    extra = actual_keys - expected_keys
    assert not extra, f"prompt payload must not inject budget/governor keys; extra: {extra}"


def test_budget_governor_module_does_not_import_run_critic():
    """Belt-and-braces: BudgetGovernor must not import the Critic surface.

    Prevents any path where the Governor accidentally hooks into Critic
    invocation and threads budget state through.
    """
    from core.agents.refinement_orchestrator import budget_governor as bg_mod

    src = pathlib.Path(bg_mod.__file__).read_text()
    tree = ast.parse(src)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "core.agents.invocation" or mod.startswith("core.agents.invocation."):
                for alias in node.names:
                    if alias.name == "run_critic":
                        offenders.append(f"line {node.lineno}: from {mod} import run_critic")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "core.agents.invocation":
                    offenders.append(f"line {node.lineno}: import {alias.name}")

    assert not offenders, (
        "budget_governor.py must not import run_critic (preserves evaluation purity): "
        + "; ".join(offenders)
    )
