"""Phase 62.1 — Prompt lint test scaffold: reader sub-profile contract compliance.

Three reader prompt directories are tested:
  - agents/trade_auditor_agent/_reader/prompts/
  - agents/behavioral_mentor_agent/_reader/prompts/
  - agents/weekly_review_agent/_reader/prompts/

Each directory must contain:
  - agent.system.main.role.md     (schema_version, STRICT OUTPUT CONTRACT, final-turn shape)
  - agent.system.main.specifics.md (schema_version, few-shot examples)

BUG-13 (partial) surfaced that:
  - trade_auditor role.md had schema_version: 2 (integer) — now fixed to "1.0" (string)
  - behavioral_mentor and weekly_review reader prompts have NOT been audited yet
  - Strict output contract sections and few-shot examples are absent from most files

Wave 1 (Plan 62.1-01) fixes all three reader profile prompts to be contract-compliant.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

# ---------------------------------------------------------------------------
# Reader prompt file paths
# ---------------------------------------------------------------------------

_READER_DIRS = {
    "trade_auditor": _VM107_ROOT / "agents" / "trade_auditor_agent" / "_reader" / "prompts",
    "behavioral_mentor": _VM107_ROOT / "agents" / "behavioral_mentor_agent" / "_reader" / "prompts",
    "weekly_review": _VM107_ROOT / "agents" / "weekly_review_agent" / "_reader" / "prompts",
}

_READER_ROLE_FILES = {
    name: d / "agent.system.main.role.md" for name, d in _READER_DIRS.items()
}
_READER_SPECIFICS_FILES = {
    name: d / "agent.system.main.specifics.md" for name, d in _READER_DIRS.items()
}

_ALL_AGENTS = list(_READER_DIRS.keys())


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _read_prompt(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="BUG-13 prompts pending in Phase 62.1 Plan 01 — currently only 1 of 3 role.md files have STRICT OUTPUT CONTRACT section",
    strict=False,
    run=True,
)
def test_all_three_reader_role_md_have_strict_output_contract_section():
    """All three reader role.md files must contain a STRICT OUTPUT CONTRACT section.

    The section heading must be present to ensure the LLM receives an explicit
    constraint about JSON-only output at the very beginning of its system prompt.
    Wave 1 will add this section to behavioral_mentor and weekly_review role.md.
    """
    missing = []
    for agent_name, role_path in _READER_ROLE_FILES.items():
        content = _read_prompt(role_path)
        if "STRICT OUTPUT CONTRACT" not in content:
            missing.append(agent_name)
    if missing:
        pytest.fail(
            f"Missing STRICT OUTPUT CONTRACT section in role.md for: {missing}. "
            "Wave 1 (Plan 62.1-01) will add these sections."
        )


@pytest.mark.xfail(
    reason="BUG-13 prompts pending in Phase 62.1 Plan 01 — schema_version string '1.0' required in all role.md",
    strict=False,
    run=True,
)
def test_all_three_reader_role_md_schema_version_is_string_1_0():
    """All three reader role.md files must declare schema_version as string '1.0'.

    The drift between integer ``2`` and string ``"1.0"`` in trade_auditor role.md
    was fixed in the Wave 0 session. This test locks that all three are consistent.
    """
    non_conformant = []
    for agent_name, role_path in _READER_ROLE_FILES.items():
        content = _read_prompt(role_path)
        # Accept both YAML-style `schema_version: "1.0"` and inline `schema_version: 1.0`
        if 'schema_version: "1.0"' not in content and "schema_version: '1.0'" not in content:
            non_conformant.append(agent_name)
    if non_conformant:
        pytest.fail(
            f"schema_version is not string '1.0' in role.md for: {non_conformant}. "
            "Wave 1 (Plan 62.1-01) will fix these."
        )


@pytest.mark.xfail(
    reason="BUG-13 prompts pending in Phase 62.1 Plan 01 — schema_version string '1.0' required in all specifics.md",
    strict=False,
    run=True,
)
def test_all_three_reader_specifics_md_schema_version_is_string_1_0():
    """All three reader specifics.md files must declare schema_version as string '1.0'."""
    non_conformant = []
    for agent_name, specifics_path in _READER_SPECIFICS_FILES.items():
        content = _read_prompt(specifics_path)
        if 'schema_version: "1.0"' not in content and "schema_version: '1.0'" not in content:
            non_conformant.append(agent_name)
    if non_conformant:
        pytest.fail(
            f"schema_version is not string '1.0' in specifics.md for: {non_conformant}. "
            "Wave 1 (Plan 62.1-01) will fix these."
        )


@pytest.mark.xfail(
    reason="BUG-13 prompts pending in Phase 62.1 Plan 01 — required final-turn shape example missing from most role.md files",
    strict=False,
    run=True,
)
def test_all_three_reader_role_md_have_required_final_turn_shape_example():
    """All three reader role.md files must include a Required final-turn shape example.

    The example must show the exact ``{tool_name: "response", tool_args: {text: "<JSON>"}}``
    wrapper so the LLM has a concrete structural anchor rather than inferred guidance.
    """
    missing = []
    for agent_name, role_path in _READER_ROLE_FILES.items():
        content = _read_prompt(role_path)
        # Accept variations of the final-turn shape section heading
        has_shape = (
            "Required final-turn shape" in content
            or "required final-turn shape" in content.lower()
            or "final_turn_shape" in content
        )
        if not has_shape:
            missing.append(agent_name)
    if missing:
        pytest.fail(
            f"Missing 'Required final-turn shape' example in role.md for: {missing}. "
            "Wave 1 (Plan 62.1-01) will add these."
        )


@pytest.mark.xfail(
    reason="BUG-13 prompts pending in Phase 62.1 Plan 01 — few-shot examples missing from most specifics.md files",
    strict=False,
    run=True,
)
def test_all_three_reader_specifics_md_have_few_shot_example():
    """All three reader specifics.md files must include at least one few-shot example.

    Few-shot examples (worked input → output pairs) are the primary mechanism for
    anchoring LLM behavior to the contract.  The absence of few-shot examples in
    specifics.md is a known cause of DeepSeek producing markdown instead of JSON.
    """
    missing = []
    for agent_name, specifics_path in _READER_SPECIFICS_FILES.items():
        content = _read_prompt(specifics_path)
        # Few-shot examples typically contain "Example input" or "Example output"
        # or are delimited by markdown code blocks with JSON
        has_few_shot = (
            "example" in content.lower()
            and ("input" in content.lower() or "output" in content.lower())
        )
        if not has_few_shot:
            missing.append(agent_name)
    if missing:
        pytest.fail(
            f"Missing few-shot example in specifics.md for: {missing}. "
            "Wave 1 (Plan 62.1-01) will add these."
        )
