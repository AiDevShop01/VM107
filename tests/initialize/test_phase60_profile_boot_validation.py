"""Phase 60.1 G8: boot hook validates Phase 60 v2 profiles."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure VM107 root is on sys.path
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# Some validator paths need VM100_INTERNAL_BASE_URL for tool imports
os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://test-vm100:8000")
os.environ.setdefault("SCOPE_DISPATCHER_SECRET_KEY", "test-secret")


def test_initialize_hook_exposed():
    """The boot hook function exists in initialize.py."""
    from initialize import initialize_validate_phase60_profiles
    assert callable(initialize_validate_phase60_profiles)


def test_real_phase60_profiles_pass_validation():
    """All shipped Phase 60 profiles + strategy/idea backfills pass boot validation."""
    from initialize import initialize_validate_phase60_profiles
    # If this raises, the boot would fail — caller should fix the YAML, not skip the test
    count = initialize_validate_phase60_profiles()
    assert count >= 1  # at least some profiles loaded


def test_invalid_profile_raises_hard(monkeypatch):
    """Inject a fake invalid SubAgent and assert AgentYamlV2Error is raised."""
    from initialize import initialize_validate_phase60_profiles
    from helpers.agent_yaml_v2_validator import AgentYamlV2Error
    from helpers import subagents

    # Construct a fake SubAgent-like with bad memory_scope
    fake = MagicMock()
    fake.schema_version = 2
    fake.memory_scope = {
        "account_scope": "required",
        "narrative_visibility": "BOGUS_NOT_IN_ALLOWED_SET",
        "cross_trade_visibility": "NONE",
        "execution_scope": "required",
    }
    fake.constitutional_skills = ["citation-discipline"]
    fake.input_contract = None
    fake.output_contract = None

    with patch.object(subagents, "get_agents_dict", return_value={"bogus_profile": fake}):
        with pytest.raises(AgentYamlV2Error) as exc_info:
            initialize_validate_phase60_profiles()

        assert "bogus_profile" in str(exc_info.value)


def test_v1_profile_warns_not_raises(monkeypatch):
    """v1 schema_version=None profiles produce a deprecation warning, not a hard-fail."""
    from initialize import initialize_validate_phase60_profiles
    from helpers import subagents

    fake = MagicMock()
    fake.schema_version = None  # v1 grandfather
    fake.constitutional_skills = None
    fake.memory_scope = None
    fake.input_contract = None
    fake.output_contract = None

    with patch.object(subagents, "get_agents_dict", return_value={"legacy": fake}):
        # Should NOT raise — v1 profiles get DeprecationWarning
        with pytest.warns(DeprecationWarning):
            initialize_validate_phase60_profiles()
