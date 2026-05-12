"""Phase 60.1 G15: SubAgent YAML loader runs semantic validation after model_validate."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from textwrap import dedent

import pytest

# Ensure VM107 root is on sys.path
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://test-vm100:8000")
os.environ.setdefault("SCOPE_DISPATCHER_SECRET_KEY", "test-secret")


def _write_yaml(tmp_path: Path, name: str, body: str) -> Path:
    profile_dir = tmp_path / name
    profile_dir.mkdir()
    yaml_path = profile_dir / "agent.yaml"
    yaml_path.write_text(dedent(body))
    return yaml_path


def test_valid_v2_profile_loads_ok():
    """Happy path: valid v2 profile loads via subagents helper without raising."""
    from helpers import subagents
    # load_agent_data returns full SubAgent for trade_auditor_agent
    sub = subagents.load_agent_data("trade_auditor_agent")
    assert sub.schema_version == 2
    assert sub.constitutional_skills is not None
    assert "citation-discipline" in sub.constitutional_skills


def test_invalid_v2_profile_raises_at_load_time(tmp_path, monkeypatch):
    """Loading a YAML with bad enum value raises AgentYamlV2Error from the loader."""
    from helpers.agent_yaml_v2_validator import AgentYamlV2Error
    from helpers import subagents

    bad_yaml = dedent("""\
        schema_version: 2
        title: bogus_test
        description: invalid profile for testing
        parent_profile: null
        memory_scope:
            account_scope: required
            narrative_visibility: BOGUS_VALUE_NOT_IN_ALLOWED_SET
            cross_trade_visibility: NONE
            execution_scope: required
        allowed_skills: []
        constitutional_skills:
            - citation-discipline
        optional_skills: []
        max_iterations: 10
        max_cost_usd: 1.0
    """)
    yaml_path = _write_yaml(tmp_path, "bogus_test", bad_yaml)

    # Monkeypatch helpers.files to serve our temp directory
    import helpers.files as files_helper
    original_get_abs_path = files_helper.get_abs_path

    def patched_get_abs_path(*parts):
        # If looking for bogus_test under DEFAULT_AGENTS_DIR, redirect to tmp_path
        joined = "/".join(str(p) for p in parts)
        if "bogus_test" in joined:
            return str(tmp_path / "bogus_test" / parts[-1])
        return original_get_abs_path(*parts)

    monkeypatch.setattr(files_helper, "get_abs_path", patched_get_abs_path)

    # load_agent_data should raise AgentYamlV2Error for invalid v2 profiles
    with pytest.raises(AgentYamlV2Error):
        subagents.load_agent_data("bogus_test")


def test_v1_profile_loads_with_deprecation_warning():
    """v1 schema_version=None profiles load with deprecation warning, no raise."""
    from helpers import subagents
    # 'default' agent is a v1 profile without schema_version
    with pytest.warns(DeprecationWarning):
        sub = subagents.load_agent_data("default")
    assert sub is not None


def test_phase60_mentor_profiles_load_successfully():
    """All Phase 60 mentor profiles load via load_agent_data without error."""
    from helpers import subagents
    mentor_profiles = [
        "trade_auditor_agent",
        "behavioral_mentor_agent",
        "weekly_review_agent",
    ]
    for profile_name in mentor_profiles:
        sub = subagents.load_agent_data(profile_name)
        assert sub.schema_version == 2, f"{profile_name} should be v2"
        assert sub.constitutional_skills is not None, f"{profile_name} missing constitutional_skills"
        assert "citation-discipline" in sub.constitutional_skills, f"{profile_name} missing citation-discipline"
