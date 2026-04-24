"""
Test configuration for AgentRunner tests.

Provides pytest fixtures for sys.path insertion so imports work from VM107 root.
"""
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_sys_path():
    """Add VM107 root to sys.path so 'from core.state_machine import ...' works."""
    vm107_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(vm107_root))
    yield
    # Cleanup not needed - session-scoped fixture
