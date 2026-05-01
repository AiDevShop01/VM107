"""
Test configuration for Phase 43 LLM Model Router tests.

Provides sys.path insertion + mock fixtures for all routing test modules.
All fixtures use unittest.mock.MagicMock — zero real Redis/MongoDB/agent
dependencies so tests run fast in any environment.

Fixtures:
    mock_agent           — Agent Zero agent stub with get_data/set_data
    mock_runner          — AgentRunner stub with execution_context
    mock_redis           — Redis client stub with HSET/HGETALL simulation
    mock_mongo           — MongoDB client stub (configurable per test)
    mock_signal_accumulator — Phase 42 SignalAccumulator stub with emit tracking
    mock_brain_layer     — Phase 42 BrainLayer stub returning exploration mode
    mock_logger          — stdlib logging.Logger stub
"""
import os
import sys

# Add VM107 root to sys.path so "from core.routing import ..." works
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_agent():
    """
    Agent Zero agent stub.

    Simulates agent.get_data() / agent.set_data() using an internal _data dict
    so tests can verify what the router stores on the agent without importing
    Agent Zero internals.
    """
    a = MagicMock()
    a.agent_name = "agent_zero"
    a._data = {}
    a.get_data.side_effect = lambda k, d=None: a._data.get(k, d)
    a.set_data.side_effect = lambda k, v: a._data.update({k: v})
    return a


@pytest.fixture
def mock_runner():
    """
    AgentRunner stub with Phase 36 ExecutionContext fields.

    execution_context has task_id + step_id + state (the fields that actually
    exist on ExecutionContext from Phase 36 — goal_id is NOT there, which is
    exactly why agent.set_data("router_context") was added in Plan 01).
    """
    r = MagicMock()
    r.execution_context = MagicMock(task_id="task-001", step_id=1, state="RUNNING")
    return r


@pytest.fixture
def mock_redis():
    """
    Redis client stub simulating HSET/HGETALL operations.

    Uses an internal _store dict to allow tests to verify key writes
    without a real Redis connection. expire() is a no-op.

    Redis key schema for router budget:
        router:budget:goal:{goal_id}     → HSET {date, spent_usd, max_usd, status}
        router:budget:agent:{agent_type} → HSET {date, spent_usd}
        router:budget:system             → HSET {date, spent_usd}
    """
    r = MagicMock()
    r._store = {}
    r.hgetall.side_effect = lambda k: r._store.get(k, {})
    r.hset.side_effect = lambda k, mapping=None, **kw: r._store.setdefault(k, {}).update(
        mapping or kw
    )
    r.expire.return_value = True
    return r


@pytest.fixture
def mock_mongo():
    """MongoDB client stub (all methods are MagicMocks — configure per test)."""
    m = MagicMock()
    return m


@pytest.fixture
def mock_signal_accumulator():
    """
    Phase 42 SignalAccumulator stub with emitted signal tracking.

    emitted list captures all Signal objects passed to emit_signal() so
    tests can assert that cost_pressure signals are fired at correct thresholds.
    """
    sa = MagicMock()
    sa.emitted = []
    sa.emit_signal.side_effect = sa.emitted.append
    return sa


@pytest.fixture
def mock_brain_layer():
    """
    Phase 42 BrainLayer stub returning exploration mode by default.

    Tests that need stabilization or exploitation mode should override:
        mock_brain_layer.get_brain_context.return_value = {"mode": "stabilization", ...}
    """
    bl = MagicMock()
    bl.get_brain_context.return_value = {
        "mode": "exploration",
        "confidence_global": 0.7,
        "resource_policy": "normal",
    }
    return bl


@pytest.fixture
def mock_logger():
    """stdlib logging.Logger stub."""
    return MagicMock()
