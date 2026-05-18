"""Phase 48 Plan 06 — strategy_refinement_critic agent_profile registry YAML.

Phase 47.6 mandate: every agent profile must have a registry entry. This
profile entry cross-references the 5 family SKILL.md overlays, declares the
HARD-blocked sensitive tools, and lists the soft-allowed read tools.

Also asserts model_routing.yaml carries the affinity block for the profile.

REQ-48-REG.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import yaml


_PROFILE_YAML = (
    _VM107_ROOT
    / "registry"
    / "agent_profile"
    / "strategy_refinement_critic.yaml"
)
_MODEL_ROUTING_YAML = _VM107_ROOT / "conf" / "model_routing.yaml"

FAMILY_SKILL_IDS = (
    "breakout-critic",
    "mean-reversion-critic",
    "trend-continuation-critic",
    "auction-rotation-critic",
    "volatility-expansion-critic",
)


def _load_profile() -> dict:
    return yaml.safe_load(_PROFILE_YAML.read_text())


def _load_routing() -> dict:
    return yaml.safe_load(_MODEL_ROUTING_YAML.read_text())


def test_profile_yaml_exists():
    assert _PROFILE_YAML.exists(), f"Missing profile YAML at {_PROFILE_YAML}"


def test_profile_yaml_required_fields():
    """YAML carries the Phase 47.6 required shape."""
    data = _load_profile()
    assert data["id"] == "strategy_refinement_critic"
    assert data["type"] == "agent_profile"
    assert data["status"] == "real"
    assert data["shipped"] == 48
    assert data["name"] == "strategy_refinement_critic"
    assert isinstance(data["description"], str) and len(data["description"]) > 0
    assert data["version"] == "1.0.0"
    assert data["phase"] == 48
    assert data["deprecated"] is False


def test_profile_yaml_id_not_critic_agent():
    """Anti-pattern enforcement: profile MUST NOT be named 'critic_agent'.

    CONTEXT § Anti-Patterns explicitly rejects that name (semantic bleed
    from Phase 60 mentor and Phase 46 mesh).
    """
    data = _load_profile()
    assert data["id"] != "critic_agent"
    assert data["name"] != "critic_agent"


def test_profile_yaml_hard_blocked_tools():
    """denied_tools lists the 3 sensitive tools (CONTEXT § Decision 1)."""
    data = _load_profile()
    denied = data["denied_tools"]
    assert "call_subordinate" in denied
    assert "code_execution_tool" in denied
    assert "trade_execution_tool" in denied


def test_profile_yaml_soft_allowed_tools():
    """allowed_tools carries the 5 soft-scope read/response tools."""
    data = _load_profile()
    allowed = data["allowed_tools"]
    for tool in (
        "search_knowledge",
        "document_query",
        "response",
        "lookup_capability",
        "skills_tool",
    ):
        assert tool in allowed, f"{tool} missing from allowed_tools"


def test_profile_yaml_lists_all_five_family_skills():
    """allowed_skills enumerates all 5 family overlays."""
    data = _load_profile()
    allowed_skills = data["allowed_skills"]
    for sid in FAMILY_SKILL_IDS:
        assert sid in allowed_skills, f"{sid} missing from allowed_skills"


def test_profile_yaml_register_capability_directive():
    """YAML header contains REGISTER_CAPABILITY directive comment."""
    text = _PROFILE_YAML.read_text()
    assert "REGISTER_CAPABILITY" in text
    assert "type=agent_profile" in text
    assert "id=strategy_refinement_critic" in text


def test_model_routing_has_critic_affinity_block():
    """conf/model_routing.yaml has a strategy_refinement_critic affinity block."""
    routing = _load_routing()
    affinity = routing["affinity"]
    assert "strategy_refinement_critic" in affinity, (
        "conf/model_routing.yaml missing strategy_refinement_critic affinity block"
    )
    block = affinity["strategy_refinement_critic"]
    # Phase 44/45 pattern — at least one task_type + a default with 3 tiers
    assert "default" in block
    for tier in ("primary", "secondary", "local"):
        assert tier in block["default"], f"affinity default missing tier {tier}"


def test_model_routing_has_critic_budget_cap():
    """budget_caps.agent_types has a strategy_refinement_critic entry."""
    routing = _load_routing()
    caps = routing["budget_caps"]["agent_types"]
    assert "strategy_refinement_critic" in caps, (
        "budget_caps.agent_types missing strategy_refinement_critic"
    )
    assert "max_usd_per_day" in caps["strategy_refinement_critic"]


def test_skill_yaml_cross_reference_matches_profile():
    """Each family skill YAML's applies_to_profiles matches profile's allowed_skills."""
    profile = _load_profile()
    profile_skills = set(profile["allowed_skills"])
    skill_root = _VM107_ROOT / "registry" / "skill"

    for sid in FAMILY_SKILL_IDS:
        assert sid in profile_skills, (
            f"Skill {sid} listed in family_skill_map but not in profile.allowed_skills"
        )
        skill_yaml = skill_root / f"{sid}.yaml"
        assert skill_yaml.exists()
        data = yaml.safe_load(skill_yaml.read_text())
        assert "strategy_refinement_critic" in data["applies_to_profiles"]
