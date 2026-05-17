"""conftest.py for VM107 capability registry tests.

Provides fixtures for valid and per-stage invalid registry roots.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def valid_registry_root() -> Path:
    """Return the path to the valid fixture registry."""
    return FIXTURES_DIR / "valid"


@pytest.fixture
def invalid_stage_root():
    """Return a factory function that maps stage number to its invalid fixture path."""

    def _path(n: int) -> Path:
        return FIXTURES_DIR / f"invalid_stage_{n}"

    return _path
