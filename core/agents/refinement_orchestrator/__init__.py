"""Phase 48 refinement orchestrator — pure Python service.

REGISTER_CAPABILITY: type=service, id=refinement_orchestrator, path=VM107/registry/service/refinement_orchestrator.yaml

CONTEXT § Decision 2: this package is a deterministic workflow compiler. NO
LLM client. NO agent profile config. NO prompts. The public entry
``run_refinement_loop`` is intentionally left unimplemented in Plan 48-03 —
loop control flow lands in Plans 04 + 05.

This Plan-48-03 surface ships the SUBSTRATE every subsequent plan calls into:

  - ``initialize_loop_state`` / ``update_loop_state`` /
    ``append_iteration_artifact`` / ``finalize_state``     (state.py)
  - ``freeze_snapshot_hash``                                (snapshot_freeze.py)
  - ``_stamp_artifact`` / ``iteration_stamps_for`` /
    ``persist_atomically``                                  (persistence.py)
  - ``load_state`` / ``resume_or_initialize``               (checkpoint.py)
"""
from __future__ import annotations

from core.agents.refinement_orchestrator.checkpoint import (
    load_state,
    resume_or_initialize,
)
from core.agents.refinement_orchestrator.persistence import (
    iteration_stamps_for,
    persist_atomically,
)
from core.agents.refinement_orchestrator.snapshot_freeze import freeze_snapshot_hash
from core.agents.refinement_orchestrator.state import (
    append_iteration_artifact,
    finalize_state,
    initialize_loop_state,
    update_loop_state,
)


def run_refinement_loop(hypothesis_id: str, *, task_id: str | None = None):
    """Phase 48 public entry — Plan 48-04 + 48-05 implement loop control flow.

    Plan 48-03 ships the substrate (state lifecycle + snapshot freeze + atomic
    persistence + crash-recovery). The loop iteration logic, acceptance gates,
    vetoes, identity-drift gate, convergence detection, and budget caps land
    in Plans 04 + 05.
    """
    raise NotImplementedError(
        "run_refinement_loop is not yet implemented. "
        "Plan 48-04 ships acceptance + vetoes; Plan 48-05 ships identity + "
        "convergence + budget; Plan 48-08b wires the main loop."
    )


__all__ = [
    "initialize_loop_state",
    "update_loop_state",
    "append_iteration_artifact",
    "finalize_state",
    "freeze_snapshot_hash",
    "iteration_stamps_for",
    "persist_atomically",
    "load_state",
    "resume_or_initialize",
    "run_refinement_loop",
]
