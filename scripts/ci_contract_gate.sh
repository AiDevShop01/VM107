#!/usr/bin/env bash
# ci_contract_gate.sh — Phase 167 (P167D / AGV-04 + AGV-05) agent-contract
# enforcement gate. Standalone: runnable locally or from ANY CI. It is
# deliberately NOT wired into Phase-154's CI (D-04) — call it explicitly.
#
# It runs the TWO whole-corpus green checks that gate the warn->block flip:
#
#   1. `agent_contract_lint.py --block`  — exit 1 on ANY parity finding
#      (orphan profile / missing Contract field / tools-authority disagreement)
#      over every in-scope registry/agent_profile ⋈ agent-catalogue pair.
#
#   2. `CONTRACT_BOOT_STRICT=1` strict-boot test — the boot validator raises
#      SystemExit on any canon-base profile missing its `agent_contract:` block;
#      this asserts all real profiles pass under strict enforcement.
#
# Exit 0 ONLY when BOTH pass. Any failure => non-zero (the block lever). This is
# the precondition that MUST hold before CONTRACT_BOOT_STRICT is enabled on a
# live container (fragile-tree guard, D-02). See
# Documentation/agent-contract-enforcement.md.
#
# Usage:
#   bash scripts/ci_contract_gate.sh            # from the VM107 repo root or anywhere
#   PYTHON=/path/to/python bash scripts/ci_contract_gate.sh
#
set -euo pipefail

# Resolve the VM107 repo root from this script's location (portable, no cwd
# assumption) so the gate is callable from any directory / CI runner.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VM107_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${VM107_ROOT}"

# Prefer an explicit $PYTHON, then a local venv, then python3 on PATH.
if [[ -n "${PYTHON:-}" ]]; then
  PY="${PYTHON}"
elif [[ -x "${VM107_ROOT}/.venv/bin/python" ]]; then
  PY="${VM107_ROOT}/.venv/bin/python"
else
  PY="$(command -v python3 || command -v python)"
fi

echo "== ci_contract_gate.sh =="
echo "   repo:   ${VM107_ROOT}"
echo "   python: ${PY}"
echo

FAIL=0

echo "== [1/2] lint --block (whole-corpus parity, exit 1 on any finding) =="
if "${PY}" scripts/agent_contract_lint.py --block; then
  echo "   PASS: lint --block exited 0 (no findings)."
else
  echo "   FAIL: lint --block reported findings (governance drift) — see above."
  FAIL=1
fi
echo

echo "== [2/2] CONTRACT_BOOT_STRICT=1 strict-boot test (all real profiles green) =="
if CONTRACT_BOOT_STRICT=1 "${PY}" -m pytest \
    tests/agent_catalogue/test_boot_validator.py::test_all_real_profiles_green_strict -q; then
  echo "   PASS: strict-boot test green over the real corpus."
else
  echo "   FAIL: strict-boot test failed — a canon-base profile is missing its agent_contract: block."
  FAIL=1
fi
echo

if [[ "${FAIL}" -ne 0 ]]; then
  echo "== ci_contract_gate: BLOCKED (do NOT enable CONTRACT_BOOT_STRICT on a live container) =="
  exit 1
fi

echo "== ci_contract_gate: GREEN (safe to enable CONTRACT_BOOT_STRICT=1) =="
exit 0
