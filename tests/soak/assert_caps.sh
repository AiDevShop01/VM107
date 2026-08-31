#!/usr/bin/env bash
#
# assert_caps.sh — Phase 154 Wave 0 (AZI-01/02 RED harness).
#
# Asserts that EVERY one of the 16 long-lived VM107 services declares an
# explicit memory cap (docker `HostConfig.Memory` != 0). This is the automated
# proof that the tiered hard-cap work of AZI-01 (154-02) actually engaged — a
# cap written under `deploy:` is a silent no-op on `docker compose up` (non-swarm),
# so the ONLY trustworthy signal is `docker inspect ... {{.HostConfig.Memory}}`.
#
# RED TODAY: no service sets a cap, so every container reports Memory 0 and this
# script exits non-zero, naming each uncapped service. It flips GREEN once
# 154-02 lands per-service mem_limit/cpus and the stack is rebuilt/recreated.
#
# Read-only: this script only INSPECTS the running stack. It never mutates
# compose, requirements, or any container.
#
# Usage:   assert_caps.sh
# Env:
#   COMPOSE_FILE   default VM107/docker-compose.yml (documentation/source-of-truth
#                  pointer; the service list below is the authoritative enumeration).
#
# Source of truth for the 16 container names: `grep container_name VM107/docker-compose.yml`.

set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-VM107/docker-compose.yml}"

# The 16 top-level VM107 services (container_name values, verbatim from the
# compose file). Monitoring sidecars in VM107/docker/run/docker-compose.yml are
# intentionally OUT of scope (RESEARCH Open Question 3 — AZI-01 is the 16 here).
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

echo "assert_caps: checking mem caps on ${#SERVICES[@]} services (COMPOSE_FILE=$COMPOSE_FILE)"

uncapped=()
missing=()

for svc in "${SERVICES[@]}"; do
  # `|| true` so a missing/stopped container does not abort the whole loop
  # under `set -e`; an empty result is treated the same as an uncapped service.
  out="$(docker inspect "$svc" --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}' 2>/dev/null || true)"
  if [ -z "$out" ]; then
    echo "  MISSING  $svc (container not found — cannot verify cap)"
    missing+=("$svc")
    continue
  fi
  mem="${out%% *}"
  cpu="${out##* }"
  if [ -z "$mem" ] || [ "$mem" = "0" ]; then
    echo "  UNCAPPED $svc (HostConfig.Memory=$mem, NanoCpus=$cpu)"
    uncapped+=("$svc")
  else
    echo "  OK       $svc (Memory=$mem, NanoCpus=$cpu)"
  fi
done

fail=0
if [ "${#uncapped[@]}" -gt 0 ]; then
  echo "FAIL: ${#uncapped[@]} service(s) have NO memory cap: ${uncapped[*]}" >&2
  fail=1
fi
if [ "${#missing[@]}" -gt 0 ]; then
  echo "FAIL: ${#missing[@]} service(s) not running — cap unverifiable: ${missing[*]}" >&2
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  exit 1
fi

echo "assert_caps: PASS — all ${#SERVICES[@]} services carry a memory cap"
