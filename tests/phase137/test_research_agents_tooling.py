"""E-HIGH3 / E-HIGH4 — research-agent tooling advertised == authorized.

The two grant surfaces disagree for the research agents today (RESEARCH §6):
  * ``search_knowledge`` is UNREGISTERED (no ``registry/tool/*.yaml``) so it is hidden
    from every research agent's index even though it is in their allowed_tools.
  * ``response`` is registered but empty-aap -> goes dark under D-01 unless granted.
  * ``research_classification_agent`` is MISSING ``search_macro_research`` that its four
    siblings hold (E-HIGH4) — needs the grant on BOTH surfaces (profile allowed_tools +
    tool allowed_agent_profiles).
  * ``research_chat_agent`` (E-HIGH3): its granted tools are not advertised to it (their
    allowed_agent_profiles omit it) — "2 of 4 unusable".

Every assertion checks the FULL invariant (advertised AND authorized) via the real hops.
RED at develop HEAD; goes green as 137-05/137-06 register search_knowledge and add the
two-surface grants.

Analog: tests/phase135/test_scope_from_registry.py (assertion shape).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from helpers.tool_scope import apply_tool_scope
from helpers.tool_scope_guard import check_tool_scope_for_profile

_PROFILE_DIR = Path(__file__).resolve().parent.parent.parent / "registry" / "agent_profile"

# The five research agents (RESEARCH §6). research_chat_agent is handled separately (E-HIGH3).
RESEARCH_AGENTS: tuple[str, ...] = (
    "vm107.research_discovery_agent",
    "vm107.research_summarisation_agent",
    "vm107.research_citation_agent",
    "vm107.research_contrarian_agent",
    "vm107.research_classification_agent",
)


def _load_profile(profile_id: str) -> dict:
    with open(_PROFILE_DIR / f"{profile_id}.yaml") as fh:
        return yaml.safe_load(fh)


def _advertised_ids(reg, profile: dict) -> set[str]:
    index = reg.get_index_for_profile(profile["id"])
    scoped = apply_tool_scope(index, profile.get("allowed_tools"), profile.get("denied_tools"))
    return {e["id"] for e in scoped}


def _assert_advertised_and_authorized(reg, profile: dict, tool_id: str) -> None:
    advertised = _advertised_ids(reg, profile)
    authorized = check_tool_scope_for_profile(tool_id, profile) is None
    assert authorized, (
        f"{profile['id']}: {tool_id!r} must be exec-authorized "
        f"(present in allowed_tools, absent from denied_tools)"
    )
    assert tool_id in advertised, (
        f"{profile['id']}: {tool_id!r} must be advertised "
        f"(register the tool and/or add {profile['id']!r} to its allowed_agent_profiles)"
    )


@pytest.mark.parametrize("profile_id", RESEARCH_AGENTS)
def test_research_agents_have_search_knowledge(profile_id, reg):
    """All 5 research agents: ``search_knowledge`` advertised == authorized.

    RED today — search_knowledge is unregistered (no tool yaml) so it never advertises.
    """
    _assert_advertised_and_authorized(reg, _load_profile(profile_id), "search_knowledge")


@pytest.mark.parametrize("profile_id", RESEARCH_AGENTS)
def test_research_agents_have_response(profile_id, reg):
    """All 5 research agents: ``response`` advertised == authorized (Pitfall 1 under D-01)."""
    _assert_advertised_and_authorized(reg, _load_profile(profile_id), "response")


def test_classification_agent_has_search_macro_research(reg):
    """E-HIGH4 — research_classification_agent can call ``search_macro_research`` on BOTH
    surfaces (its four siblings already do)."""
    _assert_advertised_and_authorized(
        reg, _load_profile("vm107.research_classification_agent"), "search_macro_research"
    )


@pytest.mark.parametrize("tool_id", ["search_knowledge", "response"])
def test_research_chat_agent_core_research_tools(tool_id, reg):
    """E-HIGH3 — research_chat_agent's core research tooling advertised == authorized.

    Its current grants are not advertised to it (their allowed_agent_profiles omit it);
    the fix wires the intended research tools on both surfaces. RED today.
    """
    _assert_advertised_and_authorized(reg, _load_profile("research_chat_agent"), tool_id)
