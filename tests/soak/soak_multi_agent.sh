#!/usr/bin/env bash
#
# soak_multi_agent.sh — Phase 154 Wave 0 (AZI-01/02 load-soak driver).
#
# Reproduces the prior dev-host wedge: fire a burst of concurrent agent
# requests at the vm107 WebUI/API while sampling per-container memory
# (`docker stats --no-stream`) and host memory pressure (macOS `vm_stat`)
# across a fixed window. On completion it runs assert_caps.sh and prints a
# per-service OOMKilled summary (`docker inspect ... {{.State.OOMKilled}}`).
#
# This task only MEASURES. It applies no caps and mutates no compose /
# requirements / container config — it is a read-only probe against the
# running stack (threat T-154-02: dev-host-only, time-boxed, run manually at
# wave/phase gates, never in unattended CI).
#
# Usage:   soak_multi_agent.sh
# Env (all overridable):
#   COMPOSE_FILE     default VM107/docker-compose.yml (passed through to assert_caps.sh)
#   VM107_URL        default http://localhost:8107  (WebUI/API base; health probe target)
#   SOAK_CONCURRENCY default 24   (parallel request fan-out)
#   SOAK_DURATION    default 60   (seconds of sustained load)
#   SOAK_SAMPLE_INT  default 5    (seconds between docker-stats/vm_stat samples)

set -euo pipefail

_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

COMPOSE_FILE="${COMPOSE_FILE:-VM107/docker-compose.yml}"
VM107_URL="${VM107_URL:-http://localhost:8107}"
SOAK_CONCURRENCY="${SOAK_CONCURRENCY:-24}"
SOAK_DURATION="${SOAK_DURATION:-60}"
SOAK_SAMPLE_INT="${SOAK_SAMPLE_INT:-5}"

SERVICES=(
  vm107-redis
  vm107-agent-zero
  vm107-macro-emitter
  vm107-agent-telemetry-publisher
  vm107-macro-release-event-listener
  vm107-task-dispatcher
  vm107-macro-story-tracker
  vm107-macro-regime-monitor
  vm107-event-bus
  vm107-theme-engine
  vm107-executive-summary-subscriber
  vm107-theme-monitor-subscriber
  vm107-timeline-subscriber
  vm107-central-bank-subscriber
  vm107-domain-analyst-subscriber
  vm107-cost-monitor
)

log() { printf '[soak %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

# --- host memory pressure sample (macOS vm_stat; no-op on non-macOS) ----------
sample_host_mem() {
  if command -v vm_stat >/dev/null 2>&1; then
    # Pages free + pages active/inactive give a coarse pressure read.
    vm_stat | awk -F: '/Pages free|Pages active|Pages inactive|Pages wired down/ {gsub(/[ .]/,"",$2); printf "%s=%s ", $1, $2}'
    echo
  else
    free -m 2>/dev/null | awk '/Mem:/ {printf "mem_used_mb=%s mem_free_mb=%s\n", $3, $4}' || echo "host-mem: unavailable"
  fi
}

# --- one unit of agent-ish load: a burst of concurrent HTTP hits -------------
fire_burst() {
  local n="$1" i
  for ((i = 0; i < n; i++)); do
    # Hit the health/base surface; -m caps each request so a wedged server
    # does not hang the driver. Failures are expected under wedge — we are
    # probing memory pressure, not asserting 200s here.
    curl -s -o /dev/null -m 10 "$VM107_URL/health" 2>/dev/null &
    curl -s -o /dev/null -m 10 "$VM107_URL/" 2>/dev/null &
  done
  wait
}

log "starting multi-agent soak: concurrency=$SOAK_CONCURRENCY duration=${SOAK_DURATION}s target=$VM107_URL"
log "host mem (pre): $(sample_host_mem)"

start_epoch="$(date +%s)"
end_epoch=$((start_epoch + SOAK_DURATION))
next_sample=$((start_epoch + SOAK_SAMPLE_INT))

while [ "$(date +%s)" -lt "$end_epoch" ]; do
  fire_burst "$SOAK_CONCURRENCY"
  now="$(date +%s)"
  if [ "$now" -ge "$next_sample" ]; then
    log "docker stats sample:"
    docker stats --no-stream --format '  {{.Name}} mem={{.MemUsage}} ({{.MemPerc}}) cpu={{.CPUPerc}}' \
      "${SERVICES[@]}" 2>/dev/null || log "  docker stats sample failed (containers down?)"
    log "host mem: $(sample_host_mem)"
    next_sample=$((now + SOAK_SAMPLE_INT))
  fi
done

log "host mem (post): $(sample_host_mem)"

# --- per-service OOMKilled summary -------------------------------------------
log "OOMKilled summary:"
oom_hit=0
for svc in "${SERVICES[@]}"; do
  oom="$(docker inspect "$svc" --format '{{.State.OOMKilled}}' 2>/dev/null || echo 'unknown')"
  printf '  %-40s OOMKilled=%s\n' "$svc" "$oom"
  [ "$oom" = "true" ] && oom_hit=1
done
if [ "$oom_hit" -eq 1 ]; then
  log "WARNING: at least one container was OOMKilled during the soak"
fi

# --- run the cap assertion (RED until AZI-01 lands) --------------------------
log "invoking assert_caps.sh ..."
if COMPOSE_FILE="$COMPOSE_FILE" bash "$_HERE/assert_caps.sh"; then
  log "assert_caps: PASS"
else
  log "assert_caps: FAIL (expected RED until AZI-01/154-02 lands per-service caps)"
fi

log "soak complete"
