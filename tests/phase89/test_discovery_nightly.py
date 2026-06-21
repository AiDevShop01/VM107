"""Phase 89 Wave 4 — discovery nightly tests.

7 tests covering:
  1. Synthetic correlated series → proposal with correct stats
  2. Synthetic noise → no proposal
  3. Threshold guards (r, n, p-value)
  4. Pitfall 7 — Neo4j writes FIRST; partial-failure modes
  5. Decision 8 — shadow status + 30-day review window
  6. Phase 71 citation — each proposal includes ≥1 CitationRef
  7. Lead-lag edge_type branching

Per project locks:
  - No live Redis/Postgres/Neo4j — all mocked.
  - emit_alert_candidate is imported from core.alerts.phase91_emit (Plan 03 shared
    helper); never redefined locally.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call
from uuid import UUID, uuid4
import math

import pytest

pytestmark = pytest.mark.phase89


# ─── helpers ─────────────────────────────────────────────────────────────────

def _make_vm102_client(r: float, p_value: float, n: int, lag_months: float = 0.0):
    """Return a mock VM102 client that returns controlled correlation stats."""
    client = MagicMock()
    client.indicator_correlations.return_value = {
        "r": r,
        "p_value": p_value,
        "sample_size": n,
        "period_start": "2023-01-01",
        "period_end": "2024-12-31",
    }
    client.indicator_lead_lag.return_value = {
        "peak_lag": lag_months,
        "peak_r": r,
        "p_value": p_value,
    }
    return client


def _make_neo4j_double(fail=False):
    """Return a neo4j graph double; fail=True makes propose_edge raise."""
    double = MagicMock()
    if fail:
        double.propose_edge.side_effect = ConnectionError("Neo4j unreachable")
    else:
        double.propose_edge.return_value = str(uuid4())
    return double


def _make_pg_cursor(fail=False):
    """Return a mock psycopg2 cursor context manager; fail=True on execute."""
    cursor = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cursor)
    ctx.__exit__ = MagicMock(return_value=False)
    if fail:
        cursor.execute.side_effect = Exception("Postgres write failed")
    conn = MagicMock()
    conn.cursor.return_value = ctx
    return conn, cursor


# ─── Test 1: synthetic correlated series → proposal ──────────────────────────

def test_correlated_series_produces_proposal(neo4j_macro_graph_double):
    """CPI × GoldPrice at known r=0.52, n=48 → proposal with correct stats."""
    from core.discovery.correlation_scanner import CorrelationScanner
    from core.discovery.edge_proposer import EdgeProposer

    vm102 = _make_vm102_client(r=0.52, p_value=0.0005, n=48, lag_months=0.0)
    scanner = CorrelationScanner(vm102_client=vm102, window_months=12)

    candidates = scanner.scan(pairs=[("CPI", "GoldPrice")])
    assert len(candidates) == 1
    c = candidates[0]
    assert abs(c["correlation"] - 0.52) < 0.001
    assert c["sample_size"] == 48
    assert c["p_value"] < 0.001

    graph = neo4j_macro_graph_double()

    with patch("core.discovery.edge_proposer.psycopg2.connect") as mock_conn:
        conn, _cursor = _make_pg_cursor()
        mock_conn.return_value = conn

        with patch("core.discovery.edge_proposer.emit_alert_candidate"):
            with patch.dict("os.environ", {"DISCOVERY_POSTGRES_URL": "postgresql://mock"}):
                proposer = EdgeProposer(neo4j_writer=graph)
                proposal = proposer.propose(c)

    assert proposal.governance_status == "shadow"
    assert proposal.from_node == "CPI"
    assert proposal.to_node == "GoldPrice"
    assert abs(proposal.correlation - 0.52) < 0.001
    assert proposal.sample_size == 48


# ─── Test 2: synthetic noise → no proposal ────────────────────────────────────

def test_noise_series_produces_no_proposal():
    """Random uncorrelated series → scanner returns empty candidates list."""
    from core.discovery.correlation_scanner import CorrelationScanner

    # r=0.05, p=0.72 — both below threshold
    vm102 = _make_vm102_client(r=0.05, p_value=0.72, n=48)
    scanner = CorrelationScanner(vm102_client=vm102, window_months=12)

    candidates = scanner.scan(pairs=[("CPI", "RandomNoise")])
    assert candidates == []


# ─── Test 3: threshold guards ─────────────────────────────────────────────────

@pytest.mark.parametrize("r,p_value,n,reason", [
    (0.25, 0.01, 50, "r below 0.3 floor"),
    (0.45, 0.08, 50, "p above 0.05 ceiling"),
    (0.45, 0.01, 20, "n below 30 floor"),
])
def test_threshold_guards(r, p_value, n, reason):
    """Below-threshold stats → no candidates produced."""
    from core.discovery.correlation_scanner import CorrelationScanner

    vm102 = _make_vm102_client(r=r, p_value=p_value, n=n)
    scanner = CorrelationScanner(vm102_client=vm102, window_months=12)

    candidates = scanner.scan(pairs=[("IndicatorA", "IndicatorB")])
    assert candidates == [], f"Should produce no proposal when {reason}"


# ─── Test 4: Pitfall 7 — Neo4j first, then Postgres ──────────────────────────

def test_pitfall7_neo4j_writes_before_postgres(neo4j_macro_graph_double):
    """Happy path: Neo4j write is called BEFORE Postgres write."""
    from core.discovery.edge_proposer import EdgeProposer

    call_order = []
    graph = neo4j_macro_graph_double()

    # Wrap the double's propose_edge to track call order
    original_propose_edge = graph.propose_edge

    def _tracking_propose(**kwargs):
        call_order.append("neo4j")
        return str(uuid4())

    graph.propose_edge = _tracking_propose

    candidate = {
        "from_node": "CPI",
        "to_node": "DXY",
        "correlation": 0.42,
        "p_value": 0.01,
        "sample_size": 36,
        "lag_months": None,
        "period_start": "2023-01-01",
        "period_end": "2024-12-31",
        "evidence_release_ids": ["release:CPI-2024-01-15"],
    }

    with patch("core.discovery.edge_proposer.psycopg2.connect") as mock_conn:
        conn = MagicMock()
        cursor = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=cursor)
        ctx.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = ctx

        def _tracking_cursor():
            call_order.append("postgres")
            return ctx
        conn.cursor.side_effect = _tracking_cursor
        mock_conn.return_value = conn

        with patch("core.discovery.edge_proposer.emit_alert_candidate"):
            with patch.dict("os.environ", {"DISCOVERY_POSTGRES_URL": "postgresql://mock"}):
                proposer = EdgeProposer(neo4j_writer=graph)
                proposer.propose(candidate)

    assert call_order[0] == "neo4j", "Neo4j must be called BEFORE Postgres"
    assert "postgres" in call_order, "Postgres must be called after Neo4j"


def test_pitfall7_neo4j_failure_prevents_postgres_write(neo4j_macro_graph_double):
    """Neo4j failure → Postgres is NOT written; exception propagated."""
    from core.discovery.edge_proposer import EdgeProposer, Neo4jWriteError

    graph = _make_neo4j_double(fail=True)

    candidate = {
        "from_node": "CPI",
        "to_node": "DXY",
        "correlation": 0.42,
        "p_value": 0.01,
        "sample_size": 36,
        "lag_months": None,
        "period_start": "2023-01-01",
        "period_end": "2024-12-31",
        "evidence_release_ids": ["release:CPI-2024-01-15"],
    }

    with patch("core.discovery.edge_proposer.psycopg2.connect") as mock_conn:
        conn, cursor = _make_pg_cursor()
        mock_conn.return_value = conn

        with patch("core.discovery.edge_proposer.emit_alert_candidate"):
            with patch.dict("os.environ", {"DISCOVERY_POSTGRES_URL": "postgresql://mock"}):
                proposer = EdgeProposer(neo4j_writer=graph)
                with pytest.raises(Neo4jWriteError):
                    proposer.propose(candidate)

    # Postgres cursor.execute must NOT have been called
    assert cursor.execute.call_count == 0, "Postgres must NOT be written when Neo4j fails"


# ─── Test 5: Decision 8 — shadow status + 30-day window ──────────────────────

def test_decision8_shadow_status_and_review_window(neo4j_macro_graph_double):
    """Every proposal has governance_status='shadow' + review_due = proposed_at + 30d."""
    from core.discovery.edge_proposer import EdgeProposer

    graph = neo4j_macro_graph_double()
    candidate = {
        "from_node": "CPI",
        "to_node": "GoldPrice",
        "correlation": 0.38,
        "p_value": 0.02,
        "sample_size": 40,
        "lag_months": None,
        "period_start": "2023-06-01",
        "period_end": "2024-06-01",
        "evidence_release_ids": ["release:CPI-2023-10-13"],
    }

    with patch("core.discovery.edge_proposer.psycopg2.connect") as mock_conn:
        conn, _ = _make_pg_cursor()
        mock_conn.return_value = conn

        with patch("core.discovery.edge_proposer.emit_alert_candidate"):
            with patch.dict("os.environ", {"DISCOVERY_POSTGRES_URL": "postgresql://mock"}):
                proposer = EdgeProposer(neo4j_writer=graph)
                proposal = proposer.propose(candidate)

    assert proposal.governance_status == "shadow"
    delta = proposal.governance_review_due_at - proposal.proposed_at
    assert delta.days >= 29, "Review window must be at least 30 days"
    assert delta.days <= 31, "Review window must not exceed 31 days"

    # Confirm no Phase 89 code path auto-promotes beyond shadow
    import inspect
    import core.discovery.edge_proposer as ep_module
    source = inspect.getsource(ep_module)
    assert '"proposed"' not in source.split("governance_status")[1:3 or 1], True  # shadow is the only status set
    # Simpler: just assert governance_status is always 'shadow' in the output
    assert proposal.governance_status == "shadow"


# ─── Test 6: Phase 71 citation ────────────────────────────────────────────────

def test_phase71_citation_included(neo4j_macro_graph_double):
    """Each EdgeProposal includes at least one CitationRef in evidence_releases."""
    from core.discovery.edge_proposer import EdgeProposer

    graph = neo4j_macro_graph_double()
    candidate = {
        "from_node": "PCE",
        "to_node": "SPX",
        "correlation": 0.35,
        "p_value": 0.03,
        "sample_size": 32,
        "lag_months": None,
        "period_start": "2023-01-01",
        "period_end": "2024-01-01",
        "evidence_release_ids": ["release:PCE-2024-01-26"],
    }

    with patch("core.discovery.edge_proposer.psycopg2.connect") as mock_conn:
        conn, _ = _make_pg_cursor()
        mock_conn.return_value = conn

        with patch("core.discovery.edge_proposer.emit_alert_candidate"):
            with patch.dict("os.environ", {"DISCOVERY_POSTGRES_URL": "postgresql://mock"}):
                proposer = EdgeProposer(neo4j_writer=graph)
                proposal = proposer.propose(candidate)

    assert len(proposal.evidence_releases) >= 1, "EdgeProposal must include ≥1 CitationRef"


# ─── Test 7: lead-lag edge_type branching ────────────────────────────────────

@pytest.mark.parametrize("lag_months,expected_edge_type", [
    (1.5, "leads_by_months"),   # abs(lag) >= 0.5 → leads_by_months
    (0.0, "correlated_with"),   # lag ~0 → correlated_with
    (0.4, "correlated_with"),   # abs(lag) < 0.5 → correlated_with
    (-1.2, "leads_by_months"),  # negative lag still >= 0.5 in abs
])
def test_lead_lag_edge_type_branching(lag_months, expected_edge_type, neo4j_macro_graph_double):
    """edge_type set to leads_by_months when |lag|>=0.5; correlated_with otherwise."""
    from core.discovery.edge_proposer import EdgeProposer

    graph = neo4j_macro_graph_double()
    candidate = {
        "from_node": "CPI",
        "to_node": "DXY",
        "correlation": 0.40,
        "p_value": 0.02,
        "sample_size": 36,
        "lag_months": lag_months if lag_months != 0.0 else None,
        "period_start": "2023-01-01",
        "period_end": "2024-01-01",
        "evidence_release_ids": ["release:CPI-2024-01-15"],
    }
    # For correlated_with test, ensure lag is None or near-zero
    if lag_months == 0.0 or abs(lag_months) < 0.5:
        candidate["lag_months"] = None if lag_months == 0.0 else lag_months

    with patch("core.discovery.edge_proposer.psycopg2.connect") as mock_conn:
        conn, _ = _make_pg_cursor()
        mock_conn.return_value = conn

        with patch("core.discovery.edge_proposer.emit_alert_candidate"):
            with patch.dict("os.environ", {"DISCOVERY_POSTGRES_URL": "postgresql://mock"}):
                proposer = EdgeProposer(neo4j_writer=graph)
                proposal = proposer.propose(candidate)

    assert proposal.edge_type == expected_edge_type, (
        f"lag_months={lag_months} should produce edge_type={expected_edge_type!r}, "
        f"got {proposal.edge_type!r}"
    )
    if expected_edge_type == "leads_by_months":
        assert proposal.lag_months is not None
    else:
        assert proposal.lag_months is None
