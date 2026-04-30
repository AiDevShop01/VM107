"""Shared fixtures for scheduling tests."""

import pytest
from datetime import datetime, timezone


@pytest.fixture
def now_utc():
    """Current UTC timestamp."""
    return datetime.now(timezone.utc)


@pytest.fixture
def valid_goal_data(now_utc):
    """Valid goal creation data."""
    return {
        "goal_id": "goal-test-001",
        "title": "Test Goal",
        "description": "A test goal for unit testing",
        "goal_type": "maintenance",
        "status": "draft",
        "priority": "P2",
        "created_by": "test_user",
        "governance_tier": "auto",
        "created_at": now_utc,
        "updated_at": now_utc,
    }


@pytest.fixture
def valid_task_data(now_utc):
    """Valid task creation data."""
    return {
        "task_id": "task-test-001",
        "goal_id": "goal-test-001",
        "task_type": "analysis",
        "status": "pending",
        "priority": "P2",
        "created_at": now_utc,
        "updated_at": now_utc,
    }
