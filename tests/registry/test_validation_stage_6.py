"""Stage 6 validation: Contract resolution.

Tests:
    1. Valid registry root passes stage 6 (no exception).
    2. invalid_stage_6 root raises RegistryValidationError with stage == 6.
    3. Error contains expected capability_id ('bad_contract_tool') and
       missing_ref ('nonexistent.module.NotAClass').
"""

from __future__ import annotations

import pytest

from fingpt_core.contracts.capability_registry import RegistryValidationError
from core.registry.validation import run_full_pipeline


def test_valid_registry_passes_stage_6(valid_registry_root):
    """A valid fixture registry (null contracts) must pass stage 6 without raising."""
    entries = run_full_pipeline(valid_registry_root)
    assert len(entries) > 0


def test_invalid_stage_6_raises(invalid_stage_root):
    """Unresolvable contract class must raise RegistryValidationError at stage 6."""
    root = invalid_stage_root(6)
    with pytest.raises(RegistryValidationError) as exc_info:
        run_full_pipeline(root)
    err = exc_info.value
    assert err.stage == 6, f"Expected stage=6, got stage={err.stage}"


def test_invalid_stage_6_error_identifies_bad_contract(invalid_stage_root):
    """Stage 6 error must identify the capability and the unresolvable contract dotted path."""
    root = invalid_stage_root(6)
    with pytest.raises(RegistryValidationError) as exc_info:
        run_full_pipeline(root)
    err = exc_info.value
    assert err.capability_id == "bad_contract_tool", (
        f"Expected capability_id='bad_contract_tool', got {err.capability_id!r}"
    )
    assert err.missing_ref == "nonexistent.module.NotAClass", (
        f"Expected missing_ref='nonexistent.module.NotAClass', got {err.missing_ref!r}"
    )
