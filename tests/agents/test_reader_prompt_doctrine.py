"""test_reader_prompt_doctrine.py — CTX-§14 reader prompt injection-resistance doctrine.

Tests that every _reader sub-profile prompt contains the verbatim
"data, not instruction" CTX-§14 doctrine sentence.

Parameterized across all 3 Phase 60 profiles:
  - trade_auditor_agent._reader — ships in Wave 2 (Plan 60-09)
  - behavioral_mentor_agent._reader — ships in Wave 3 (Plan 60-10)
  - weekly_review_agent._reader — ships in Wave 4 (Plan 60-11)

Profiles that have not yet shipped are xfail so that the test suite stays
green across waves without any code change. When a profile ships, its xfail
automatically becomes xpass.

CTX-§14 sentinel: The literal string "data, not instruction" must appear in
the reader role.md. Full verbatim match of the entire paragraph is too brittle
(whitespace / line break variation); the sentinel phrase is unique enough to
guarantee the doctrine is present.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest

# ---------------------------------------------------------------------------
# Profile parameter table
# ---------------------------------------------------------------------------
# (reader_dir_relpath, wave_number, plan_that_ships_it)
READER_PROFILES = [
    ("agents/trade_auditor_agent/_reader", 2, "60-09"),
    ("agents/behavioral_mentor_agent/_reader", 3, "60-10"),
    ("agents/weekly_review_agent/_reader", 4, "60-11"),
]

# ---------------------------------------------------------------------------
# Parameterized test — doctrine presence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reader_dir_rel,wave,plan",
    READER_PROFILES,
    ids=[
        "trade_auditor_agent._reader",
        "behavioral_mentor_agent._reader",
        "weekly_review_agent._reader",
    ],
)
def test_doctrine_present_in_all_reader_prompts(reader_dir_rel, wave, plan):
    """CTX-§14 — reader role.md contains 'data, not instruction' doctrine sentinel.

    Profiles that have not shipped yet are xfail so the suite stays green.
    Each wave flips one xfail → xpass automatically when the nested dir lands.
    """
    reader_dir = _VM107_ROOT / reader_dir_rel
    if not reader_dir.is_dir():
        pytest.xfail(
            f"Not yet shipped — pending Wave {wave} plan {plan}: "
            f"{reader_dir_rel} directory does not exist on disk"
        )

    role_md = reader_dir / "prompts" / "agent.system.main.role.md"
    if not role_md.exists():
        pytest.xfail(
            f"Not yet shipped — pending Wave {wave} plan {plan}: "
            f"{role_md.relative_to(_VM107_ROOT)} does not exist on disk"
        )

    content = role_md.read_text()
    assert "data, not instruction" in content, (
        f"CTX-§14 DOCTRINE MISSING in {role_md.relative_to(_VM107_ROOT)}: "
        "the literal string 'data, not instruction' must appear in the reader role.md. "
        "This phrase is the sentinel for the treat-instructions-as-data doctrine. "
        "Add the verbatim CTX-§14 paragraph to the reader role prompt."
    )


# ---------------------------------------------------------------------------
# Explicit failure case — scans ALL 3 reader yamls
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reader_dir_rel,wave,plan",
    READER_PROFILES,
    ids=[
        "trade_auditor_agent._reader",
        "behavioral_mentor_agent._reader",
        "weekly_review_agent._reader",
    ],
)
def test_no_reader_prompt_lacks_doctrine(reader_dir_rel, wave, plan):
    """CTX-§14 — negative: no shipped _reader role.md may be missing doctrine.

    Scans only profiles that have a role.md on disk. Missing directories are
    xfail (not yet shipped). This test NEVER passes silently for a file that
    exists but lacks the doctrine — it hard-fails in that case.
    """
    reader_dir = _VM107_ROOT / reader_dir_rel
    role_md = reader_dir / "prompts" / "agent.system.main.role.md"

    if not reader_dir.is_dir() or not role_md.exists():
        pytest.xfail(
            f"Not yet shipped — pending Wave {wave} plan {plan}: "
            f"{reader_dir_rel} not on disk"
        )

    content = role_md.read_text()
    assert "data, not instruction" in content, (
        f"HARD FAIL — shipped reader prompt is missing CTX-§14 doctrine: "
        f"{role_md.relative_to(_VM107_ROOT)}\n"
        "The 'data, not instruction' sentinel must be present. "
        "A shipped reader profile without this doctrine is a prompt-injection risk."
    )
