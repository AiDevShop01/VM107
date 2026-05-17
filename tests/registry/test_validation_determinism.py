"""Determinism test: identical inputs produce identical RegistryValidationError.

Runs the full pipeline 5 times on the invalid_stage_3 fixture (duplicate id)
and asserts that each run produces the same (stage, capability_id, missing_ref) tuple.

This verifies LD-2 deterministic ordering: any given invalid graph always produces
the same error sequence, enabling reproducible test failures and CI consistency.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fingpt_core.contracts.capability_registry import RegistryValidationError
from core.registry.validation import run_full_pipeline


def test_deterministic_error_on_invalid_stage_3(invalid_stage_root):
    """Running pipeline 5 times on invalid_stage_3 produces identical errors."""
    root = invalid_stage_root(3)

    errors: list[tuple[int, str | None, str | None]] = []
    for _ in range(5):
        with pytest.raises(RegistryValidationError) as exc_info:
            run_full_pipeline(root)
        err = exc_info.value
        errors.append((err.stage, err.capability_id, err.missing_ref))

    # All 5 runs must produce exactly the same error tuple
    assert len(set(errors)) == 1, (
        f"Expected identical error tuples across 5 runs, got {errors}"
    )

    stage, cap_id, missing = errors[0]
    assert stage == 3, f"All runs must raise at stage 3, got stage={stage}"
    assert cap_id == "duplicate_id", f"Expected capability_id='duplicate_id', got {cap_id!r}"
