"""Tests for CTX-§2 nested sub-profile discovery in helpers/subagents.py.

Tests verify:
  - _get_agents_list_from_dir recurses one level into _reader/_analyzer/_writer subdirs
  - Nested sub-profiles are registered under dotted agent_ids (e.g. "trade_auditor_agent._reader")
  - Top-level profiles (v1) with no sentinel subdirs continue to load as before
  - load_agent_data("profile._reader") resolves to agents/profile/_reader/ via standard cascade
  - Non-sentinel subdir names (prompts/, skills/, tools/) are NOT treated as sub-profiles

BLOCKER #1 closure: this file existing + tests passing unblocks Wave 2 (60-09/60-10/60-11)
which writes NESTED profile YAMLs at agents/<profile>/_reader/agent.yaml.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure VM107 root is on sys.path — tests/ directory must NOT have __init__.py
# in tests/helpers/ or it would shadow the real helpers package.
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest

from helpers.subagents import _get_agents_list_from_dir, load_agent_data


def _seed_nested_profile(
    tmp_path: Path,
    profile: str,
    sub_profiles: tuple[str, ...] = ("_reader", "_analyzer", "_writer"),
):
    """Create a nested profile directory structure under tmp_path.

    Layout:
        tmp_path/<profile>/agent.yaml
        tmp_path/<profile>/_reader/agent.yaml
        tmp_path/<profile>/_reader/prompts/agent.system.main.role.md
        (same for _analyzer and _writer)
    """
    prof_dir = tmp_path / profile
    prof_dir.mkdir()
    (prof_dir / "agent.yaml").write_text(
        f"name: {profile}\ntitle: {profile}\ndescription: top-level\n"
    )
    for sp in sub_profiles:
        sd = prof_dir / sp
        sd.mkdir()
        (sd / "agent.yaml").write_text(
            f"name: {profile}{sp}\ntitle: {profile}{sp}\ndescription: nested\n"
        )
        (sd / "prompts").mkdir()
        (sd / "prompts" / "agent.system.main.role.md").write_text("nested role")
    return prof_dir


def test_nested_sub_profile_discovery(tmp_path: Path):
    """CTX-§2 LOCKED — _get_agents_list_from_dir must discover nested _reader/_analyzer/_writer
    subdirs under a top-level profile dir and register them under dotted agent_ids.

    This is BLOCKER #1 closure: proves the discovery cascade handles the NESTED on-disk layout
    mandated by CONTEXT.md §2.
    """
    _seed_nested_profile(tmp_path, "trade_auditor_agent")
    result = _get_agents_list_from_dir(str(tmp_path), origin="user")
    assert "trade_auditor_agent" in result, "top-level profile must still register"
    assert "trade_auditor_agent._reader" in result, (
        "nested _reader must register under dotted agent_id 'trade_auditor_agent._reader'"
    )
    assert "trade_auditor_agent._analyzer" in result, (
        "nested _analyzer must register under dotted agent_id 'trade_auditor_agent._analyzer'"
    )
    assert "trade_auditor_agent._writer" in result, (
        "nested _writer must register under dotted agent_id 'trade_auditor_agent._writer'"
    )


def test_top_level_only_v1_profile_still_discovered(tmp_path: Path):
    """Backward compat — a v1 profile dir with no _reader/_analyzer/_writer must still load.

    Existing profiles (strategy_agent, idea_agent, agent0) must not be broken by the patch.
    """
    prof = tmp_path / "strategy_agent"
    prof.mkdir()
    (prof / "agent.yaml").write_text(
        "name: strategy_agent\ntitle: strategy\ndescription: v1\n"
    )
    result = _get_agents_list_from_dir(str(tmp_path), origin="user")
    assert "strategy_agent" in result, "v1 profile must still be discovered"
    assert not any(
        k.startswith("strategy_agent.") for k in result
    ), "no spurious nested entries for a v1 profile without sentinel subdirs"


def test_dotted_load_resolves_nested_path(tmp_path: Path, monkeypatch):
    """call_subordinate(profile='trade_auditor_agent._reader') resolves to the nested
    directory under the standard cascade (default → user → project).

    BLOCKER #1 verification: load_agent_data('trade_auditor_agent._reader') must work
    after the _load_agent_data_from_dir patch.
    """
    _seed_nested_profile(tmp_path, "trade_auditor_agent")
    # Monkeypatch DEFAULT_AGENTS_DIR and USER_AGENTS_DIR so load_agent_data picks up
    # our seeded tree. USER_AGENTS_DIR is set to a non-existent path so only the
    # default cascade fires.
    import helpers.subagents as sa

    monkeypatch.setattr(sa, "DEFAULT_AGENTS_DIR", str(tmp_path))
    monkeypatch.setattr(sa, "USER_AGENTS_DIR", str(tmp_path / "_user_unused"))
    loaded = sa.load_agent_data("trade_auditor_agent._reader")
    assert loaded is not None, (
        "load_agent_data('trade_auditor_agent._reader') must not return None"
    )
    assert loaded.name == "trade_auditor_agent._reader", (
        f"Expected name 'trade_auditor_agent._reader', got {loaded.name!r}"
    )


def test_nested_marker_only_for_sentinel_names(tmp_path: Path):
    """Subdirs named anything other than _reader/_analyzer/_writer must NOT be
    registered as sub-profiles.

    Pitfall guard: prompts/, skills/, tools/ are common non-sentinel subdirs that
    must be ignored by the nested discovery logic.
    """
    prof = tmp_path / "trade_auditor_agent"
    prof.mkdir()
    (prof / "agent.yaml").write_text(
        "name: trade_auditor_agent\ntitle: x\ndescription: x\n"
    )
    for noise in ("prompts", "skills", "tools"):
        noise_dir = prof / noise
        noise_dir.mkdir()
        # Each has an agent.yaml to ensure it would register IF the logic were wrong
        (noise_dir / "agent.yaml").write_text(
            f"name: noise_{noise}\ntitle: noise\ndescription: noise\n"
        )
    result = _get_agents_list_from_dir(str(tmp_path), origin="user")
    assert "trade_auditor_agent" in result, "top-level profile must register"
    assert not any(
        k.startswith("trade_auditor_agent.") for k in result
    ), (
        f"Non-sentinel subdirs (prompts/skills/tools) must not become sub-profiles. "
        f"Got unexpected keys: {[k for k in result if k.startswith('trade_auditor_agent.')]}"
    )
