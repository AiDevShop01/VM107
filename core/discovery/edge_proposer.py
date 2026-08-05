"""Phase 89 Wave 4 — EdgeProposer: atomic Neo4j-first write + governance.

Builds EdgeProposal contracts from CandidateEdge dicts and writes them via the
atomic Pitfall 7 write order:
  1. Neo4j shadow edge FIRST (authoritative record)
  2. Postgres proposal row SECOND (on Neo4j success only)
  3. On Postgres failure: log reconciliation warning + retry up to 3×; proposal_id
     unique constraint enforces idempotency on retry.

Decision 8 lock: ALL proposals enter governance with status='shadow' and a 30-day
review window. No Phase 89 code path sets status to anything other than 'shadow'.

Decision 13: emits alert_candidate_created to Phase 91 UAE via the SHARED helper
from Plan 03 (core.alerts.phase91_emit.emit_alert_candidate). NOT redefined here.

Per project lock: DISCOVERY_POSTGRES_URL from env — NO fallback default.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

import psycopg2

# SHARED Phase 89↔Phase 91 helper — Plan 03 ships this (never redefine locally)
from core.alerts.phase91_emit import emit_alert_candidate
from emitters.source_health_registry import SourceHealthRegistry

logger = logging.getLogger(__name__)

# ─── Typed exception (Pitfall 7) ─────────────────────────────────────────────


class Neo4jWriteError(RuntimeError):
    """Raised when the Neo4j shadow edge write fails.

    Pitfall 7: on Neo4j failure → Postgres is NOT written.
    The caller must handle this exception and NOT proceed with downstream writes.
    """


# ─── EdgeProposal contract ───────────────────────────────────────────────────


@dataclass
class EdgeProposal:
    """Immutable proposal artifact produced by EdgeProposer.propose().

    Governance contract (Decision 8):
      - governance_status ALWAYS 'shadow' in Phase 89.
      - governance_review_due_at = proposed_at + 30 days.
      - Promotion to 'proposed' / 'live' requires human review via Phase 53 UI.
    """

    proposal_id: UUID
    from_node: str
    to_node: str
    edge_type: Literal["leads_by_months", "correlated_with"]
    sample_size: int
    period_start: str
    period_end: str
    correlation: float
    lag_months: float | None
    p_value: float
    confidence: float
    evidence_releases: list[str]
    governance_status: Literal["shadow"] = "shadow"       # Decision 8 — NEVER auto-promoted
    proposed_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    governance_review_due_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


# ─── EdgeProposer ─────────────────────────────────────────────────────────────


class EdgeProposer:
    """Proposes new Neo4j edges from surviving CandidateEdge dicts.

    Write order (Pitfall 7):
      1. neo4j_writer.propose_edge(...) — MUST succeed first
      2. Postgres INSERT into macro_discovery_proposals — on success only

    Env var required:
      DISCOVERY_POSTGRES_URL — no fallback default (fail-fast per project lock)

    Args:
        neo4j_writer: Object with propose_edge(**kwargs) → str (neo4j edge uuid).
                      Typically an instance of services.neo4j_edge_proposal_writer
                      or the Neo4jMacroGraphDouble test double.
        shadow_window_days: Number of days until governance review (default 30).
                            Matches Decision 8 / agent profile YAML.
        max_pg_retries: Max Postgres write retries on transient failure (default 3).
    """

    _SHADOW_WINDOW_DAYS = 30  # Decision 8

    def __init__(
        self,
        neo4j_writer: Any,
        shadow_window_days: int = _SHADOW_WINDOW_DAYS,
        max_pg_retries: int = 3,
    ) -> None:
        self._neo4j_writer = neo4j_writer
        self._shadow_window_days = shadow_window_days
        self._max_pg_retries = max_pg_retries

    def propose(self, candidate: dict) -> EdgeProposal:
        """Build an EdgeProposal from a CandidateEdge dict and persist it.

        Pitfall 7 write order enforced:
          1. Neo4j shadow edge (authoritative) — raises Neo4jWriteError on failure.
          2. Postgres proposal row — retried up to max_pg_retries on failure.
          3. Phase 91 alert emit (via shared helper).

        Args:
            candidate: CandidateEdge dict from CorrelationScanner.scan().

        Returns:
            EdgeProposal on success.

        Raises:
            Neo4jWriteError: if Neo4j write fails (Postgres NOT written).
        """
        proposal_id = uuid4()
        now = datetime.now(tz=timezone.utc)
        review_due = now + timedelta(days=self._shadow_window_days)

        from_node = candidate["from_node"]
        to_node = candidate["to_node"]
        lag_months = candidate.get("lag_months")
        correlation = candidate["correlation"]
        p_value = candidate["p_value"]
        sample_size = candidate["sample_size"]
        period_start = candidate.get("period_start", "")
        period_end = candidate.get("period_end", "")
        evidence_release_ids = candidate.get("evidence_release_ids", [])

        # Determine edge_type from lag_months (Decision 4)
        edge_type: str
        stored_lag: float | None
        if lag_months is not None and abs(lag_months) >= 0.5:
            edge_type = "leads_by_months"
            stored_lag = lag_months
        else:
            edge_type = "correlated_with"
            stored_lag = None

        # Confidence heuristic based on |r| and sample size
        confidence = min(abs(correlation) + min(sample_size / 200.0, 0.30), 1.0)

        # Build CitationRef list (Phase 71 — evidence_release_ids already provided)
        evidence_releases = list(evidence_release_ids)
        if not evidence_releases:
            # Synthesize a minimal citation from node pair + period
            evidence_releases = [f"release:{from_node}-{to_node}-{period_end}"]

        # ── Step 1: Neo4j FIRST (Pitfall 7) ──────────────────────────────────
        try:
            self._neo4j_writer.propose_edge(
                from_node=from_node,
                to_node=to_node,
                edge_type=edge_type,
                strength=correlation,
                confidence=confidence,
                edge_lifecycle_state="shadow",  # Decision 8
                proposal_id=str(proposal_id),
            )
            logger.info({
                "event": "phase89_neo4j_shadow_edge_written",
                "proposal_id": str(proposal_id),
                "from_node": from_node,
                "to_node": to_node,
            })
        except Exception as exc:
            logger.error({
                "event": "phase89_neo4j_write_failed",
                "proposal_id": str(proposal_id),
                "from_node": from_node,
                "to_node": to_node,
                "error": str(exc),
            })
            # Pitfall 7: on Neo4j failure → do NOT write Postgres
            raise Neo4jWriteError(
                f"Neo4j shadow edge write failed for {from_node}->{to_node}: {exc}"
            ) from exc

        # ── Step 2: Postgres (after Neo4j success) ────────────────────────────
        pg_url = os.environ.get("DISCOVERY_POSTGRES_URL")
        if not pg_url:
            raise RuntimeError(
                "Required env var 'DISCOVERY_POSTGRES_URL' not set — "
                "fail-fast per project env-driven config lock."
            )

        self._write_to_postgres(
            proposal_id=proposal_id,
            from_node=from_node,
            to_node=to_node,
            edge_type=edge_type,
            sample_size=sample_size,
            period_start=period_start,
            period_end=period_end,
            correlation=correlation,
            lag_months=stored_lag,
            p_value=p_value,
            confidence=confidence,
            evidence_releases=evidence_releases,
            proposed_at=now,
            governance_review_due_at=review_due,
            pg_url=pg_url,
        )

        # ── Step 3: Build proposal artifact ──────────────────────────────────
        proposal = EdgeProposal(
            proposal_id=proposal_id,
            from_node=from_node,
            to_node=to_node,
            edge_type=edge_type,          # type: ignore[arg-type]
            sample_size=sample_size,
            period_start=period_start,
            period_end=period_end,
            correlation=correlation,
            lag_months=stored_lag,
            p_value=p_value,
            confidence=confidence,
            evidence_releases=evidence_releases,
            governance_status="shadow",   # Decision 8 — NEVER auto-promoted
            proposed_at=now,
            governance_review_due_at=review_due,
        )

        # ── Step 4: Phase 91 alert emit (Decision 13) ─────────────────────────
        # Uses the SHARED helper from Plan 03 — imported at top of this module.
        # b13_internal_severity=None for discovery → defaults to "Info".
        narrative = (
            f"New macro relationship proposed: {from_node} → {to_node} "
            f"({edge_type}, r={correlation:.3f}, n={sample_size}, p={p_value:.4f})"
        )
        emit_alert_candidate(
            alert_type="discovery",
            producer_agent_id="vm107.macro_relationship_discovery",
            subject_id=f"{from_node}->{to_node}",
            b13_internal_severity=None,   # discovery has no B13 severity → "Info"
            explanation=narrative,
            citations=evidence_releases,
            proposal_id=proposal_id,
        )

        logger.info({
            "event": "phase89_proposal_written",
            "proposal_id": str(proposal_id),
            "from_node": from_node,
            "to_node": to_node,
            "edge_type": edge_type,
            "governance_status": "shadow",
        })
        return proposal

    def _write_to_postgres(
        self,
        *,
        proposal_id: UUID,
        from_node: str,
        to_node: str,
        edge_type: str,
        sample_size: int,
        period_start: str,
        period_end: str,
        correlation: float,
        lag_months: float | None,
        p_value: float,
        confidence: float,
        evidence_releases: list[str],
        proposed_at: datetime,
        governance_review_due_at: datetime,
        pg_url: str,
    ) -> None:
        """Write proposal row to Postgres with retry and idempotency.

        On unique constraint violation (proposal already exists) → skip silently.
        On other errors → retry up to max_pg_retries; log reconciliation warning.
        """
        import json

        sql = """
            INSERT INTO macro_discovery_proposals (
                proposal_id, from_node, to_node, edge_type, sample_size,
                period_start, period_end, correlation, lag_months, p_value,
                confidence, evidence_releases, governance_status,
                proposed_at, governance_review_due_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s
            )
            ON CONFLICT (from_node, to_node, edge_type, period_start, period_end)
            DO NOTHING
        """
        params = (
            str(proposal_id),
            from_node,
            to_node,
            edge_type,
            sample_size,
            period_start,
            period_end,
            correlation,
            lag_months,
            p_value,
            confidence,
            json.dumps(evidence_releases),
            "shadow",  # Decision 8 — always shadow
            proposed_at,
            governance_review_due_at,
        )

        last_exc: Exception | None = None
        for attempt in range(1, self._max_pg_retries + 1):
            # WR-05: init before the try so the finally can close it even when the
            # statement (not the connect) fails — otherwise a cur.execute/commit error
            # orphans the open connection and the next iteration rebinds conn, leaking
            # up to _max_pg_retries connections per call. Mirrors throughput_governor.
            conn = None
            try:
                # connect_timeout bounds the psycopg2 connect so a down Postgres
                # fast-fails within budget instead of hanging (SC-1). Env-driven
                # resilience default, not a target/credential fallback (D-05/D-06).
                conn = psycopg2.connect(
                    pg_url,
                    connect_timeout=int(os.getenv("A0_PG_CONNECT_TIMEOUT", "5")),
                )
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                conn.commit()
                SourceHealthRegistry.get_shared_instance().report(
                    "postgres", available=True
                )
                logger.info({
                    "event": "phase89_proposal_postgres_written",
                    "proposal_id": str(proposal_id),
                    "attempt": attempt,
                })
                return
            except Exception as exc:
                last_exc = exc
                # Report guard matches this module's existing swallow-and-retry
                # idiom (D-07) — no secrets in failure_reason.
                SourceHealthRegistry.get_shared_instance().report(
                    "postgres", available=False, failure_reason=type(exc).__name__
                )
                logger.warning({
                    "event": "phase89_proposal_postgres_reconciliation_warning",
                    "proposal_id": str(proposal_id),
                    "attempt": attempt,
                    "error": str(exc),
                    "note": (
                        "Neo4j edge is authoritative. "
                        "Postgres write will be retried or picked up by reconciliation job."
                    ),
                })
            finally:
                # WR-05: always close the connection (success, statement failure, or
                # connect failure where conn stays None).
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:  # noqa: BLE001 — close must never mask the real error
                        pass

        # Exhausted retries — surface to DLQ / monitoring
        logger.error({
            "event": "phase89_proposal_postgres_write_exhausted",
            "proposal_id": str(proposal_id),
            "max_retries": self._max_pg_retries,
            "last_error": str(last_exc),
        })
