#!/usr/bin/env python3
"""revert_guard.py — D-03 SC-1 mutation gate for the Phase 139 F5 regression suite.

Turns SC-1 from "the F5 tests pass" into "the F5 tests provably FAIL when the fix is
gone." For each guarded fix it:

  1. creates a throwaway `git worktree` off `develop` (the live VM107 tree is NEVER
     mutated — T-139-11);
  2. applies the fix's *effective revert* inside the worktree — either a clean
     `git revert --no-edit -n <sha>` (P0, P3-D3) or a hunk-level reverse `git apply`
     of a stored patch (P1, P2, P3-D1, whose original shas were refactored by later
     phases — Pitfall 3);
  3. runs the guarding test under the CORRECT interpreter — the Tier-2 CI venv
     (`.venv/bin/python`) for `requires_deps` tests, host `python` for host-clean —
     EXPECTING a genuine assertion RED (pytest exit code 1);
  4. removes the worktree (finally-cleanup) and restores.

Classification is strict (T-139-12 — a broken env must NEVER be scored as the RED):
  * pytest exit 1  + no import/collection signature  -> RED   (the required proof)
  * pytest exit 0                                     -> GREEN (fix NOT proven — FAIL)
  * pytest exit 2/3/5, or any ModuleNotFoundError / ImportError / "errors during
    collection" / "no tests ran" in the output       -> HARNESS_ERROR (FAIL LOUD)
  * a non-clean revert / non-applying patch           -> STALE_MAP (FAIL LOUD:
    "cannot cleanly revert <sha> on develop — guarded-commit map is stale")

Exit 0 only if EVERY guarded fix produced a genuine exit-1 RED (or, in --dry-run,
every effective revert applied cleanly) AND the live tree is clean + on `develop`
afterward. Anything else exits non-zero.

CLI (skeleton borrowed from `scripts/check_forbidden_patterns.py`):
  python tests/regression_p7/revert_guard.py            # run all 5 (the SC-1 gate)
  python tests/regression_p7/revert_guard.py --dry-run  # apply-only, prove non-stale + tree-clean
  python tests/regression_p7/revert_guard.py --only test_p2_chaos  # smoke one fix

Reads `GUARDED_COMMITS` (the single-source annotation map) + `EFFECTIVE_REVERTS`
(the runnable revert plan) from `guarded_commits.py`. DEV-ONLY; operates on the
nested `VM107/` repo, branch `develop`.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_THIS = Path(__file__).resolve()
_PKG_DIR = _THIS.parent                      # tests/regression_p7
VM107_ROOT = _PKG_DIR.parent.parent          # VM107/
# Tier-2 CI venv interpreter (139-01, rebuilt on py3.12 in 139-02). Every
# `requires_deps` guarding test runs here; host-clean tests run under the
# interpreter that invoked this harness.
VENV_PYTHON = VM107_ROOT / ".venv/bin/python"

# Import the single-source maps (works whether run as a script or imported).
if str(VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(VM107_ROOT))
from tests.regression_p7.guarded_commits import (  # noqa: E402
    EFFECTIVE_REVERTS,
    GUARDED_COMMITS,
)

# Per-test interpreter + pytest marker selection. "venv" -> VENV_PYTHON; "host" ->
# the invoking interpreter. The marker filter selects the subset that actually goes
# RED when the fix is reverted (see 139-04/139-02 summaries):
#   * P0 watchdog behavior + P3-D3 cause classification are `requires_deps` (Tier-2).
#   * P2's RED lives in the host-clean datastore cases; its vm100 case is `requires_deps`
#     (jsonschema absent on host) and MUST be deselected or it ModuleNotFounds on host.
INTERPRETER: dict[str, tuple[str, list[str]]] = {
    "test_p0_boot_restart":     ("venv", ["-m", "requires_deps"]),
    "test_p1_loop_stall":       ("venv", []),
    "test_p3d1_tool_load":      ("venv", []),
    "test_p3d3_degraded_cause": ("venv", ["-m", "requires_deps"]),
    "test_p2_chaos":            ("host", ["-m", "not requires_deps"]),
}

# Output signatures that mean "the test did not actually RUN under its interpreter"
# (a broken venv / missing dep / collection failure) — NEVER the required RED.
_HARNESS_SIGNATURES = (
    "ModuleNotFoundError",
    "ImportError",
    "errors during collection",
    "no tests ran",
    "INTERNALERROR",
)


class StaleMapError(RuntimeError):
    """A guarded revert did not apply cleanly on current develop (map is stale)."""


class HarnessError(RuntimeError):
    """The harness itself could not run the guarding test (env/worktree failure)."""


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )


def classify_result(returncode: int, output: str) -> tuple[str, str]:
    """Map a pytest run to RED / GREEN / HARNESS_ERROR. Strict, order matters:
    import/collection signatures are checked BEFORE accepting exit 1 as RED, so a
    deferred-import ModuleNotFoundError from a broken venv can never masquerade as
    the required assertion-RED (D-02a / T-139-12)."""
    if returncode in (2, 3, 5):
        return "HARNESS_ERROR", (
            f"pytest exit {returncode} (collection/usage/internal error or no tests "
            f"collected) — did not run under its interpreter, cannot be counted as RED"
        )
    for sign in _HARNESS_SIGNATURES:
        if sign in output:
            return "HARNESS_ERROR", (
                f"import/collection signature {sign!r} in output — the guarding test "
                f"did not genuinely run (broken interpreter/deps), cannot be counted as RED"
            )
    if returncode == 0:
        return "GREEN", (
            "pytest exit 0 — fix NOT proven: the test stayed GREEN after reverting the "
            "guarded fix (the revert removed the wrong lines, or the test is not sensitive)"
        )
    if returncode == 1:
        return "RED", "genuine assertion failure (pytest exit 1) — fix proven"
    return "HARNESS_ERROR", f"unexpected pytest exit {returncode}"


def _apply_effective_revert(worktree: Path, test_id: str) -> str:
    """Apply the effective revert for `test_id` inside `worktree`. Raises
    StaleMapError on any non-clean revert / non-applying patch. Returns a short
    description of what was reverted."""
    spec = EFFECTIVE_REVERTS[test_id]
    if "shas" in spec:
        shas = spec["shas"]  # type: ignore[assignment]
        for sha in shas:  # type: ignore[union-attr]
            r = _git(worktree, "revert", "--no-edit", "-n", sha)
            if r.returncode != 0:
                _git(worktree, "revert", "--abort")  # best-effort cleanup
                raise StaleMapError(
                    f"cannot cleanly revert {sha} on develop — guarded-commit map is "
                    f"stale (test {test_id}). git: {r.stderr.strip()[:220]}"
                )
        return f"git revert {', '.join(shas)}"  # type: ignore[arg-type]
    if "patch" in spec:
        patch = _PKG_DIR / str(spec["patch"])
        if not patch.is_file():
            raise StaleMapError(
                f"effective-revert patch missing for {test_id}: {patch} — map is stale"
            )
        r = _git(worktree, "apply", "--verbose", str(patch))
        if r.returncode != 0:
            raise StaleMapError(
                f"cannot cleanly apply effective revert {patch.name} on develop — "
                f"guarded-commit map is stale (test {test_id}). git: {r.stderr.strip()[:220]}"
            )
        return f"git apply {patch.name}"
    raise StaleMapError(f"no effective-revert strategy defined for {test_id}")


def _run_guarding_test(worktree: Path, test_id: str) -> tuple[str, str]:
    kind, extra = INTERPRETER[test_id]
    if kind == "venv":
        if not VENV_PYTHON.exists():
            return "HARNESS_ERROR", (
                f"Tier-2 venv interpreter missing at {VENV_PYTHON} — provision it "
                f"(139-01) before running the SC-1 gate; a requires_deps test cannot "
                f"run under host python"
            )
        py = str(VENV_PYTHON)
    else:
        py = sys.executable
    target = f"tests/regression_p7/{test_id}.py"
    cmd = [py, "-m", "pytest", target, *extra, "-x", "-q"]
    # Do not let an inherited PYTHONPATH leak the live tree into the worktree run.
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    try:
        proc = subprocess.run(
            cmd, cwd=str(worktree), env=env, capture_output=True, text=True, timeout=600
        )
    except subprocess.TimeoutExpired:
        return "HARNESS_ERROR", f"guarding test timed out after 600s ({test_id})"
    return classify_result(proc.returncode, proc.stdout + proc.stderr)


def check_fix(test_id: str, dry_run: bool = False) -> tuple[str, str]:
    """Full revert -> (RED expected) -> restore for one guarded fix, in a throwaway
    worktree. Returns (verdict, detail). Verdicts: RED / GREEN / HARNESS_ERROR /
    STALE_MAP (and APPLIED for --dry-run)."""
    base = Path(tempfile.mkdtemp(prefix=f"revert-guard-{test_id}-"))
    worktree = base / "wt"
    try:
        add = _git(VM107_ROOT, "worktree", "add", "--detach", "--quiet", str(worktree), "develop")
        if add.returncode != 0:
            return "HARNESS_ERROR", f"git worktree add failed: {add.stderr.strip()[:200]}"
        try:
            what = _apply_effective_revert(worktree, test_id)
        except StaleMapError as exc:
            return "STALE_MAP", str(exc)
        if dry_run:
            return "APPLIED", f"{what} applied cleanly (dry-run — guarding test not executed)"
        verdict, detail = _run_guarding_test(worktree, test_id)
        return verdict, f"reverted via {what}; {detail}"
    finally:
        _git(VM107_ROOT, "worktree", "remove", "--force", str(worktree))
        _git(VM107_ROOT, "worktree", "prune")
        shutil.rmtree(base, ignore_errors=True)


def _live_tree_state() -> tuple[str, str]:
    porcelain = _git(VM107_ROOT, "status", "--porcelain").stdout.strip()
    branch = _git(VM107_ROOT, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    return porcelain, branch


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="D-03 SC-1 mutation gate: prove each F5 fix goes RED on revert."
    )
    parser.add_argument(
        "--only", metavar="TEST_ID", default=None,
        help="run the gate for a single guarded test_id (smoke mode)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="only prove each effective revert APPLIES cleanly (non-stale) + leaves the "
             "tree clean; do not run the (slow) guarding tests",
    )
    args = parser.parse_args(argv)

    if args.only and args.only not in GUARDED_COMMITS:
        print(f"FATAL: unknown test_id {args.only!r} (not in GUARDED_COMMITS)", file=sys.stderr)
        return 1
    test_ids = [args.only] if args.only else list(GUARDED_COMMITS)

    # Every guarded test must have a runnable revert plan, or the gate is incomplete.
    missing = [t for t in test_ids if t not in EFFECTIVE_REVERTS]
    if missing:
        print(
            f"FATAL: no EFFECTIVE_REVERTS entry for {missing} — the guarded-commit map "
            f"grew without a revert plan; refusing to report a false-green gate.",
            file=sys.stderr,
        )
        return 1

    # T-139-11: snapshot the live tree BEFORE the run so we assert the harness DISTURBS
    # nothing (before == after) — robust to a developer's pre-existing uncommitted edits,
    # while still catching any worktree residue / branch drift the harness might leak.
    before_porcelain, before_branch = _live_tree_state()

    print(f"== D-03 revert-guard (SC-1 mutation gate) — {len(test_ids)} fix(es), "
          f"dry_run={args.dry_run} ==")
    results: dict[str, tuple[str, str]] = {}
    for test_id in test_ids:
        verdict, detail = check_fix(test_id, dry_run=args.dry_run)
        results[test_id] = (verdict, detail)
        good = verdict in ("RED", "APPLIED")
        print(f"  [{'PASS' if good else 'FAIL'}] {test_id}: {verdict}\n         {detail}")

    # The live tree must be UNTOUCHED by the harness (same status as before) and still
    # on develop — worktree isolation invariant (T-139-11).
    after_porcelain, after_branch = _live_tree_state()
    tree_ok = (after_porcelain == before_porcelain) and (after_branch == before_branch == "develop")
    if not tree_ok:
        print(
            f"\nFATAL: the harness disturbed the live VM107 tree — "
            f"branch {before_branch!r}->{after_branch!r}, porcelain delta detected "
            f"(before={before_porcelain!r}, after={after_porcelain!r}); expected no change + develop.",
            file=sys.stderr,
        )

    passed = [t for t, (v, _) in results.items() if v in ("RED", "APPLIED")]
    failed = {t: v for t, (v, _) in results.items() if v not in ("RED", "APPLIED")}
    print(f"\n== SUMMARY: {len(passed)}/{len(test_ids)} "
          f"{'applied-clean' if args.dry_run else 'RED-on-revert'}; tree_clean={tree_ok} ==")
    if failed:
        print(f"   FAILURES: {failed}")

    return 0 if (not failed and tree_ok) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
