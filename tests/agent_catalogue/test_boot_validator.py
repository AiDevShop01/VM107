"""Phase 167 Plan 08 (AGV-05): boot-validator tests for the NEW additive iterator
``initialize.initialize_validate_agent_contracts()``.

The iterator globs ``registry/agent_profile/*.yaml``, does presence/parity ONLY
(never mutates a profile), and is env-gated with the INVERTED default (D-02
fragile-tree guard): ``CONTRACT_BOOT_STRICT`` absent / != "1" => WARN-and-continue
(never raises); == "1" => raise ``SystemExit``. It reuses ``canon()`` + ``EXCLUDED_IDS``
from ``scripts/agent_contract_lint.py`` so the 3 infra profiles are skipped and the 9
nested ``._role`` sub-profiles inherit their canon-base parent's contract (must NOT
false-fail).

Mirrors the ``tests/initialize/test_phase60_profile_boot_validation.py`` header
(sys.path + os.environ.setdefault). Fixture profiles are written into a tmp dir and the
iterator's glob root is pointed at them; the green-gate case runs against the REAL
``registry/agent_profile/`` corpus (all in-scope agents authored green by 167-03..07).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

# Ensure VM107 root is on sys.path so `import initialize` / `scripts...` resolve.
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# Some VM107 import paths expect these env vars; set benign test defaults.
os.environ.setdefault("VM100_INTERNAL_BASE_URL", "http://test-vm100:8000")
os.environ.setdefault("SCOPE_DISPATCHER_SECRET_KEY", "test-secret")

_REAL_PROFILE_DIR = _VM107_ROOT / "registry" / "agent_profile"

# A minimal valid agent_contract: block (presence is all the boot check asserts).
_VALID_CONTRACT = {
    "contract_version": 1,
    "catalogue_ref": "markets/some-agent.md",
    "authority": "recommend",
}


def _write_profile(profile_dir: Path, filename: str, **fields) -> Path:
    """Write a registry-profile YAML into ``profile_dir`` (mirrors conftest.write_profile)."""
    path = profile_dir / filename
    path.write_text(yaml.safe_dump(fields, sort_keys=False))
    return path


def test_default_warn_never_raises(tmp_path, monkeypatch):
    """Flag unset => a canon-base profile MISSING agent_contract does NOT raise (WARN)."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.delenv("CONTRACT_BOOT_STRICT", raising=False)
    d = tmp_path / "agent_profile"
    d.mkdir()
    _write_profile(d, "vm107.blockless_agent.yaml", id="vm107.blockless_agent",
                   allowed_tools=["tool_a"])  # NO agent_contract block

    # Must not raise even though a finding exists — env-absent => WARN-and-continue.
    count = initialize_validate_agent_contracts(profile_dir=d)
    assert count == 1  # one canon-base profile validated (counted, warned, not raised)


def test_strict_raises_on_missing(tmp_path, monkeypatch):
    """CONTRACT_BOOT_STRICT=1 + a canon-base profile missing the block => SystemExit."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.setenv("CONTRACT_BOOT_STRICT", "1")
    d = tmp_path / "agent_profile"
    d.mkdir()
    _write_profile(d, "vm107.blockless_agent.yaml", id="vm107.blockless_agent",
                   allowed_tools=["tool_a"])  # NO agent_contract block

    with pytest.raises(SystemExit):
        initialize_validate_agent_contracts(profile_dir=d)


def test_nested_subprofile_inherits_not_fail(tmp_path, monkeypatch):
    """A ``._reader`` sub-profile WITHOUT a block does NOT raise under STRICT when its
    canon-base parent HAS the block (the sub-profile inherits the parent's contract).

    Pins the inheritance mechanism BEFORE the real-corpus gate: a blockless sub-profile
    must never independently produce a missing-block finding.
    """
    from initialize import initialize_validate_agent_contracts

    monkeypatch.setenv("CONTRACT_BOOT_STRICT", "1")
    d = tmp_path / "agent_profile"
    d.mkdir()
    # Canon-base parent WITH a contract block.
    _write_profile(d, "collapse_agent.yaml", id="collapse_agent",
                   allowed_tools=["tool_a", "tool_b"], agent_contract=dict(_VALID_CONTRACT))
    # Nested sub-profile WITHOUT a block — inherits the parent, must NOT false-fail.
    _write_profile(d, "collapse_agent._reader.yaml", id="collapse_agent._reader",
                   allowed_tools=["tool_a"])

    # STRICT + no finding on the parent => no raise; the sub-profile is skipped entirely.
    count = initialize_validate_agent_contracts(profile_dir=d)
    assert count == 1  # only the canon-base parent is counted; the sub-profile is not


def test_excluded_infra_not_counted(tmp_path, monkeypatch):
    """The 3 infra profiles (default/agent_zero/vm107) are skipped — never counted,
    never fail — even under STRICT and even without an agent_contract block (D-07)."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.setenv("CONTRACT_BOOT_STRICT", "1")
    d = tmp_path / "agent_profile"
    d.mkdir()
    _write_profile(d, "default.yaml", id="default")
    _write_profile(d, "agent_zero.yaml", id="agent_zero")
    _write_profile(d, "vm107.yaml", id="vm107")

    # All excluded => zero validated, no finding, no raise.
    count = initialize_validate_agent_contracts(profile_dir=d)
    assert count == 0


def test_never_mutates_profile(tmp_path, monkeypatch):
    """The on-disk fixture YAML is byte-identical before/after a run (presence/parity only)."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.delenv("CONTRACT_BOOT_STRICT", raising=False)
    d = tmp_path / "agent_profile"
    d.mkdir()
    p = _write_profile(d, "vm107.valid_agent.yaml", id="vm107.valid_agent",
                       allowed_tools=["tool_a"], agent_contract=dict(_VALID_CONTRACT))
    before = p.read_bytes()

    initialize_validate_agent_contracts(profile_dir=d)

    assert p.read_bytes() == before  # never writes back to any profile path


def test_all_real_profiles_green_strict(monkeypatch):
    """CONTRACT_BOOT_STRICT=1 over the REAL registry/agent_profile/ raises nothing —
    the green gate after 167-03..07 authoring. The 9 nested ``._role`` sub-profiles
    must NOT false-fail (they inherit their canon-base parent's contract)."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.setenv("CONTRACT_BOOT_STRICT", "1")
    # No profile_dir arg => the real registry corpus. Must not raise.
    count = initialize_validate_agent_contracts(profile_dir=_REAL_PROFILE_DIR)
    assert count >= 40  # all in-scope canon-base agents validated green


# ---------------------------------------------------------------------------
# P169 (169-05, D-11 / AGV-09 / AGV-11) — domain_definition: boot-check coverage
#
# The SAME env-gated boot hook now also presence/schema-validates the net-new
# `domain_definition:` block on the 12 vm107.*_domain_analyst.yaml manifests via
# DomainDefinition.from_profile (yaml.safe_load ONLY). It carries its OWN inverted-
# default flag DOMAIN_DEF_BOOT_STRICT (absent/!=1 => WARN-and-continue; ==1 => raise)
# so boot NEVER bricks on the fragile tree before all 12 blocks land (Pitfall 3).
# ---------------------------------------------------------------------------

# A minimal, schema-valid domain_definition: block (version/knowledge_version +
# a reasoning_rules with a default_state is the smallest thing that parses).
_VALID_DOMAIN_DEF = {
    "version": "1.0.0",
    "knowledge_version": "test-domain-v1",
    "reasoning_rules": {"default_state": "Neutral"},
}

# The 12 canonical domain slugs the block is authored for (Plan 169-05).
_DOMAIN_SLUGS = [
    "inflation", "growth", "labour", "housing", "credit", "monetary_policy",
    "fiscal", "external_sector", "manufacturing", "consumer",
    "financial_conditions", "commodities",
]


def test_domain_def_default_warn_never_raises(tmp_path, monkeypatch):
    """Flag unset => a domain-analyst manifest MISSING domain_definition does NOT raise."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.delenv("DOMAIN_DEF_BOOT_STRICT", raising=False)
    monkeypatch.delenv("CONTRACT_BOOT_STRICT", raising=False)
    d = tmp_path / "agent_profile"
    d.mkdir()
    # A domain-analyst profile WITH agent_contract but WITHOUT domain_definition.
    _write_profile(d, "vm107.inflation_domain_analyst.yaml",
                   id="vm107.inflation_domain_analyst",
                   allowed_tools=["tool_a"], agent_contract=dict(_VALID_CONTRACT))

    # Env-absent for BOTH flags => WARN-and-continue; must not raise.
    initialize_validate_agent_contracts(profile_dir=d)


def test_domain_def_strict_raises_on_missing(tmp_path, monkeypatch):
    """DOMAIN_DEF_BOOT_STRICT=1 + a domain-analyst manifest missing the block => SystemExit."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.setenv("DOMAIN_DEF_BOOT_STRICT", "1")
    monkeypatch.delenv("CONTRACT_BOOT_STRICT", raising=False)
    d = tmp_path / "agent_profile"
    d.mkdir()
    _write_profile(d, "vm107.inflation_domain_analyst.yaml",
                   id="vm107.inflation_domain_analyst",
                   allowed_tools=["tool_a"], agent_contract=dict(_VALID_CONTRACT))

    with pytest.raises(SystemExit):
        initialize_validate_agent_contracts(profile_dir=d)


def test_domain_def_strict_raises_on_malformed(tmp_path, monkeypatch):
    """DOMAIN_DEF_BOOT_STRICT=1 + a domain_definition block missing a required key
    (reasoning_rules) => SystemExit (schema validation, not just presence)."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.setenv("DOMAIN_DEF_BOOT_STRICT", "1")
    monkeypatch.delenv("CONTRACT_BOOT_STRICT", raising=False)
    d = tmp_path / "agent_profile"
    d.mkdir()
    malformed = {"version": "1.0.0", "knowledge_version": "x"}  # no reasoning_rules
    _write_profile(d, "vm107.inflation_domain_analyst.yaml",
                   id="vm107.inflation_domain_analyst",
                   allowed_tools=["tool_a"], agent_contract=dict(_VALID_CONTRACT),
                   domain_definition=malformed)

    with pytest.raises(SystemExit):
        initialize_validate_agent_contracts(profile_dir=d)


def test_domain_def_valid_block_no_raise_under_strict(tmp_path, monkeypatch):
    """A schema-valid domain_definition block passes even under strict (no false-fail)."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.setenv("DOMAIN_DEF_BOOT_STRICT", "1")
    monkeypatch.delenv("CONTRACT_BOOT_STRICT", raising=False)
    d = tmp_path / "agent_profile"
    d.mkdir()
    _write_profile(d, "vm107.inflation_domain_analyst.yaml",
                   id="vm107.inflation_domain_analyst",
                   allowed_tools=["tool_a"], agent_contract=dict(_VALID_CONTRACT),
                   domain_definition=dict(_VALID_DOMAIN_DEF))

    # Valid block => no finding => no raise.
    initialize_validate_agent_contracts(profile_dir=d)


def test_all_12_real_domain_defs_parse():
    """Every one of the 12 real domain-analyst manifests carries a conforming
    domain_definition: block (DomainDefinition.from_profile parses each)."""
    from core.agents.domain_definition import DomainDefinition

    for slug in _DOMAIN_SLUGS:
        path = _REAL_PROFILE_DIR / f"vm107.{slug}_domain_analyst.yaml"
        dd = DomainDefinition.from_profile(str(path))
        assert dd.version  # non-empty version
        assert dd.reasoning_rules.default_state  # classifier default present


def test_all_real_domain_defs_green_strict(monkeypatch):
    """DOMAIN_DEF_BOOT_STRICT=1 over the REAL corpus raises nothing — all 12 blocks
    are present + schema-valid (the green gate after 169-05 authoring)."""
    from initialize import initialize_validate_agent_contracts

    monkeypatch.setenv("DOMAIN_DEF_BOOT_STRICT", "1")
    monkeypatch.delenv("CONTRACT_BOOT_STRICT", raising=False)
    # Real corpus; the domain_definition strict pass must not raise.
    initialize_validate_agent_contracts(profile_dir=_REAL_PROFILE_DIR)
