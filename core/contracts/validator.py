"""
Validation enforcement layer.

Provides format_validation_error() for error formatting and
validate_agent_output() for schema validation against registry.
"""
from typing import Any

from pydantic import ValidationError

from core.contracts.base import BaseContract
from core.contracts.registry import SCHEMA_REGISTRY


def format_validation_error(e: ValidationError) -> dict[str, Any]:
    """
    Format Pydantic ValidationError into structured error dict.

    Extracts field paths and constraint violations without leaking
    Python internals (class names, source paths, etc).

    Args:
        e: Pydantic ValidationError with field-level error details

    Returns:
        Dict with structure:
        {
            "error": "validation_failed",
            "details": [
                {"field": "dotted.path", "type": "error_type", "message": "error message"},
                ...
            ]
        }

    Example:
        >>> try:
        ...     Hypothesis.model_validate({"confidence": 2.0})
        ... except ValidationError as e:
        ...     result = format_validation_error(e)
        >>> result["error"]
        'validation_failed'
        >>> result["details"][0]["field"]
        'confidence'
    """
    details = []

    for error in e.errors():
        # Extract field path (tuple of field names for nested fields)
        # Join with dots for dotted path notation
        field_path = ".".join(str(loc) for loc in error["loc"])

        # Extract error type and message
        error_type = error["type"]
        error_msg = error["msg"]

        details.append({
            "field": field_path,
            "type": error_type,
            "message": error_msg,
        })

    return {
        "error": "validation_failed",
        "details": details,
    }


def validate_agent_output(output_type: str, data: dict[str, Any]) -> BaseContract:
    """
    Validate agent output data against named schema type.

    Looks up schema class from SCHEMA_REGISTRY, then validates data
    using Pydantic's model_validate. Lets ValidationError propagate
    naturally for field-level error details.

    Args:
        output_type: Schema type name (e.g., "hypothesis", "backtest_result")
        data: Dict to validate against schema

    Returns:
        Validated schema instance (Hypothesis, BacktestResult, etc.)

    Raises:
        ValueError: If output_type not in SCHEMA_REGISTRY
        ValidationError: If data validation fails (field-level errors preserved)

    Example:
        >>> data = {"hypothesis": "Price increases", "variables": ["price"], "confidence": 0.8}
        >>> result = validate_agent_output("hypothesis", data)
        >>> isinstance(result, Hypothesis)
        True
    """
    # Look up schema class
    schema_class = SCHEMA_REGISTRY.get(output_type)

    if schema_class is None:
        valid_types = ", ".join(sorted(SCHEMA_REGISTRY.keys()))
        raise ValueError(
            f"Unknown output_type: {output_type}. Valid types: {valid_types}"
        )

    # Validate data - let Pydantic errors propagate naturally
    # No re-raising into new exception - preserves field-level error details
    return schema_class.model_validate(data)
