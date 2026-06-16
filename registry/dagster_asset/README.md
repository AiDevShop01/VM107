# registry/dagster_asset/

Capability descriptors for Dagster materialised assets shipped from the
`fingpt_orchestration` package (the Dagster code location).

**Type:** `dagster_asset` (added to `CapabilityType` enum in Phase 88 Plan 09,
mirroring the Phase 86 `vm102_api` / `agent` extension pattern.)

## Required fields (Stage 2 schema validation)

Every YAML in this folder must declare the base `CapabilityType` fields:

- `id` — globally unique across the entire registry, prefix `dagster_` recommended.
- `type` — must be exactly `dagster_asset`.
- `status` — one of `stub` / `experimental` / `real` / `deprecated`.
- `impact_on_decision` — `HIGH` / `MEDIUM` / `LOW`.

## Conventional fields (for `lookup_capability` consumers)

- `phase` — phase that shipped the asset.
- `asset_key` — Dagster asset key (matches the `@asset` function name or
  explicit `key_prefix` / `name=` in the decorator).
- `group_name` — Dagster group the asset belongs to.
- `source` — upstream data source (e.g. `alfred`, `fred`, `ctrader`).
- `compute` — VM where the materialisation runs (e.g. `vm101`, `vm102`).
- `vm` — VM hosting the Dagster code location for THIS materialisation
  (typically `vm111` in prod, `mac-docker` in dev).
- `refresh_frequency` — `daily` / `hourly` / `event` / `manual`.
- `partition_strategy` — free-form description of partition shape.
- `owner` — team/group ownership.
- `last_changed` — ISO date the YAML last changed.
- `description` — block scalar describing what the asset produces and who
  consumes it downstream.

## First entry

`macro_alfred_vintages.yaml` — daily ALFRED vintage refresh for the
64 Phase-83 macro indicators. Shipped Phase 88 Plan 09.
