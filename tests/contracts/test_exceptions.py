"""
Phase 44 SchemaVersionMismatchError exception tests.

Covers:
- .expected / .received attributes
- message format
- isinstance ValueError
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from core.contracts.exceptions import SchemaVersionMismatchError


def test_schema_version_mismatch_attributes():
    """
    SchemaVersionMismatchError exposes .expected, .received, correct message,
    and inherits from ValueError.
    """
    err = SchemaVersionMismatchError(expected=1, received=2)

    assert err.expected == 1
    assert err.received == 2
    assert "expected=1" in str(err)
    assert "received=2" in str(err)
    assert isinstance(err, ValueError)
