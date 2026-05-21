"""Phase 62.1 — Prompt lint test: reader sub-profile contract compliance.

Three reader prompt directories are tested:
  - agents/trade_auditor_agent/_reader/prompts/
  - agents/behavioral_mentor_agent/_reader/prompts/
  - agents/weekly_review_agent/_reader/prompts/

Each directory must contain:
  - agent.system.main.role.md     (schema_version "1.0", STRICT OUTPUT CONTRACT,
                                   final-turn shape, Prohibited outputs)
  - agent.system.main.specifics.md (schema_version "1.0", wrapper instruction,
                                    no 'raw JSON object', few-shot example)

This test is the permanent gate against future prompt drift introduced by BUG-13.
All tests are LIVE (no xfail) after Plan 03 ships the prompt hardening.
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

PROFILES = ["trade_auditor_agent", "behavioral_mentor_agent", "weekly_review_agent"]

_READER_DIRS = {
    p: _VM107_ROOT / "agents" / p / "_reader" / "prompts"
    for p in PROFILES
}

_READER_ROLE_FILES = {
    name: d / "agent.system.main.role.md" for name, d in _READER_DIRS.items()
}
_READER_SPECIFICS_FILES = {
    name: d / "agent.system.main.specifics.md" for name, d in _READER_DIRS.items()
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _read_role(profile: str) -> str:
    path = _READER_ROLE_FILES[profile]
    if not path.exists():
        pytest.skip(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def _read_specifics(profile: str) -> str:
    path = _READER_SPECIFICS_FILES[profile]
    if not path.exists():
        pytest.skip(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# role.md tests (5 assertions × 3 profiles = 15 parameterized cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES)
def test_role_md_has_strict_output_contract(profile: str) -> None:
    """role.md must contain a STRICT OUTPUT CONTRACT section heading."""
    role = _read_role(profile)
    assert "STRICT OUTPUT CONTRACT" in role, (
        f"{profile} role.md missing STRICT OUTPUT CONTRACT section. "
        "This is the primary LLM discipline anchor."
    )


@pytest.mark.parametrize("profile", PROFILES)
def test_role_md_schema_version_is_string_1_0(profile: str) -> None:
    """role.md must declare schema_version as string '1.0' (not integer 2)."""
    role = _read_role(profile)
    has_string_version = (
        'schema_version: "1.0"' in role
        or "schema_version: '1.0'" in role
    )
    assert has_string_version, (
        f"{profile} role.md does not contain schema_version: \"1.0\" (string). "
        "Integer schema_version: 2 was the BUG-13 root cause."
    )


@pytest.mark.parametrize("profile", PROFILES)
def test_role_md_has_final_turn_shape(profile: str) -> None:
    """role.md must include tool_args + text + response as final-turn shape elements."""
    role = _read_role(profile)
    assert "tool_args" in role, f"{profile} role.md missing tool_args in final-turn shape"
    assert "text" in role, f"{profile} role.md missing 'text' key in final-turn shape"
    assert "response" in role.lower(), f"{profile} role.md missing 'response' tool reference"


@pytest.mark.parametrize("profile", PROFILES)
def test_role_md_has_prohibited_outputs_section(profile: str) -> None:
    """role.md must enumerate Prohibited outputs to block markdown/prose LLM drift."""
    role = _read_role(profile)
    assert "Prohibited" in role or "prohibited" in role, (
        f"{profile} role.md missing Prohibited outputs section. "
        "This enumeration prevents the LLM from emitting markdown trade reports."
    )


@pytest.mark.parametrize("profile", PROFILES)
def test_role_md_has_required_final_turn_shape_example(profile: str) -> None:
    """role.md must include a Required final-turn shape example heading."""
    role = _read_role(profile)
    has_shape_heading = (
        "Required final-turn shape" in role
        or "required final-turn shape" in role.lower()
        or "final_turn_shape" in role
    )
    assert has_shape_heading, (
        f"{profile} role.md missing 'Required final-turn shape' example heading. "
        "The concrete structural anchor is required for LLM output discipline."
    )


# ---------------------------------------------------------------------------
# specifics.md tests (3 assertions × 3 profiles = 9 parameterized cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", PROFILES)
def test_specifics_md_schema_version_is_string_1_0(profile: str) -> None:
    """specifics.md must declare schema_version as string '1.0'."""
    spec = _read_specifics(profile)
    has_string_version = (
        'schema_version: "1.0"' in spec
        or "schema_version: '1.0'" in spec
    )
    assert has_string_version, (
        f"{profile} specifics.md does not contain schema_version: \"1.0\" (string)."
    )


@pytest.mark.parametrize("profile", PROFILES)
def test_specifics_md_no_raw_json_object_contradiction(profile: str) -> None:
    """specifics.md must NOT contain the contradictory 'raw JSON object' instruction."""
    spec = _read_specifics(profile)
    assert "raw JSON object" not in spec, (
        f"{profile} specifics.md still contains 'raw JSON object' phrasing "
        "that contradicts the role.md tool-call wrapper protocol (BUG-13)."
    )


@pytest.mark.parametrize("profile", PROFILES)
def test_specifics_md_has_wrapper_instruction(profile: str) -> None:
    """specifics.md must contain tool_args.text or tool_args['text'] wrapper instruction."""
    spec = _read_specifics(profile)
    has_wrapper = (
        "tool_args.text" in spec
        or 'tool_args["text"]' in spec
        or "tool_args['text']" in spec
    )
    assert has_wrapper, (
        f"{profile} specifics.md missing tool_args.text wrapper instruction. "
        "The specifics.md must tell the LLM to use the response tool wrapper."
    )
