"""Phase 43.1 — KB routing portability tests (Wave 0 scaffold; Plan 02 turns GREEN).

Verifies KB-ROUTING-PORTABLE-01:
  - prompts/agent.system.main.kb_routing.md exists
  - prompts/agent.system.main.md includes it
  - agents/default/agent.system.main.specifics.md and agents/agent0/prompts/agent.system.main.specifics.md
    no longer carry duplicated KB ROUTING block
  - kb_routing.md content reachable for all 5 profiles
"""
import os, pytest

VM107_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILES = ["default", "agent0", "developer", "hacker", "researcher"]


@pytest.mark.xfail(reason="Plan 02 creates prompts/agent.system.main.kb_routing.md")
def test_kb_routing_file_exists():
    assert os.path.exists(os.path.join(VM107_ROOT, "prompts", "agent.system.main.kb_routing.md"))


@pytest.mark.xfail(reason="Plan 02 adds {{ include }} to prompts/agent.system.main.md")
def test_main_md_includes_kb_routing():
    main = open(os.path.join(VM107_ROOT, "prompts", "agent.system.main.md")).read()
    assert 'include "agent.system.main.kb_routing.md"' in main


@pytest.mark.xfail(reason="Plan 02 removes duplicated KB block from default + agent0 specifics.md")
def test_no_duplicates():
    paths = [
        os.path.join(VM107_ROOT, "agents", "default", "agent.system.main.specifics.md"),
        os.path.join(VM107_ROOT, "agents", "agent0", "prompts", "agent.system.main.specifics.md"),
    ]
    for p in paths:
        if os.path.exists(p):
            content = open(p).read()
            # KB routing rules contain phrase "KNOWLEDGE ROUTING RULES" or "MUST call `search_knowledge`"
            assert "KNOWLEDGE ROUTING RULES" not in content, f"Duplicate KB block in {p}"
            assert "MUST call `search_knowledge`" not in content, f"Duplicate KB block in {p}"


@pytest.mark.xfail(reason="Plan 02 portability simulation: kb_routing reaches all 5 profiles")
@pytest.mark.parametrize("profile", PROFILES)
def test_kb_routing_reaches_profile(profile):
    # Simulates _10_main_prompt.py path-resolution: profile prompts/ shadows base prompts/
    # If profile has no kb_routing override AND no inline KB block, base prompts/agent.system.main.kb_routing.md applies.
    profile_override = os.path.join(VM107_ROOT, "agents", profile, "prompts", "agent.system.main.kb_routing.md")
    base = os.path.join(VM107_ROOT, "prompts", "agent.system.main.kb_routing.md")
    resolved = profile_override if os.path.exists(profile_override) else base
    content = open(resolved).read()
    assert "search_knowledge" in content, f"Profile {profile}: kb_routing.md must contain search_knowledge mandate"
