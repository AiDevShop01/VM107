"""Phase 139 P7 — CI wrapper for the D-03 revert-guard mutation gate (SC-1).

Proves the harness (`revert_guard.py`) is CI-invocable, that a broken-env import
error can NEVER be scored as the required RED (T-139-12), and that running the gate
leaves the live VM107 working tree untouched and on `develop` (T-139-11).

Three layers, cheapest first:
  1. unit  — `classify_result` never counts an import/collection error as RED, and
             only pytest-exit-1 (a genuine assertion failure) is RED.
  2. slow  — `--dry-run` proves every effective revert APPLIES cleanly on develop
             (map not stale) and disturbs nothing in the live tree.
  3. slow  — `--only test_p2_chaos` end-to-end proves a genuine exit-1 RED-on-revert
             (an import/collection error would be a FAIL, not a pass) and, again,
             leaves the tree clean + on develop.

The full 5-fix gate (`python tests/regression_p7/revert_guard.py`) is the phase
acceptance run (see 139-05-SUMMARY); this wrapper smoke-tests one fix to stay fast.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.regression_p7 import revert_guard

_HARNESS = Path(revert_guard.__file__).resolve()
_VM107_ROOT = revert_guard.VM107_ROOT


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(_VM107_ROOT), capture_output=True, text=True
    ).stdout.strip()


def _tree_state() -> tuple[str, str]:
    return _git("status", "--porcelain"), _git("rev-parse", "--abbrev-ref", "HEAD")


# ── (1) unit: import/collection errors are NEVER the required RED ──────────────────

def test_import_or_collection_error_is_never_scored_as_red():
    """A broken interpreter/deps run must be a HARNESS_ERROR, not the RED (D-02a)."""
    # exit 1 but with a deferred-import ModuleNotFoundError -> NOT red (the trap D-02a warns about)
    verdict, _ = revert_guard.classify_result(
        1, "E   ModuleNotFoundError: No module named 'litellm'\n1 failed"
    )
    assert verdict == "HARNESS_ERROR", "a ModuleNotFoundError must never count as the RED"

    # collection error / usage error exit codes -> harness error
    assert revert_guard.classify_result(2, "errors during collection")[0] == "HARNESS_ERROR"
    assert revert_guard.classify_result(5, "no tests ran")[0] == "HARNESS_ERROR"

    # a plain ImportError likewise
    assert revert_guard.classify_result(1, "ImportError: cannot import name X")[0] == "HARNESS_ERROR"


def test_only_genuine_assertion_failure_is_red():
    """exit 1 (no import signature) = RED; exit 0 = GREEN (fix not proven)."""
    red, _ = revert_guard.classify_result(1, "E   assert 1 == 2\n1 failed in 0.10s")
    assert red == "RED"
    green, _ = revert_guard.classify_result(0, "3 passed in 0.20s")
    assert green == "GREEN", "a fix that stays green on revert is NOT proven — must FAIL"


def test_every_guarded_fix_has_a_runnable_revert_plan():
    """The harness refuses a false-green gate: each guarded test needs an effective revert."""
    for test_id in revert_guard.GUARDED_COMMITS:
        assert test_id in revert_guard.EFFECTIVE_REVERTS, (
            f"{test_id} is guarded but has no EFFECTIVE_REVERTS entry — the gate would "
            f"be incomplete"
        )
        assert test_id in revert_guard.INTERPRETER, f"{test_id} missing an interpreter mapping"


# ── (2) slow: dry-run applies clean + leaves the tree untouched ────────────────────

@pytest.mark.slow
def test_dry_run_applies_clean_and_leaves_tree_untouched():
    before = _tree_state()
    proc = subprocess.run(
        [sys.executable, str(_HARNESS), "--dry-run"],
        cwd=str(_VM107_ROOT), capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, (
        f"--dry-run must exit 0 (every effective revert applies cleanly — map not "
        f"stale). stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    after = _tree_state()
    assert after == before, (
        f"the harness disturbed the live tree: before={before} after={after}"
    )
    assert after[1] == "develop", "HEAD must remain on develop"


# ── (3) slow: one fix end-to-end proves a genuine exit-1 RED-on-revert ─────────────

@pytest.mark.slow
def test_smoke_one_fix_goes_red_and_tree_stays_clean():
    before = _tree_state()
    proc = subprocess.run(
        [sys.executable, str(_HARNESS), "--only", "test_p2_chaos"],
        cwd=str(_VM107_ROOT), capture_output=True, text=True, timeout=300,
    )
    # exit 0 REQUIRES a genuine RED-on-revert; an import/collection error would make
    # the harness exit non-zero (HARNESS_ERROR), so a green here proves a real RED.
    assert proc.returncode == 0, (
        f"the smoke fix must go RED-on-revert via a genuine exit-1 assertion failure "
        f"(import/collection errors are a FAIL, not a pass). stdout:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}"
    )
    assert "RED" in proc.stdout and "HARNESS_ERROR" not in proc.stdout
    after = _tree_state()
    assert after == before, f"tree disturbed: before={before} after={after}"
    assert after[1] == "develop", "HEAD must remain on develop after the run"
