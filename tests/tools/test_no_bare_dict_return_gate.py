"""Phase 70.5 REQ-70.5-8 — pytest wrapper for the no-bare-dict-return CI gate.

Tests:
  1. Script exits 0 against the current codebase (green pass).
  2. A deliberately violating .py file in a temp VM107/tools overlay causes non-zero exit.
  3. Same violating file with `# PROVENANCE-EXEMPT` marker causes exit 0 (escape hatch).
  4. A private helper `def _compute(...)` with `return {` causes exit 0 (private exempt).

The tests invoke the bash script via subprocess so they reproduce exactly what CI
sees.  No mocking of AWK/grep — the real script runs against real or synthetic files.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent  # .../VM107/
_SCRIPT = _VM107_ROOT / "tools" / "no-bare-dict-return.sh"


def _run_script(tools_dir: Path) -> subprocess.CompletedProcess:
    """Invoke the gate script against the given tools_dir, return CompletedProcess."""
    result = subprocess.run(
        ["bash", str(_SCRIPT), str(tools_dir)],
        capture_output=True,
        text=True,
    )
    return result


# ---------------------------------------------------------------------------
# Test 1 — current codebase is green
# ---------------------------------------------------------------------------

def test_current_codebase_passes():
    """REQ-70.5-8: no bare dict dispatch-path returns in the current VM107/tools/."""
    actual_tools_dir = _VM107_ROOT / "tools"
    result = _run_script(actual_tools_dir)
    assert result.returncode == 0, (
        f"CI gate FAILED against actual codebase.\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# Test 2 — deliberate violation is caught
# ---------------------------------------------------------------------------

def test_violation_detected(tmp_path):
    """A public function with bare `return {{...}}` must be flagged."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    bad_file = tools_dir / "bad_tool.py"
    bad_file.write_text(
        "class BadTool:\n"
        "    def run(self, **kwargs):\n"
        "        return {'foo': 'bar'}\n"
    )

    result = _run_script(tools_dir)
    assert result.returncode != 0, (
        "Expected CI gate to fail on bare dict return — it passed instead.\n"
        f"STDOUT:\n{result.stdout}"
    )
    assert "bad_tool.py" in result.stdout, (
        f"Expected offending filename in output.\nSTDOUT:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# Test 3 — PROVENANCE-EXEMPT escape hatch suppresses the violation
# ---------------------------------------------------------------------------

def test_provenance_exempt_suppresses_violation(tmp_path):
    """A `return {{...}}  # PROVENANCE-EXEMPT` line must not be flagged."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    exempt_file = tools_dir / "exempt_tool.py"
    exempt_file.write_text(
        "class ExemptTool:\n"
        "    def run(self, **kwargs):\n"
        "        return {'foo': 'bar'}  # PROVENANCE-EXEMPT — internal helper\n"
    )

    result = _run_script(tools_dir)
    assert result.returncode == 0, (
        "Expected PROVENANCE-EXEMPT to suppress the violation.\n"
        f"STDOUT:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# Test 4 — private helper def _compute(...) is exempt
# ---------------------------------------------------------------------------

def test_private_helper_is_exempt(tmp_path):
    """A `def _helper()` with bare dict return must not be flagged."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    private_file = tools_dir / "private_helper_tool.py"
    private_file.write_text(
        "class PrivateTool:\n"
        "    def _compute(self, x):\n"
        "        return {'metric': x}\n"
        "\n"
        "    async def run_async(self, **kwargs):\n"
        "        data = self._compute(kwargs.get('x', 0))\n"
        "        return data\n"
    )

    result = _run_script(tools_dir)
    # run_async returns a variable (not a bare dict literal), so no violation.
    # _compute is private — not flagged even if it returned a literal.
    assert result.returncode == 0, (
        "Expected private helper to be exempt from gate.\n"
        f"STDOUT:\n{result.stdout}"
    )
