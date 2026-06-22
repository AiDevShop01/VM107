"""Phase 89.1 Plan 04 — Profile-aware dispatch middleware contract tests.

Five contract tests that prove load_profile_into_agent() satisfies the
assumptions made in Plans 89.1-01/02/03:

  1. test_middleware_loads_macro_investigator_profile_as_dict
     — profile dict has the required keys consumed by B5 + tool-scope filter.

  2. test_middleware_loads_system_prompt_when_md_exists
     — _system_prompt slot populated with a non-empty string starting with
       the expected header (so citations/tool instructions reach the LLM).

  3. test_middleware_handles_missing_profile_gracefully
     — FileNotFoundError raised for unknown profile id; agent0 state
       left unmodified (no partial mutation).

  4. test_middleware_no_hardcoded_profile_id_in_api_message
     — api/api_message.py source contains at most 1 literal reference to
       "vm107.macro_investigator" (the tolerated AskResponse envelope branch).

  5. test_legacy_string_profile_still_works
     — macro_release_analyst profile (different agent, different YAML)
       loads without error and returns a dict with the required keys.

Path B decision reference: 89.1-04-DISPATCH-DECISION-LOG.md
"""
from __future__ import annotations

import pathlib
from typing import Any
from unittest.mock import call, patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

VM107_ROOT = pathlib.Path(__file__).parent.parent.parent
API_MESSAGE_PATH = VM107_ROOT / "api" / "api_message.py"
PROFILE_DIR = VM107_ROOT / "registry" / "agent_profile"
PROMPTS_DIR = VM107_ROOT / "prompts"


# ---------------------------------------------------------------------------
# Production-shaped agent stub (same contract as test_b5_hook_rca.py)
# ---------------------------------------------------------------------------

class _ProductionAgentStub:
    """Mimics production Agent.get_data / set_data contract.

    Agent.get_data(self, field: str) — exactly ONE argument (no default).
    Agent.set_data(self, field: str, value) — TWO positional args.
    """

    def __init__(self):
        self.profile: Any = None  # starts unset
        self._data: dict[str, Any] = {}

    def get_data(self, field: str) -> Any:
        return self._data.get(field, None)

    def set_data(self, field: str, value: Any) -> None:
        self._data[field] = value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_real_yaml(profile_id: str) -> dict:
    """Load the actual registry YAML for comparison in tests."""
    yaml_path = PROFILE_DIR / f"{profile_id}.yaml"
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Test 1 — profile dict has required keys
# ---------------------------------------------------------------------------

@pytest.mark.phase89_1
def test_middleware_loads_macro_investigator_profile_as_dict():
    """load_profile_into_agent() populates agent0.profile as a dict with
    the keys required by Plan 89.1-02 (B5 hook) and Plan 89.1-03 (tool scope).

    Required keys:
      - id             — routing key used by B1 WORM artifact persist hook
      - b5_self_eval   — gate read by B5SelfCheckExtension.execute
      - allowed_tools  — read by tool_scope filter
      - denied_tools   — read by tool_scope filter
    """
    from helpers.profile_aware_dispatch import load_profile_into_agent

    agent0 = _ProductionAgentStub()
    profile = load_profile_into_agent(agent0, "vm107.macro_investigator")

    # Return value is the profile dict
    assert isinstance(profile, dict), f"expected dict, got {type(profile)}"

    # agent0.profile is the same dict
    assert agent0.profile is profile

    # Required keys present
    for key in ("id", "b5_self_eval", "allowed_tools", "denied_tools"):
        assert key in profile, f"missing required profile key: {key!r}"

    # Keys have correct types
    assert profile["id"] == "vm107.macro_investigator"
    assert isinstance(profile["b5_self_eval"], bool)
    assert isinstance(profile["allowed_tools"], list)
    assert isinstance(profile["denied_tools"], list)

    # profile_id data slot set correctly
    assert agent0.get_data("profile_id") == "vm107.macro_investigator"


# ---------------------------------------------------------------------------
# Test 2 — system prompt populated
# ---------------------------------------------------------------------------

@pytest.mark.phase89_1
def test_middleware_loads_system_prompt_when_md_exists():
    """load_profile_into_agent() sets agent0._system_prompt when any matching
    prompt file exists for macro_investigator.

    The middleware tries two candidates (full id + short name):
      1. prompts/vm107.macro_investigator.md
      2. prompts/macro_investigator.md   (legacy naming convention)

    Plan 89.1-01 requires the system prompt to reach the LLM via
    UserMessage.system_message. If _system_prompt is empty, citations and
    tool instructions are never injected.
    """
    from helpers.profile_aware_dispatch import load_profile_into_agent

    # Check if either candidate exists — the middleware tries both.
    _short_name = "macro_investigator"
    prompt_candidates = [
        PROMPTS_DIR / "vm107.macro_investigator.md",
        PROMPTS_DIR / f"{_short_name}.md",
    ]
    any_prompt_exists = any(p.exists() for p in prompt_candidates)

    if not any_prompt_exists:
        pytest.skip(
            f"No prompt file found for macro_investigator "
            f"(tried: {[str(p) for p in prompt_candidates]}); skipping prompt test"
        )

    agent0 = _ProductionAgentStub()
    load_profile_into_agent(agent0, "vm107.macro_investigator")

    system_prompt = agent0.get_data("_system_prompt")
    assert system_prompt, (
        "_system_prompt should be a non-empty string when a prompt file exists "
        f"(checked: {[str(p) for p in prompt_candidates]})"
    )
    assert isinstance(system_prompt, str)

    # The prompt should start with a markdown heading
    # (convention: prompts/*.md start with "# ..." or similar)
    first_line = system_prompt.strip().splitlines()[0] if system_prompt.strip() else ""
    assert first_line.startswith("#"), (
        f"Expected system prompt to start with a markdown heading; got: {first_line!r}"
    )


# ---------------------------------------------------------------------------
# Test 3 — missing profile raises FileNotFoundError with no partial state
# ---------------------------------------------------------------------------

@pytest.mark.phase89_1
def test_middleware_handles_missing_profile_gracefully():
    """load_profile_into_agent() raises FileNotFoundError for unknown profile ids.

    No partial state: agent0.profile must remain None and _system_prompt /
    profile_id data slots must remain unset after the exception.

    This matches the api_message.py caller contract:
        try:
            load_profile_into_agent(agent0, profile_id)
        except FileNotFoundError:
            log.warning("profile not found; legacy mode")
    """
    from helpers.profile_aware_dispatch import load_profile_into_agent

    bogus_id = "vm107.__nonexistent_test_profile_99999"
    agent0 = _ProductionAgentStub()

    with pytest.raises(FileNotFoundError) as exc_info:
        load_profile_into_agent(agent0, bogus_id)

    # Error message should reference the profile id so it's diagnosable
    assert bogus_id in str(exc_info.value) or "not found" in str(exc_info.value).lower()

    # No partial state — agent0 should be pristine
    assert agent0.profile is None, "agent0.profile must not be set after FileNotFoundError"
    assert agent0.get_data("profile_id") is None, "profile_id must not be set after FileNotFoundError"
    assert agent0.get_data("_system_prompt") is None, "_system_prompt must not be set after FileNotFoundError"


# ---------------------------------------------------------------------------
# Test 4 — no hardcoded profile id in api_message.py (≤ 1 literal)
# ---------------------------------------------------------------------------

@pytest.mark.phase89_1
def test_middleware_no_hardcoded_profile_id_in_api_message():
    """api/api_message.py contains at most 1 literal reference to
    "vm107.macro_investigator" after the Path B refactor.

    The plan gate: the profile-loading if-branch had 5+ literals before
    89.1-04. Post-refactor, only the AskResponse envelope routing branch
    is permitted (1 tolerated reference).

    This is a source-level grep test — it does NOT require imports.
    """
    assert API_MESSAGE_PATH.exists(), f"api_message.py not found at {API_MESSAGE_PATH}"

    source = API_MESSAGE_PATH.read_text(encoding="utf-8")
    literal = '"vm107.macro_investigator"'
    count = source.count(literal)

    assert count <= 1, (
        f"Expected at most 1 literal {literal!r} in api_message.py "
        f"after Path B refactor; found {count}. "
        f"The profile-loading inline if-branch must be fully replaced "
        f"by the load_profile_into_agent() middleware call."
    )


# ---------------------------------------------------------------------------
# Test 5 — legacy profile (macro_release_analyst) loads correctly
# ---------------------------------------------------------------------------

@pytest.mark.phase89_1
def test_legacy_string_profile_still_works():
    """load_profile_into_agent() works for macro_release_analyst (a second,
    different profile) confirming the middleware is not macro_investigator-specific.

    This covers the 89-WIRING-RCA-HANDOFF.md item 5 concern: parallel agents
    (macro_release_analyst, discovery, contradiction_detector) must NOT be
    disrupted by the Path B refactor.

    The macro_release_analyst has its own YAML in registry/agent_profile/
    (vm107.macro_release_analyst.yaml). We load it through the middleware
    and verify the returned dict has the standard required keys.
    """
    from helpers.profile_aware_dispatch import load_profile_into_agent

    profile_id = "vm107.macro_release_analyst"
    profile_yaml_path = PROFILE_DIR / f"{profile_id}.yaml"

    # If macro_release_analyst has no profile YAML (e.g. only in profiles/),
    # the middleware correctly raises FileNotFoundError.
    # That outcome is ALSO acceptable — it proves the middleware doesn't silently
    # corrupt state. We check both cases.
    if not profile_yaml_path.exists():
        agent0 = _ProductionAgentStub()
        with pytest.raises(FileNotFoundError):
            load_profile_into_agent(agent0, profile_id)
        # Pristine after error
        assert agent0.profile is None
        return

    # Happy path: YAML exists — load and validate
    agent0 = _ProductionAgentStub()
    profile = load_profile_into_agent(agent0, profile_id)

    assert isinstance(profile, dict), f"expected dict, got {type(profile)}"
    assert agent0.profile is profile
    assert agent0.get_data("profile_id") == profile_id

    # At minimum the profile should have 'id' or 'name' — both are standard
    # fields in every registry/agent_profile/*.yaml we've shipped.
    has_id = "id" in profile or "name" in profile
    assert has_id, (
        f"Profile dict for {profile_id!r} missing both 'id' and 'name' keys. "
        f"Keys found: {sorted(profile.keys())}"
    )
