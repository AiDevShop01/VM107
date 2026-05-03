"""
Phase 44 contract exceptions.

Defines strict fail-fast exceptions for schema version enforcement.
Per CONTEXT.md § A2A Envelope Structure: NO implicit migration.
"""
from __future__ import annotations


class SchemaVersionMismatchError(ValueError):
    """Raised when a typed payload's schema_version does not match expected.

    Phase 44: strict fail-fast — NO implicit migration. See CONTEXT.md § A2A Envelope Structure.
    """

    def __init__(self, expected: int, received: int) -> None:
        self.expected = expected
        self.received = received
        super().__init__(f"Schema version mismatch: expected={expected}, received={received}")
