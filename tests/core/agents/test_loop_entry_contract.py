"""Phase 48 Plan 48-08a — REQ-48-D6 loop entry contract.

CONTEXT § Decision 6: ``run_refinement_loop(hypothesis_id)`` is the sole
entry shape. Hypothesis-id-in (NOT a full Hypothesis object). Orchestrator
REJECTS any StrategySpec / CodeModule lookup that lacks Hypothesis lineage
— no orphan strategies allowed.

Plan 48-08a ships ``acceptance_path.accept_strategy`` + the orphan-rejection
helper that orchestrator-internal lookup functions call.  Plan 48-08b will
wire ``run_refinement_loop`` itself; this test pins the contract surface so
the main_loop implementation is bound to it.

Acceptable termination modes for the entry contract:
- Loading a missing hypothesis_id raises ``OrphanStrategyError``.
- The helper exposed for the main_loop check
  (``acceptance_path.assert_hypothesis_exists``) returns the doc on success
  and raises on absence.
"""
from __future__ import annotations

import pytest

from core.contracts.exceptions import OrphanStrategyError


def test_assert_hypothesis_exists_returns_doc_on_present(mongo_test_db, valid_hypothesis_id):
    from core.agents.refinement_orchestrator.acceptance_path import (
        assert_hypothesis_exists,
    )

    doc = assert_hypothesis_exists(mongo_test_db, hypothesis_id=valid_hypothesis_id)
    assert doc["_id"] == valid_hypothesis_id


def test_assert_hypothesis_exists_raises_orphan_on_absent(mongo_test_db):
    from core.agents.refinement_orchestrator.acceptance_path import (
        assert_hypothesis_exists,
    )

    with pytest.raises(OrphanStrategyError):
        assert_hypothesis_exists(mongo_test_db, hypothesis_id="hyp_does_not_exist")
