"""Phase 43.2 Plan 03 — codebase walker enforcing forbidden patterns absent outside allowlist.

CI source of truth (cannot be bypassed by --no-verify). Companion: scripts/check_forbidden_patterns.py
runs at commit time as first line of defense.

Covers STRUCTURED-IO-PHASE44-CONTRACT-01.

SCAN_ROOTS: core/, extensions/python/, agents/, scripts/
NOTE: agent.py is intentionally excluded from scan roots — it is Agent Zero core code
that legitimately calls unified_call() via the monkey-patch wire-site. All new code
must go through the allowlisted wrappers.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Import the LOCKED patterns + allowlist from the script (single source of truth).
import sys
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS_DIR = _VM107_ROOT / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
from check_forbidden_patterns import FORBIDDEN_PATTERNS, ALLOWLIST_PREFIXES, is_allowlisted

# Directories to scan (relative to VM107 root).
# agent.py excluded: Agent Zero core code that legitimately uses unified_call() at wire-site.
# models.py excluded: it defines unified_call (method definition, not call), but is in allowlist anyway.
SCAN_ROOTS = ["core", "extensions/python", "agents", "scripts"]


def _walk_python_files(vm107_root: Path):
    for root_str in SCAN_ROOTS:
        root = vm107_root / root_str
        if root.is_file() and root.suffix == ".py":
            yield root
        elif root.is_dir():
            for path in root.rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                yield path


def _scan(path: Path, regex: str, vm107_root: Path) -> list[tuple[int, str]]:
    """Return list of (lineno, line) violations for a single regex in this file."""
    rel = path.relative_to(vm107_root).as_posix()
    if is_allowlisted(rel):
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    violations = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("#"):
            continue
        if re.search(regex, line):
            violations.append((lineno, line.strip()[:120]))
    return violations


class TestForbidden:
    """STRUCTURED-IO-PHASE44-CONTRACT-01: forbidden patterns absent outside allowlist."""

    @pytest.mark.parametrize("regex,label,_", FORBIDDEN_PATTERNS, ids=[p[1] for p in FORBIDDEN_PATTERNS])
    def test_pattern_absent_outside_allowlist(self, regex, label, _):
        vm107_root = _VM107_ROOT
        all_violations: list[tuple[str, int, str]] = []
        for path in _walk_python_files(vm107_root):
            for lineno, excerpt in _scan(path, regex, vm107_root):
                rel = path.relative_to(vm107_root).as_posix()
                all_violations.append((rel, lineno, excerpt))

        assert not all_violations, (
            f"\nForbidden pattern '{label}' ({regex}) found outside allowlist:\n"
            + "\n".join(f"  {p}:{ln}: {ex}" for p, ln, ex in all_violations)
            + f"\nAllowlist: {ALLOWLIST_PREFIXES}"
        )

    def test_allowlist_membership_function(self):
        """Smoke test for is_allowlisted itself."""
        assert is_allowlisted("core/routing/router.py") is True
        assert is_allowlisted("core/agents/structured_output.py") is True
        assert is_allowlisted("core/contracts/something.py") is True
        assert is_allowlisted("extensions/python/foo/bar.py") is True   # CONTEXT.md: extensions allowlisted
        assert is_allowlisted("tests/agents/test_x.py") is True
        # agent.py is NOT allowlisted (Phase 36 boundary — agent.py is excluded from scan, not allowlisted)
        assert is_allowlisted("agent.py") is False
        assert is_allowlisted("agents/agent0/something.py") is False
