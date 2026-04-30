"""Tests for migration 004: Goal/Task system schema upgrade."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, call
import pytest


# Import migration module dynamically (file starts with number)
def get_migration_module():
    """Load migration module dynamically since filename starts with number."""
    migration_path = Path(__file__).parent.parent.parent / "core" / "migrations" / "scripts" / "004_goal_task_system.py"
    spec = importlib.util.spec_from_file_location("migration_004", migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_renames_collection():
    """Upgrade should rename agent_objectives to agent_goals."""
    migration = get_migration_module()

    # Mock MongoDB database
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_db.__getitem__.return_value = mock_collection

    context = {"mongo": {"fingpt_agents": mock_db}}

    # Execute upgrade
    migration.upgrade(context)

    # Verify rename was called
    mock_collection.rename.assert_called_once_with("agent_goals")


def test_upgrade_creates_indexes():
    """Upgrade should create all required indexes."""
    migration = get_migration_module()

    # Mock MongoDB database
    mock_db = MagicMock()
    context = {"mongo": {"fingpt_agents": mock_db}}

    # Execute upgrade
    migration.upgrade(context)

    # Verify create_index was called for agent_goals
    assert mock_db["agent_goals"].create_index.called

    # Check that indexes were created for all collections
    collections_with_indexes = ["agent_goals", "agent_tasks", "brain_state", "agent_progress", "agent_runs"]
    for collection_name in collections_with_indexes:
        assert mock_db[collection_name].create_index.called


def test_upgrade_updates_validators():
    """Upgrade should update validators for all stub collections."""
    migration = get_migration_module()

    # Mock MongoDB database
    mock_db = MagicMock()
    context = {"mongo": {"fingpt_agents": mock_db}}

    # Execute upgrade
    migration.upgrade(context)

    # Verify collMod commands were issued
    assert mock_db.command.called

    # Should have called command for each collection update
    # (agent_goals, agent_tasks, brain_state, agent_progress, agent_runs)
    assert mock_db.command.call_count >= 5


def test_downgrade_renames_back():
    """Downgrade should rename agent_goals back to agent_objectives."""
    migration = get_migration_module()

    # Mock MongoDB database
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_db.__getitem__.return_value = mock_collection

    context = {"mongo": {"fingpt_agents": mock_db}}

    # Execute downgrade
    migration.downgrade(context)

    # Verify rename was called
    mock_collection.rename.assert_called_once_with("agent_objectives")


def test_downgrade_drops_indexes():
    """Downgrade should drop indexes from all collections."""
    migration = get_migration_module()

    # Mock MongoDB database
    mock_db = MagicMock()
    context = {"mongo": {"fingpt_agents": mock_db}}

    # Execute downgrade
    migration.downgrade(context)

    # Verify drop_indexes was called for all collections
    collections = ["agent_goals", "agent_tasks", "brain_state", "agent_progress", "agent_runs"]
    for collection_name in collections:
        assert mock_db[collection_name].drop_indexes.called


def test_goal_status_enum_values_match_validator():
    """GoalStatus enum values should match migration validator."""
    from core.scheduling.enums import GoalStatus

    # Expected values from migration validator
    expected_statuses = {"draft", "proposed", "approved", "active", "paused", "completed", "failed", "cancelled"}

    # Actual enum values
    actual_statuses = {status.value for status in GoalStatus}

    assert actual_statuses == expected_statuses


def test_task_status_enum_values_match_validator():
    """TaskStatus enum values should match migration validator."""
    from core.scheduling.enums import TaskStatus

    # Expected values from migration validator
    expected_statuses = {"pending", "blocked", "queued", "running", "completed", "failed", "cancelled"}

    # Actual enum values
    actual_statuses = {status.value for status in TaskStatus}

    assert actual_statuses == expected_statuses


def test_priority_enum_values_match_validator():
    """Priority enum values should match migration validator."""
    from core.scheduling.enums import Priority

    # Expected values from migration validator
    expected_priorities = {"P1", "P2", "P3", "P4"}

    # Actual enum values
    actual_priorities = {priority.value for priority in Priority}

    assert actual_priorities == expected_priorities


def test_goal_type_enum_values_match_validator():
    """GoalType enum values should match migration validator."""
    from core.scheduling.enums import GoalType

    # Expected values from migration validator
    expected_types = {"maintenance", "learning", "research", "execution", "system"}

    # Actual enum values
    actual_types = {goal_type.value for goal_type in GoalType}

    assert actual_types == expected_types
