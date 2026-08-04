#!/usr/bin/env bash
# Phase 132 SC-2 — self-heal fault-injection verifier (dev box only).
#
# Proves the boot self-heal chain end-to-end for the AS-BUILT design (RESEARCH
# Pattern 2: bounded InitTimeout abort + supervisor auto-restart). Inject a wedged
# deferred init via A0_FAULT_INJECT_INIT_HANG=1, recreate vm107, and assert:
#
#   Phase A (while injected — a permanent fault loops, so /api/health stays down):
#     (a) the dormant fault hook fires (loud "FAULT INJECTION ACTIVE" warning), and
#     (b) the boot SELF-TERMINATES within a bounded time — helpers.defer.InitTimeout
#         is raised from init_a0's bounded init_chats.result_sync (NOT an unbounded
#         park), and
#     (c) the boot AUTO-RESTARTS — supervisord respawns run_ui (>=2 'spawned: run_ui'
#         observations within the injected window).
#   Phase B (after the trap unsets the toggle + recreates):
#     (d) /api/health recovers to 200 within 180s.
#
# Why not a faulthandler all-thread traceback / a Docker RestartCount climb?
# Those are a DIFFERENT recovery layer. This fault hangs inside the 60s
# init_chats.result_sync, so the typed InitTimeout fires FIRST (well before the
# 150s faulthandler watchdog), and run_ui is a supervised CHILD — supervisord
# respawns it inside the container, so the container never dies and Docker's
# container-level RestartCount stays 0. The 150s faulthandler + os._exit(1) is the
# independent C-level backstop for a hang the timeout CANNOT catch; it is proven
# separately by tests/boot/test_boot_watchdog_cancel.py, not by this fault class.
#
# A trap ALWAYS restores the box (unset the toggle + --force-recreate) so it is
# never left with the fault hook enabled (T-132-01 / T-132-02).
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
#   0 — fault fired + InitTimeout self-termination + supervisord respawn + /api/health 200 < 180s
#   1 — self-heal assertion failed (no fault fire / no bounded abort / no restart / no recovery)
#   2 — env / preconditions not met (project dir or .env.local missing)
#   3 — docker / docker compose (v2) CLI unavailable

set -euo pipefail

COMPOSE_PROJECT_DIR="${COMPOSE_PROJECT_DIR:-/Volumes/ HardDrive/FinGPT/VM107}"
SERVICE="vm107"
CONTAINER="vm107-agent-zero"
HEALTH_URL="http://localhost:50081/api/health"
TOGGLE="A0_FAULT_INJECT_INIT_HANG"
# How long to watch the injected boot for bounded self-termination + a respawn.
# One InitTimeout cycle is ~A0_INIT_CHATS_TIMEOUT_SECONDS (default 60s); 150s
# comfortably covers a self-terminate + at least one supervisor respawn.
INJECT_OBSERVE_SECONDS="${INJECT_OBSERVE_SECONDS:-150}"
RECOVER_TIMEOUT_SECONDS="${RECOVER_TIMEOUT_SECONDS:-180}"

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
# Phase B's recovery assertion runs INSIDE cleanup so a bad exit still restores.
recovered=0
cleanup() {
  echo "[selfheal] cleanup: removing ${TOGGLE} and recreating vm107 to restore..."
  _strip_toggle
  docker compose --env-file .env.local up -d --force-recreate "${SERVICE}" >/dev/null 2>&1 || true
  # Phase B (d): assert clean recovery to /api/health 200 within the timeout.
  local waited=0
  while [[ "${waited}" -lt "${RECOVER_TIMEOUT_SECONDS}" ]]; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "${HEALTH_URL}" 2>/dev/null || true)
    if [[ "${code}" == "200" ]]; then recovered=1; break; fi
    sleep 2; waited=$((waited + 2))
  done
  echo "[selfheal] post-restore recovery: healthy=${recovered} after ~${waited}s"
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

# 2) Record Docker RestartCount (informational: expected to STAY 0 — recovery is
#    intra-container via supervisord, not a container-level restart).
baseline_restarts=$(docker inspect -f '{{.RestartCount}}' "${CONTAINER}" 2>/dev/null || echo 0)
echo "[selfheal] baseline container RestartCount=${baseline_restarts} (expected to stay flat)"

# 3) Enable the fault toggle and recreate.
_strip_toggle
printf '%s=1\n' "${TOGGLE}" >> .env.local
echo "[selfheal] enabled ${TOGGLE}=1; recreating ${SERVICE}..."
docker compose --env-file .env.local up -d --force-recreate "${SERVICE}" >/dev/null

# 4) Phase A — assert bounded self-termination + auto-restart WHILE injected.
#    A permanent fault loops (each boot aborts at the InitTimeout), so /api/health
#    is expected to stay down here; recovery is asserted in Phase B (cleanup).
saw_fault_fire=0
saw_init_timeout=0
saw_respawn=0
waited=0
while [[ "${waited}" -lt "${INJECT_OBSERVE_SECONDS}" ]]; do
  logs=$(docker logs "${CONTAINER}" 2>&1 || true)
  if printf '%s' "${logs}" | grep -q 'FAULT INJECTION ACTIVE'; then saw_fault_fire=1; fi
  if printf '%s' "${logs}" | grep -q 'InitTimeout'; then saw_init_timeout=1; fi
  # >=2 run_ui spawns == at least one supervisord respawn after a self-termination.
  spawn_count=$(printf '%s' "${logs}" | grep -c "spawned: 'run_ui'" || true)
  if [[ "${spawn_count}" -ge 2 ]]; then saw_respawn=1; fi
  if [[ "${saw_fault_fire}" == "1" && "${saw_init_timeout}" == "1" && "${saw_respawn}" == "1" ]]; then
    break
  fi
  sleep 3; waited=$((waited + 3))
done

injected_restarts=$(docker inspect -f '{{.RestartCount}}' "${CONTAINER}" 2>/dev/null || echo 0)
echo "[selfheal] injected window (~${waited}s): fault_fire=${saw_fault_fire}" \
     "init_timeout=${saw_init_timeout} respawn=${saw_respawn}" \
     "container_RestartCount=${injected_restarts} (0 == intra-container recovery, expected)"

# cleanup() runs via trap on exit: it restores the box AND sets recovered=1 iff
# /api/health returns to 200 within RECOVER_TIMEOUT_SECONDS. Evaluate the full
# verdict AFTER cleanup by trapping into a final check.
finalize() {
  if [[ "${saw_fault_fire}" == "1" && "${saw_init_timeout}" == "1" \
        && "${saw_respawn}" == "1" && "${recovered}" == "1" ]]; then
    echo "PASS: SC-2 — injected init hang fired the fault hook, SELF-TERMINATED via a"
    echo "      bounded helpers.defer.InitTimeout, was AUTO-RESTARTED by supervisord, and"
    echo "      /api/health recovered to 200 within ${RECOVER_TIMEOUT_SECONDS}s once the"
    echo "      toggle was unset. As-built self-heal chain verified (RESEARCH Pattern 2)."
    exit 0
  fi
  echo "FAIL: SC-2 — self-heal assertion failed" \
       "(fault_fire=${saw_fault_fire} init_timeout=${saw_init_timeout}" \
       "respawn=${saw_respawn} recovered=${recovered})." >&2
  exit 1
}
# Chain finalize after cleanup: replace the EXIT trap so cleanup runs then finalize.
trap 'cleanup; finalize' EXIT
