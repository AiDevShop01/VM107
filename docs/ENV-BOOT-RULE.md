# VM107 Canonical env-file Boot Rule (F4)

**Status:** CANONICAL · **Decided:** 2026-08-12 (Phase 138 / Plan 138-07, F4) · **Scope:** VM107 (Agent Zero) DEV stack

## The rule

**`.env.local` is the operative boot env file for VM107.** Recreate the stack with:

```bash
docker compose --env-file .env.local up -d --force-recreate <service>
```

`env_file:` is read only at container **CREATE** time, and the image is built on-host — so you must
`up -d --force-recreate` after any env change. **Never** `docker restart` (it ignores `env_file:` edits).
This matches `scripts/soak_boot_recreate.sh`, which pins `--env-file .env.local` and exits `2` if
`.env.local` is missing.

## Why `.env.local` (empirically determined, not assumed)

The original CONTEXT premise ("canonical = `.env`, quarantine `.env.local`") was **stale** — inherited
from VM100 and contradicted by the live VM107 tree. The operative file was determined **empirically**
against the running container (Task 1, 138-07), not by assumption:

```
# docker exec vm107-agent-zero sh -c 'echo AUTH_LOGIN=[$AUTH_LOGIN]; \
#   echo A0_LLM_SECONDARY_MODEL=[$A0_LLM_SECONDARY_MODEL]; echo NEO4J_USER=[$NEO4J_USER]'
AUTH_LOGIN=[]                                    # .env-only key -> present as an empty declaration
A0_LLM_SECONDARY_MODEL=[gemini/gemini-2.0-flash] # .env.local-only key -> POPULATED
NEO4J_USER=[neo4j]                               # .env.local-only key -> POPULATED
```

- `.env.local`'s unique keys (`A0_LLM_SECONDARY_*`, `NEO4J_*`) are **populated** in the container.
- `.env`'s unique keys (`AUTH_LOGIN`, `MACRO_EMITTER_*`, `VM107_TASK_DISPATCHER_*`) reach the container
  only as **empty-valued declarations** from the `environment: KEY: ${KEY}` lines — `.env`'s real
  values never load.

Corroborating evidence:
- `docker-compose.yml` declares `env_file: - .env.local` at **15** service sites.
- `scripts/soak_boot_recreate.sh` boots with `--env-file .env.local` (header: "`--env-file .env.local` always").
- `.env.local` satisfies **every** fail-fast `${VAR:?}` interpolation key required by compose
  (verified: `VM107_MCP_JWKS_URI`, `VM100_BASE_URL`, `VM107_INTERNAL_TOKEN`, `VM107_MCP_PORT`,
  `PHASE_91_UAE_URL`).

## Dual-source model (how env actually reaches a container)

Each service's container environment is a **merge of two layers**:

1. **`env_file: - .env.local`** — injects `.env.local`'s ~69 keys as the base container env
   (this is where `A0_LLM_SECONDARY_*` / `NEO4J_*` come from).
2. **`environment:` block `${VAR}` interpolation** — resolved from the `--env-file` interpolation
   source (`.env.local` under the canonical boot). Keys absent from the interpolation source render
   **empty** (e.g. `AUTH_LOGIN`), unless they carry a `:-default` or `:?fail-fast` operator.

Because the canonical boot uses `--env-file .env.local`, `.env.local` is BOTH the `env_file:` base
AND the interpolation source. `.env` is **retained but non-operative** — its unique values do not
reach any container under this rule.

## File dispositions

| File | Disposition |
|------|-------------|
| `.env.local` | **CANONICAL / operative** — do NOT quarantine or rename. |
| `.env` | **Retained, non-operative** — kept for reference; its unique values are not loaded at boot. |
| `.env.example` | KEEP (template). |
| `.env.production` | KEEP (prod reference — DEV stack does not use it). |
| `.env.bak-costmonitor` | **REMOVED** (untracked stray backup, zero references — 138-07 Task 1). |

## Known follow-up (NOT reconciled in 138-07)

`.env.local` is missing **29 keys** that `.env` has, so the following container keys are currently
**empty declarations** under the canonical boot: `AUTH_LOGIN`, `AUTH_PASSWORD`, the `MACRO_EMITTER_*`
cadence/health set, `VM107_TASK_DISPATCHER_*`, `VM107_AGENT_ZERO_URL`, `VM107_BRAIN_DB`, and the
`SUPERVISORY_COOLDOWN_*` / `AGENT_TELEMETRY_*` sets. This has been the operative state (soaks pass,
`:50081/api/health` = 200), so it is flagged as **reconciliation follow-up**, not fixed here: a future
pass should decide, per key, whether to (a) add the real value to `.env.local`, or (b) delete the dead
`environment: KEY: ${KEY}` declaration from `docker-compose.yml`. Reconciling now was explicitly out of
scope for 138-07 (accept-local path) to avoid boot risk on a fragile tree.

## DEV-only

This rule governs the DEV `vm107-agent-zero` stack on this box. Prod (`.207`/`.209`) is untouched by
138-07.
