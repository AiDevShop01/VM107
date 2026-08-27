"""Unit tests for scripts/agent_contract_lint.py (Phase 167-01, AGV-03/AGV-04).

RED-first (Task 1): these fail with ImportError until Task 2 lands the lint.
Standalone by construction — no `import frontmatter`, no VM107 app runtime import.
"""
from __future__ import annotations

from pathlib import Path


def test_join_key_normalization():
    """canon() resolves the 3-way id inconsistency (AGV-03 / E-CRIT2)."""
    from scripts.agent_contract_lint import canon

    # vm107.-prefix stripped, snake->kebab, lowercased — both sides land equal.
    assert canon("vm107.growth_domain_analyst") == "growth-domain-analyst"
    assert canon("growth-domain-analyst") == "growth-domain-analyst"
    assert canon("vm107.growth_domain_analyst") == canon("growth-domain-analyst")
    # dotted ._role sub-profile suffix collapses onto the parent kebab id.
    assert canon("behavioral_mentor_agent._reader") == "behavioral-mentor-agent"
    # bare (un-prefixed) snake id.
    assert canon("macro_agent") == "macro-agent"


def test_three_checks(corpus):
    """check-(a) orphan / check-(b) missing field / check-(c) tools disagreement fire."""
    from scripts.agent_contract_lint import run_checks

    findings = run_checks(*corpus)
    agents_by_check = lambda c: {f.agent for f in findings if f.check == c}  # noqa: E731

    assert "orphan-agent" in agents_by_check("a")
    assert "missing-field-agent" in agents_by_check("b")
    assert "disagree-agent" in agents_by_check("c")


def test_subprofile_check_c_collapses_to_parent(corpus):
    """A `._reader` sub-profile's NARROWER allow-list must not false-disagree.

    check-(c) collapses by canon() and evaluates ONLY the canon-base parent
    against the single catalogue §6 — so `collapse-agent` never appears in (c).
    """
    from scripts.agent_contract_lint import run_checks

    findings = run_checks(*corpus)
    c_agents = {f.agent for f in findings if f.check == "c"}
    assert "collapse-agent" not in c_agents


def test_warn_vs_block_exit(corpus, profile_dir, catalogue_dir, write_profile, write_catalogue):
    """WARN mode always exits 0; --block exits 1 on findings, 0 when clean."""
    from scripts.agent_contract_lint import run_lint

    # The static corpus HAS findings.
    assert run_lint(*corpus, block=False) == 0   # WARN → always 0
    assert run_lint(*corpus, block=True) == 1    # BLOCK → 1 on any finding

    # A clean corpus (one fully-conformant pair, tools agree) → 0 in both modes.
    write_profile(profile_dir, "vm107.solo.yaml", id="vm107.solo", allowed_tools=["tool_a"])
    write_catalogue(
        catalogue_dir,
        "solo.md",
        {
            "agent": "solo",
            "family": "macro",
            "status": "built",
            "authority": "propose",
            "trigger": ["event-driven"],
            "contract_version": 1,
        },
        tools=["tool_a"],
    )
    assert run_lint(profile_dir, catalogue_dir, block=False) == 0
    assert run_lint(profile_dir, catalogue_dir, block=True) == 0


def test_excluded_ids_never_orphan(corpus):
    """default / agent_zero / vm107 infra profiles never raise check-(a) (D-07)."""
    from scripts.agent_contract_lint import run_checks, EXCLUDED_IDS

    assert EXCLUDED_IDS == {"default", "agent-zero", "vm107"}
    findings = run_checks(*corpus)
    a_agents = {f.agent for f in findings if f.check == "a"}
    assert "default" not in a_agents
    assert "agent-zero" not in a_agents
    assert "vm107" not in a_agents


def test_malformed_frontmatter_warns_not_crashes(profile_dir, catalogue_dir):
    """A catalogue .md with a broken --- fence is skipped with a WARN, never raises."""
    from scripts.agent_contract_lint import run_checks

    (catalogue_dir / "broken.md").write_text(
        "---\nagent: [unterminated\nfamily: macro\n---\n\n## 1. Mission\nx\n"
    )
    # Must not raise despite the malformed frontmatter.
    findings = run_checks(profile_dir, catalogue_dir)
    assert any(f.check == "warn" for f in findings)


def test_lint_is_standalone():
    """The lint imports neither python-frontmatter nor the VM107 app runtime, and
    never uses the unsafe yaml.load (AGV-04 / D-08 / ASVS V5 / T-167-01)."""
    lint_path = (
        Path(__file__).resolve().parent.parent.parent
        / "scripts"
        / "agent_contract_lint.py"
    )
    src = lint_path.read_text()
    assert "import frontmatter" not in src
    # only yaml.safe_load — no bare yaml.load(
    import re

    assert not re.search(r"yaml\.load\(", src)


def test_required_contract_fields_published():
    """REQUIRED_CONTRACT_FIELDS is the schema every authoring plan (167-03..07) conforms to."""
    from scripts.agent_contract_lint import REQUIRED_CONTRACT_FIELDS

    for field in ("agent", "family", "status", "authority", "trigger", "contract_version"):
        assert field in REQUIRED_CONTRACT_FIELDS
