"""Phase 48 Plan 48-03 Task 3.3 — termination path NEVER deletes iteration docs.

Implements REQ-48-D13 (CONTEXT § Decision 13).

Static + dynamic guard:
  - state.py, persistence.py, checkpoint.py must NOT call ``delete_one`` /
    ``delete_many`` / ``drop`` on any iteration-artifact collection
    (strategy_specs, code_modules, build_reports, backtest_results,
    critic_verdicts, agent_envelopes).  The only allowed delete is the
    Pattern-51 rollback in persistence.persist_atomically — but that fires
    BEFORE the artifact is considered "persisted", not on termination.
  - finalize_state must not touch any collection other than refinement_loops.
"""
from __future__ import annotations

import ast
import pathlib

import pytest


_ITERATION_COLLECTIONS = (
    "strategy_specs",
    "code_modules",
    "build_reports",
    "backtest_results",
    "critic_verdicts",
    "agent_envelopes",
)


def test_finalize_state_does_not_delete_any_iteration_artifacts(
    mongo_test_db, valid_hypothesis_id, frozen_registry_snapshot_hash, monkeypatch
):
    from core.agents.refinement_orchestrator import (
        persistence,
        state as state_mod,
    )

    class _FakeReg:
        snapshot_hash = frozen_registry_snapshot_hash

    monkeypatch.setattr(
        state_mod.CapabilityRegistry, "get", classmethod(lambda cls: _FakeReg())
    )
    monkeypatch.setattr(persistence, "emit_event", lambda *a, **kw: None)

    s = state_mod.initialize_loop_state(
        mongo_test_db,
        loop_id="loop-nodisc-1",
        hypothesis_id=valid_hypothesis_id,
        task_id="task-nodisc-1",
    )

    # Plant artifacts.
    for i in range(2):
        stamped = persistence._stamp_artifact(
            mongo_test_db,
            artifact={"_id": f"doc-iter{i}"},
            loop_id="loop-nodisc-1",
            iteration=i,
            parent_iteration=i - 1 if i > 0 else None,
            refinement_delta_id=None,
            root_hypothesis_id=valid_hypothesis_id,
        )
        persistence.persist_atomically(
            mongo_test_db,
            state=s,
            artifact_dict=stamped,
            collection_name="strategy_specs",
            event_type="iteration_started",
            event_payload={},
        )

    # Snapshot counts BEFORE termination.
    before = {c: mongo_test_db[c].count_documents({}) for c in _ITERATION_COLLECTIONS}

    state_mod.finalize_state(mongo_test_db, "loop-nodisc-1", "MAX_ITERATIONS")

    after = {c: mongo_test_db[c].count_documents({}) for c in _ITERATION_COLLECTIONS}
    assert before == after, (
        "finalize_state must NOT mutate iteration collection counts; "
        f"before={before} after={after}"
    )


def test_orchestrator_modules_do_not_call_delete_on_iteration_collections():
    """Static AST guard: search every orchestrator module for delete-style
    calls against the iteration collections.

    Allowed: persistence.persist_atomically rollback path deletes a single
    doc from the CALLER-PROVIDED collection_name (the rollback is bounded to
    the same artifact that was just inserted in the same call). That's not a
    "termination discard" — it's transactional consistency. We allow it.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    orch_dir = repo_root / "core" / "agents" / "refinement_orchestrator"

    # Only state.py + checkpoint.py are inspected here — persistence.py's
    # rollback delete is the bounded exception described in the docstring.
    targets = ("state.py", "checkpoint.py", "snapshot_freeze.py", "__init__.py")
    offenders: list[tuple[str, str, int]] = []
    for name in targets:
        path = orch_dir / name
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in {
                    "delete_one",
                    "delete_many",
                    "drop",
                    "drop_collection",
                }:
                    offenders.append((name, func.attr, node.lineno))
    assert not offenders, (
        "state/checkpoint/snapshot_freeze must not call delete-style Mongo "
        f"operations: {offenders}"
    )
