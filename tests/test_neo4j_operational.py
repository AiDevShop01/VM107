"""
Tests for Neo4j operational schema and relationship type system.

Validates:
- Fixed relationship type enum (9 members)
- Text-to-enum mapping with confidence scores
- 8-stage status lifecycle
- Status transition validation
- Migration script structure
"""

import pytest
import importlib.util
from pathlib import Path


# Helper to load relationship_types module without Django dependencies
def _load_relationship_types():
    """Load relationship_types module directly to avoid Django init."""
    vm101_path = Path(__file__).parent.parent.parent / "VM101" / "backend"
    rel_types_file = vm101_path / "knowledge" / "graph" / "relationship_types.py"

    spec = importlib.util.spec_from_file_location("relationship_types", rel_types_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_relationship_type_enum_has_nine_members():
    """Verify RelationshipTypeEnum has exactly 9 members."""
    rel_types = _load_relationship_types()
    RelationshipTypeEnum = rel_types.RelationshipTypeEnum

    assert len(RelationshipTypeEnum) == 9
    expected = {
        "CAUSES",
        "INDICATES",
        "CONTRADICTS",
        "PRECEDES",
        "FOLLOWS",
        "INCREASES_PROBABILITY",
        "DECREASES_PROBABILITY",
        "IS_PART_OF",
        "DERIVED_FROM",
    }
    actual = {member.name for member in RelationshipTypeEnum}
    assert actual == expected


def test_map_text_to_relationship_type_for_all_enum_values():
    """Test text-to-enum mapping covers all 9 enum values."""
    rel_types = _load_relationship_types()
    RelationshipTypeEnum = rel_types.RelationshipTypeEnum
    map_text_to_relationship_type = rel_types.map_text_to_relationship_type

    # Test mappings for each enum value
    test_cases = [
        ("causes", RelationshipTypeEnum.CAUSES, 0.9),
        ("leads to", RelationshipTypeEnum.CAUSES, 0.9),
        ("indicates", RelationshipTypeEnum.INDICATES, 0.85),
        ("signals", RelationshipTypeEnum.INDICATES, 0.85),
        ("contradicts", RelationshipTypeEnum.CONTRADICTS, 0.9),
        ("conflicts with", RelationshipTypeEnum.CONTRADICTS, 0.9),
        ("precedes", RelationshipTypeEnum.PRECEDES, 0.85),
        ("comes before", RelationshipTypeEnum.PRECEDES, 0.85),
        ("follows", RelationshipTypeEnum.FOLLOWS, 0.85),
        ("comes after", RelationshipTypeEnum.FOLLOWS, 0.85),
        ("increases probability", RelationshipTypeEnum.INCREASES_PROBABILITY, 0.8),
        ("makes more likely", RelationshipTypeEnum.INCREASES_PROBABILITY, 0.8),
        ("decreases probability", RelationshipTypeEnum.DECREASES_PROBABILITY, 0.8),
        ("makes less likely", RelationshipTypeEnum.DECREASES_PROBABILITY, 0.8),
        ("is part of", RelationshipTypeEnum.IS_PART_OF, 0.85),
        ("belongs to", RelationshipTypeEnum.IS_PART_OF, 0.85),
        ("derived from", RelationshipTypeEnum.DERIVED_FROM, 0.85),
        ("based on", RelationshipTypeEnum.DERIVED_FROM, 0.85),
    ]

    for text, expected_type, expected_confidence in test_cases:
        rel_type, confidence = map_text_to_relationship_type(text)
        assert rel_type == expected_type, f"Failed for text: {text}"
        assert confidence == expected_confidence, f"Wrong confidence for text: {text}"


def test_map_text_to_relationship_type_returns_indicates_for_unknown():
    """Unknown text should map to INDICATES with low confidence."""
    rel_types = _load_relationship_types()
    RelationshipTypeEnum = rel_types.RelationshipTypeEnum
    map_text_to_relationship_type = rel_types.map_text_to_relationship_type

    rel_type, confidence = map_text_to_relationship_type("totally unknown phrase")
    assert rel_type == RelationshipTypeEnum.INDICATES
    assert confidence == 0.5


def test_relationship_status_lifecycle_has_eight_stages():
    """Verify status lifecycle has 8 stages."""
    rel_types = _load_relationship_types()
    RELATIONSHIP_STATUS_LIFECYCLE = rel_types.RELATIONSHIP_STATUS_LIFECYCLE

    assert len(RELATIONSHIP_STATUS_LIFECYCLE) == 8
    expected = [
        "pending",
        "insufficient_data",
        "prior_seeded",
        "weak_evidence",
        "validated",
        "decaying",
        "contradicted",
        "retired",
    ]
    assert RELATIONSHIP_STATUS_LIFECYCLE == expected


def test_is_valid_status_transition_allowed_transitions():
    """Test allowed status transitions."""
    rel_types = _load_relationship_types()
    is_valid_status_transition = rel_types.is_valid_status_transition

    # Test allowed transitions
    allowed = [
        ("pending", "validated"),
        ("pending", "insufficient_data"),
        ("pending", "prior_seeded"),
        ("pending", "weak_evidence"),
        ("insufficient_data", "pending"),
        ("insufficient_data", "weak_evidence"),
        ("prior_seeded", "validated"),
        ("weak_evidence", "validated"),
        ("validated", "decaying"),
        ("validated", "contradicted"),
        ("decaying", "weak_evidence"),
        ("decaying", "retired"),
        ("contradicted", "retired"),
    ]

    for current, target in allowed:
        assert is_valid_status_transition(current, target), \
            f"Should allow {current} -> {target}"


def test_is_valid_status_transition_disallowed_transitions():
    """Test disallowed status transitions."""
    rel_types = _load_relationship_types()
    is_valid_status_transition = rel_types.is_valid_status_transition

    # Test disallowed transitions
    disallowed = [
        ("retired", "validated"),  # Terminal state
        ("retired", "pending"),  # Terminal state
        ("validated", "pending"),  # Can't go backward
        ("weak_evidence", "pending"),  # Can't go backward
        ("unknown_status", "validated"),  # Unknown current
    ]

    for current, target in disallowed:
        assert not is_valid_status_transition(current, target), \
            f"Should NOT allow {current} -> {target}"


def test_migration_script_upgrade_is_callable():
    """Test migration script structure (doesn't execute)."""
    migrations_path = Path(__file__).parent.parent / "core" / "migrations" / "scripts"
    migration_file = migrations_path / "003_neo4j_operational_schema.py"

    spec = importlib.util.spec_from_file_location("migration_003", migration_file)
    migration_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration_module)

    upgrade = migration_module.upgrade
    downgrade = migration_module.downgrade

    # Verify functions are callable
    assert callable(upgrade)
    assert callable(downgrade)

    # Verify they accept context dict
    # Mock context without Neo4j driver should skip gracefully
    mock_context = {}
    upgrade(mock_context)  # Should print "SKIP" but not error
    downgrade(mock_context)  # Should print "SKIP" but not error
