"""Phase 73 follow-up — guard against the CAPABILITY_REGISTRY_PERMISSIVE
escape hatch being re-introduced via committed env files.

History: Phase 72-02 + 73-00 shipped registry data with schema drift,
and the dev-only `CAPABILITY_REGISTRY_PERMISSIVE=1` flag in
``VM107/.env.local`` let VM107 boot anyway by downgrading
``RegistryValidationError`` to a warning. Phase 73 follow-up reconciled
the widget yaml ↔ schema drift (active_trade_supervision /
workflow_action_bar / opportunity_lifecycle_pill: `dependencies`
flattened to `list[str]` matching the validator; structured info
preserved under `dependency_details`).

Once the yaml reconciliation lands, the escape hatch must STAY retired.
If somebody re-adds `CAPABILITY_REGISTRY_PERMISSIVE=1` to a committed
env file as a quick fix, that hides every future LD-2 regression and
defeats the hard-fail guarantee. This test makes that mistake fail loud
in CI.

Runtime override (a developer shell-exporting the flag locally) is NOT
caught here — that's intentional. The variable in initialize.py is
still respected for genuine remediation cycles; this test only locks
the *committed* state of env files.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_VM107_ROOT = Path(__file__).resolve().parent.parent.parent

# Committed env files that must NOT carry the escape hatch unset
# (`CAPABILITY_REGISTRY_PERMISSIVE=` with no value or `=0` is fine — the
# initialize.py check is `== "1"`).
_FORBIDDEN_LINE_PREFIX = "CAPABILITY_REGISTRY_PERMISSIVE=1"

_ENV_FILES_TO_CHECK = [
    _VM107_ROOT / ".env.local",
    _VM107_ROOT / ".env",
    _VM107_ROOT / ".env.example",
    _VM107_ROOT / "docker-compose.yml",
]


@pytest.mark.parametrize(
    "env_path",
    [p for p in _ENV_FILES_TO_CHECK if p.exists()],
    ids=[p.name for p in _ENV_FILES_TO_CHECK if p.exists()],
)
def test_committed_env_does_not_set_permissive(env_path: Path):
    """`CAPABILITY_REGISTRY_PERMISSIVE=1` MUST NOT appear in any committed
    env file as an active assignment.

    Comments are tolerated — the retirement note in `.env.local` is a
    comment block, not an assignment.
    """
    text = env_path.read_text(encoding="utf-8")
    offending = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        # Skip pure comments (whole line starts with '#').
        if stripped.startswith("#"):
            continue
        # Match the active-assignment form anywhere on the line — covers
        # `CAPABILITY_REGISTRY_PERMISSIVE=1` and YAML's
        # `  - CAPABILITY_REGISTRY_PERMISSIVE=1`. Trailing junk (spaces,
        # quotes) is tolerated as long as the prefix lands.
        if _FORBIDDEN_LINE_PREFIX in stripped:
            offending.append(f"{env_path.name}:{lineno}: {line!r}")
    assert not offending, (
        "CAPABILITY_REGISTRY_PERMISSIVE=1 must not appear as an active "
        "assignment in committed env files (the dev escape hatch was "
        "retired in the Phase 73 follow-up). Offending lines:\n  "
        + "\n  ".join(offending)
    )
