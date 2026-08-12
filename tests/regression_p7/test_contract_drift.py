"""SC-3 acceptance — contract-drift gate: pass-clean + fail-on-injected-drift.

Wraps `scripts/check_contract_drift.py` (Plan 139-06 Task 2) in the F5 regression
suite. Two assertions, matching the SC-3 acceptance bar:

1. pass-clean — the checker on the live (re-synced) repo returns exit 0. This proves
   the snapshot.py re-sync (Task 1) landed and every vendored economic_intelligence
   file is byte-identical to the fingpt_core source.
2. fail-on-injected-drift — copy the vendored tree to a tmp dir, write a one-byte
   change into a vendored file, point the checker's compare function at the tmp copy,
   and assert it reports drift (non-zero). This proves the gate actually catches
   drift rather than trivially passing.

Host-clean: `contracts.economic_intelligence` imports host-clean and the checker is
stdlib-only (`hashlib`, `pathlib`), so this test needs neither the Tier-2 venv nor the
`requires_deps` marker — it runs on the bare dev host.

Byte-only (T-139-13): the checker compares bytes; nothing here imports or executes the
compared trees.

Analog: tests/phase134/test_timeout_static_scan.py (explicit-manifest static-scan +
non-zero-count assertion shape).
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

# Repo-root-relative resolution of the checker under test. This test lives at
# <repo-root>/VM107/tests/regression_p7/, so parents[2] = VM107 root.
_VM107_ROOT = Path(__file__).resolve().parents[2]
_CHECKER_PATH = _VM107_ROOT / "scripts" / "check_contract_drift.py"


def _load_checker():
    """Load check_contract_drift.py as a module without requiring it on sys.path."""
    spec = importlib.util.spec_from_file_location("check_contract_drift", _CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_contract_drift_passes_clean():
    """The gate exits 0 on the live, re-synced repo (SC-3 pass-clean)."""
    checker = _load_checker()

    # The checker's own resolved defaults (the real vendored + upstream trees).
    mismatches = checker.find_drift(checker.VENDORED_DIR, checker.UPSTREAM_DIR)
    assert mismatches == [], (
        "expected zero drift on the clean repo, but these vendored files differ "
        f"from fingpt_core: {mismatches}"
    )

    # And the CLI entrypoint returns exit code 0.
    assert checker.main() == 0


def test_contract_drift_fails_on_injected_drift(tmp_path):
    """A one-byte change to a vendored copy makes the gate report drift (SC-3 fail-on-drift)."""
    checker = _load_checker()

    # Copy the real vendored tree into a tmp dir so we never mutate the repo.
    vendored_copy = tmp_path / "economic_intelligence"
    shutil.copytree(checker.VENDORED_DIR, vendored_copy)

    # Baseline: the tmp copy is still byte-identical to upstream → no drift.
    assert checker.find_drift(vendored_copy, checker.UPSTREAM_DIR) == []

    # Inject a one-byte change into one vendored file.
    target = vendored_copy / "snapshot.py"
    target.write_bytes(target.read_bytes() + b"#")

    # The checker now reports that file as drifted (non-empty → the CLI would exit 1).
    mismatches = checker.find_drift(vendored_copy, checker.UPSTREAM_DIR)
    assert "snapshot.py" in mismatches, (
        "injected one-byte drift was not detected — the gate does not fail on drift"
    )


def test_contract_drift_fails_on_missing_vendored_file(tmp_path):
    """A deleted vendored file is reported as drift (manifest coverage cannot silently shrink)."""
    checker = _load_checker()

    vendored_copy = tmp_path / "economic_intelligence"
    shutil.copytree(checker.VENDORED_DIR, vendored_copy)

    (vendored_copy / "snapshot.py").unlink()

    mismatches = checker.find_drift(vendored_copy, checker.UPSTREAM_DIR)
    assert "snapshot.py" in mismatches
