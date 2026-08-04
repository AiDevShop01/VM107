#!/usr/bin/env bash
# Phase 134 SC-2 / D-10 — dependency-resilience chaos verifier (dev box only).
#
# Higher-fidelity companion to tests/phase134/test_chaos_dependency_resilience.py. Injects a
# SINGLE down dependency via a per-dep env toggle, recreates vm107 with the toggle set, runs the
# matching chaos pytest IN the recreated container, and asserts it passes (bounded fast-fail +
# deterministic fallback + health signal). A `trap cleanup EXIT` ALWAYS unsets the toggle and
# recreates the container clean, so the box is never left with a fault hook enabled (T-134-TAMPER).
#
# ⚠️ D-10 hard constraint: this NEVER `docker stop`s a shared dev dependency (Mongo/Postgres/
#    Qdrant @ 192.168.1.151). The fault is a monkeypatch-redirect to 127.0.0.1:1 inside the
#    pytest fixtures; the only container touched is `vm107-agent-zero` (recreated, not stopped).
#
# NOTE: the pytest form is the MERGE GATE (CI-repeatable, Phase 139-absorbable). This shell form
# is an operator convenience for a full-container recreate cycle with the toggle present in env.
#
# Per VM107 project rule: `docker compose` (v2, NEVER `docker-compose`), ALWAYS
# `up -d --force-recreate` (never `restart`), and ALWAYS `--env-file .env.local`.
#
# Usage:
#   COMPOSE_PROJECT_DIR=/path/to/VM107 bash scripts/verify_dependency_resilience.sh <dep>
#     <dep> ∈ { mongo | postgres | qdrant | vm100 }
#
# Exit codes:
#   0 — chaos test PASSED for <dep> (bounded + fallback + health signal), box restored clean
#   1 — chaos assertion failed (RED — expected in Wave 0 until Wave 1 lands the fix)
#   2 — env / preconditions not met (bad <dep>, project dir or .env.local missing)
#   3 — docker / docker compose (v2) CLI unavailable

set -euo pipefail

COMPOSE_PROJECT_DIR="${COMPOSE_PROJECT_DIR:-/Volumes/ HardDrive/FinGPT/VM107}"
SERVICE="vm107"
CONTAINER="vm107-agent-zero"
VENV_PY="/opt/venv-a0/bin/python"
TEST_ID="tests/phase134/test_chaos_dependency_resilience.py::test_dependency_down_is_bounded_falls_back_and_signals"

DEP="${1:-}"
case "${DEP}" in
  mongo)    TOGGLE="A0_FAULT_INJECT_MONGO_DOWN" ;;
  postgres) TOGGLE="A0_FAULT_INJECT_POSTGRES_DOWN" ;;
  qdrant)   TOGGLE="A0_FAULT_INJECT_QDRANT_DOWN" ;;
  vm100)    TOGGLE="A0_FAULT_INJECT_VM100_DOWN" ;;
  *)
    echo "FAIL: <dep> must be one of {mongo|postgres|qdrant|vm100} (got '${DEP}')" >&2
    exit 2 ;;
esac

if ! command -v docker >/dev/null 2>&1; then
  echo "FAIL: docker CLI not on PATH" >&2
  exit 3
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "FAIL: 'docker compose' (v2) subcommand unavailable" >&2
  exit 3
fi
if [[ ! -d "${COMPOSE_PROJECT_DIR}" ]]; then
  echo "FAIL: COMPOSE_PROJECT_DIR=${COMPOSE_PROJECT_DIR} not a directory" >&2
  exit 2
fi

cd "${COMPOSE_PROJECT_DIR}"

if [[ ! -f .env.local ]]; then
  echo "FAIL: .env.local not found in ${COMPOSE_PROJECT_DIR}" >&2
  exit 2
fi

# Idempotently strip any prior toggle line from .env.local.
_strip_toggle() {
  if grep -q "^${TOGGLE}=" .env.local 2>/dev/null; then
    grep -v "^${TOGGLE}=" .env.local > .env.local.chaos.tmp || true
    mv .env.local.chaos.tmp .env.local
  fi
}

# ALWAYS restore the box: unset the toggle + recreate clean, regardless of how we exit
# (T-134-TAMPER — never leave a fault hook enabled). Only `vm107-agent-zero` is recreated;
# no shared dev dependency is ever stopped (D-10).
cleanup() {
  echo "[chaos] cleanup: removing ${TOGGLE} and recreating ${SERVICE} clean to restore..."
  _strip_toggle
  docker compose --env-file .env.local up -d --force-recreate "${SERVICE}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "############################################################"
echo "# FAULT INJECTION ACTIVE — dev only. dep=${DEP} toggle=${TOGGLE}=1"
echo "# Redirect-to-127.0.0.1:1 chaos (D-10). NEVER run in production."
echo "############################################################"

# 1) Enable the toggle and recreate the service with it present in env.
_strip_toggle
printf '%s=1\n' "${TOGGLE}" >> .env.local
docker compose --env-file .env.local up -d --force-recreate "${SERVICE}" >/dev/null

# 2) Ensure the (baked) test package is present in the recreated container, then run the
#    chaos test for THIS dep only (fixtures perform the redirect; toggle is present in env).
docker cp tests/phase134/. "${CONTAINER}:/a0/tests/phase134/" >/dev/null 2>&1 || true

set +e
docker exec "${CONTAINER}" bash -lc \
  "cd /a0 && ${VENV_PY} -m pytest '${TEST_ID}[${DEP}]' -q"
rc=$?
set -e

if [[ "${rc}" -eq 0 ]]; then
  echo "PASS: SC-2 chaos — ${DEP} down → bounded fast-fail + deterministic fallback + health signal."
  exit 0
fi
echo "FAIL: SC-2 chaos — ${DEP} chaos test RED (rc=${rc}). Expected in Wave 0 until Wave 1 lands the fix." >&2
exit 1
