"""Shared pytest fixtures for Phase 90 — Macro Forecast Intelligence Engine (VM107 side).

VM107 owns the narrative / explanation layer (Plan 6) and the Brain-B5 pass-through
contract. This conftest exposes:

- `forecast_result_stub` — the acceptance-contract dict that downstream consumers
  (Phase 89 counterfactual engine, Phase 85 §11 widget) expect to round-trip.
- `b5_stub` — a Phase 89 Brain B5 self-eval wrapper stand-in that passes payloads
  through unchanged. Used by Plan 6 tests to assert the narrator agent does NOT
  smuggle a `ForecastResult` out of an explanation envelope (LD-90-1 lock).
- `phase90_marker` — exposes the canonical `pytest.mark.phase90` marker object.

Fixture locking notes:
- The stub JSON file (`fixtures/forecast_result_stub.json`) is the single source of
  truth for the `ForecastResult` shape on VM107. If the shape changes, update the
  JSON and the VM102 producers in lockstep — do NOT hand-edit fixtures inline
  inside individual tests.
- `b5_stub` deliberately implements the minimum surface area needed by Plan 6 tests
  (a callable that returns its input). Tests that need richer Brain-B5 behaviour
  must monkey-patch from a per-test fixture rather than mutating this shared one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

# Module-level marker every test under tests/phase90/ inherits.
pytestmark = pytest.mark.phase90

# Resolve the bundled fixtures dir once — relative to *this* file, so the
# tests don't break if pytest is invoked from a different cwd.
_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_FORECAST_RESULT_STUB_PATH = _FIXTURES_DIR / "forecast_result_stub.json"


# ---------------------------------------------------------------------------
# ForecastResult acceptance contract fixture
# ---------------------------------------------------------------------------
@pytest.fixture
def forecast_result_stub() -> Dict[str, Any]:
    """Load and parse the canonical ForecastResult stub JSON.

    Returns the raw dict (NOT a Pydantic instance). Plan 6 tests should
    assert that this exact shape passes the `ForecastResult` validator
    that Plan 1 ships. If the validator rejects this stub, the contract
    has drifted and one side (validator OR fixture) is wrong — never both.
    """
    with _FORECAST_RESULT_STUB_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Brain B5 self-eval wrapper stub
# ---------------------------------------------------------------------------
@pytest.fixture
def b5_stub() -> MagicMock:
    """Return a MagicMock that mimics Phase 89 Brain B5's pass-through interface.

    Behavior:
      - `wrap(envelope)` returns the envelope unchanged.
      - `__call__(envelope)` mirrors `wrap` so callers using either style succeed.

    Used by Plan 6 tests asserting the narrator agent emits only
    `ExplanationResult` / `ScenarioResult` envelopes and never a
    `ForecastResult` (LD-90-1: LLMs MUST NOT be primary forecasters).
    """
    mock = MagicMock(name="brain_b5_pass_through")
    mock.wrap.side_effect = lambda envelope: envelope
    mock.side_effect = lambda envelope: envelope
    return mock


# ---------------------------------------------------------------------------
# Marker convenience
# ---------------------------------------------------------------------------
@pytest.fixture
def phase90_marker():
    """Return the `pytest.mark.phase90` marker object."""
    return pytest.mark.phase90
