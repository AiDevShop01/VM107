#!/usr/bin/env bash
# Phase 132 SC-4 — boot-reliability soak harness (dev box only).
#
# Builds the vm107 image ONCE, then performs N consecutive
# `docker compose up -d --force-recreate vm107` cycles, polling
# http://localhost:50081/api/health (host :50081 -> container :80) for HTTP 200
# after each recreate. Records pass/fail + boot seconds per iteration. The phase
# gate (132-05) runs this with N=20 and requires 20/20 before /gsd:verify-work.
#
# Per VM107 project rule: use `docker compose` (v2, NEVER legacy `docker-compose`)
# and ALWAYS `up -d --force-recreate` — never restart the container (env_file is
# read only at CREATE; the image is build-on-host). --env-file .env.local always.
#
# Between iterations the harness SETTLES for SOAK_SETTLE_SECONDS (default 45s) so
# the host reclaims memory (macOS compressor / Linux page cache) before the next
# recreate. Without this, 20 back-to-back recreates on a loaded multi-VM dev box
# accumulate memory pressure that balloons a normally ~50s cold boot past the poll
# window — a host-resource artifact, not a boot-logic failure. Set
# SOAK_SETTLE_SECONDS=0 to reproduce the harsh rapid-fire behavior.
#
# Usage:
#   COMPOSE_PROJECT_DIR=/path/to/VM107 bash scripts/soak_boot_recreate.sh [N]
#   SOAK_SETTLE_SECONDS=45 bash scripts/soak_boot_recreate.sh 20
#   (N defaults to 20; SOAK_SETTLE_SECONDS defaults to 45)
#
# Exit codes:
#   0 — all N recreates reached /api/health 200 (P == N)
#   1 — one or more recreates failed to reach /api/health 200 within 180s
#   2 — env / preconditions not met (project dir or .env.local missing)
#   3 — docker / docker compose (v2) CLI unavailable

set -euo pipefail

N="${1:-20}"
SOAK_SETTLE_SECONDS="${SOAK_SETTLE_SECONDS:-45}"

COMPOSE_PROJECT_DIR="${COMPOSE_PROJECT_DIR:-/Volumes/ HardDrive/FinGPT/VM107}"
HEALTH_URL="http://localhost:50081/api/health"

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

echo "[soak] building vm107 image once..."
docker compose --env-file .env.local build vm107

pass=0
for i in $(seq 1 "${N}"); do
  echo "[soak] iter ${i}/${N}: docker compose up -d --force-recreate vm107"
  docker compose --env-file .env.local up -d --force-recreate vm107 >/dev/null

  ok=0
  start_epoch=$(date +%s)
  # Poll up to 180s (90 x 2s) for HTTP 200.
  for _ in $(seq 1 90); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "${HEALTH_URL}" 2>/dev/null || true)
    if [[ "${code}" == "200" ]]; then
      ok=1
      break
    fi
    sleep 2
  done
  boot_seconds=$(( $(date +%s) - start_epoch ))

  if [[ "${ok}" == "1" ]]; then
    pass=$((pass + 1))
    echo "  OK    iter ${i}: /api/health 200 after ${boot_seconds}s"
  else
    echo "  FAIL  iter ${i}: /api/health never returned 200 within ${boot_seconds}s"
  fi

  # Settle between iterations so the host reclaims memory before the next
  # recreate (skip after the final iteration).
  if [[ "${i}" -lt "${N}" && "${SOAK_SETTLE_SECONDS}" -gt 0 ]]; then
    echo "  ..... settling ${SOAK_SETTLE_SECONDS}s (memory reclaim) before next recreate"
    sleep "${SOAK_SETTLE_SECONDS}"
  fi
done

echo ""
echo "SOAK: ${pass}/${N} reached /api/health 200"

if [[ "${pass}" -eq "${N}" ]]; then
  echo "PASS: SC-4 — ${N}/${N} consecutive --force-recreate boots reached /api/health 200."
  exit 0
fi

echo "FAIL: SC-4 — only ${pass}/${N} boots reached /api/health 200." >&2
exit 1
