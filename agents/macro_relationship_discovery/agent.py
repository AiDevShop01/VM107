"""Phase 89.2 — MacroRelationshipDiscovery scheduled background agent.

Orchestrates the VM107/core/discovery library
(:class:`core.discovery.correlation_scanner.CorrelationScanner` +
:class:`core.discovery.edge_proposer.EdgeProposer` +
:class:`core.discovery.throughput_governor.ThroughputGovernor` +
:class:`services.neo4j_edge_proposal_writer.Neo4jEdgeProposalWriter`)
into a single :meth:`MacroRelationshipDiscovery.run` call.

Invocation contract (REQ-89.2-1 — Plan 89.2-03):

    >>> MacroRelationshipDiscovery().run(message="nightly", run_mode="scheduled")
    {"proposals_created": 7, "scan_duration_s": 12.3, "throughput_action": "ok"}

Response keys are EXACT — Dagster's macro_discovery_nightly asset
(Phase 89-04) hardcodes these names; extras / missing keys break the asset.

Locked design constraints (89.2-RESEARCH.md):

- Agent reads tightened ``r_min_applied`` from
  ``macro_discovery_throughput`` on startup so a previous week's
  ``tighten_thresholds()`` call persists across nightly runs (closes Open
  Question 3).
- All env vars (``DISCOVERY_POSTGRES_URL``, ``NEO4J_URI``, ``VM102_API_URL``,
  ``VM102_SERVICE_JWT``) are read fail-fast at :meth:`run` invocation, NEVER
  at module import time (env-driven-no-fallbacks lock; matches sibling
  ``agents/macro_historical_analyst/agent.py`` pattern).
- Per-candidate exceptions are caught + logged so one bad pair cannot abort
  the whole nightly scan (RESEARCH §Execution Resilience).
- Pitfall 7 (Neo4j-first write order) is enforced by :class:`EdgeProposer`
  itself — the agent only orchestrates; it does NOT re-implement the write
  order locally.
- Decision 8 (governance_status='shadow' on all proposals) is enforced by
  :class:`EdgeProposer` — agent does NOT set status here.
- Decision 4 (≥1 / ≤10 proposals per week thresholds) is enforced by
  :class:`ThroughputGovernor.evaluate_threshold` — agent only relays the
  governor's verdict back through the response dict.

The class is structured so unit tests can patch
``Vm102DiscoveryClient`` / ``CorrelationScanner`` / ``EdgeProposer`` /
``Neo4jEdgeProposalWriter`` / ``ThroughputGovernor`` / ``psycopg2`` on
this module's namespace and exercise the orchestration logic without any
real HTTP, Postgres, or Neo4j calls.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import psycopg2

from agents.macro_relationship_discovery.scan_pairs import DEFAULT_SCAN_PAIRS
from agents.macro_relationship_discovery.vm102_discovery_client import (
    Vm102DiscoveryClient,
)
from core.discovery.correlation_scanner import CorrelationScanner
from core.discovery.edge_proposer import EdgeProposer
from core.discovery.throughput_governor import ThroughputGovernor
from services.neo4j_edge_proposal_writer import Neo4jEdgeProposalWriter

logger = logging.getLogger(__name__)

# Default r_min when ``macro_discovery_throughput`` has no row yet
# (matches :data:`core.discovery.throughput_governor.DEFAULT_R_MIN`).
_DEFAULT_R_MIN: float = 0.30


def _required_env(key: str) -> str:
    """Return ``os.environ[key]`` — KeyError on missing (fail-fast)."""
    return os.environ[key]


def _read_tightened_r_min(pg_url: str) -> float:
    """Read the persisted tightened r_min from ``macro_discovery_throughput``.

    Closes RESEARCH Open Question 3: a previous week's
    ``tighten_thresholds()`` call writes ``r_min_applied`` to the throughput
    table; we honour that on startup so the floor stays tight across runs.

    Returns ``_DEFAULT_R_MIN`` (0.30) on empty table or NULL value.
    """
    sql = (
        "SELECT MAX(r_min_applied) FROM macro_discovery_throughput "
        "WHERE r_min_applied IS NOT NULL"
    )
    conn = psycopg2.connect(pg_url)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None or row[0] is None:
        return _DEFAULT_R_MIN
    return float(row[0])


def _read_weekly_proposal_count(pg_url: str, fallback: int) -> int:
    """Read this week's ``proposal_count`` from ``macro_discovery_throughput``.

    Used to feed :meth:`ThroughputGovernor.evaluate_threshold` AFTER the
    scan loop. Falls back to ``fallback`` (typically the just-counted
    in-memory ``proposals_created``) when no row exists for this week.
    """
    sql = (
        "SELECT proposal_count FROM macro_discovery_throughput "
        "WHERE week_start_iso = date_trunc('week', now())::date"
    )
    conn = psycopg2.connect(pg_url)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None or row[0] is None:
        return fallback
    return int(row[0])


class MacroRelationshipDiscovery:
    """Phase 89.2 nightly macro relationship discovery agent.

    Invocation contract (the only public method):

        :meth:`run(message=..., run_mode=...) -> dict`
            Returns ``{proposals_created: int, scan_duration_s: float,
            throughput_action: str}`` — exact key set.

    Env vars (all fail-fast at :meth:`run` time):

      - ``DISCOVERY_POSTGRES_URL`` — Postgres URL hosting
        ``macro_discovery_proposals`` + ``macro_discovery_throughput``
        (consumed by :class:`EdgeProposer` and :class:`ThroughputGovernor`).
      - ``NEO4J_URI`` — Bolt URL for the macro graph
        (consumed by :class:`Neo4jEdgeProposalWriter` at ``__init__``).
      - ``VM102_API_URL`` — VM102 analytics base URL.
      - ``VM102_SERVICE_JWT`` — service JWT for VM102 auth.
    """

    agent_id: str = "vm107.macro_relationship_discovery"

    def run(
        self,
        message: str = "run nightly scan",
        run_mode: str = "scheduled",
    ) -> dict[str, Any]:
        """Execute one nightly discovery scan.

        Steps (per 89.2-RESEARCH.md §Missing 1 — VM107 Agent Module):

          1. Read persisted ``r_min_applied`` from
             ``macro_discovery_throughput`` (closes Open Q3).
          2. Construct :class:`Vm102DiscoveryClient` (fail-fast on
             ``VM102_API_URL`` / ``VM102_SERVICE_JWT``).
          3. Construct :class:`CorrelationScanner` with the tightened r_min.
          4. Construct :class:`Neo4jEdgeProposalWriter` (fail-fast on
             ``NEO4J_URI``) + :class:`EdgeProposer` wrapping it.
          5. Construct :class:`ThroughputGovernor` with the tightened r_min.
          6. Scan all pairs in :data:`DEFAULT_SCAN_PAIRS`.
          7. For each surviving candidate: propose via :class:`EdgeProposer`,
             record on :class:`ThroughputGovernor`. Per-candidate exceptions
             are swallowed + logged so one bad pair does not abort the run.
          8. Re-read this week's count from Postgres; evaluate threshold.
          9. If ``threshold_action == "tightened"``: call
             :meth:`ThroughputGovernor.tighten_thresholds` so next week's
             scan reads the tighter floor (closes Open Q3 on the
             persist side).
          10. Return the exact 3-key response dict.

        Args:
            message: Human-readable invocation reason (logged; not used in
                     orchestration).
            run_mode: ``"scheduled"`` (Dagster nightly), ``"manual"``
                     (operator-triggered), or other free-form tag (logged).

        Returns:
            ``{"proposals_created": int,
              "scan_duration_s": float,
              "throughput_action": str}``
        """
        t0 = time.time()
        logger.info(
            {
                "event": "phase89_discovery_run_start",
                "agent_id": self.agent_id,
                "message": message,
                "run_mode": run_mode,
            }
        )

        try:
            # 1. Fail-fast env reads (DISCOVERY_POSTGRES_URL is consumed
            #    immediately by step 1; the other env vars are consumed
            #    transitively by the constructors below).
            pg_url = _required_env("DISCOVERY_POSTGRES_URL")

            # 2. Pull persisted tightened r_min (Open Q3).
            tightened_r_min = _read_tightened_r_min(pg_url)
            logger.info(
                {
                    "event": "phase89_discovery_r_min_loaded",
                    "r_min_applied": tightened_r_min,
                }
            )

            # 3. Construct VM102 client (fail-fast on VM102 env vars).
            vm102_client = Vm102DiscoveryClient()

            # 4. Construct scanner with the tightened r_min — leave p_max,
            #    n_min, window_months at module defaults from
            #    core.discovery.correlation_scanner so future threshold
            #    tuning only touches one place.
            scanner = CorrelationScanner(
                vm102_client=vm102_client,
                r_min=tightened_r_min,
            )

            # 5. Neo4j writer (fail-fast on NEO4J_URI) → EdgeProposer.
            neo4j_writer = Neo4jEdgeProposalWriter()
            proposer = EdgeProposer(neo4j_writer=neo4j_writer)

            # 6. Governor reuses the same tightened floor; if it decides
            #    to tighten again this run, the post-step write to
            #    macro_discovery_throughput stays in lockstep.
            governor = ThroughputGovernor(base_r_min=tightened_r_min)

            # 7. Scan the fixed pair list (Phase 86 known relationships).
            candidates = scanner.scan(pairs=DEFAULT_SCAN_PAIRS)
            logger.info(
                {
                    "event": "phase89_discovery_candidates_found",
                    "candidates": len(candidates),
                    "pairs_scanned": len(DEFAULT_SCAN_PAIRS),
                }
            )

            # 8. Propose each surviving candidate; record on governor.
            #    EdgeProposer.propose returns an EdgeProposal dataclass; we
            #    pass its proposal_id (UUID) to the governor as a string.
            proposals_created = 0
            for candidate in candidates:
                try:
                    proposal = proposer.propose(candidate)
                    governor.record_proposal(str(proposal.proposal_id))
                    proposals_created += 1
                except Exception as exc:
                    # Per-candidate failure is non-fatal (RESEARCH
                    # §Execution Resilience) — log + continue.
                    logger.error(
                        {
                            "event": "phase89_discovery_candidate_failed",
                            "from_node": candidate.get("from_node"),
                            "to_node": candidate.get("to_node"),
                            "error": str(exc),
                        }
                    )

            # 9. Pull this week's authoritative count from Postgres so
            #    multiple runs in the same week aggregate correctly.
            weekly_count = _read_weekly_proposal_count(
                pg_url, fallback=proposals_created
            )
            throughput_action = governor.evaluate_threshold(weekly_count)

            # 10. Persist the tightened threshold if the governor wants it
            #     so next week's r_min read picks it up.
            if throughput_action == "tightened":
                governor.tighten_thresholds()

            scan_duration_s = float(time.time() - t0)

            response: dict[str, Any] = {
                "proposals_created": int(proposals_created),
                "scan_duration_s": scan_duration_s,
                "throughput_action": str(throughput_action),
            }
            logger.info(
                {
                    "event": "phase89_discovery_run_complete",
                    **response,
                }
            )
            return response

        except Exception as exc:
            # Surface a single structured log line and re-raise — the
            # Dagster nightly asset turns the raise into a run failure
            # (per RESEARCH §Failure Semantics).
            logger.exception(
                {
                    "event": "phase89_discovery_run_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            raise
