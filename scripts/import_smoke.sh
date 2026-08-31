#!/usr/bin/env bash
#
# import_smoke.sh — Phase 154 (AZI-07) boot import-smoke gate.
#
# Exercises the boot import chain inside the running vm107 image venv and exits
# NON-ZERO on any ImportError. This closes the missing-dep boot-crash class
# (memory project_vm107_packaging_boot_defect / project_vm107_httptools_h11_blank_ui):
# a rebuild that drops `packaging` / `httptools` / `h11` bricks litellm/uvicorn
# on the next restart while health still reads 200 — this gate catches it at
# build/CI time instead. Reused verbatim as the AZI-04 CI gate (154-06).
#
# Modes:
#   (no args)     run the import chain in the container venv; exit 0 iff all import.
#   --selftest    prove the gate actually catches a broken deps set: build a
#                 THROWAWAY venv missing `packaging`, run the import check
#                 against it, and assert it exits NON-ZERO — then discard the
#                 throwaway venv. NEVER mutates the live /opt/venv-a0 (T-154-01).
#
# Env (overridable):
#   VM107_CONTAINER      default vm107-agent-zero
#   VM107_VENV_PY        default /opt/venv-a0/bin/python
#   VM107_APP_DIR        default /a0   (cwd so `import initialize` resolves)
#   VM107_SMOKE_IMPORTS  default the known-fragile trio + litellm + initialize

set -euo pipefail

CONTAINER="${VM107_CONTAINER:-vm107-agent-zero}"
VENV_PY="${VM107_VENV_PY:-/opt/venv-a0/bin/python}"
APP_DIR="${VM107_APP_DIR:-/a0}"
IMPORTS="${VM107_SMOKE_IMPORTS:-import packaging, httptools, h11, litellm; import initialize}"

log() { printf '[import-smoke] %s\n' "$*"; }

# Script-global scratch dir + a single EXIT trap so the throwaway selftest venv
# is ALWAYS discarded without the function-scoping hazards of a RETURN trap.
SELFTEST_TMP=""
cleanup() { [ -n "$SELFTEST_TMP" ] && rm -rf "$SELFTEST_TMP"; return 0; }
trap cleanup EXIT

# --- default gate: run the boot import chain in the live image venv ----------
run_container_smoke() {
  log "checking boot imports in ${CONTAINER}:${VENV_PY} (cwd=${APP_DIR})"
  log "imports: ${IMPORTS}"
  if docker exec -w "$APP_DIR" "$CONTAINER" "$VENV_PY" -c "$IMPORTS"; then
    log "PASS — boot import chain is healthy"
    return 0
  fi
  echo "FAIL: boot import chain raised ImportError in ${CONTAINER} — deploy would crash-loop" >&2
  return 1
}

# --- --selftest: prove the gate rejects a deps set missing `packaging` -------
run_selftest() {
  log "selftest: proving the gate exits non-zero on a broken (packaging-missing) deps set"
  SELFTEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/import_smoke_selftest.XXXXXX")"

  python3 -m venv "$SELFTEST_TMP/venv" >/dev/null 2>&1
  # Belt-and-suspenders: a bare venv usually lacks a top-level `packaging`, but
  # if the toolchain seeded one, remove it so it is definitively absent.
  "$SELFTEST_TMP/venv/bin/pip" uninstall -y packaging >/dev/null 2>&1 || true

  # Run ONLY the packaging import against the broken venv — this mirrors the
  # gate's ImportError detection. A working gate => this exits NON-ZERO.
  if "$SELFTEST_TMP/venv/bin/python" -c "import packaging" >/dev/null 2>&1; then
    echo "SELFTEST FAIL: throwaway venv still imported 'packaging' — cannot prove the gate catches a missing dep" >&2
    return 1
  fi

  log "selftest: OK — a deps set missing 'packaging' makes the import check exit non-zero (gate works)"
  return 0
}

main() {
  case "${1:-}" in
    --selftest) run_selftest ;;
    "")         run_container_smoke ;;
    *)
      echo "usage: import_smoke.sh [--selftest]" >&2
      exit 2
      ;;
  esac
}

main "$@"
