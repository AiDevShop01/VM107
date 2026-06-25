"""Phase 92 Plan 4 — Wave 0 RED test for RelationshipTypeEnum extension.

Asserts that the 3 new Phase 92 relationship types are added to the
Phase 41 ``RelationshipTypeEnum``:

- ``DISCUSSES_INDICATOR = 'discusses_indicator'``
- ``AFFECTS_ASSET     = 'affects_asset'``
- ``AUTHORED_BY       = 'authored_by'``

Total enum count must be exactly 12 (was 9, +3 = Pitfall 5 formal extension —
NOT silently added via raw Cypher).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


pytestmark = pytest.mark.phase92


# Load the standalone Phase 41 module directly from file. We bypass the
# ``knowledge`` package ``__init__`` (which triggers Django ORM loading) so the
# pure-Python enum module can be exercised from the VM107 host shell.
_REL_TYPES_PATH = Path(
    "/Volumes/ HardDrive/FinGPT/VM101/backend/knowledge/graph/relationship_types.py"
)


def _load_relationship_types_module():
    spec = importlib.util.spec_from_file_location(
        "phase92_rel_types_under_test", _REL_TYPES_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _import_enum():
    return _load_relationship_types_module().RelationshipTypeEnum


def test_discusses_indicator_member_exists():
    Enum = _import_enum()
    assert hasattr(Enum, "DISCUSSES_INDICATOR")
    assert Enum.DISCUSSES_INDICATOR.value == "discusses_indicator"


def test_affects_asset_member_exists():
    Enum = _import_enum()
    assert hasattr(Enum, "AFFECTS_ASSET")
    assert Enum.AFFECTS_ASSET.value == "affects_asset"


def test_authored_by_member_exists():
    Enum = _import_enum()
    assert hasattr(Enum, "AUTHORED_BY")
    assert Enum.AUTHORED_BY.value == "authored_by"


def test_enum_count_is_exactly_twelve():
    """9 original Phase 41 members + 3 Phase 92 additions = 12 total."""
    Enum = _import_enum()
    members = list(Enum)
    assert len(members) == 12, (
        f"RelationshipTypeEnum must contain exactly 12 members "
        f"(9 Phase 41 + 3 Phase 92); got {len(members)}: "
        f"{[m.value for m in members]}"
    )
