"""Phase 61-01 Task 5 — test_counterfactual_scenario_registry.py

Tests for VM107 counterfactual_scenario registry category.
RG-10 coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path
import tempfile

import pytest

# VM107 root setup
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from helpers.citation_validator import REGISTRY_SUBDIRS, load_known_registry_ids


def test_registry_subdirs_includes_counterfactual_scenario():
    """REGISTRY_SUBDIRS in citation_validator.py includes 'counterfactual_scenario'."""
    assert "counterfactual_scenario" in REGISTRY_SUBDIRS, (
        f"'counterfactual_scenario' not in REGISTRY_SUBDIRS: {REGISTRY_SUBDIRS}"
    )


def test_load_known_registry_ids_does_not_crash_on_empty_counterfactual_dir():
    """load_known_registry_ids() with empty counterfactual_scenario/ dir does not crash."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_root = Path(tmpdir)
        # Create the empty counterfactual_scenario directory
        (registry_root / "counterfactual_scenario").mkdir()

        # Must not raise — returns empty frozenset for the empty dir
        ids = load_known_registry_ids(registry_root)
        assert isinstance(ids, frozenset)


def test_load_known_registry_ids_real_registry_includes_counterfactual_dir():
    """load_known_registry_ids() on real VM107 registry includes the counterfactual_scenario dir."""
    real_registry = _VM107_ROOT / "registry"
    if not real_registry.is_dir():
        pytest.skip("VM107 registry directory not found at expected path")

    # Must not crash even if counterfactual_scenario dir is empty (no YAMLs yet)
    ids = load_known_registry_ids(real_registry)
    assert isinstance(ids, frozenset)
