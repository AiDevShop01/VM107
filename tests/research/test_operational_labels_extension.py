"""Phase 92 Plan 4 — Wave 0 RED test for OPERATIONAL_LABELS extension.

Asserts that the 7 new Phase 92 operational labels are added to the
Phase 41 ``OPERATIONAL_LABELS`` set used by ``OperationalGraphBuilder`` for
node-label validation (Pitfall 5 mitigation — formal extension instead of
silently dropping raw labels).

New members:
- ResearchDocument
- CentralBankStatement
- Speech
- ResearchPaper
- Author
- EconomicIndicator
- Asset

Also asserts the validator still rejects unknown labels.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


pytestmark = pytest.mark.phase92


_GRAPH_DIR = Path("/Volumes/ HardDrive/FinGPT/VM101/backend/knowledge/graph")


def _import_builder_module():
    """Load operational_graph_builder.py standalone.

    The module's ``from .relationship_types import ...`` references inside
    methods need a sibling import to resolve. We stage a synthetic parent
    package so the relative import works without dragging the Django-loading
    ``knowledge.__init__``.
    """
    # 1. Build synthetic parent package ``phase92_graph_pkg``
    pkg_name = "phase92_graph_pkg_under_test"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(_GRAPH_DIR)]
        sys.modules[pkg_name] = pkg

    # 2. Load relationship_types as ``phase92_graph_pkg.relationship_types``
    rel_name = f"{pkg_name}.relationship_types"
    if rel_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            rel_name, _GRAPH_DIR / "relationship_types.py"
        )
        assert spec is not None and spec.loader is not None
        m = importlib.util.module_from_spec(spec)
        sys.modules[rel_name] = m
        spec.loader.exec_module(m)

    # 3. Load operational_graph_builder as a child of the synthetic package
    builder_name = f"{pkg_name}.operational_graph_builder"
    if builder_name in sys.modules:
        del sys.modules[builder_name]
    spec = importlib.util.spec_from_file_location(
        builder_name, _GRAPH_DIR / "operational_graph_builder.py"
    )
    assert spec is not None and spec.loader is not None
    builder_mod = importlib.util.module_from_spec(spec)
    sys.modules[builder_name] = builder_mod
    spec.loader.exec_module(builder_mod)
    return builder_mod


_EXPECTED_NEW = {
    "ResearchDocument",
    "CentralBankStatement",
    "Speech",
    "ResearchPaper",
    "Author",
    "EconomicIndicator",
    "Asset",
}


def test_phase92_labels_present_in_operational_labels():
    mod = _import_builder_module()
    OPERATIONAL_LABELS = mod.OPERATIONAL_LABELS
    missing = _EXPECTED_NEW - set(OPERATIONAL_LABELS)
    assert not missing, (
        f"OPERATIONAL_LABELS missing Phase 92 entries: {missing}. "
        f"Current: {sorted(OPERATIONAL_LABELS)}"
    )


def test_operational_labels_total_count_is_twentyone():
    """14 original Phase 41 labels + 7 Phase 92 additions = 21 total."""
    mod = _import_builder_module()
    assert len(mod.OPERATIONAL_LABELS) == 21, (
        f"OPERATIONAL_LABELS must contain 21 entries (14 + 7); "
        f"got {len(mod.OPERATIONAL_LABELS)}"
    )


def test_add_node_for_research_document_succeeds():
    """OperationalGraphBuilder must accept the new ResearchDocument label.

    We exercise the ``add_node`` helper (alias surface introduced by Plan 4
    that funnels into ``create_node`` after label validation). The plan
    contract requires ``add_node`` to exist on the builder.
    """
    mod = _import_builder_module()
    Builder = mod.OperationalGraphBuilder

    # MagicMock the neo4j driver so create_node doesn't try to talk to the DB.
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    result = MagicMock()
    record = {"id": "rd_001"}
    result.single.return_value = record
    session.run.return_value = result

    b = Builder(neo4j_driver=driver)

    # Use add_node (validation-first alias). Property dict must satisfy
    # create_node's required = {id, name, source_type}; we pass document_id
    # so the plan's intent is exercised but also id+name+source_type which
    # the existing create_node enforces.
    out = b.add_node(
        "ResearchDocument",
        {
            "id": "rd_001",
            "document_id": "rd_001",
            "name": "Test FOMC release 2026-06-17",
            "source_type": "research_document",
            "tier": 1,
        },
    )
    assert out == "rd_001"


def test_add_node_for_unknown_label_still_raises():
    """Validation must still reject labels outside OPERATIONAL_LABELS."""
    mod = _import_builder_module()
    Builder = mod.OperationalGraphBuilder

    driver = MagicMock()
    b = Builder(neo4j_driver=driver)

    with pytest.raises((ValueError, KeyError)):
        b.add_node("UnknownLabel", {"id": "x", "name": "x", "source_type": "x"})
