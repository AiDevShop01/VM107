"""Phase 83 VM107 conftest — shared fixtures for the FRED API rebuild test substrate.

This conftest provides import shims and placeholder fixtures.
Full FRED HTTP mock fixtures land in Task 4 (per-VM conftests).
"""
from __future__ import annotations

import pytest


@pytest.fixture
def mock_fred_release_dates_response():
    """Placeholder — full fixture set landed in Task 4 VM101 conftest."""
    return {
        "realtime_start": "2026-06-04",
        "realtime_end": "2026-09-04",
        "release_dates": [
            {"release_id": 21, "date": "2026-06-13"},
            {"release_id": 21, "date": "2026-07-15"},
        ],
    }
