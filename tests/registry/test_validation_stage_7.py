"""Stage 7 validation: Cross-type linkage rules.

Tests:
    1. Valid registry root passes stage 7 (no exception).
    2. invalid_stage_7 root raises RegistryValidationError with stage == 7.
    3. Error contains expected capability_id ('bad_applies_to_skill') and
       missing_ref ('nonexistent_agent_for_stage7').
"""

from __future__ import annotations

import pytest

from fingpt_core.contracts.capability_registry import RegistryValidationError
from core.registry.validation import run_full_pipeline


def test_valid_registry_passes_stage_7(valid_registry_root):
    """A valid fixture registry must pass all 7 stages including stage 7."""
    entries = run_full_pipeline(valid_registry_root)
    assert len(entries) > 0


def test_invalid_stage_7_raises(invalid_stage_root):
    """Skill referencing nonexistent agent_profile must raise RegistryValidationError at stage 7."""
    root = invalid_stage_root(7)
    with pytest.raises(RegistryValidationError) as exc_info:
        run_full_pipeline(root)
    err = exc_info.value
    assert err.stage == 7, f"Expected stage=7, got stage={err.stage}"


def test_invalid_stage_7_error_identifies_bad_profile(invalid_stage_root):
    """Stage 7 error must identify the skill and the unresolvable applies_to_profiles entry."""
    root = invalid_stage_root(7)
    with pytest.raises(RegistryValidationError) as exc_info:
        run_full_pipeline(root)
    err = exc_info.value
    assert err.capability_id == "bad_applies_to_skill", (
        f"Expected capability_id='bad_applies_to_skill', got {err.capability_id!r}"
    )
    assert err.missing_ref == "nonexistent_agent_for_stage7", (
        f"Expected missing_ref='nonexistent_agent_for_stage7', got {err.missing_ref!r}"
    )
