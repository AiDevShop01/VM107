"""Phase 94 Wave 0 — Executive Summary event subscription + cache RED scaffold.

Becomes GREEN in 94-06.
"""

from __future__ import annotations

import importlib

import pytest


def _require_agent():
    try:
        return importlib.import_module("agents.executive_summary.agent")
    except ImportError as exc:
        pytest.fail(
            "Wave 6 (94-06) must create agents/executive_summary/agent.py. "
            f"ImportError: {exc}"
        )


def test_executive_summary_regens_only_on_high_plus_events():
    _require_agent()
    pytest.fail("Wave 6 must regen on HIGH or CRITICAL events only")


def test_low_severity_event_does_not_trigger_regen():
    _require_agent()
    pytest.fail("Wave 6 must NOT regen on LOW severity events")


def test_cached_summary_returned_when_no_new_high_event():
    _require_agent()
    pytest.fail("Wave 6 must return cached summary if no new HIGH+ event")
