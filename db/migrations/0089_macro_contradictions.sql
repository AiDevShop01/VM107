-- Phase 89 Plan 03 — macro_contradictions table
-- Per ARCHITECTURE §5.4
-- Run: psql "$CONTRADICTION_POSTGRES_URL" -f db/migrations/0089_macro_contradictions.sql -v ON_ERROR_STOP=1

-- ── UP ───────────────────────────────────────────────────────────────────────

CREATE TABLE macro_contradictions (
    contradiction_id  UUID PRIMARY KEY,
    indicator_id      TEXT NOT NULL,
    asset_keys        TEXT[],
    predicted_value   JSONB,
    actual_value      JSONB,
    divergence_sigma  JSONB,
    severity          TEXT NOT NULL CHECK (severity IN ('info','warning','blocking')),
    explanation_candidates JSONB,
    related_belief_id UUID,
    conflict_strength FLOAT NOT NULL,
    unresolved        BOOLEAN NOT NULL DEFAULT TRUE,
    resolution_strategy TEXT,
    resolution_artifact_id UUID,
    detected_at       TIMESTAMPTZ NOT NULL,
    resolved_at       TIMESTAMPTZ
);

CREATE INDEX ON macro_contradictions (indicator_id, unresolved);
CREATE INDEX ON macro_contradictions (severity, unresolved);

-- ── DOWN (rollback) ──────────────────────────────────────────────────────────
-- DROP TABLE macro_contradictions;
