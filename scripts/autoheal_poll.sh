#!/usr/bin/env bash
# Phase 132 SC-2 (defense-in-depth, spec task 5) — VM107 autoheal poller (dev box only).
#
# The Docker `restart: unless-stopped` policy fires only on process EXIT. A
# container that is alive-but-unhealthy (the boot-wedge class this phase targets)
# reports `unhealthy` via the healthcheck forever and never self-recovers. This
# poller closes that gap: on SUSTAINED unhealthy it recreates the container via
# `docker compose --env-file .env.local up -d --force-recreate vm107`.
#
# DELIVERY MECHANISM (owner decision, 132-04 T1): HOST CRON — least-privilege.
# No container is granted /var/run/docker.sock (a host-control escalation surface).
# This script is designed to be invoked single-shot and idempotently from cron
# (e.g. every minute). It tracks the first-seen-unhealthy timestamp in a small
# state file so a slow cold boot (healthcheck start_period is 120s; `unhealthy`
# is only declared ~210s after start) is NEVER flapped: it acts only once the
# container has been continuously unhealthy for the sustained-unhealthy threshold
# (default 4 minutes / 240s, > the 120s start_period + ~210s declaration window).
#
# Per VM107 project rule: recovery is ONLY `docker compose up -d --force-recreate`
# (the env_file is read at CREATE time; the image is build-on-host). This script
# NEVER uses the docker `restart` subcommand — that would ignore .env.local edits
# and is forbidden project-wide.
#
# Tunables (all env-overridable):
#   COMPOSE_PROJECT_DIR                   VM107 compose project dir (default dev path below)
#   AUTOHEAL_UNHEALTHY_THRESHOLD_SECONDS  sustained-unhealthy gate in seconds (default 240 = 4 min)
#   AUTOHEAL_CONTAINER                    container_name to inspect (default vm107-agent-zero)
#   AUTOHEAL_SERVICE                      compose service to recreate (default vm107)
#   AUTOHEAL_ENV_FILE                     compose env file (default .env.local)
#   AUTOHEAL_STATE_FILE                   unhealthy-since marker file (default /tmp/vm107_autoheal_unhealthy_since)
#
# Usage (single-shot, from cron):
#   COMPOSE_PROJECT_DIR=/opt/vm107 bash scripts/autoheal_poll.sh
#
# Exit codes:
#   0 — healthy, OR unhealthy-but-under-threshold (no action), OR recreate succeeded
#   1 — sustained unhealthy detected but `--force-recreate` failed
#   2 — env / preconditions not met (project dir or env file missing)
#   3 — docker / docker compose (v2) CLI unavailable

set -euo pipefail

COMPOSE_PROJECT_DIR="${COMPOSE_PROJECT_DIR:-/Volumes/ HardDrive/FinGPT/VM107}"
THRESHOLD_SECONDS="${AUTOHEAL_UNHEALTHY_THRESHOLD_SECONDS:-240}"
CONTAINER="${AUTOHEAL_CONTAINER:-vm107-agent-zero}"
SERVICE="${AUTOHEAL_SERVICE:-vm107}"
ENV_FILE="${AUTOHEAL_ENV_FILE:-.env.local}"
STATE_FILE="${AUTOHEAL_STATE_FILE:-/tmp/vm107_autoheal_unhealthy_since}"

log() {
  # Timestamped decision log line (UTC).
  printf '[autoheal %s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

# --- Preflight guards ------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  log "FAIL: docker CLI not on PATH"
  exit 3
fi

if ! docker compose version >/dev/null 2>&1; then
  log "FAIL: 'docker compose' (v2) subcommand unavailable"
  exit 3
fi

if [[ ! -d "${COMPOSE_PROJECT_DIR}" ]]; then
  log "FAIL: COMPOSE_PROJECT_DIR=${COMPOSE_PROJECT_DIR} is not a directory"
  exit 2
fi

if [[ ! -f "${COMPOSE_PROJECT_DIR}/${ENV_FILE}" ]]; then
  log "FAIL: env file ${ENV_FILE} not found in ${COMPOSE_PROJECT_DIR}"
  exit 2
fi

# --- Read current health ---------------------------------------------------
# Empty when the container is absent or has no healthcheck; treat as not-unhealthy.
status="$(docker inspect -f '{{.State.Health.Status}}' "${CONTAINER}" 2>/dev/null || true)"
now="$(date +%s)"

if [[ "${status}" != "unhealthy" ]]; then
  # Healthy / starting / absent — clear any pending unhealthy marker and exit.
  if [[ -f "${STATE_FILE}" ]]; then
    rm -f "${STATE_FILE}"
    log "status='${status:-<none>}' — cleared unhealthy marker (recovered)"
  else
    log "status='${status:-<none>}' — no action"
  fi
  exit 0
fi

# --- Unhealthy: gate on the sustained window -------------------------------
if [[ -f "${STATE_FILE}" ]]; then
  since="$(cat "${STATE_FILE}" 2>/dev/null || echo "${now}")"
  # Guard against a corrupt/non-numeric marker.
  if ! [[ "${since}" =~ ^[0-9]+$ ]]; then
    since="${now}"
    printf '%s\n' "${since}" >"${STATE_FILE}"
  fi
else
  since="${now}"
  printf '%s\n' "${since}" >"${STATE_FILE}"
  log "container '${CONTAINER}' first observed unhealthy — starting sustained-window timer (${THRESHOLD_SECONDS}s)"
fi

elapsed=$(( now - since ))

if (( elapsed < THRESHOLD_SECONDS )); then
  log "container '${CONTAINER}' unhealthy for ${elapsed}s (< ${THRESHOLD_SECONDS}s threshold) — waiting, no action"
  exit 0
fi

# --- Sustained unhealthy: recreate (NEVER the docker `restart` subcommand) ---
log "container '${CONTAINER}' unhealthy for ${elapsed}s (>= ${THRESHOLD_SECONDS}s) — recreating service '${SERVICE}' via docker compose --force-recreate"

cd "${COMPOSE_PROJECT_DIR}"
if docker compose --env-file "${ENV_FILE}" up -d --force-recreate "${SERVICE}"; then
  rm -f "${STATE_FILE}"
  log "recreate OK — cleared unhealthy marker; sustained-window timer reset"
  exit 0
fi

log "FAIL: 'docker compose --force-recreate ${SERVICE}' returned non-zero"
exit 1
