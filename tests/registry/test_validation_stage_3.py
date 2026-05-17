"""Stage 3 validation: Identity uniqueness.

Tests:
    1. Valid registry root passes stage 3 (no exception).
    2. invalid_stage_3 root raises RegistryValidationError with stage == 3.
    3. Error contains expected capability_id ('duplicate_id') and
       missing_ref (the type of the first occurrence).
"""

from __future__ import annotations

import pytest

from fingpt_core.contracts.capability_registry import RegistryValidationError
from core.registry.validation import run_full_pipeline


def test_valid_registry_passes_stage_3(valid_registry_root):
    """A valid fixture registry must pass all 7 stages including stage 3."""
    entries = run_full_pipeline(valid_registry_root)
    assert len(entries) > 0


def test_invalid_stage_3_raises(invalid_stage_root):
    """Duplicate id across type folders must raise RegistryValidationError at stage 3."""
    root = invalid_stage_root(3)
    with pytest.raises(RegistryValidationError) as exc_info:
        run_full_pipeline(root)
    err = exc_info.value
    assert err.stage == 3, f"Expected stage=3, got stage={err.stage}"


def test_invalid_stage_3_error_identifies_duplicate(invalid_stage_root):
    """Stage 3 error must identify the duplicate capability_id."""
    root = invalid_stage_root(3)
    with pytest.raises(RegistryValidationError) as exc_info:
        run_full_pipeline(root)
    err = exc_info.value
    assert err.capability_id == "duplicate_id", (
        f"Expected capability_id='duplicate_id', got {err.capability_id!r}"
    )
    assert err.missing_ref is not None, "missing_ref should contain the type of first occurrence"
