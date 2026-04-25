"""
Tests for BaseContract immutability and validation.

These tests verify that BaseContract enforces:
- frozen=True (no attribute mutation after creation)
- extra="forbid" (no unknown fields accepted)
- validate_assignment=True (validation on assignment)
"""
import pytest
from pydantic import ValidationError

from core.contracts.base import BaseContract


def test_frozen_rejects_mutation():
    """BaseContract should reject attribute mutation after creation."""

    class TestContract(BaseContract):
        name: str
        value: int

    instance = TestContract(name="test", value=42)

    with pytest.raises(ValidationError) as exc_info:
        instance.value = 100

    assert "frozen" in str(exc_info.value).lower()


def test_extra_forbid_rejects_unknown_fields():
    """BaseContract should reject unknown fields."""

    class TestContract(BaseContract):
        name: str

    with pytest.raises(ValidationError) as exc_info:
        TestContract(name="test", unknown_field="should fail")

    assert "extra" in str(exc_info.value).lower() or "unexpected" in str(exc_info.value).lower()


def test_valid_creation():
    """BaseContract should allow valid instance creation."""

    class TestContract(BaseContract):
        name: str
        value: int

    instance = TestContract(name="test", value=42)

    assert instance.name == "test"
    assert instance.value == 42


def test_inherits_config():
    """Subclasses should inherit frozen/forbid/validate_assignment config."""

    class SubContract(BaseContract):
        field1: str
        field2: int

    # Test frozen is inherited
    instance = SubContract(field1="test", field2=10)
    with pytest.raises(ValidationError):
        instance.field1 = "mutated"

    # Test extra="forbid" is inherited
    with pytest.raises(ValidationError):
        SubContract(field1="test", field2=10, extra_field="bad")


def test_model_dump_works():
    """BaseContract should support model_dump for serialization."""

    class TestContract(BaseContract):
        name: str
        value: int

    instance = TestContract(name="test", value=42)
    data = instance.model_dump()

    assert data == {"name": "test", "value": 42}


def test_model_validate_works():
    """BaseContract should support model_validate for deserialization."""

    class TestContract(BaseContract):
        name: str
        value: int

    data = {"name": "test", "value": 42}
    instance = TestContract.model_validate(data)

    assert instance.name == "test"
    assert instance.value == 42


def test_validate_assignment_enforced():
    """BaseContract should validate on assignment if mutation were allowed."""
    # This is a conceptual test - since frozen=True prevents assignment,
    # we can't directly test validate_assignment. But we verify the config is set.

    class TestContract(BaseContract):
        name: str

    # The config should have validate_assignment=True
    assert TestContract.model_config["validate_assignment"] is True


def test_nested_contracts_work():
    """BaseContract should support nesting."""

    class Inner(BaseContract):
        value: int

    class Outer(BaseContract):
        inner: Inner
        name: str

    instance = Outer(inner=Inner(value=42), name="test")

    assert instance.inner.value == 42
    assert instance.name == "test"
