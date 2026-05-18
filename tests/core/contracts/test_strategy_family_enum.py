"""Phase 48 Plan 48-01 — REQ-48-D10. StrategyFamily enum + StrategySpec.strategy_family REQUIRED."""
import pytest
from pydantic import ValidationError

from core.contracts.schemas import StrategyFamily, StrategySpec


def test_strategy_family_has_five_starter_values() -> None:
    """REQ-48-D10: 5 starter family values."""
    members = {m.name for m in StrategyFamily}
    assert members == {
        "BREAKOUT",
        "MEAN_REVERSION",
        "TREND_CONTINUATION",
        "AUCTION_ROTATION",
        "VOLATILITY_EXPANSION",
    }


def test_strategy_family_values_are_strings() -> None:
    """StrEnum — values match names (uppercase)."""
    for m in StrategyFamily:
        assert isinstance(m.value, str)
        assert m.value == m.name


def test_strategy_spec_strategy_family_is_required() -> None:
    """REQ-48-D10: omitting strategy_family raises ValidationError (REQUIRED, not Optional)."""
    with pytest.raises(ValidationError):
        StrategySpec(
            name="dummy",
            features=["f1"],
            rules=["r1"],
            timeframes=["1m"],
            version="0.1.0",
            # strategy_family deliberately omitted
        )


def test_strategy_spec_accepts_valid_family() -> None:
    """Constructing with a valid StrategyFamily succeeds and round-trips."""
    spec = StrategySpec(
        name="brk",
        features=["f1"],
        rules=["r1"],
        timeframes=["1m"],
        version="0.1.0",
        strategy_family=StrategyFamily.BREAKOUT,
    )
    assert spec.strategy_family is StrategyFamily.BREAKOUT
    dumped = spec.model_dump()
    rehydrated = StrategySpec.model_validate(dumped)
    assert rehydrated.strategy_family is StrategyFamily.BREAKOUT


def test_strategy_spec_rejects_unknown_family() -> None:
    """ValidationError on unknown family literal."""
    with pytest.raises(ValidationError):
        StrategySpec(
            name="brk",
            features=["f1"],
            rules=["r1"],
            timeframes=["1m"],
            version="0.1.0",
            strategy_family="NOT_A_REAL_FAMILY",  # type: ignore[arg-type]
        )
