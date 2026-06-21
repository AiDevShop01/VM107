-- Phase 89 Wave 4 — macro_relationship_discovery agent
-- Creates:
--   macro_discovery_proposals  — shadow EdgeProposal records (Decision 8)
--   macro_discovery_throughput — weekly proposal counter for throughput governor (Decision 4)
--
-- Decision 8: governance_status defaults to 'shadow'.
--   Phase 53 governance UI promotes shadow → proposed → live via human review.
--   NO auto-promotion in Phase 89.
--
-- Pitfall 7: Neo4j edge is the authoritative record.
--   Postgres row is the secondary record; unique constraint on
--   (from_node, to_node, edge_type, period_start, period_end) enforces idempotency
--   on reconciliation retry.
--
-- Rollback: See ROLLBACK section at bottom.


-- ─── Forward ──────────────────────────────────────────────────────────────────

BEGIN;

CREATE TABLE macro_discovery_proposals (
    proposal_id              UUID PRIMARY KEY,
    from_node                TEXT NOT NULL,
    to_node                  TEXT NOT NULL,
    edge_type                TEXT NOT NULL,                -- 'leads_by_months' | 'correlated_with'
    sample_size              INT  NOT NULL,
    period_start             DATE NOT NULL,
    period_end               DATE NOT NULL,
    correlation              FLOAT NOT NULL,
    lag_months               FLOAT,                       -- NULL when edge_type = 'correlated_with'
    p_value                  FLOAT NOT NULL,
    confidence               FLOAT NOT NULL,
    evidence_releases        JSONB NOT NULL DEFAULT '[]',  -- Phase 71 CitationRef list
    governance_status        TEXT NOT NULL
                             CHECK (governance_status IN ('shadow','proposed','live','rejected'))
                             DEFAULT 'shadow',
    proposed_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    governance_review_due_at TIMESTAMPTZ NOT NULL,         -- proposed_at + 30 days (Decision 8)
    promoted_at              TIMESTAMPTZ,                  -- set by Phase 53 governance UI
    reviewer_user_id         INT,                          -- set by Phase 53 governance UI

    -- Idempotency constraint — Pitfall 7 reconciliation retry safe
    UNIQUE (from_node, to_node, edge_type, period_start, period_end)
);

COMMENT ON TABLE macro_discovery_proposals IS
    'Phase 89 Wave 4 — shadow EdgeProposal records from macro_relationship_discovery '
    'nightly scan. All rows enter governance at status=shadow (Decision 8). '
    'Neo4j is the authoritative record per Pitfall 7; this table is the secondary '
    'read-optimised store for Phase 53 governance UI.';

-- Governance UI queries: pending review, overdue shadow, status filter
CREATE INDEX idx_discovery_proposals_governance
    ON macro_discovery_proposals (governance_status, governance_review_due_at);

-- Chronological query (most recent proposals first)
CREATE INDEX idx_discovery_proposals_proposed_at
    ON macro_discovery_proposals (proposed_at DESC);

-- Node-pair queries (counterfactual engine, investigator, contradiction detector)
CREATE INDEX idx_discovery_proposals_from_node
    ON macro_discovery_proposals (from_node, to_node, governance_status);


-- ─── Throughput governor counter (Decision 4) ─────────────────────────────────

CREATE TABLE macro_discovery_throughput (
    week_start_iso       DATE PRIMARY KEY,   -- ISO date of Monday that starts the week
    proposal_count       INT  NOT NULL DEFAULT 0,
    threshold_action     TEXT,               -- 'ok' | 'warned_low' | 'tightened'
    threshold_action_at  TIMESTAMPTZ,
    r_min_applied        FLOAT,              -- r_min used for this week's scan
    r_min_previous       FLOAT               -- r_min before any tightening
);

COMMENT ON TABLE macro_discovery_throughput IS
    'Phase 89 Wave 4 — weekly proposal throughput counter for the throughput governor. '
    'Decision 4: <1/week → warned_low; >10/week → tightened (r_min += 0.05). '
    'Counters reset weekly via upsert on week_start_iso.';


COMMIT;


-- ─── Rollback ─────────────────────────────────────────────────────────────────
-- To roll back this migration:
--
-- BEGIN;
-- DROP TABLE IF EXISTS macro_discovery_throughput;
-- DROP TABLE IF EXISTS macro_discovery_proposals;
-- COMMIT;
