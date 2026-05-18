"""Phase 48 refinement orchestrator — pure Python service.

REGISTER_CAPABILITY: type=service, id=refinement_orchestrator, path=VM107/registry/service/refinement_orchestrator.yaml

CONTEXT § Decision 2: this package is a deterministic workflow compiler. NO
LLM client. NO agent profile config. NO prompts. The public entry
``run_refinement_loop`` is wired in Plan 48-08b — it composes Plans 03/04/05/06/07/08a.

Plan 48-03 shipped the SUBSTRATE every subsequent plan calls into:

  - ``initialize_loop_state`` / ``update_loop_state`` /
    ``append_iteration_artifact`` / ``finalize_state``     (state.py)
  - ``freeze_snapshot_hash``                                (snapshot_freeze.py)
  - ``_stamp_artifact`` / ``iteration_stamps_for`` /
    ``persist_atomically``                                  (persistence.py)
  - ``load_state`` / ``resume_or_initialize``               (checkpoint.py)

Plan 48-08b ships:

  - ``run_refinement_loop``                                 (main_loop.py)
"""
from __future__ import annotations

from core.agents.refinement_orchestrator.checkpoint import (
    load_state,
    resume_or_initialize,
)
from core.agents.refinement_orchestrator.main_loop import run_refinement_loop
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
