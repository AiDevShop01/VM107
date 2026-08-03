#!/usr/bin/env bash
# Phase 132 SC-2 — self-heal fault-injection verifier (dev box only).
#
# Proves the boot self-heal chain end-to-end: inject a wedged deferred init via
# A0_FAULT_INJECT_INIT_HANG=1, recreate vm107, and assert (a) an all-thread
# traceback is dumped, (b) the container RestartCount climbs, and (c)
# /api/health reaches 200 within 180s. A trap ALWAYS restores the box (unset the
# toggle + --force-recreate) so it is never left with the fault hook enabled.
#
# This is NOT the full soak (that is scripts/soak_boot_recreate.sh, run by the
# 132-05 phase gate). One fault-injection recreate cycle only.
#
# Per VM107 project rule: `docker compose` (v2, NEVER `docker-compose`) and ALWAYS
# `up -d --force-recreate` — never restart the container. --env-file .env.local always.
#
# Usage:
#   COMPOSE_PROJECT_DIR=/path/to/VM107 bash scripts/verify_selfheal.sh
#
# Exit codes:
#   0 — traceback dumped + RestartCount climbed + /api/health 200 < 180s
#   1 — self-heal assertion failed (no traceback / no restart / no health)
#   2 — env / preconditions not met (project dir or .env.local missing)
#   3 — docker / docker compose (v2) CLI unavailable

set -euo pipefail

COMPOSE_PROJECT_DIR="${COMPOSE_PROJECT_DIR:-/Volumes/ HardDrive/FinGPT/VM107}"
SERVICE="vm107"
CONTAINER="vm107-agent-zero"
HEALTH_URL="http://localhost:50081/api/health"
TOGGLE="A0_FAULT_INJECT_INIT_HANG"

if [[ ! -d "${COMPOSE_PROJECT_DIR}" ]]; then
  echo "FAIL: COMPOSE_PROJECT_DIR=${COMPOSE_PROJECT_DIR} not a directory" >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "FAIL: docker CLI not on PATH" >&2
  exit 3
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "FAIL: 'docker compose' (v2) subcommand unavailable" >&2
  exit 3
fi

cd "${COMPOSE_PROJECT_DIR}"

if [[ ! -f .env.local ]]; then
  echo "FAIL: .env.local not found in ${COMPOSE_PROJECT_DIR}" >&2
  exit 2
fi

# Remove any existing toggle line from .env.local (idempotent).
_strip_toggle() {
  if grep -q "^${TOGGLE}=" .env.local 2>/dev/null; then
    grep -v "^${TOGGLE}=" .env.local > .env.local.selfheal.tmp || true
    mv .env.local.selfheal.tmp .env.local
  fi
}

# ALWAYS restore the box: unset the toggle + recreate so the fault hook is never
# left enabled, regardless of how this script exits (T-132-01 / T-132-02).
cleanup() {
  echo "[selfheal] cleanup: removing ${TOGGLE} and recreating vm107 to restore..."
  _strip_toggle
  docker compose --env-file .env.local up -d --force-recreate "${SERVICE}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# 1) Ensure a freshly built image so the dormant fault hook is baked in.
echo "[selfheal] building ${SERVICE} image (fresh) so the fault hook is baked..."
docker compose --env-file .env.local build "${SERVICE}"
image_created=$(docker inspect -f '{{.Created}}' vm107-agent-zero:local 2>/dev/null || true)
if [[ -z "${image_created}" ]]; then
  echo "FAIL: vm107-agent-zero:local image not present after build" >&2
  exit 2
fi
echo "[selfheal] image vm107-agent-zero:local created at ${image_created}"

# 2) Capture baseline RestartCount (0 if the container does not exist yet).
baseline_restarts=$(docker inspect -f '{{.RestartCount}}' "${CONTAINER}" 2>/dev/null || echo 0)
echo "[selfheal] baseline RestartCount=${baseline_restarts}"

# 3) Enable the fault toggle and recreate.
_strip_toggle
printf '%s=1\n' "${TOGGLE}" >> .env.local
echo "[selfheal] enabled ${TOGGLE}=1; recreating ${SERVICE}..."
docker compose --env-file .env.local up -d --force-recreate "${SERVICE}" >/dev/null

# 4) Assert (a) an all-thread traceback is dumped, (b) RestartCount climbs, and
#    (c) /api/health reaches 200 within 180s (self-heal completed).
saw_traceback=0
restart_climbed=0
healthy=0
for _ in $(seq 1 90); do   # up to 180s at 2s
  if docker logs "${CONTAINER}" 2>&1 | grep -qE 'Current thread|Thread 0x|dump_traceback'; then
    saw_traceback=1
  fi
  now_restarts=$(docker inspect -f '{{.RestartCount}}' "${CONTAINER}" 2>/dev/null || echo 0)
  if [[ "${now_restarts}" -gt "${baseline_restarts}" ]]; then
    restart_climbed=1
  fi
  code=$(curl -s -o /dev/null -w '%{http_code}' "${HEALTH_URL}" 2>/dev/null || true)
  if [[ "${code}" == "200" ]]; then
    healthy=1
    break
  fi
  sleep 2
done

echo "[selfheal] traceback=${saw_traceback} restart_climbed=${restart_climbed} healthy=${healthy}"

# cleanup() runs via trap on exit and restores the box.
if [[ "${saw_traceback}" == "1" && "${restart_climbed}" == "1" && "${healthy}" == "1" ]]; then
  echo "PASS: SC-2 — injected init hang dumped a traceback, RestartCount climbed, and"
  echo "      /api/health recovered to 200 within 180s. Self-heal chain verified."
  exit 0
fi

echo "FAIL: SC-2 — self-heal assertion failed" \
     "(traceback=${saw_traceback} restart_climbed=${restart_climbed} healthy=${healthy})." >&2
exit 1
