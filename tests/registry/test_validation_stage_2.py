"""Stage 2 validation: Pydantic schema validation.

Tests:
    1. Valid registry root passes stage 2 (no exception).
    2. invalid_stage_2 root raises RegistryValidationError with stage == 2.
    3. Error contains expected capability_id ('missing_impact_tool') and
       missing_ref ('impact_on_decision').
"""

from __future__ import annotations

import pytest

from fingpt_core.contracts.capability_registry import RegistryValidationError
from core.registry.validation import run_full_pipeline


def test_valid_registry_passes_stage_2(valid_registry_root):
    """A valid fixture registry must pass all 7 stages including stage 2."""
    entries = run_full_pipeline(valid_registry_root)
    assert len(entries) > 0


def test_invalid_stage_2_raises(invalid_stage_root):
    """YAML missing required field must raise RegistryValidationError at stage 2."""
    root = invalid_stage_root(2)
    with pytest.raises(RegistryValidationError) as exc_info:
        run_full_pipeline(root)
    err = exc_info.value
    assert err.stage == 2, f"Expected stage=2, got stage={err.stage}"


def test_invalid_stage_2_error_contains_capability_and_field(invalid_stage_root):
    """Stage 2 error must identify the bad capability and the missing field."""
    root = invalid_stage_root(2)
    with pytest.raises(RegistryValidationError) as exc_info:
        run_full_pipeline(root)
    err = exc_info.value
    assert err.capability_id == "missing_impact_tool", (
        f"Expected capability_id='missing_impact_tool', got {err.capability_id!r}"
    )
    assert err.missing_ref == "impact_on_decision", (
        f"Expected missing_ref='impact_on_decision', got {err.missing_ref!r}"
    )
