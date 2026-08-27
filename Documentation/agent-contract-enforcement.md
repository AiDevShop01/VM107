# Agent-Contract Enforcement (P167D / AGV-04 + AGV-05)

**Status:** enforcement mechanism landed and reversible. This is the last-wave
(167-09) flip that turns the agent-contract governance corpus from *advisory*
(WARN) into an *enforced* gate — but only after the whole corpus is proven green,
and only via levers that can be turned back off with **no code change**.

Two independent enforcement surfaces:

| Surface | Lever | Effect when ON | Default |
|---------|-------|----------------|---------|
| CI / local gate | `agent_contract_lint.py --block` (wrapped by `scripts/ci_contract_gate.sh`) | exit 1 on any parity finding — governance drift can no longer merge silently | WARN (exit 0) |
| Live boot path | `CONTRACT_BOOT_STRICT=1` env var (read by `initialize_validate_agent_contracts()`) | `raise SystemExit` if any canon-base profile is missing its `agent_contract:` block | absent/`!=1` => WARN-and-continue |

Both are **additive and reversible** (D-02, fragile-tree guard). Neither mutates a
profile. Unsetting the flag / dropping `--block` restores WARN behavior instantly.

---

## `CONTRACT_BOOT_STRICT` — the reversible enforcement lever (AGV-05)

`initialize_validate_agent_contracts()` (in `initialize.py`, wired into
`run_ui.py::run_migration_checks()`) iterates `registry/agent_profile/*.yaml` and
presence-checks the `agent_contract:` block on every **canon-base** manifest. Its
behavior is gated on a single environment variable with an **INVERTED default**:

```python
strict = os.environ.get("CONTRACT_BOOT_STRICT") == "1"
```

| `CONTRACT_BOOT_STRICT` | Boot behavior | Security posture |
|------------------------|---------------|------------------|
| absent / any value `!= "1"` | **WARN-and-continue** — logs findings, never raises, boot proceeds | safe default — env-absent must **never** brick boot (a prior session bricked this tree) |
| `"1"` | **strict** — `raise SystemExit` on the first missing-block finding | security-positive — governed runtime, no ungoverned agent boots |

**Scope of the check (no false-fails):**

- The **3 infra profiles** (`default`, `agent_zero`, `vm107`) are excluded via the
  shared `EXCLUDED_IDS` allowlist (D-07) — never counted, never a finding.
- The **9 nested `._role` sub-profiles** (`._reader` / `._analyzer` / `._writer`)
  inherit their canon-base parent's contract via `is_subprofile()` (167-07) — a
  blockless sub-profile never independently produces a finding.
- Presence/parity **only** — the hook reads and compares, it never writes back to
  any profile path (byte-identity pre/post, pinned by `test_never_mutates_profile`).

**Reversibility (D-02):** strict boot is enabled *only* by setting the env var to
`1`. Unset it (or set it to anything else) and recreate — boot returns to WARN with
**no code change and no profile edit**. This is the load-bearing fragile-tree
discipline: the flip is a config toggle, not a code path you have to revert.

---

## Green-gate precondition — MUST hold before enabling strict

**Never enable `CONTRACT_BOOT_STRICT=1` (in CI or on a container) until the whole
corpus is proven green.** A partially-authored corpus under strict boot would brick
the container (self-inflicted DoS, threat T-167-08). Run the standalone gate:

```bash
bash scripts/ci_contract_gate.sh
```

It runs, and requires exit 0 from, **both** checks:

1. **`agent_contract_lint.py --block`** — exit 1 on any parity finding
   (orphan profile / missing Contract field / tools-authority disagreement) over
   every in-scope `registry/agent_profile` ⋈ `agent-catalogue` pair.
2. **`CONTRACT_BOOT_STRICT=1` strict-boot test**
   (`tests/agent_catalogue/test_boot_validator.py::test_all_real_profiles_green_strict`)
   — asserts all real canon-base profiles validate under strict enforcement without
   raising.

The gate is **standalone** (local + any CI) and is deliberately **NOT** wired into
Phase-154's CI (D-04) — call it explicitly. If either check is red, the gate prints
`BLOCKED` and exits non-zero; do **not** flip strict until it is `GREEN`.

---

## Safe-recreate rule (VM107 dev container) — AVOID the `.env.local` trap

To enable strict boot on the **dev** container (`.62`/`.210` — **dev only, never
prod in this phase**):

1. Set `CONTRACT_BOOT_STRICT=1` in the VM107 **default `.env`** — **NOT** `.env.local`.
2. Recreate with the **plain** command (default `.env` substitution):

   ```bash
   docker compose up -d --no-deps --force-recreate vm107
   ```

**Do NOT pass `--env-file .env.local`.** `AUTH_LOGIN` / `AUTH_PASSWORD` are supplied
by `${}` substitution against the default `.env`; passing `--env-file .env.local`
blanks them and **breaks WebUI login** even though `/api/health` returns 200
(threat T-167-09). This is a recurring, documented VM107 boot trap.

**Post-recreate boot verification (fragile-tree, MEMORY hazards):**

- `docker logs vm107 --tail 80` shows `initialize_validate_agent_contracts` ran with
  a validated count `> 0` and **no** `SystemExit` / crash-loop.
- `docker exec vm107 python -c "import httptools, packaging"` succeeds
  (httptools → blank-WebUI defect; missing `packaging` → litellm import crash-loop).
- WebUI login works (AUTH_* intact).

**To disable / roll back:** unset `CONTRACT_BOOT_STRICT` (or set `!= 1`) in `.env`
and recreate with the same plain `--force-recreate vm107` command. Boot returns to
WARN mode — no code change.

---

## Reference

- Lever source: `scripts/agent_contract_lint.py` (`--block`), `initialize.py`
  (`initialize_validate_agent_contracts`), `run_ui.py` (`run_migration_checks`).
- Gate wrapper: `scripts/ci_contract_gate.sh`.
- Tests: `tests/agent_catalogue/test_boot_validator.py`,
  `tests/agent_catalogue/test_lint.py`.
- Decisions: `.planning/phases/167-vm107-agent-governance-foundation/167-CONTEXT.md`
  (D-01 full rollout, D-02 fragile-tree sequencing, D-04 standalone gate, D-07 infra
  exclusion, D-08 additive boot validator).
