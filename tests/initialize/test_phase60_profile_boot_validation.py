"""Phase 60.1 G8: boot hook validates Phase 60 v2 profiles.

P170 (170-05, D-01a / AGV-12): extended with the additive `critic_definition:`
lens-config boot check — a sibling to the DOMAIN_DEF_BOOT_STRICT block inside
``initialize_validate_agent_contracts`` (the registry-manifest iterator). It carries
its OWN inverted-default flag ``CRITIC_DEF_BOOT_STRICT`` (absent/!=1 => WARN-and-continue,
boot NEVER bricks; ==1 => raise ``SystemExit``) and validates each lens entry via
``LensConfig.from_profile`` (``yaml.safe_load`` ONLY — ASVS V5; presence/schema, never mutates).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

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


# ---------------------------------------------------------------------------
# P170 (170-05, D-01a / AGV-12) — critic_definition: lens-config boot-check coverage
#
# The registry-manifest iterator ``initialize_validate_agent_contracts`` now also
# presence/schema-validates the net-new ``critic_definition:`` block (the five lens
# configs) via ``LensConfig.from_profile`` (yaml.safe_load ONLY). Its OWN inverted-default
# flag ``CRITIC_DEF_BOOT_STRICT`` (absent/!=1 => WARN-and-continue; ==1 => raise) keeps the
# fragile-tree floor: boot NEVER bricks on a config finding. Left OFF this phase — flipped
# ON only after all-green + the Plan 06 live verify (reversible by unsetting, no code change).
# ---------------------------------------------------------------------------

_VM107_ROOT_CD = Path(__file__).resolve().parent.parent.parent
_REAL_PROFILE_DIR_CD = _VM107_ROOT_CD / "registry" / "agent_profile"

# A minimal, schema-valid single-lens critic_definition: block (one entry is enough to
# prove the iterator parses + validates each entry against the frozen LensConfig schema).
_VALID_CRITIC_DEF = {
    "EVIDENCE": {
        "version": "1.0.0",
        "lens": "EVIDENCE",
        "facets": ["top_contributors", "top_signals", "data_quality"],
        "failure_modes": ["EVIDENCE_UNSUPPORTED"],
        "scope": "CLAIM",
        "target_field": "claims",
    }
}

# A MALFORMED block: the lens entry is missing the required ``facets`` (min_length=1) key —
# LensConfig (extra="forbid", frozen) raises a ValidationError => one finding.
_MALFORMED_CRITIC_DEF = {
    "EVIDENCE": {
        "version": "1.0.0",
        "lens": "EVIDENCE",
        "failure_modes": ["EVIDENCE_UNSUPPORTED"],
        "scope": "CLAIM",
        "target_field": "claims",
    }
}


def _write_critic_profile(profile_dir: Path, filename: str, critic_definition: dict) -> Path:
    """Write a registry profile carrying a ``critic_definition:`` block into ``profile_dir``."""
    path = profile_dir / filename
    path.write_text(
        yaml.safe_dump(
            {"id": "vm107.specialized_critics", "critic_definition": critic_definition},
            sort_keys=False,
        )
    )
    return path


def test_critic_def_default_warn_never_raises(tmp_path, monkeypatch):
    """Flag unset => a MALFORMED critic_definition block does NOT raise (WARN-and-continue)."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.delenv("CRITIC_DEF_BOOT_STRICT", raising=False)
    monkeypatch.delenv("CONTRACT_BOOT_STRICT", raising=False)
    monkeypatch.delenv("DOMAIN_DEF_BOOT_STRICT", raising=False)
    d = tmp_path / "agent_profile"
    d.mkdir()
    _write_critic_profile(d, "vm107.specialized_critics.yaml", _MALFORMED_CRITIC_DEF)

    # Env-absent => WARN-and-continue; must not raise despite the malformed block.
    initialize_validate_agent_contracts(profile_dir=d)


def test_critic_def_strict_raises_on_malformed(tmp_path, monkeypatch):
    """CRITIC_DEF_BOOT_STRICT=1 + a malformed lens entry (missing facets) => SystemExit."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.setenv("CRITIC_DEF_BOOT_STRICT", "1")
    monkeypatch.delenv("CONTRACT_BOOT_STRICT", raising=False)
    monkeypatch.delenv("DOMAIN_DEF_BOOT_STRICT", raising=False)
    d = tmp_path / "agent_profile"
    d.mkdir()
    _write_critic_profile(d, "vm107.specialized_critics.yaml", _MALFORMED_CRITIC_DEF)

    with pytest.raises(SystemExit):
        initialize_validate_agent_contracts(profile_dir=d)


def test_critic_def_valid_block_no_raise_under_strict(tmp_path, monkeypatch):
    """A schema-valid critic_definition block passes even under strict (no false-fail)."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.setenv("CRITIC_DEF_BOOT_STRICT", "1")
    monkeypatch.delenv("CONTRACT_BOOT_STRICT", raising=False)
    monkeypatch.delenv("DOMAIN_DEF_BOOT_STRICT", raising=False)
    d = tmp_path / "agent_profile"
    d.mkdir()
    _write_critic_profile(d, "vm107.specialized_critics.yaml", _VALID_CRITIC_DEF)

    # Valid block => no finding => no raise, even under strict.
    initialize_validate_agent_contracts(profile_dir=d)


def test_critic_def_underscore_scaffold_skipped(tmp_path, monkeypatch):
    """A leading-underscore scaffold file with a malformed block is SKIPPED (no false-fail),
    even under strict — mirrors the _TEMPLATE.yaml skip convention (169-05/169-06)."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.setenv("CRITIC_DEF_BOOT_STRICT", "1")
    monkeypatch.delenv("CONTRACT_BOOT_STRICT", raising=False)
    monkeypatch.delenv("DOMAIN_DEF_BOOT_STRICT", raising=False)
    d = tmp_path / "agent_profile"
    d.mkdir()
    _write_critic_profile(d, "_scaffold.yaml", _MALFORMED_CRITIC_DEF)

    # Underscore scaffold => never iterated => no finding => no raise despite malformed.
    initialize_validate_agent_contracts(profile_dir=d)


def test_critic_def_never_mutates_profile(tmp_path, monkeypatch):
    """The on-disk critic_definition YAML is byte-identical before/after a run (read-only)."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.delenv("CRITIC_DEF_BOOT_STRICT", raising=False)
    monkeypatch.delenv("CONTRACT_BOOT_STRICT", raising=False)
    monkeypatch.delenv("DOMAIN_DEF_BOOT_STRICT", raising=False)
    d = tmp_path / "agent_profile"
    d.mkdir()
    p = _write_critic_profile(d, "vm107.specialized_critics.yaml", _VALID_CRITIC_DEF)
    before = p.read_bytes()

    initialize_validate_agent_contracts(profile_dir=d)

    assert p.read_bytes() == before  # never writes back to any profile path


def test_real_specialized_critics_green_strict(monkeypatch):
    """CRITIC_DEF_BOOT_STRICT=1 over the REAL registry corpus raises nothing — the shipped
    vm107.specialized_critics.yaml block is present + schema-valid (green gate after 170-05)."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.setenv("CRITIC_DEF_BOOT_STRICT", "1")
    monkeypatch.delenv("CONTRACT_BOOT_STRICT", raising=False)
    monkeypatch.delenv("DOMAIN_DEF_BOOT_STRICT", raising=False)
    # Real corpus; the critic_definition strict pass must not raise.
    initialize_validate_agent_contracts(profile_dir=_REAL_PROFILE_DIR_CD)
