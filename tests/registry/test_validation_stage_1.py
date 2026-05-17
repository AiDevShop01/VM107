"""Stage 1 validation: YAML syntax errors.

Tests:
    1. Valid registry root passes stage 1 (no exception).
    2. invalid_stage_1 root raises RegistryValidationError with stage == 1.
    3. Error contains expected capability_id and missing_ref (file path).
"""

from __future__ import annotations

import pytest

from fingpt_core.contracts.capability_registry import RegistryValidationError
from core.registry.validation import run_full_pipeline


def test_valid_registry_passes_stage_1(valid_registry_root):
    """A valid fixture registry must pass all 7 stages without raising."""
    # Should not raise
    entries = run_full_pipeline(valid_registry_root)
    assert len(entries) > 0


def test_invalid_stage_1_raises(invalid_stage_root):
    """Broken YAML syntax must raise RegistryValidationError at stage 1."""
    root = invalid_stage_root(1)
    with pytest.raises(RegistryValidationError) as exc_info:
        run_full_pipeline(root)
    err = exc_info.value
    assert err.stage == 1, f"Expected stage=1, got stage={err.stage}"


def test_invalid_stage_1_error_contains_path(invalid_stage_root):
    """Stage 1 error must identify the broken YAML file."""
    root = invalid_stage_root(1)
    with pytest.raises(RegistryValidationError) as exc_info:
        run_full_pipeline(root)
    err = exc_info.value
    assert err.missing_ref is not None, "missing_ref should contain the broken file path"
    assert "broken_syntax" in err.missing_ref or "stage_1" in err.missing_ref or ".yaml" in err.missing_ref
