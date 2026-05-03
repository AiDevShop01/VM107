"""
Phase 44 Wave 0 — Strategy endpoint integration test scaffolds.

Tests POST /api/v1/agents/strategy/invoke via Flask test client.
All tests are xfail(strict=False) until Plan 44-04 Task 1 implements the
Flask ApiHandler endpoint at api/v1/agents/strategy/invoke.py.

Test names MUST match 44-VALIDATION.md "Per-Task Verification Map" exactly.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


@pytest.mark.xfail(reason="Implementation pending in Plan 44-04", strict=False)
def test_sync_success():
    """
    POST /api/v1/agents/strategy/invoke with valid Hypothesis returns 200 + StrategySpec body.

    Response must contain strategy_spec dict and meta block with envelope_id,
    source_envelope_id, agent_id, model_used, fallback_used, duration_ms.
    Graduates in Plan 44-04 Task 1.
    """
    # Import the Flask app and use test client — both pending Plan 44-04
    from api.v1.agents.strategy.invoke import StrategyInvoke  # noqa: F401  # will exist in Plan 44-04
    raise NotImplementedError("Endpoint not yet implemented — Plan 44-04 Task 1")


@pytest.mark.xfail(reason="Implementation pending in Plan 44-04", strict=False)
def test_invalid_hypothesis():
    """
    POST with malformed hypothesis JSON returns 422 Unprocessable Entity.

    Endpoint must validate Hypothesis with model_validate() BEFORE invoking agent.
    Graduates in Plan 44-04 Task 1.
    """
    from api.v1.agents.strategy.invoke import StrategyInvoke  # noqa: F401
    raise NotImplementedError("Endpoint not yet implemented — Plan 44-04 Task 1")


@pytest.mark.xfail(reason="Implementation pending in Plan 44-04", strict=False)
def test_agent_failure():
    """
    POST where Strategy Agent safe_parse fails twice returns 502 Bad Gateway.

    AgentEnvelope status=failure must be persisted.
    Graduates in Plan 44-04 Task 1.
    """
    from api.v1.agents.strategy.invoke import StrategyInvoke  # noqa: F401
    raise NotImplementedError("Endpoint not yet implemented — Plan 44-04 Task 1")


@pytest.mark.xfail(reason="Implementation pending in Plan 44-04", strict=False)
def test_async_mode():
    """
    POST ?async=true returns 202 Accepted + {"task_id": ...} body.

    Graduates in Plan 44-04 Task 1.
    """
    from api.v1.agents.strategy.invoke import StrategyInvoke  # noqa: F401
    raise NotImplementedError("Endpoint not yet implemented — Plan 44-04 Task 1")
