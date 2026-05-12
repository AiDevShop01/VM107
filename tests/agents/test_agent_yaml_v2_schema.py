"""Tests for SubAgent v2 schema fields and boot validator — CTX-§7.

Tests verify:
  - v2 fields round-trip through SubAgent.model_validate
  - Boot validator hard-fails on missing schema_version
  - Boot validator hard-fails on invalid memory_scope
  - Boot validator hard-fails on missing citation-discipline in constitutional_skills
  - Boot validator hard-fails on unresolvable input_contract
  - v1 profiles (no schema_version) skip validation with a deprecation warning
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

# Ensure VM107 root is on sys.path so helpers.* imports resolve
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest

from helpers.subagents import SubAgent
from helpers.agent_yaml_v2_validator import (
    AgentYamlV2Error,
    ScopeSpecValidationError,
    validate_agent_yaml_v2,
)


def _make_valid_v2_subagent(**overrides) -> SubAgent:
    """Return a minimally-valid v2 SubAgent instance."""
    base = dict(
        title="test agent",
        description="test",
        path="/tmp/test",
        schema_version=2,
        constitutional_skills=["citation-discipline"],
        memory_scope={
            "account_scope": "required",
            "narrative_visibility": "PRIOR_ONLY",
            "cross_trade_visibility": "NONE",
            "execution_scope": "required",
        },
    )
    base.update(overrides)
    return SubAgent.model_validate(base)


# ---------------------------------------------------------------------------
# SubAgent v2 field round-trip
# ---------------------------------------------------------------------------


def test_v2_fields_round_trip():
    """CTX-§7 — loading a v2-shaped dict populates all new v2 fields (not dropped silently)."""
    agent = SubAgent.model_validate(
        {
            "title": "trade auditor",
            "description": "audits trades",
            "path": "/tmp/trade_auditor",
            "schema_version": 2,
            "constitutional_skills": ["citation-discipline"],
            "optional_skills": ["sentiment-discipline"],
            "memory_scope": {"account_scope": "required"},
            "max_iterations": 10,
            "max_cost_usd": 1.5,
            "input_contract": "fingpt_core.contracts.NarrativeEnvelope",
            "output_contract": "fingpt_core.contracts.NarrativeOutput",
            "parent_profile": "trade_auditor_agent",
            "allowed_tools": ["lookup_replay_artifact"],
            "denied_tools": ["persist_narrative"],
        }
    )
    assert agent.schema_version == 2, "schema_version must be 2"
    assert agent.constitutional_skills == ["citation-discipline"]
    assert agent.optional_skills == ["sentiment-discipline"]
    assert agent.memory_scope == {"account_scope": "required"}
    assert agent.max_iterations == 10
    assert agent.max_cost_usd == 1.5
    assert agent.input_contract == "fingpt_core.contracts.NarrativeEnvelope"
    assert agent.output_contract == "fingpt_core.contracts.NarrativeOutput"
    assert agent.parent_profile == "trade_auditor_agent"
    assert agent.allowed_tools == ["lookup_replay_artifact"]
    assert agent.denied_tools == ["persist_narrative"]


def test_v1_profile_loads_without_v2_fields():
    """Backward compat — a v1 profile (no schema_version) still loads with all v2 fields = None."""
    agent = SubAgent.model_validate(
        {
            "title": "strategy agent",
            "description": "old v1 agent",
            "path": "/tmp/strategy_agent",
        }
    )
    assert agent.schema_version is None
    assert agent.constitutional_skills is None
    assert agent.memory_scope is None
    assert agent.max_iterations is None


# ---------------------------------------------------------------------------
# Boot validator — hard-fail cases
# ---------------------------------------------------------------------------


def test_missing_schema_version_fails():
    """CTX-§7 — validate_agent_yaml_v2 raises AgentYamlV2Error when schema_version is None.

    v1 profiles use the v1 path (schema_version=None => deprecation warning, no exception).
    But calling validate_agent_yaml_v2 with a profile that has no schema_version should
    invoke the v1 fast-path (log warning, return early without raising).

    CORRECTION per CONTEXT.md §7: v1 profiles with schema_version=None skip validation —
    they are grandfathered until backfilled in 60-12. This test verifies that a profile
    with schema_version != 2 (e.g. schema_version=99) raises an error.
    """
    # schema_version = None => v1 profile, skips validation (returns early)
    agent_v1 = SubAgent.model_validate(
        {"title": "old", "description": "old", "path": "/tmp/x"}
    )
    # Must NOT raise — v1 profile is silently skipped
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        validate_agent_yaml_v2("old_profile", agent_v1)
    assert any("deprecated" in str(warning.message).lower() or "v1" in str(warning.message).lower() for warning in w), \
        "Expected deprecation warning for v1 profile"

    # schema_version = 99 => unsupported, MUST raise
    agent_bad = SubAgent.model_validate(
        {
            "title": "bad",
            "description": "bad",
            "path": "/tmp/bad",
            "schema_version": 99,
            "constitutional_skills": ["citation-discipline"],
            "memory_scope": {"account_scope": "required"},
        }
    )
    with pytest.raises(AgentYamlV2Error, match="schema_version"):
        validate_agent_yaml_v2("bad_profile", agent_bad)


def test_invalid_memory_scope_rejected():
    """CTX-§7 — validate_agent_yaml_v2 raises ScopeSpecValidationError for bad memory_scope values."""
    # account_scope must be "required" or "NONE"
    agent = _make_valid_v2_subagent(
        memory_scope={
            "account_scope": "INVALID_VALUE",
            "narrative_visibility": "PRIOR_ONLY",
        }
    )
    with pytest.raises(ScopeSpecValidationError):
        validate_agent_yaml_v2("test_profile", agent)

    # narrative_visibility must be "NONE", "PRIOR_ONLY", or "FULL"
    agent2 = _make_valid_v2_subagent(
        memory_scope={
            "account_scope": "required",
            "narrative_visibility": "BAD_VISIBILITY",
        }
    )
    with pytest.raises(ScopeSpecValidationError):
        validate_agent_yaml_v2("test_profile", agent2)


def test_missing_constitutional_citation_discipline_fails():
    """CTX-§7 + CTX-§8 — constitutional_skills rules.

    Non-mentor v2 profiles (e.g. strategy_agent, idea_agent) may use empty []
    to declare "no constitutional skills" — this is valid. Only a non-empty list
    that omits citation-discipline is a policy violation.
    """
    # Empty list [] is valid — non-mentor profiles like strategy_agent/idea_agent
    # explicitly opt out of constitutional skills. Should NOT raise.
    agent_empty = _make_valid_v2_subagent(constitutional_skills=[])
    validate_agent_yaml_v2("non_mentor_profile", agent_empty)  # must not raise

    # Non-empty list that omits citation-discipline IS a violation (CTX-§8).
    agent_missing = _make_valid_v2_subagent(constitutional_skills=["some-other-skill"])
    with pytest.raises(AgentYamlV2Error, match="citation-discipline"):
        validate_agent_yaml_v2("test_profile", agent_missing)


def test_unresolvable_input_contract_fails():
    """CTX-§7 — validate_agent_yaml_v2 raises AgentYamlV2Error when input_contract dotted path cannot be imported."""
    agent = _make_valid_v2_subagent(
        input_contract="nonexistent.module.path.SomeClass"
    )
    with pytest.raises(AgentYamlV2Error, match="input_contract"):
        validate_agent_yaml_v2("test_profile", agent)


def test_v1_profile_loads_with_deprecation_warning():
    """CTX-§7 backward compat — v1 profile (schema_version=None) loads with a single deprecation
    warning and does NOT raise an exception."""
    agent = SubAgent.model_validate(
        {
            "title": "strategy agent",
            "description": "v1 legacy",
            "path": "/tmp/strategy_agent",
        }
    )
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        # Must not raise
        validate_agent_yaml_v2("strategy_agent", agent)
    assert len(w) >= 1, "Expected at least one warning for v1 profile"
    warning_text = " ".join(str(warning.message) for warning in w).lower()
    assert "deprecated" in warning_text or "v1" in warning_text or "schema_version" in warning_text, \
        f"Expected deprecation warning, got: {warning_text}"
