"""Stage 4 validation: Dependency graph integrity.

Tests:
    1. Valid registry root passes stage 4 (no exception).
    2. invalid_stage_4 root raises RegistryValidationError with stage == 4.
    3. Error contains expected capability_id ('bad_dependency_tool') and
       missing_ref ('nonexistent_tool').
"""

from __future__ import annotations

import pytest

from fingpt_core.contracts.capability_registry import RegistryValidationError
from core.registry.validation import run_full_pipeline


def test_valid_registry_passes_stage_4(valid_registry_root):
    """A valid fixture registry must pass all 7 stages including stage 4."""
    entries = run_full_pipeline(valid_registry_root)
    assert len(entries) > 0


def test_invalid_stage_4_raises(invalid_stage_root):
    """Unresolved related_capability must raise RegistryValidationError at stage 4."""
    root = invalid_stage_root(4)
    with pytest.raises(RegistryValidationError) as exc_info:
        run_full_pipeline(root)
    err = exc_info.value
    assert err.stage == 4, f"Expected stage=4, got stage={err.stage}"


def test_invalid_stage_4_error_identifies_bad_ref(invalid_stage_root):
    """Stage 4 error must identify the capability with the bad reference and the ref itself."""
    root = invalid_stage_root(4)
    with pytest.raises(RegistryValidationError) as exc_info:
        run_full_pipeline(root)
    err = exc_info.value
    assert err.capability_id == "bad_dependency_tool", (
        f"Expected capability_id='bad_dependency_tool', got {err.capability_id!r}"
    )
    assert err.missing_ref == "nonexistent_tool", (
        f"Expected missing_ref='nonexistent_tool', got {err.missing_ref!r}"
    )
