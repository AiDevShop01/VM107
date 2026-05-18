"""Phase 48 Plan 08b — E2E golden integration tests.

Re-export the Plan 00 / Wave 0 fixtures (mongo_test_db, valid_hypothesis_id,
frozen_registry_snapshot_hash, mock_typed_wrappers, mock_emit_event) into
``tests/integration/`` so the 9 phase-48 goldens can use them without
scavenger-hunting.

Pytest doesn't propagate fixtures from a sibling-tree conftest, so this
shim imports the canonical surface from
``tests/core/agents/refinement_orchestrator/conftest.py``. Single source of
truth preserved; this file is a thin re-export shim (same pattern Plan 03
used at ``tests/core/agents/conftest.py``).
"""
from __future__ import annotations

from tests.core.agents.refinement_orchestrator.conftest import (  # noqa: F401
    frozen_registry_snapshot_hash,
    mock_emit_event,
    mock_typed_wrappers,
    mongo_test_db,
    valid_hypothesis_id,
)
