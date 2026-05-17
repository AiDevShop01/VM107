"""Phase 47.6 Plan 07 — boot assertion: no filesystem walkers in _11_tools_prompt.py.

REG-05 LD-8: assert_no_filesystem_walkers() must:
1. PASS after walker deletion (current state — Task 2 Step A).
2. FAIL (AssertionError) if anyone re-adds walker code to the protected path.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


def test_tool_prompt_walker_removed():
    """assert_no_filesystem_walkers passes on the real VM107 repo.

    Confirms that the walker deletion in _11_tools_prompt.py is complete.
    If this test fails, the walker code was re-added — LD-8 regression.
    """
    from core.agents.boot_assertions import assert_no_filesystem_walkers

    # Should NOT raise — walker code is gone
    assert_no_filesystem_walkers(repo_root=_VM107_ROOT)


def test_walker_regression_caught():
    """assert_no_filesystem_walkers raises AssertionError if walker code is re-added.

    Uses a temporary directory with a fake _11_tools_prompt.py that contains
    the walker fragment. Confirms the guard catches regressions.
    """
    from core.agents.boot_assertions import assert_no_filesystem_walkers, WALKER_CALL_FRAGMENTS, PROTECTED_PATHS

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        # Replicate the directory structure
        protected = tmp_root / PROTECTED_PATHS[0]
        protected.parent.mkdir(parents=True, exist_ok=True)
        # Write a fake file containing the walker fragment
        protected.write_text(
            f"# Fake regression\n{WALKER_CALL_FRAGMENTS[0]}(prompt_dirs, pattern)\n",
            encoding="utf-8",
        )

        with pytest.raises(AssertionError) as exc_info:
            assert_no_filesystem_walkers(repo_root=tmp_root)

        assert WALKER_CALL_FRAGMENTS[0] in str(exc_info.value)
        assert "LD-8" in str(exc_info.value)


def test_walker_clean_file_passes():
    """assert_no_filesystem_walkers passes when the protected file has no walker code."""
    from core.agents.boot_assertions import assert_no_filesystem_walkers, PROTECTED_PATHS

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        protected = tmp_root / PROTECTED_PATHS[0]
        protected.parent.mkdir(parents=True, exist_ok=True)
        protected.write_text(
            "# Registry-driven. No walker code.\nfrom core.registry.capability_registry import CapabilityRegistry\n",
            encoding="utf-8",
        )

        # Should NOT raise
        assert_no_filesystem_walkers(repo_root=tmp_root)
