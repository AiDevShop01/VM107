"""Stage 5 validation: Scope reference integrity.

Tests:
    1. Valid registry root passes stage 5 (no exception).
    2. invalid_stage_5 root raises RegistryValidationError with stage == 5.
    3. Error contains expected capability_id ('bad_scope_tool') and
       missing_ref ('nonexistent_agent').
"""

from __future__ import annotations

import pytest

from fingpt_core.contracts.capability_registry import RegistryValidationError
from core.registry.validation import run_full_pipeline


def test_valid_registry_passes_stage_5(valid_registry_root):
    """A valid fixture registry must pass all 7 stages including stage 5."""
    entries = run_full_pipeline(valid_registry_root)
    assert len(entries) > 0


def test_invalid_stage_5_raises(invalid_stage_root):
    """Unresolved agent_profile must raise RegistryValidationError at stage 5."""
    root = invalid_stage_root(5)
    with pytest.raises(RegistryValidationError) as exc_info:
        run_full_pipeline(root)
    err = exc_info.value
    assert err.stage == 5, f"Expected stage=5, got stage={err.stage}"


def test_invalid_stage_5_error_identifies_bad_profile(invalid_stage_root):
    """Stage 5 error must identify the capability and the unresolvable profile."""
    root = invalid_stage_root(5)
    with pytest.raises(RegistryValidationError) as exc_info:
        run_full_pipeline(root)
    err = exc_info.value
    assert err.capability_id == "bad_scope_tool", (
        f"Expected capability_id='bad_scope_tool', got {err.capability_id!r}"
    )
    assert err.missing_ref == "nonexistent_agent", (
        f"Expected missing_ref='nonexistent_agent', got {err.missing_ref!r}"
    )
