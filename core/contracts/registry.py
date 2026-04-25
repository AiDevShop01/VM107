"""
Schema registry and message validation.

Provides SCHEMA_REGISTRY dict for O(1) message type to schema class resolution,
and validate_message() function for payload validation.
"""
from typing import TYPE_CHECKING

from core.contracts.base import BaseContract
from core.contracts.schemas import (
    A2AMessage,
    BacktestResult,
    CodeModule,
    Critique,
    Hypothesis,
    StrategySpec,
)

# Type checking import to avoid circular dependency issues
if TYPE_CHECKING:
    pass


# Schema registry: message_type -> schema class
# O(1) dict lookup for fast schema resolution
SCHEMA_REGISTRY: dict[str, type[BaseContract]] = {
    "hypothesis": Hypothesis,
    "strategy_spec": StrategySpec,
    "code_module": CodeModule,
    "backtest_result": BacktestResult,
    "critique": Critique,
}


def validate_message(msg: A2AMessage) -> BaseContract:
    """
    Validate A2AMessage payload against registered schema.

    Resolves schema class from SCHEMA_REGISTRY using message_type,
    then validates payload dict using Pydantic's model_validate.

    Args:
        msg: A2AMessage envelope with payload to validate

    Returns:
        Validated schema instance (Hypothesis, StrategySpec, etc.)

    Raises:
        ValueError: If message_type not in SCHEMA_REGISTRY
        ValidationError: If payload validation fails (field-level errors preserved)
    """
    # Look up schema class
    schema_class = SCHEMA_REGISTRY.get(msg.message_type)

    if schema_class is None:
        valid_types = ", ".join(sorted(SCHEMA_REGISTRY.keys()))
        raise ValueError(
            f"Unknown message_type: {msg.message_type}. Valid types: {valid_types}"
        )

    # Validate payload - let Pydantic errors propagate naturally
    # No re-raising into new exception - preserves field-level error details
    return schema_class.model_validate(msg.payload)
