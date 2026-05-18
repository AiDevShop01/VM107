"""
Phase 44 contract schema tests.

Covers:
- Hypothesis backward-compat with source_envelope_id optional field
- Hypothesis schema_version default
- StrategySpec schema_version default
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest
import pydantic

from core.contracts.schemas import Hypothesis, StrategySpec


def test_hypothesis_source_envelope():
    """
    Backward-compat: Hypothesis without source_envelope_id defaults to None.
    Explicit value accepted. Type rejection on non-str.
    """
    # Backward compat — no source_envelope_id provided
    h = Hypothesis(hypothesis="example strategy signal", variables=["x"], confidence=0.5)
    assert h.source_envelope_id is None

    # Explicit value accepted
    h2 = Hypothesis(
        hypothesis="example strategy signal",
        variables=["x"],
        confidence=0.5,
        source_envelope_id="env_idea_123",
    )
    assert h2.source_envelope_id == "env_idea_123"

    # Type rejection: non-str value raises ValidationError
    with pytest.raises(pydantic.ValidationError):
        Hypothesis(
            hypothesis="example strategy signal",
            variables=["x"],
            confidence=0.5,
            source_envelope_id=42,
        )


def test_hypothesis_schema_version_default():
    """Hypothesis.schema_version defaults to 1."""
    h = Hypothesis(hypothesis="test hypothesis text", variables=["var_a"], confidence=0.7)
    assert h.schema_version == 1


def test_strategy_spec_schema_version_default():
    """StrategySpec.schema_version defaults to 1.

    Phase 48 Plan 48-01: strategy_family REQUIRED — added here for fixture validity.
    """
    from core.contracts.schemas import StrategyFamily

    s = StrategySpec(
        name="RSI crossover",
        features=["rsi_14"],
        rules=["rsi > 70 sell"],
        timeframes=["1h"],
        version="1.0.0",
        strategy_family=StrategyFamily.MEAN_REVERSION,
    )
    assert s.schema_version == 1
