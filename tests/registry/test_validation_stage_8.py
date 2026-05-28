"""Stage 8 validation: Tool provenance fields (Phase 70.5).

Tests:
    1. Valid Phase-70.5-specific fixture registry passes all 8 stages.
    2. Stage 8 hard-fails on missing typical_confidence (RegistryValidationError stage=8).
    3. Stage 8 hard-fails on missing version (RegistryValidationError stage=8).
    4. Stage 8 raises envelope_field_out_of_range for typical_confidence outside [0.0, 1.0]
       — called directly (Stage 2 Pydantic validator rejects 1.5 before pipeline reaches Stage 8).
    5. Stage 8 skips non-tool entries (signal without provenance fields passes Stage 8).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fingpt_core.contracts.capability_registry import (
    CapabilitySnapshotEntry,
    CapabilityStatus,
    CapabilityType,
    ImpactLevel,
    RegistryValidationError,
)
from core.registry.validation import run_full_pipeline, validate_tool_provenance_fields

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
VALID_STAGE_8_ROOT = FIXTURES_DIR / "valid_stage_8"
INVALID_STAGE_8_ROOT = FIXTURES_DIR / "invalid_stage_8"


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_tool_entry(**kwargs) -> CapabilitySnapshotEntry:
    """Return a minimal valid CapabilitySnapshotEntry of type tool with provenance fields."""
    defaults = {
        "id": "test_tool",
        "type": CapabilityType.TOOL,
        "status": CapabilityStatus.REAL,
        "impact_on_decision": ImpactLevel.MEDIUM,
        "deprecated": False,
        "hard_scoped": False,
        "typical_confidence": 0.85,
        "expected_freshness_seconds": 60,
        "is_deterministic": True,
        "version": "1.0.0",
    }
    defaults.update(kwargs)
    return CapabilitySnapshotEntry(**defaults)


# ---------------------------------------------------------------------------
# Test 1: Valid Phase-70.5-specific fixture passes all 8 stages
# ---------------------------------------------------------------------------


def test_valid_stage_8_registry_passes_all_8_stages():
    """A Phase-70.5-specific valid fixture with all 4 provenance fields must pass all 8 stages."""
    entries = run_full_pipeline(VALID_STAGE_8_ROOT)
    assert len(entries) > 0, "Expected at least 1 entry from valid_stage_8 fixture"
    # Verify the tool entry has provenance fields populated
    tool_entries = [e for e in entries if e.type == CapabilityType.TOOL]
    assert len(tool_entries) == 1, f"Expected exactly 1 tool entry, got {len(tool_entries)}"
    entry = tool_entries[0]
    assert entry.typical_confidence is not None
    assert entry.expected_freshness_seconds is not None
    assert entry.is_deterministic is not None
    assert entry.version is not None


# ---------------------------------------------------------------------------
# Test 2: Missing typical_confidence triggers Stage 8
# ---------------------------------------------------------------------------


def test_stage_8_hard_fails_on_missing_typical_confidence():
    """run_full_pipeline against a fixture missing typical_confidence must raise stage=8."""
    # Build an invalid_stage_8 root that is otherwise valid (has agent_profile from valid fixture)
    # We need to construct a single-file invalid registry.
    # Use direct validate_tool_provenance_fields call to test Stage 8 in isolation.
    entry = _make_tool_entry(typical_confidence=None)
    with pytest.raises(RegistryValidationError) as exc_info:
        validate_tool_provenance_fields([entry])
    err = exc_info.value
    assert err.stage == 8, f"Expected stage=8, got stage={err.stage}"
    assert err.type == "missing_envelope_field", f"Expected type='missing_envelope_field', got {err.type!r}"
    assert err.missing_ref == "typical_confidence", (
        f"Expected missing_ref='typical_confidence', got {err.missing_ref!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: Missing version triggers Stage 8
# ---------------------------------------------------------------------------


def test_stage_8_hard_fails_on_missing_version():
    """Tool entry missing version must raise RegistryValidationError at stage=8."""
    entry = _make_tool_entry(version=None)
    with pytest.raises(RegistryValidationError) as exc_info:
        validate_tool_provenance_fields([entry])
    err = exc_info.value
    assert err.stage == 8, f"Expected stage=8, got stage={err.stage}"
    assert err.type == "missing_envelope_field", f"Expected type='missing_envelope_field', got {err.type!r}"
    assert err.missing_ref == "version", (
        f"Expected missing_ref='version', got {err.missing_ref!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: Out-of-range typical_confidence triggers Stage 8
# ---------------------------------------------------------------------------


def test_stage_8_raises_on_out_of_range_confidence():
    """Stage 8 must raise envelope_field_out_of_range when typical_confidence > 1.0.

    NOTE: CapabilitySnapshotEntry.validate_typical_confidence (Phase 70.5 Plan 01 field_validator)
    rejects out-of-range values at Pydantic construction time, so we bypass construction and
    test validate_tool_provenance_fields directly with a monkey-patched entry. We use
    object.__setattr__ to override the frozen model field for the test scenario — this tests
    the Stage 8 guard independently from the Plan 01 Pydantic validator.

    In practice, both guards fire: Plan 01 at Stage 2 (construction), Stage 8 at boot-check.
    """
    # Create a valid entry first, then override the value to test Stage 8's own check
    entry = _make_tool_entry(typical_confidence=0.85)
    # Bypass the frozen model to set an out-of-range value directly
    object.__setattr__(entry, "typical_confidence", 1.5)
    with pytest.raises(RegistryValidationError) as exc_info:
        validate_tool_provenance_fields([entry])
    err = exc_info.value
    assert err.stage == 8, f"Expected stage=8, got stage={err.stage}"
    assert err.type == "envelope_field_out_of_range", (
        f"Expected type='envelope_field_out_of_range', got {err.type!r}"
    )
    assert err.missing_ref == "typical_confidence", (
        f"Expected missing_ref='typical_confidence', got {err.missing_ref!r}"
    )


# ---------------------------------------------------------------------------
# Test 5: Stage 8 skips non-tool entries
# ---------------------------------------------------------------------------


def test_stage_8_skips_non_tool_entries():
    """Stage 8 must silently pass entries that are not type=tool, even without provenance fields."""
    # A signal entry without any provenance fields must pass Stage 8 without error
    signal_entry = CapabilitySnapshotEntry(
        id="test_signal",
        type=CapabilityType.SIGNAL,
        status=CapabilityStatus.REAL,
        impact_on_decision=ImpactLevel.LOW,
        deprecated=False,
        hard_scoped=False,
        # No provenance fields — Stage 8 must skip non-tool types
        typical_confidence=None,
        expected_freshness_seconds=None,
        is_deterministic=None,
        version=None,
    )
    # Should not raise
    result = validate_tool_provenance_fields([signal_entry])
    assert result == [signal_entry]


# ---------------------------------------------------------------------------
# Test 6: Missing expected_freshness_seconds triggers Stage 8
# ---------------------------------------------------------------------------


def test_stage_8_hard_fails_on_missing_expected_freshness_seconds():
    """Tool entry missing expected_freshness_seconds must raise RegistryValidationError at stage=8."""
    entry = _make_tool_entry(expected_freshness_seconds=None)
    with pytest.raises(RegistryValidationError) as exc_info:
        validate_tool_provenance_fields([entry])
    err = exc_info.value
    assert err.stage == 8, f"Expected stage=8, got stage={err.stage}"
    assert err.type == "missing_envelope_field"
    assert err.missing_ref == "expected_freshness_seconds"


# ---------------------------------------------------------------------------
# Test 7: Missing is_deterministic triggers Stage 8
# ---------------------------------------------------------------------------


def test_stage_8_hard_fails_on_missing_is_deterministic():
    """Tool entry missing is_deterministic must raise RegistryValidationError at stage=8."""
    entry = _make_tool_entry(is_deterministic=None)
    with pytest.raises(RegistryValidationError) as exc_info:
        validate_tool_provenance_fields([entry])
    err = exc_info.value
    assert err.stage == 8, f"Expected stage=8, got stage={err.stage}"
    assert err.type == "missing_envelope_field"
    assert err.missing_ref == "is_deterministic"


# ---------------------------------------------------------------------------
# Test 8: Valid entry with all 4 fields passes Stage 8
# ---------------------------------------------------------------------------


def test_stage_8_passes_on_complete_tool_entry():
    """Tool entry with all 4 fields populated and in-range must pass Stage 8 without error."""
    entry = _make_tool_entry()
    result = validate_tool_provenance_fields([entry])
    assert result == [entry]


# ---------------------------------------------------------------------------
# Test 9: Sorting by (type, id) is deterministic — first failure is alphabetically first
# ---------------------------------------------------------------------------


def test_stage_8_errors_sorted_deterministically():
    """Stage 8 must report the alphabetically-first failing tool id, consistent with LD-2."""
    entry_b = _make_tool_entry(id="beta_tool", typical_confidence=None)
    entry_a = _make_tool_entry(id="alpha_tool", typical_confidence=None)
    # Pass beta first, alpha second — Stage 8 must sort and fail on alpha_tool first
    with pytest.raises(RegistryValidationError) as exc_info:
        validate_tool_provenance_fields([entry_b, entry_a])
    err = exc_info.value
    assert err.capability_id == "alpha_tool", (
        f"Stage 8 should fail on 'alpha_tool' first (alphabetical); got {err.capability_id!r}"
    )
