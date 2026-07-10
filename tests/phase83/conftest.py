"""Phase 83 VM107 conftest — shared fixtures for the FRED API rebuild test substrate.

This conftest provides import shims and placeholder fixtures.
Full FRED HTTP mock fixtures land in Task 4 (per-VM conftests).
"""
from __future__ import annotations

import os

# Fail-fast modules (services/macro_calendar_client, services/snapshot_writer,
# emitters/intelligence_feed_macro_emitter) read these via os.environ[...] at
# import time per the env-driven / no-fallback contract. Seed harmless test
# values before any test module imports them.
os.environ.setdefault("MACRO_EMITTER_CALENDAR_URL", "http://test-calendar.local")
os.environ.setdefault("MACRO_EMITTER_SNAPSHOT_URL", "http://test-snapshot.local")
os.environ.setdefault("MACRO_EMITTER_REDIS_URL", "redis://test-redis.local:6379/0")
os.environ.setdefault("VM107_SERVICE_JWT", "test-jwt-not-real")

import pytest  # noqa: E402


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
