"""Phase 89.2 Plan 03 — MacroRelationshipDiscovery agent module tests (REQ-89.2-1).

Plan 01 shipped these as xfail stubs targeting
``agents.macro_relationship_discovery.agent``. Plan 03 lands the production
class and flips the stubs to real assertions covering:

  - Response dict shape (3 exact keys + types)
  - Vm102DiscoveryClient wiring (instantiated + scanner called with
    DEFAULT_SCAN_PAIRS)
  - throughput_action enum (one of {ok, warned_low, tightened}) +
    tighten_thresholds() side-effect when governor returns "tightened"

Per project locks:
  - No live VM102 / Postgres / Neo4j — every dependency is patched on the
    agent module's namespace via ``unittest.mock.patch``.
  - Env vars are set via ``monkeypatch.setenv`` so the agent's fail-fast
    ``os.environ[...]`` reads succeed against sentinel values; nothing real
    is dialled.
  - Tests run in < 2s and require no external services.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.phase89


# ─── Shared test scaffolding ──────────────────────────────────────────────────


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set all four env vars the agent reads fail-fast at .run() time."""
    monkeypatch.setenv(
        "DISCOVERY_POSTGRES_URL",
        "postgresql://test:test@localhost:5432/test_discovery",
    )
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("VM102_API_URL", "http://localhost:8002")
    monkeypatch.setenv("VM102_SERVICE_JWT", "test-jwt-sentinel")


def _make_candidate(from_node: str = "CPIAUCSL", to_node: str = "gold") -> dict:
    """Build a minimal CandidateEdge dict matching CorrelationScanner output."""
    return {
        "from_node": from_node,
        "to_node": to_node,
        "correlation": 0.45,
        "p_value": 0.01,
        "sample_size": 48,
        "lag_months": None,
        "period_start": "2023-01-01",
        "period_end": "2024-12-31",
        "evidence_release_ids": [f"release:{from_node}-2024-12-31"],
    }


def _patch_agent_dependencies(
    *,
    scanner_candidates: list[dict],
    governor_action: str = "ok",
):
    """Return a context manager that patches every external dependency the
    agent touches inside .run(): the four orchestrator classes, the
    Vm102DiscoveryClient, and the two psycopg2.connect calls (r_min read +
    weekly_count read).

    Returns the ``patch.multiple`` mock dict + the mocked governor instance
    so individual tests can assert side-effects on them.
    """
    from agents.macro_relationship_discovery import agent as agent_mod

    # Build stubbed instances first so individual tests can wire return values.
    mock_vm102_client_cls = MagicMock(name="Vm102DiscoveryClient")
    mock_vm102_client_instance = MagicMock(name="vm102_client_instance")
    mock_vm102_client_cls.return_value = mock_vm102_client_instance

    mock_scanner_cls = MagicMock(name="CorrelationScanner")
    mock_scanner_instance = MagicMock(name="scanner_instance")
    mock_scanner_instance.scan.return_value = list(scanner_candidates)
    mock_scanner_cls.return_value = mock_scanner_instance

    mock_neo4j_writer_cls = MagicMock(name="Neo4jEdgeProposalWriter")
    mock_neo4j_writer_instance = MagicMock(name="neo4j_writer_instance")
    mock_neo4j_writer_cls.return_value = mock_neo4j_writer_instance

    mock_proposer_cls = MagicMock(name="EdgeProposer")
    mock_proposer_instance = MagicMock(name="proposer_instance")
    # EdgeProposer.propose returns an EdgeProposal dataclass — mimic with a
    # MagicMock that has a proposal_id attribute (the agent str()s it).
    def _propose_side_effect(_candidate: dict):
        ep = MagicMock(name="edge_proposal")
        ep.proposal_id = uuid4()
        return ep

    mock_proposer_instance.propose.side_effect = _propose_side_effect
    mock_proposer_cls.return_value = mock_proposer_instance

    mock_governor_cls = MagicMock(name="ThroughputGovernor")
    mock_governor_instance = MagicMock(name="governor_instance")
    mock_governor_instance.evaluate_threshold.return_value = governor_action
    mock_governor_cls.return_value = mock_governor_instance

    # Stub psycopg2.connect on the agent module's namespace so the
    # _read_tightened_r_min + _read_weekly_proposal_count helpers do not
    # dial Postgres. Both helpers do: connect() → cursor() → execute() →
    # fetchone() → close(); the connection is a context manager via
    # ``with conn.cursor() as cur``.
    mock_psycopg2 = MagicMock(name="psycopg2")
    mock_conn = MagicMock(name="pg_conn")
    mock_cursor = MagicMock(name="pg_cursor")
    # First fetchone() (r_min read) → None means "no rows", agent defaults
    # to 0.30; second fetchone() (weekly_count) → None means "use fallback
    # (in-memory proposals_created)".
    mock_cursor.fetchone.return_value = None
    # ``with conn.cursor() as cur`` → cursor must support __enter__/__exit__.
    mock_cursor_ctx = MagicMock()
    mock_cursor_ctx.__enter__.return_value = mock_cursor
    mock_cursor_ctx.__exit__.return_value = False
    mock_conn.cursor.return_value = mock_cursor_ctx
    mock_psycopg2.connect.return_value = mock_conn

    return (
        agent_mod,
        patch.multiple(
            agent_mod,
            Vm102DiscoveryClient=mock_vm102_client_cls,
            CorrelationScanner=mock_scanner_cls,
            Neo4jEdgeProposalWriter=mock_neo4j_writer_cls,
            EdgeProposer=mock_proposer_cls,
            ThroughputGovernor=mock_governor_cls,
            psycopg2=mock_psycopg2,
        ),
        {
            "vm102_client_cls": mock_vm102_client_cls,
            "vm102_client_instance": mock_vm102_client_instance,
            "scanner_cls": mock_scanner_cls,
            "scanner_instance": mock_scanner_instance,
            "neo4j_writer_cls": mock_neo4j_writer_cls,
            "proposer_cls": mock_proposer_cls,
            "proposer_instance": mock_proposer_instance,
            "governor_cls": mock_governor_cls,
            "governor_instance": mock_governor_instance,
            "psycopg2": mock_psycopg2,
        },
    )


# ─── Tests ────────────────────────────────────────────────────────────────────


def test_run_returns_correct_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """MacroRelationshipDiscovery.run() returns the documented dict shape.

    Expected keys (per Phase 89.2 RESEARCH + VALIDATION):
      - proposals_created: int
      - scan_duration_s: float
      - throughput_action: str (one of {"ok", "warned_low", "tightened"})

    Body uses two mocked CandidateEdges that survive the proposer happy path,
    so ``proposals_created`` must be 2; ``scan_duration_s`` must be a
    non-negative float; ``throughput_action`` must equal the mocked
    governor return ("ok").
    """
    _set_required_env(monkeypatch)
    candidates = [_make_candidate("CPIAUCSL", "gold"), _make_candidate("FEDFUNDS", "eur")]

    agent_mod, patches, _mocks = _patch_agent_dependencies(
        scanner_candidates=candidates, governor_action="ok"
    )
    with patches:
        agent = agent_mod.MacroRelationshipDiscovery()
        result = agent.run(message="smoke", run_mode="manual")

    # Exact key set — Dagster asset hardcodes these names.
    assert set(result.keys()) == {
        "proposals_created",
        "scan_duration_s",
        "throughput_action",
    }, f"unexpected key set: {set(result.keys())}"

    # Types.
    assert isinstance(result["proposals_created"], int)
    assert isinstance(result["scan_duration_s"], float)
    assert isinstance(result["throughput_action"], str)

    # Values — both candidates survived the proposer happy path.
    assert result["proposals_created"] == 2
    assert result["scan_duration_s"] >= 0.0
    assert result["throughput_action"] == "ok"


def test_run_calls_vm102_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent.run() instantiates Vm102DiscoveryClient and feeds the scanner.

    Asserts:
      - Vm102DiscoveryClient class on agent module namespace is called once
        (instantiation inside .run()).
      - The same client instance is passed as ``vm102_client`` to
        CorrelationScanner's constructor.
      - CorrelationScanner.scan() is called with ``pairs=DEFAULT_SCAN_PAIRS``
        (the actual 12-tuple list, not a substitute).
    """
    _set_required_env(monkeypatch)
    from agents.macro_relationship_discovery.scan_pairs import DEFAULT_SCAN_PAIRS

    agent_mod, patches, mocks = _patch_agent_dependencies(
        scanner_candidates=[_make_candidate()], governor_action="ok"
    )
    with patches:
        agent = agent_mod.MacroRelationshipDiscovery()
        agent.run(message="smoke", run_mode="manual")

    # 1. Vm102DiscoveryClient was instantiated exactly once.
    mocks["vm102_client_cls"].assert_called_once_with()

    # 2. CorrelationScanner was constructed with the client instance.
    scanner_call = mocks["scanner_cls"].call_args
    assert scanner_call is not None, "CorrelationScanner was never instantiated"
    assert scanner_call.kwargs.get("vm102_client") is mocks["vm102_client_instance"], (
        "CorrelationScanner did not receive the Vm102DiscoveryClient instance"
    )

    # 3. scanner.scan was called with the actual DEFAULT_SCAN_PAIRS list.
    scan_call = mocks["scanner_instance"].scan.call_args
    assert scan_call is not None, "CorrelationScanner.scan was never called"
    assert scan_call.kwargs.get("pairs") == DEFAULT_SCAN_PAIRS, (
        "scanner.scan(pairs=...) must be called with the imported DEFAULT_SCAN_PAIRS"
    )
    assert len(scan_call.kwargs["pairs"]) == 12, (
        "DEFAULT_SCAN_PAIRS must contain the canonical 12 (FRED_code, asset_slug) tuples"
    )


@pytest.mark.parametrize("evaluate_return", ["ok", "warned_low", "tightened"])
def test_throughput_action_enum(
    monkeypatch: pytest.MonkeyPatch, evaluate_return: str
) -> None:
    """``throughput_action`` mirrors the governor's evaluate_threshold return.

    Also verifies the tighten_thresholds side-effect: when the governor
    returns "tightened", the agent MUST call governor.tighten_thresholds()
    so next week's r_min read picks up the tighter floor (Open Q3 close
    on the persist side).
    """
    _set_required_env(monkeypatch)
    candidates = [_make_candidate()]

    agent_mod, patches, mocks = _patch_agent_dependencies(
        scanner_candidates=candidates, governor_action=evaluate_return
    )
    with patches:
        agent = agent_mod.MacroRelationshipDiscovery()
        result = agent.run(message="smoke", run_mode="manual")

    assert result["throughput_action"] == evaluate_return, (
        f"throughput_action must equal governor.evaluate_threshold return "
        f"({evaluate_return!r}); got {result['throughput_action']!r}"
    )
    assert result["throughput_action"] in {"ok", "warned_low", "tightened"}, (
        f"throughput_action must be one of the ThroughputGovernor enum values; "
        f"got {result['throughput_action']!r}"
    )

    # Side-effect: tighten_thresholds() called iff governor returned "tightened".
    if evaluate_return == "tightened":
        mocks["governor_instance"].tighten_thresholds.assert_called_once_with()
    else:
        mocks["governor_instance"].tighten_thresholds.assert_not_called()
