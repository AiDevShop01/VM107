# VM107 Autoheal Runbook (defense-in-depth self-heal)

> **Phase 132 — SC-2 (spec task 5).** Install/operate the autoheal poller that
> recovers a **wedged-but-alive** `vm107-agent-zero` container.
>
> **DEV-ONLY.** Everything below is for the dev box. Do **NOT** enable autoheal on
> prod (`192.168.1.207`) without an explicit owner decision — see
> [Prod parity](#5-dev-only--prod-parity).

---

## 1. What autoheal covers (and why restart-policy misses it)

Docker's `restart: unless-stopped` policy fires only when the container **process
exits**. Phase 132's boot-wedge class is different: the process is **alive but
unhealthy** — `/api/health` never returns 200, so the compose healthcheck
(`docker-compose.yml:119-124`: `interval 30s`, `timeout 10s`, `start_period 120s`,
`retries 3`) declares the container **`unhealthy` ~210s after start** and it stays
that way **forever**. `restart:` never triggers because the process never exits.

Autoheal closes that residual gap (v2 audit B3). It polls the container health and,
on **sustained** `unhealthy`, recreates the service with the mandated recovery
command:

```
docker compose --env-file .env.local up -d --force-recreate vm107
```

> With 132-02's `os._exit` boot watchdog, most wedges now *exit* and supervisor /
> restart-policy relaunch them. Autoheal is the belt-and-suspenders layer for the
> case where the process stays alive but never serves health.

**Never `docker restart`.** The VM107 image is build-on-host and the `env_file` is
read only at **CREATE** time — the `restart` subcommand would reuse stale env/config.
Recovery is **always** `docker compose up -d --force-recreate`. The poller
(`scripts/autoheal_poll.sh`) enforces this and contains no `restart` subcommand.

---

## 2. Delivery mechanism: HOST CRON (owner decision, least-privilege)

**Chosen mechanism (132-04 T1): host cron.** The alternative — a compose sidecar
running the poller inside a container — would require mounting `/var/run/docker.sock`
into that container, which grants it full control of the host Docker daemon (a
privilege-escalation surface, threat T-132-09). A **host cron** runs the poller as a
host user and needs **no** socket mounted into any container, so it is the
least-privilege choice and the default here. (If prod parity ever demands a
socket-mounted sidecar, guard it with a read-only socket proxy and document the
escalation explicitly — but that is out of scope for the dev verification.)

### Install (host cron)

The poller is **single-shot and idempotent** — one invocation checks health and
maybe recreates, then returns. Run it **every minute** from cron; the poller itself
tracks how long the container has been continuously unhealthy (via a small state
file) and only acts once the sustained-unhealthy threshold is crossed.

Add this crontab line (`crontab -e`) — adjust `COMPOSE_PROJECT_DIR` to the compose
project dir on this host (dev default shown; prod would be `/opt/vm107`):

```cron
# VM107 autoheal — poll health every minute; recreate on sustained unhealthy.
* * * * * COMPOSE_PROJECT_DIR="/Volumes/ HardDrive/FinGPT/VM107" /bin/bash "/Volumes/ HardDrive/FinGPT/VM107/scripts/autoheal_poll.sh" >> /tmp/vm107_autoheal.log 2>&1
```

Verify it is installed:

```bash
crontab -l | grep autoheal_poll.sh
```

### Remove (host cron)

```bash
crontab -e            # delete the autoheal_poll.sh line, save
# then clear any pending state marker:
rm -f /tmp/vm107_autoheal_unhealthy_since
```

### Tunables (all env-overridable)

| Env var | Default | Purpose |
|---------|---------|---------|
| `COMPOSE_PROJECT_DIR` | `/Volumes/ HardDrive/FinGPT/VM107` | compose project dir (set to `/opt/vm107` on other hosts) |
| `AUTOHEAL_UNHEALTHY_THRESHOLD_SECONDS` | `240` (4 min) | sustained-unhealthy gate before any recreate |
| `AUTOHEAL_CONTAINER` | `vm107-agent-zero` | `container_name` inspected for health |
| `AUTOHEAL_SERVICE` | `vm107` | compose service recreated |
| `AUTOHEAL_ENV_FILE` | `.env.local` | compose env file (read at CREATE) |
| `AUTOHEAL_STATE_FILE` | `/tmp/vm107_autoheal_unhealthy_since` | first-seen-unhealthy marker |

**Exit codes:** `0` healthy / under-threshold / recreate-OK · `1` recreate failed ·
`2` project dir or env file missing · `3` docker / compose v2 CLI unavailable.

---

## 3. Sustained-unhealthy threshold: 4 minutes (240s)

The poller acts **only after the container has been continuously unhealthy for the
threshold**, defaulting to **4 minutes (240s)**. This is deliberately larger than the
healthcheck `start_period` (120s) **plus** the ~210s `unhealthy`-declaration window,
so a **slow cold boot is never flapped** into a recreate loop (threat T-132-10). A
single transient `unhealthy` reading does **not** trigger a recreate — the poller
records a first-seen-unhealthy timestamp and clears it the moment health recovers,
so the timer only fires on a *genuinely stuck* container.

Override per host with `AUTOHEAL_UNHEALTHY_THRESHOLD_SECONDS` if your cold-boot p95
is unusually long (measure via `scripts/soak_boot_recreate.sh`).

---

## 4. Verify it works (dev box)

1. Ensure the stack is up: `docker compose --env-file .env.local up -d vm107`.
2. Simulate a **wedged-but-alive** process (the container stays up but `/api/health`
   stops returning 200) — use the env-gated fault hook baked in
   `helpers/persist_chat.py` (`A0_FAULT_INJECT_INIT_HANG=1` in `.env.local`, then
   `up -d --force-recreate vm107`), or otherwise force the healthcheck to fail while
   the process stays alive.
3. Watch the poller decide over wall-clock time:
   ```bash
   COMPOSE_PROJECT_DIR="/Volumes/ HardDrive/FinGPT/VM107" \
     bash scripts/autoheal_poll.sh
   docker inspect -f '{{.State.Health.Status}}' vm107-agent-zero
   ```
   For the first ~4 minutes of sustained `unhealthy` the poller logs
   `unhealthy for Ns (< 240s threshold) — waiting`; once the threshold is crossed it
   logs the `--force-recreate` and the container is recreated.
4. Confirm recovery: `/api/health` returns 200 within the boot window after recreate,
   and remember to **unset the fault toggle** and recreate to restore normal boot.

This wall-clock behaviour is the **manual-only** verification row in
[`132-VALIDATION.md`](../../.planning/phases/132-p0-boot-reliability-self-heal-critical/132-VALIDATION.md)
("*Healthcheck acts — wedged-but-alive process → autoheal recreates within the
configured window*"). The soak (`scripts/soak_boot_recreate.sh`) and fault-injection
recreate cycle (`scripts/verify_selfheal.sh`) are automated; only the autoheal
wall-clock window is exercised manually, at owner discretion, on the dev box.

---

## 5. DEV-ONLY / prod parity

- This runbook and the cron entry are for the **dev box only**.
- **Do NOT enable autoheal on prod (`192.168.1.207`)** without an explicit owner
  decision. Prod deployment of this layer must go through the `vm107-deploy-prod`
  process, use the prod compose project dir (`/opt/vm107`), and re-confirm the
  threshold against prod cold-boot timings.
- If a socket-mounted sidecar is ever chosen for prod parity instead of host cron,
  it **must** carry an explicit `/var/run/docker.sock` escalation SECURITY WARNING
  and should front the socket with a read-only proxy (threat T-132-09). Host cron is
  the recommended least-privilege default on every host.
- The poller layer is **additive and independent of the baked image** — it needs no
  132-05 image rebuild to take effect.
