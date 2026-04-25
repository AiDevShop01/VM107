"""
Base contract class for all agent communication schemas.

All contract classes inherit from BaseContract to enforce:
- Immutability (frozen=True)
- Strict schema validation (extra="forbid")
- Validation on assignment (validate_assignment=True)
"""
from pydantic import BaseModel, ConfigDict


class BaseContract(BaseModel):
    """
    Base class for all agent contract schemas.

    Enforces immutability, strict validation, and no unknown fields.
    All agent communication schemas should inherit from this class.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_assignment=True,
    )
