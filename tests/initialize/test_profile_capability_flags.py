"""BUG-23 / Phase 62.1: unit tests for model_tier + thinking_mode capability flags.

Tests cover:
  1. agent.yaml with model_tier: utility → SubAgent has model_tier == "utility"
  2. agent.yaml with model_tier: chat → SubAgent has model_tier == "chat"
  3. agent.yaml with no model_tier → SubAgent defaults to None (inherits chat behavior)
  4. agent.yaml with model_tier: bogus → raises AgentYamlV2Error (v2 schema validator)
  5. agent.yaml with thinking_mode: false → SubAgent has thinking_mode == False
  6. agent.yaml with thinking_mode: true → SubAgent has thinking_mode == True
  7. agent.yaml with no thinking_mode → SubAgent defaults to None
  8. Two sub-profiles with different flags do not share global state (no leak)
  9. Real reader YAMLs (trade_auditor_agent, behavioral_mentor_agent,
     weekly_review_agent) have model_tier='utility' and thinking_mode=False
 10. Real brain profiles (trade_auditor_agent, behavioral_mentor_agent,
     weekly_review_agent top-level) do NOT have model_tier or thinking_mode set
     (brain-preservation check)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from textwrap import dedent

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://test-vm100:8000")
os.environ.setdefault("SCOPE_DISPATCHER_SECRET_KEY", "test-secret")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_yaml(
    name: str,
    model_tier: str | None = None,
    thinking_mode: bool | None = None,
    include_model_tier_field: bool = True,
    include_thinking_mode_field: bool = True,
) -> str:
    """Build a minimal valid v2 agent.yaml string with optional capability flags."""
    lines = [
        "schema_version: 2",
        f"title: {name}",
        "description: test profile",
        "memory_scope:",
        "  account_scope: required",
        "  execution_scope: required",
        "  cross_trade_visibility: NONE",
        "  narrative_visibility: NONE",
        "constitutional_skills:",
        "  - citation-discipline",
        "max_iterations: 3",
        "max_cost_usd: 0.10",
        "input_contract: fingpt_core.contracts.narrative.reader_io.ReaderInput",
        "output_contract: fingpt_core.contracts.narrative.reader_io.ReaderOutput",
    ]
    if include_model_tier_field and model_tier is not None:
        lines.append(f"model_tier: {model_tier}")
    if include_thinking_mode_field and thinking_mode is not None:
        mode_str = "true" if thinking_mode else "false"
        lines.append(f"thinking_mode: {mode_str}")
    return "\n".join(lines) + "\n"


def _load_subagent_from_yaml(yaml_str: str) -> "SubAgent":
    """Parse a YAML string into a SubAgent (Pydantic model_validate)."""
    from helpers.subagents import SubAgent
    from helpers.yaml import loads as yaml_loads

    data = yaml_loads(yaml_str) or {}
    return SubAgent.model_validate(data)


# ---------------------------------------------------------------------------
# Tests: SubAgent field parsing
# ---------------------------------------------------------------------------


class TestSubAgentModelTierField:
    def test_model_tier_utility(self):
        """model_tier: utility → SubAgent.model_tier == 'utility'."""
        yaml_str = _make_yaml("test_reader", model_tier="utility")
        sub = _load_subagent_from_yaml(yaml_str)
        assert sub.model_tier == "utility"

    def test_model_tier_chat(self):
        """model_tier: chat → SubAgent.model_tier == 'chat'."""
        yaml_str = _make_yaml("test_reader", model_tier="chat")
        sub = _load_subagent_from_yaml(yaml_str)
        assert sub.model_tier == "chat"

    def test_model_tier_absent_defaults_to_none(self):
        """No model_tier field → SubAgent.model_tier is None (brain default)."""
        yaml_str = _make_yaml("test_reader", include_model_tier_field=False)
        sub = _load_subagent_from_yaml(yaml_str)
        assert sub.model_tier is None

    def test_model_tier_bogus_raises_at_parse(self):
        """model_tier: bogus → error raised at parse time.

        Pydantic enforces the Literal["utility", "chat"] constraint at model_validate
        time, so the error is a ValidationError before the semantic validator runs.
        Both Pydantic ValidationError and AgentYamlV2Error from the semantic validator
        are acceptable — what matters is that an invalid value is rejected with a clear
        error message rather than silently accepted as None.
        """
        from pydantic import ValidationError
        from helpers.agent_yaml_v2_validator import AgentYamlV2Error

        yaml_str = _make_yaml("test_reader", model_tier="bogus")

        # Pydantic Literal enforcement rejects it before semantic validation
        with pytest.raises((ValidationError, AgentYamlV2Error)):
            _load_subagent_from_yaml(yaml_str)


class TestSubAgentThinkingModeField:
    def test_thinking_mode_false(self):
        """thinking_mode: false → SubAgent.thinking_mode == False."""
        yaml_str = _make_yaml("test_reader", thinking_mode=False)
        sub = _load_subagent_from_yaml(yaml_str)
        assert sub.thinking_mode is False

    def test_thinking_mode_true(self):
        """thinking_mode: true → SubAgent.thinking_mode == True."""
        yaml_str = _make_yaml("test_reader", thinking_mode=True)
        sub = _load_subagent_from_yaml(yaml_str)
        assert sub.thinking_mode is True

    def test_thinking_mode_absent_defaults_to_none(self):
        """No thinking_mode field → SubAgent.thinking_mode is None (brain default)."""
        yaml_str = _make_yaml("test_reader", include_thinking_mode_field=False)
        sub = _load_subagent_from_yaml(yaml_str)
        assert sub.thinking_mode is None


# ---------------------------------------------------------------------------
# Tests: no global state leak between profiles
# ---------------------------------------------------------------------------


class TestNoGlobalStateLeak:
    def test_two_sub_profiles_get_different_flags(self):
        """Two different SubAgent instances with different flags don't share state."""
        yaml_utility = _make_yaml("reader_a", model_tier="utility", thinking_mode=False)
        yaml_chat = _make_yaml("reader_b", model_tier="chat", thinking_mode=True)

        sub_a = _load_subagent_from_yaml(yaml_utility)
        sub_b = _load_subagent_from_yaml(yaml_chat)

        # Assert each has its own values
        assert sub_a.model_tier == "utility"
        assert sub_a.thinking_mode is False
        assert sub_b.model_tier == "chat"
        assert sub_b.thinking_mode is True

        # Re-read sub_a to confirm no mutation from sub_b
        assert sub_a.model_tier == "utility"
        assert sub_a.thinking_mode is False


# ---------------------------------------------------------------------------
# Tests: real reader YAMLs have the correct flags (integration check)
# ---------------------------------------------------------------------------


class TestRealReaderYamlsHaveFlags:
    """Confirm that the three reader sub-profiles have model_tier=utility + thinking_mode=False."""

    @pytest.mark.parametrize("profile_name", [
        "trade_auditor_agent._reader",
        "behavioral_mentor_agent._reader",
        "weekly_review_agent._reader",
    ])
    def test_reader_has_utility_tier(self, profile_name):
        """Reader YAML should declare model_tier: utility (BUG-23)."""
        from helpers import subagents
        sub = subagents.load_agent_data(profile_name)
        assert sub.model_tier == "utility", (
            f"{profile_name}: expected model_tier='utility' but got {sub.model_tier!r}. "
            "Did you forget to add 'model_tier: utility' to the agent.yaml?"
        )

    @pytest.mark.parametrize("profile_name", [
        "trade_auditor_agent._reader",
        "behavioral_mentor_agent._reader",
        "weekly_review_agent._reader",
    ])
    def test_reader_has_thinking_off(self, profile_name):
        """Reader YAML should declare thinking_mode: false (BUG-23)."""
        from helpers import subagents
        sub = subagents.load_agent_data(profile_name)
        assert sub.thinking_mode is False, (
            f"{profile_name}: expected thinking_mode=False but got {sub.thinking_mode!r}. "
            "Did you forget to add 'thinking_mode: false' to the agent.yaml?"
        )


# ---------------------------------------------------------------------------
# Tests: brain-preservation — top-level brain profiles must NOT have flags set
# ---------------------------------------------------------------------------


class TestBrainPreservationYaml:
    """BRAIN PRESERVATION: top-level agent.yaml profiles must NOT set model_tier or thinking_mode.

    This test FAILS LOUDLY if someone accidentally biases the brain by adding
    model_tier or thinking_mode to the top-level (non-sub-profile) agent.yaml.
    """

    @pytest.mark.parametrize("brain_profile", [
        "trade_auditor_agent",
        "behavioral_mentor_agent",
        "weekly_review_agent",
    ])
    def test_brain_has_no_model_tier(self, brain_profile):
        """Top-level brain YAML must NOT declare model_tier — brain stays at chat tier."""
        from helpers import subagents
        sub = subagents.load_agent_data(brain_profile)
        assert sub.model_tier is None, (
            f"BRAIN PRESERVATION VIOLATED: {brain_profile} has model_tier={sub.model_tier!r}. "
            "Top-level brain agents must not declare model_tier. "
            "Remove it from the top-level agent.yaml immediately."
        )

    @pytest.mark.parametrize("brain_profile", [
        "trade_auditor_agent",
        "behavioral_mentor_agent",
        "weekly_review_agent",
    ])
    def test_brain_has_no_thinking_mode(self, brain_profile):
        """Top-level brain YAML must NOT declare thinking_mode — brain stays at provider default."""
        from helpers import subagents
        sub = subagents.load_agent_data(brain_profile)
        assert sub.thinking_mode is None, (
            f"BRAIN PRESERVATION VIOLATED: {brain_profile} has thinking_mode={sub.thinking_mode!r}. "
            "Top-level brain agents must not declare thinking_mode. "
            "Remove it from the top-level agent.yaml immediately."
        )
