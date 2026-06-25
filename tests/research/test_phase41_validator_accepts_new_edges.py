"""Phase 92 Plan 4 — Wave 0 RED test for Phase 41 edge validator acceptance.

The Phase 41 ``OperationalGraphBuilder.create_or_update_relationship`` method
validates ``rel_type`` against ``{e.value for e in RelationshipTypeEnum}
| OPERATIONAL_RELATIONSHIPS | HYBRID_BRIDGE_RELATIONSHIPS``. After Plan 4 adds
3 new enum members the validator must accept edges of:

- ``discusses_indicator``
- ``affects_asset``
- ``authored_by``

We exercise this via the same internal valid-types check the
create_or_update_relationship method computes — if the enum addition is
formal the check passes; if someone tried to ship via raw Cypher it would
not.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


pytestmark = pytest.mark.phase92


_REL_TYPES_PATH = Path(
    "/Volumes/ HardDrive/FinGPT/VM101/backend/knowledge/graph/relationship_types.py"
)


def _load_rel_types_module():
    spec = importlib.util.spec_from_file_location(
        "phase92_rel_types_validator_under_test", _REL_TYPES_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _valid_rel_types() -> set[str]:
    rel_mod = _load_rel_types_module()
    RelationshipTypeEnum = rel_mod.RelationshipTypeEnum
    OPERATIONAL_RELATIONSHIPS = rel_mod.OPERATIONAL_RELATIONSHIPS
    HYBRID_BRIDGE_RELATIONSHIPS = rel_mod.HYBRID_BRIDGE_RELATIONSHIPS
    return (
        {e.value for e in RelationshipTypeEnum}
        | OPERATIONAL_RELATIONSHIPS
        | HYBRID_BRIDGE_RELATIONSHIPS
    )


@pytest.mark.parametrize(
    "rel_type",
    ["discusses_indicator", "affects_asset", "authored_by"],
)
def test_phase92_edge_types_pass_phase41_validator(rel_type: str):
    """No ``unknown_type=<rel_type>`` rejection from Phase 41 validation set."""
    valid = _valid_rel_types()
    assert rel_type in valid, (
        f"Phase 41 validation set rejects Phase 92 edge type {rel_type!r}. "
        f"Add it to RelationshipTypeEnum (NOT raw Cypher). Current valid set: "
        f"{sorted(valid)}"
    )


def test_phase41_existing_types_unchanged():
    """Phase 41 originals must still be in the valid set after the extension
    (regression guard — Pitfall 5 says the extension must be ADDITIVE)."""
    valid = _valid_rel_types()
    for original in (
        "causes",
        "indicates",
        "contradicts",
        "precedes",
        "follows",
        "is_part_of",
        "derived_from",
    ):
        assert original in valid, f"Phase 41 original type {original!r} was lost during extension"
