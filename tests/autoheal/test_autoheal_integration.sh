#!/usr/bin/env bash
#
# test_autoheal_integration.sh — Phase 154 Wave 0 (AZI-03 RED harness).
#
# Proves the AZI-03 contract: an unhealthy container gets RESTARTED by a
# compose-native autoheal sidecar (no host crontab). The test forces a
# long-lived service (vm107-cost-monitor) unhealthy by freezing it
# (`docker kill --signal=STOP`), then polls for a restart (RestartCount
# increment or a newer StartedAt).
#
# RED TODAY: no `vm107-autoheal` sidecar exists, so nothing restarts the
# frozen container. The script fails fast on the missing sidecar (exit 1)
# WITHOUT freezing anything, so it is a safe, quick RED now; it becomes a real
# force-unhealthy -> restart integration test once 154-03 lands the sidecar.
#
# Cleanup is unconditional: if the target was frozen, it is ALWAYS unfrozen
# (SIGCONT) on exit so the running dev stack is never left wedged.
#
# Usage:   test_autoheal_integration.sh
# Env (overridable):
#   AUTOHEAL_TARGET      default vm107-cost-monitor
#   AUTOHEAL_SIDECAR     default vm107-autoheal
#   AUTOHEAL_INTERVAL    default 30   (matches Pattern 2 sidecar env)
#   AUTOHEAL_START_PERIOD default 60
#   POLL_TIMEOUT         default AUTOHEAL_INTERVAL + AUTOHEAL_START_PERIOD + 60

set -euo pipefail

AUTOHEAL_TARGET="${AUTOHEAL_TARGET:-vm107-cost-monitor}"
AUTOHEAL_SIDECAR="${AUTOHEAL_SIDECAR:-vm107-autoheal}"
AUTOHEAL_INTERVAL="${AUTOHEAL_INTERVAL:-30}"
AUTOHEAL_START_PERIOD="${AUTOHEAL_START_PERIOD:-60}"
POLL_TIMEOUT="${POLL_TIMEOUT:-$((AUTOHEAL_INTERVAL + AUTOHEAL_START_PERIOD + 60))}"

FROZEN=0
cleanup() {
  # Always thaw the target if we froze it — never leave the dev stack wedged.
  if [ "$FROZEN" -eq 1 ]; then
    docker kill --signal=CONT "$AUTOHEAL_TARGET" >/dev/null 2>&1 || true
    echo "cleanup: thawed $AUTOHEAL_TARGET (SIGCONT)"
  fi
}
trap cleanup EXIT

log() { printf '[autoheal-test %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

# --- (0) sidecar presence gate — RED fast today ------------------------------
sidecar="$(docker ps --filter "name=${AUTOHEAL_SIDECAR}" --format '{{.Names}}' 2>/dev/null || true)"
if [ -z "$sidecar" ]; then
  echo "FAIL: autoheal sidecar '${AUTOHEAL_SIDECAR}' not running — AZI-03 not yet delivered (RED)" >&2
  echo "      (expected until 154-03 adds the willfarrell/autoheal service to the compose)" >&2
  exit 1
fi
log "autoheal sidecar present: $sidecar"

# --- (1) verify target is running before we perturb it -----------------------
if ! docker inspect "$AUTOHEAL_TARGET" >/dev/null 2>&1; then
  echo "FAIL: target '${AUTOHEAL_TARGET}' not found — cannot run autoheal integration" >&2
  exit 1
fi

restarts_before="$(docker inspect "$AUTOHEAL_TARGET" --format '{{.RestartCount}}' 2>/dev/null || echo 0)"
started_before="$(docker inspect "$AUTOHEAL_TARGET" --format '{{.State.StartedAt}}' 2>/dev/null || echo '')"
log "before: RestartCount=$restarts_before StartedAt=$started_before"

# --- (2) force unhealthy: freeze the container so its healthcheck fails -------
log "freezing $AUTOHEAL_TARGET (SIGSTOP) to force an unhealthy state ..."
docker kill --signal=STOP "$AUTOHEAL_TARGET" >/dev/null 2>&1
FROZEN=1

# --- (3) poll for a restart --------------------------------------------------
log "polling up to ${POLL_TIMEOUT}s for autoheal to restart the container ..."
deadline=$(( $(date +%s) + POLL_TIMEOUT ))
restarted=0
while [ "$(date +%s)" -lt "$deadline" ]; do
  restarts_now="$(docker inspect "$AUTOHEAL_TARGET" --format '{{.RestartCount}}' 2>/dev/null || echo "$restarts_before")"
  started_now="$(docker inspect "$AUTOHEAL_TARGET" --format '{{.State.StartedAt}}' 2>/dev/null || echo "$started_before")"
  if [ "$restarts_now" != "$restarts_before" ] || [ "$started_now" != "$started_before" ]; then
    restarted=1
    FROZEN=0   # a restart replaces the frozen process; nothing to thaw
    log "RESTART detected: RestartCount $restarts_before->$restarts_now StartedAt $started_now"
    break
  fi
  sleep 5
done

if [ "$restarted" -ne 1 ]; then
  echo "FAIL: $AUTOHEAL_TARGET was NOT restarted within ${POLL_TIMEOUT}s (autoheal did not act)" >&2
  exit 1
fi

log "PASS: autoheal restarted the unhealthy container"
