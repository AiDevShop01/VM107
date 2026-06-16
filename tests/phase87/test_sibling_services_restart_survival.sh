#!/usr/bin/env bash
# Phase 87 REQ-87-8 / AC-87-8 / VAL row 87-08-01 — sibling-service restart survival.
#
# Per LOCK-8 + feedback_mgmt_commands_need_compose_service: vm107-macro-story-tracker
# + vm107-macro-regime-monitor are declared as docker-compose sibling services that
# share env+volumes with vm107-backend via &backend-env / &backend-volumes anchors.
#
# This script reproduces the Phase 74-03 regression: long-running mgmt commands die
# on every backend restart unless they ship as sibling services. The test asserts
# both sibling services come back HEALTHY within 60s of a `docker compose restart
# vm107-backend`.
#
# Per project lock: use `docker compose` (NOT legacy `docker-compose`).
# Per feedback_no_docker_restart_after_env_change: `restart` is fine for code-only
# changes (we're not touching env here); for env changes use
# `up -d --force-recreate --no-deps <svc>` instead.
#
# Usage:
#   COMPOSE_PROJECT_DIR=/path/to/VM107 \
#     bash tests/phase87/test_sibling_services_restart_survival.sh
#
# Exit codes:
#   0 — both sibling services healthy within 60s (REQ-87-8 + AC-87-8 PASS)
#   1 — one or both sibling services failed healthcheck
#   2 — env / preconditions not met (e.g., vm107-backend not running)
#   3 — docker compose CLI unavailable
#
# Run by Plan 87-14 Task 3 (dev deploy verification) — not in CI on Mac dev
# because docker daemon access varies.

set -euo pipefail

# Locate docker compose project dir.
COMPOSE_PROJECT_DIR="${COMPOSE_PROJECT_DIR:-/Volumes/ HardDrive/FinGPT/VM107}"

if [[ ! -d "${COMPOSE_PROJECT_DIR}" ]]; then
  echo "FAIL: COMPOSE_PROJECT_DIR=${COMPOSE_PROJECT_DIR} not a directory" >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "FAIL: docker CLI not on PATH" >&2
  exit 3
fi

# Use the modern `docker compose` (v2) subcommand. Legacy `docker-compose` is
# explicitly NOT supported per CLAUDE.md lock.
if ! docker compose version >/dev/null 2>&1; then
  echo "FAIL: 'docker compose' (v2) subcommand unavailable" >&2
  exit 3
fi

cd "${COMPOSE_PROJECT_DIR}"

# Precondition: vm107-backend must be running before we test restart-survival.
if ! docker compose ps --status running --services 2>/dev/null | grep -q '^vm107-backend$'; then
  echo "FAIL: vm107-backend not running in ${COMPOSE_PROJECT_DIR}; bring the" >&2
  echo "       stack up first ('docker compose up -d') and retry." >&2
  exit 2
fi

SIBLING_SERVICES=("vm107-macro-story-tracker" "vm107-macro-regime-monitor")

echo "[1/4] Verifying sibling services are present in compose config..."
for svc in "${SIBLING_SERVICES[@]}"; do
  if ! docker compose config --services 2>/dev/null | grep -q "^${svc}$"; then
    echo "FAIL: ${svc} not declared in docker-compose.yml — LOCK-8 violated" >&2
    exit 2
  fi
done

echo "[2/4] Restarting vm107-backend..."
docker compose restart vm107-backend

echo "[3/4] Sleeping 60s to give sibling services time to settle..."
sleep 60

echo "[4/4] Checking sibling service healthchecks..."
HEALTHY_COUNT=0
FAILED_SERVICES=()
for svc in "${SIBLING_SERVICES[@]}"; do
  # `docker compose ps --format json` returns 1 line per service with Health field.
  # Fall back to the human-readable format for older compose versions.
  health_status="$(docker compose ps "${svc}" 2>/dev/null | tail -n +2 || true)"
  if echo "${health_status}" | grep -qE '\(healthy\)|healthy'; then
    HEALTHY_COUNT=$((HEALTHY_COUNT + 1))
    echo "  OK    ${svc}: healthy"
  else
    FAILED_SERVICES+=("${svc}")
    echo "  FAIL  ${svc}: not healthy — ${health_status}"
  fi
done

if [[ ${HEALTHY_COUNT} -lt 2 ]]; then
  echo "" >&2
  echo "FAIL: REQ-87-8 + AC-87-8 — expected 2 healthy sibling services after" >&2
  echo "      'docker compose restart vm107-backend', got ${HEALTHY_COUNT}." >&2
  echo "      Failed services: ${FAILED_SERVICES[*]}" >&2
  echo "" >&2
  echo "Full status snapshot:" >&2
  docker compose ps >&2 || true
  exit 1
fi

echo ""
echo "PASS: REQ-87-8 + AC-87-8 — both sibling services healthy within 60s of"
echo "      vm107-backend restart. LOCK-8 sibling-service contract upheld."
exit 0
