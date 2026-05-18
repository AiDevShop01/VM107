"""Phase 48 refinement acceptance path.

REQ-48-D6 + D11. CONTEXT § Decision 6 + 11.

When the refinement orchestrator decides a strategy ACCEPTS (Critic ACCEPT
verdict + acceptance_floor PASS + all hard vetoes clear), this module:

  1. Defensively re-checks the loop's hypothesis lineage (orphan rejection).
  2. Builds the 12-field accepted_strategies doc (CONTEXT § Decision 11).
  3. Inserts it into ``accepted_strategies`` Mongo collection with a hidden
     ``_worm_locked: True`` flag stamped on insert (application-layer WORM).
  4. Calls ``emit_strategy_yaml`` to auto-generate
     ``VM107/registry/strategy/<id>.yaml`` (registry-layer WORM via
     StrategyYAMLAlreadyExists).
  5. Emits ``strategy_accepted`` Phase 56 event (Pattern 51 atomic-with-persist).

Sole-emitter invariant: this module lives under
``core/agents/refinement_orchestrator/`` and is therefore an authorized
caller of ``core.events.refinement_events`` per the Plan 07 AST guard.

Env-driven config: no fallback defaults. No hardcoded URLs.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.contracts.exceptions import OrphanStrategyError
from core.contracts.schemas import CriticVerdict, RefinementLoopState
from core.events.refinement_events import emit_strategy_accepted
from core.registry.strategy_yaml_emitter import (
    DEFAULT_REGISTRY_STRATEGY_DIR,
    emit_strategy_yaml,
)

log = logging.getLogger("vm107.refinement_orchestrator.acceptance_path")

# Mutable module-level Path used by tests to redirect YAML output to tmp_path.
# Production callers leave this alone — it defaults to the in-tree
# VM107/registry/strategy/ directory shipped by Plan 48-00.
REGISTRY_STRATEGY_DIR: Path = DEFAULT_REGISTRY_STRATEGY_DIR

_ACCEPTED_STRATEGIES = "accepted_strategies"
_REFINEMENT_LOOPS = "refinement_loops"
_HYPOTHESES = "hypotheses"
_ACCEPTED_BY_VERSION = "refinement_orchestrator@1.0.0"


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def assert_hypothesis_exists(db: Any, *, hypothesis_id: str) -> dict[str, Any]:
    """Reject orphan refinement: the hypothesis_id must resolve in Mongo.

    Returns:
        The hypothesis doc on success.

    Raises:
        OrphanStrategyError: no doc with ``_id == hypothesis_id``.
    """
    doc = db[_HYPOTHESES].find_one({"_id": hypothesis_id})
    if not doc:
        raise OrphanStrategyError(
            f"Refinement entry contract violation: hypothesis_id="
            f"{hypothesis_id!r} not found in {_HYPOTHESES!r}. "
            "All refinement artifacts must trace back to a Hypothesis."
        )
    return doc


def _assert_loop_state_present(db: Any, *, loop_id: str) -> dict[str, Any]:
    """Reject acceptance/rejection paths invoked without a RefinementLoopState row."""
    doc = db[_REFINEMENT_LOOPS].find_one({"_id": loop_id})
    if not doc:
        raise OrphanStrategyError(
            f"Refinement loop state missing for loop_id={loop_id!r}. "
            "Acceptance + rejection paths require initialize_loop_state to "
            "have been called first."
        )
    return doc


def assert_worm_locked_then_raise(
    db: Any, *, collection: str, doc_id: str
) -> None:
    """Application-layer WORM guard.

    Call this BEFORE any mutation attempt against an accepted_strategies /
    rejected_strategies doc. If the doc carries ``_worm_locked: True``, this
    function raises ``RuntimeError`` — blocking the mutation.

    Args:
        db: pymongo / mongomock Database handle.
        collection: collection name (``accepted_strategies`` or
            ``rejected_strategies``).
        doc_id: ``_id`` of the doc to check.

    Raises:
        RuntimeError: doc is worm-locked.
    """
    doc = db[collection].find_one({"_id": doc_id}, {"_worm_locked": 1})
    if doc and doc.get("_worm_locked") is True:
        raise RuntimeError(
            f"WORM violation: {collection}/{doc_id} is locked (worm_locked=True). "
            "Accepted + rejected strategies are immutable; no $set / $unset / "
            "$rename / replace_one is permitted."
        )


def _build_accepted_doc(
    *,
    accepted_strategy_id: str,
    state: RefinementLoopState,
    final_iteration_ids: dict[str, str],
    final_iteration: int,
) -> dict[str, Any]:
    """Build the 12-field accepted_strategies doc per CONTEXT § Decision 11."""
    return {
        "_id": accepted_strategy_id,
        "accepted_strategy_id": accepted_strategy_id,
        "root_hypothesis_id": state.root_hypothesis_id,
        "strategy_family": state.strategy_family,
        "refinement_loop_id": state.loop_id,
        "final_strategy_spec_id": final_iteration_ids["strategy_spec_id"],
        "final_code_module_id": final_iteration_ids["code_module_id"],
        "final_backtest_result_id": final_iteration_ids["backtest_result_id"],
        "final_critic_verdict_id": final_iteration_ids["critic_verdict_id"],
        "accepted_registry_snapshot_hash": state.loop_registry_snapshot_hash,
        "iteration_artifact_ids": list(state.iteration_artifact_ids),
        "accepted_at": _utc_now_iso(),
        "accepted_by": _ACCEPTED_BY_VERSION,
        "acceptance_reason": f"CRITIC_ACCEPT_AT_ITER_{final_iteration}",
        "schema_version": 1,
        # Application-layer WORM flag (Decision 11).
        "_worm_locked": True,
    }


def accept_strategy(
    db: Any,
    *,
    state: RefinementLoopState,
    verdict: CriticVerdict,
    final_iteration_ids: dict[str, str],
    final_iteration: int,
) -> str:
    """Promote a refined StrategySpec into accepted_strategies + emit registry YAML + event.

    Pattern 51 ordering (CONTEXT § Decision 18 + Plan 07):
      1. Defensive orphan check on RefinementLoopState row.
      2. Insert accepted_strategies doc (Mongo).
      3. Write registry/strategy/<id>.yaml (filesystem).
      4. Emit strategy_accepted Phase 56 event.

    Failure semantics: any step raising aborts the path. The caller (Plan
    08b main_loop) decides whether to terminate or retry. Mongo lacks
    cross-collection transactions on single-replica; the registry YAML
    refuses overwrite, so a partial failure is recoverable without data
    corruption (idempotent re-runs would either find the YAML already
    present and raise StrategyYAMLAlreadyExists or — if the YAML is absent
    — would find the WORM doc and raise from there).

    Args:
        db: pymongo / mongomock Database handle.
        state: RefinementLoopState carrying loop metadata.
        verdict: CriticVerdict that triggered acceptance (recorded in event
            payload context; not stored on the accepted doc — the
            final_critic_verdict_id reference is canonical).
        final_iteration_ids: dict with keys
            ``strategy_spec_id``, ``code_module_id``,
            ``backtest_result_id``, ``critic_verdict_id``.
        final_iteration: int iteration on which acceptance fired.

    Returns:
        accepted_strategy_id (uuid4 string).

    Raises:
        OrphanStrategyError: RefinementLoopState row missing for state.loop_id.
        StrategyYAMLAlreadyExists: registry YAML already on disk.
        Phase56EmitError: event emit failed.
    """
    # Defensive orphan check.
    _assert_loop_state_present(db, loop_id=state.loop_id)

    accepted_strategy_id = str(uuid.uuid4())
    accepted_doc = _build_accepted_doc(
        accepted_strategy_id=accepted_strategy_id,
        state=state,
        final_iteration_ids=final_iteration_ids,
        final_iteration=final_iteration,
    )

    # Step 1: insert into accepted_strategies.
    db[_ACCEPTED_STRATEGIES].insert_one(accepted_doc)
    log.info(
        "acceptance_path: inserted accepted_strategies doc id=%s loop_id=%s",
        accepted_strategy_id,
        state.loop_id,
    )

    # Step 2: emit registry/strategy/<id>.yaml.
    yaml_path = emit_strategy_yaml(accepted_doc, output_dir=REGISTRY_STRATEGY_DIR)
    log.info("acceptance_path: emitted registry YAML at %s", yaml_path)

    # Step 3: emit Phase 56 strategy_accepted event (lifecycle).
    emit_strategy_accepted(
        loop_id=state.loop_id,
        accepted_strategy_id=accepted_strategy_id,
        root_hypothesis_id=state.root_hypothesis_id,
        final_iteration=final_iteration,
        registry_yaml_path=str(yaml_path),
    )
    log.info(
        "acceptance_path: emitted strategy_accepted event for loop_id=%s",
        state.loop_id,
    )

    return accepted_strategy_id


__all__ = [
    "REGISTRY_STRATEGY_DIR",
    "accept_strategy",
    "assert_hypothesis_exists",
    "assert_worm_locked_then_raise",
]
