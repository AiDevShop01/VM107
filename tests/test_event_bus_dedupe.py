"""Phase 94 Wave 0 — Event bus dedupe RED scaffold.

Becomes GREEN in 94-02.
"""

from __future__ import annotations

import importlib

import pytest


def _require_bus():
    try:
        return importlib.import_module("core.event_bus.bus")
    except ImportError as exc:
        pytest.fail(
            "Wave 2 (94-02) must create core/event_bus/bus.py. "
            f"ImportError: {exc}"
        )


def test_same_event_id_processed_once():
    _require_bus()
    pytest.fail(
        "Wave 2 must dedupe by event_id — second publish of the same "
        "event_id must not trigger subscribers."
    )
