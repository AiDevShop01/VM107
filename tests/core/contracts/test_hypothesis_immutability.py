"""Phase 48 Plan 48-01 — REQ-48-D6. Hypothesis remains immutable WORM.

CONTEXT.md § Decision 6: 'Hypothesis is IMMUTABLE WORM — never mutated, overwritten,
or refined.' BaseContract is already frozen=True; this test enforces the contract at
the schema layer so any future BaseContract relaxation surfaces here first.
"""
import pytest
from pydantic import ValidationError

from core.contracts.schemas import Hypothesis


def _make() -> Hypothesis:
    return Hypothesis(
        hypothesis="When VIX rises above 30, equities trend down for 3 days.",
        variables=["vix", "spx"],
        confidence=0.7,
    )


def test_hypothesis_is_frozen() -> None:
    """Attempting to mutate any field must raise ValidationError (frozen=True)."""
    h = _make()
    with pytest.raises(ValidationError):
        h.confidence = 0.9  # type: ignore[misc]


def test_hypothesis_variables_list_assignment_blocked() -> None:
    """Assignment to a list-typed field is also blocked."""
    h = _make()
    with pytest.raises(ValidationError):
        h.variables = ["spx", "vix", "ndx"]  # type: ignore[misc]


def test_hypothesis_model_copy_returns_new_instance() -> None:
    """Hypothesis supports model_copy(update={...}) for derivation without in-place mutation."""
    h = _make()
    h2 = h.model_copy(update={"confidence": 0.8})
    assert h.confidence == pytest.approx(0.7)
    assert h2.confidence == pytest.approx(0.8)
    assert h is not h2
