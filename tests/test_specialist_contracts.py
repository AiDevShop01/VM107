"""Phase 94 Wave 0 — Specialist agent typed contract RED scaffold.

Becomes GREEN in 94-05 / 94-06.
"""

from __future__ import annotations

import importlib

import pytest


def _require_specialist():
    try:
        return importlib.import_module("agents.growth_analyst.agent")
    except ImportError as exc:
        pytest.fail(
            "Wave 6 (94-06) must create agents/growth_analyst/agent.py. "
            f"ImportError: {exc}"
        )


def test_growth_analyst_invoke_returns_specialist_response_shape():
    _require_specialist()
    pytest.fail(
        "Wave 6 must return a SpecialistResponse-shaped payload from invoke()"
    )
