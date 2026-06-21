"""Phase 89 Wave 4 — discovery governance tests.

7 tests covering:
  1. Dagster schedule cron == '0 3 * * *' (Decision 4)
  2. Dagster asset dispatches discovery agent via HTTP POST (_dispatch_agent_sync)
  3. Throughput governor under-threshold (0 proposals/week → warned_low)
  4. Throughput governor over-threshold (12 proposals/week → tightened thresholds)
  5. WS publish + Phase 91 emit per proposal (shared helper, no redefinition)
  6. Decision 8 — no auto-promote after 30-day shadow window
  7. Pitfall 4 — no vm107-macro-relationship-discovery service in docker-compose.yml

Per project locks:
  - emit_alert_candidate is imported from core.alerts.phase91_emit (Plan 03 shared
    helper); NOT redefined anywhere in Phase 89 discovery code.
  - No live Redis/Postgres — all mocked.
  - WS payload is thin-invalidation only (Phase 74 contract).
"""
from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call
from uuid import uuid4
import inspect

import pytest
import yaml

pytestmark = pytest.mark.phase89

VM107_DIR = pathlib.Path(__file__).parents[2]
DAGSTER_DIR = pathlib.Path("/Volumes/ HardDrive/FinGPT/Dagster")

SCHED_PATH = (
    DAGSTER_DIR
    / "fingpt_orchestration"
    / "src"
    / "fingpt_orchestration"
    / "schedules"
    / "macro_discovery_nightly.py"
)

DOCKER_COMPOSE_PATH = VM107_DIR / "docker-compose.yml"


# ─── Test 1: Dagster schedule cron == '0 3 * * *' ────────────────────────────

def test_schedule_cron_is_03_utc():
    """macro_discovery_nightly_schedule has cron_schedule='0 3 * * *' (Decision 4)."""
    if not SCHED_PATH.exists():
        pytest.fail(f"Schedule file not found: {SCHED_PATH}")

    src = SCHED_PATH.read_text()
    assert "0 3 * * *" in src, (
        "macro_discovery_nightly schedule must use cron '0 3 * * *' per Decision 4"
    )
    assert "macro_discovery_nightly" in src

    # Verify via source text (avoids triggering the full Dagster definitions import
    # which would fail on missing VM101_API_URL and other service env vars)
    src = SCHED_PATH.read_text()
    assert "cron_schedule=\"0 3 * * *\"" in src or "cron_schedule='0 3 * * *'" in src, (
        "macro_discovery_nightly schedule file must contain cron_schedule='0 3 * * *'"
    )
    assert "macro_discovery_nightly_job" in src, (
        "Schedule must reference macro_discovery_nightly_job"
    )


# ─── Test 2: Dagster asset dispatches via _dispatch_agent_sync ───────────────

def test_dagster_asset_dispatches_discovery_agent():
    """Dagster macro_relationship_discovery asset source calls _dispatch_agent_sync."""
    asset_path = (
        DAGSTER_DIR
        / "fingpt_orchestration"
        / "src"
        / "fingpt_orchestration"
        / "assets"
        / "macro"
        / "macro_relationship_discovery.py"
    )
    if not asset_path.exists():
        pytest.fail(f"Asset file not found: {asset_path}")

    # Read source text (avoids triggering full Dagster definitions import
    # which would fail on missing service env vars like VM101_API_URL)
    src = asset_path.read_text()
    assert "vm107.macro_relationship_discovery" in src, (
        "Asset must dispatch to 'vm107.macro_relationship_discovery' profile"
    )
    assert "_dispatch_agent_sync" in src, (
        "Asset must use _dispatch_agent_sync for HTTP dispatch"
    )


# ─── Test 3: Throughput governor under-threshold ──────────────────────────────

def test_throughput_governor_under_threshold():
    """0 proposals in a week → governor sets threshold_action='warned_low'."""
    from core.discovery.throughput_governor import ThroughputGovernor

    with patch("core.discovery.throughput_governor.psycopg2.connect") as mock_conn:
        conn = MagicMock()
        cursor = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=cursor)
        ctx.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = ctx
        mock_conn.return_value = conn

        with patch.dict("os.environ", {"DISCOVERY_POSTGRES_URL": "postgresql://mock"}):
            gov = ThroughputGovernor()
            action = gov.evaluate_threshold(this_week_count=0)

    assert action == "warned_low", (
        f"0 proposals/week must return 'warned_low', got {action!r}"
    )


# ─── Test 4: Throughput governor over-threshold ───────────────────────────────

def test_throughput_governor_over_threshold():
    """12 proposals in a week → governor sets threshold_action='tightened'."""
    from core.discovery.throughput_governor import ThroughputGovernor

    with patch("core.discovery.throughput_governor.psycopg2.connect") as mock_conn:
        conn = MagicMock()
        cursor = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=cursor)
        ctx.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = ctx
        mock_conn.return_value = conn

        with patch.dict("os.environ", {"DISCOVERY_POSTGRES_URL": "postgresql://mock"}):
            gov = ThroughputGovernor()
            action = gov.evaluate_threshold(this_week_count=12)

    assert action == "tightened", (
        f"12 proposals/week must return 'tightened', got {action!r}"
    )


def test_throughput_governor_tighten_raises_r_min():
    """tighten_thresholds() returns new r_min = base_r_min + 0.05."""
    from core.discovery.throughput_governor import ThroughputGovernor

    with patch("core.discovery.throughput_governor.psycopg2.connect") as mock_conn:
        conn = MagicMock()
        cursor = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=cursor)
        ctx.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = ctx
        mock_conn.return_value = conn

        with patch.dict("os.environ", {"DISCOVERY_POSTGRES_URL": "postgresql://mock"}):
            gov = ThroughputGovernor(base_r_min=0.30)
            new_r_min = gov.tighten_thresholds()

    assert abs(new_r_min - 0.35) < 0.001, (
        f"tighten_thresholds() must raise r_min by 0.05: expected 0.35, got {new_r_min}"
    )


# ─── Test 5: WS publish + Phase 91 emit via shared helper ────────────────────

def test_ws_publish_and_phase91_emit_per_proposal(neo4j_macro_graph_double):
    """Each proposal triggers publish_discovery_proposed AND emit_alert_candidate (shared helper)."""
    from core.discovery.edge_proposer import EdgeProposer
    from publishers.macro_ws_invalidation import publish_discovery_proposed

    graph = neo4j_macro_graph_double()
    candidate = {
        "from_node": "CPI",
        "to_node": "DXY",
        "correlation": 0.41,
        "p_value": 0.015,
        "sample_size": 38,
        "lag_months": None,
        "period_start": "2023-06-01",
        "period_end": "2024-06-01",
        "evidence_release_ids": ["release:CPI-2024-06-12"],
    }

    published_proposals = []
    emitted_alerts = []

    def _mock_ws_publish(proposal_id, from_node, to_node):
        published_proposals.append({
            "proposal_id": proposal_id,
            "from_node": from_node,
            "to_node": to_node,
        })

    def _mock_emit(alert_type, producer_agent_id, subject_id,
                   b13_internal_severity, explanation, citations, **kwargs):
        emitted_alerts.append({
            "alert_type": alert_type,
            "producer_agent_id": producer_agent_id,
            "subject_id": subject_id,
            "b13_internal_severity": b13_internal_severity,
        })

    with patch("core.discovery.edge_proposer.psycopg2.connect") as mock_conn:
        conn = MagicMock()
        cursor = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=cursor)
        ctx.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = ctx
        mock_conn.return_value = conn

        with patch("core.discovery.edge_proposer.emit_alert_candidate", side_effect=_mock_emit):
            with patch.dict("os.environ", {"DISCOVERY_POSTGRES_URL": "postgresql://mock"}):
                proposer = EdgeProposer(neo4j_writer=graph)
                proposal = proposer.propose(candidate)

    # Phase 91 emit must have fired with discovery type + None severity → Info
    assert len(emitted_alerts) == 1
    alert = emitted_alerts[0]
    assert alert["alert_type"] == "discovery"
    assert alert["producer_agent_id"] == "vm107.macro_relationship_discovery"
    assert alert["b13_internal_severity"] is None, (
        "Discovery has no B13 severity — must pass None → default 'Info'"
    )

    # Verify the import path is the shared helper from Plan 03 (not redefined)
    import core.discovery.edge_proposer as ep_mod
    src = inspect.getsource(ep_mod)
    assert "from core.alerts.phase91_emit import emit_alert_candidate" in src, (
        "edge_proposer must import emit_alert_candidate from core.alerts.phase91_emit "
        "(Plan 03 shared helper — NOT redefined locally)"
    )
    assert "def emit_alert_candidate" not in src, (
        "edge_proposer must NOT redefine emit_alert_candidate locally"
    )


# ─── Test 6: Decision 8 — no auto-promote after shadow window ────────────────

def test_decision8_no_auto_promote_after_shadow_window(neo4j_macro_graph_double):
    """After 30-day shadow window, status STAYS shadow — no background promoter in Phase 89."""
    from core.discovery.edge_proposer import EdgeProposer

    graph = neo4j_macro_graph_double()
    candidate = {
        "from_node": "CPI",
        "to_node": "Gold",
        "correlation": 0.44,
        "p_value": 0.01,
        "sample_size": 42,
        "lag_months": None,
        "period_start": "2022-01-01",
        "period_end": "2023-01-01",
        "evidence_release_ids": ["release:CPI-2023-01-13"],
    }

    with patch("core.discovery.edge_proposer.psycopg2.connect") as mock_conn:
        conn = MagicMock()
        cursor = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=cursor)
        ctx.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = ctx
        mock_conn.return_value = conn

        with patch("core.discovery.edge_proposer.emit_alert_candidate"):
            with patch.dict("os.environ", {"DISCOVERY_POSTGRES_URL": "postgresql://mock"}):
                proposer = EdgeProposer(neo4j_writer=graph)
                proposal = proposer.propose(candidate)

    # Proposal is shadow at creation
    assert proposal.governance_status == "shadow"

    # Simulate 31 days passing — no background promoter changes the status
    # (Governance promotion is a human action via Phase 53 UI — Decision 8)
    fake_now = proposal.proposed_at + timedelta(days=31)

    # Verify no Phase 89 code path auto-promotes (review the source)
    import core.discovery.edge_proposer as ep_mod
    src = inspect.getsource(ep_mod)

    # No code path sets governance_status to anything other than 'shadow'
    lines_with_status = [
        line.strip()
        for line in src.splitlines()
        if "governance_status" in line and "shadow" not in line and "=" in line
    ]
    auto_promote_lines = [
        line for line in lines_with_status
        if any(s in line for s in ('"proposed"', "'proposed'", '"live"', "'live'"))
    ]
    assert not auto_promote_lines, (
        f"Phase 89 edge_proposer must NOT set governance_status to anything other than "
        f"'shadow'. Found: {auto_promote_lines}"
    )

    # The proposal still has shadow status (no auto-promotion)
    assert proposal.governance_status == "shadow", (
        "Proposal governance_status must remain 'shadow' — "
        "promotion requires human review via Phase 53 UI (Decision 8)"
    )


# ─── Test 7: Pitfall 4 — no sibling docker-compose service ───────────────────

def test_pitfall4_no_sibling_docker_compose_service():
    """docker-compose.yml must NOT contain a vm107-macro-relationship-discovery service."""
    if not DOCKER_COMPOSE_PATH.exists():
        pytest.skip(f"docker-compose.yml not found at {DOCKER_COMPOSE_PATH}")

    compose_src = DOCKER_COMPOSE_PATH.read_text()

    forbidden_service_names = [
        "vm107-macro-relationship-discovery",
        "vm107-macro-discovery",
        "macro-relationship-discovery",
        "macro_relationship_discovery",
    ]

    for service_name in forbidden_service_names:
        assert service_name not in compose_src, (
            f"Pitfall 4 violation: '{service_name}' found in docker-compose.yml. "
            "The discovery agent must NOT be a sibling service — it is invoked "
            "exclusively by the Dagster nightly job (Decision 4)."
        )

    # Also verify in the agent profile YAML
    profile_path = VM107_DIR / "registry" / "agent_profile" / "vm107.macro_relationship_discovery.yaml"
    if profile_path.exists():
        profile = yaml.safe_load(profile_path.read_text())
        assert profile.get("sibling_service") is None, (
            "Agent profile must have sibling_service: null (Pitfall 4)"
        )
        assert profile.get("trigger") == "schedule", (
            "Agent profile must have trigger: schedule (Decision 4)"
        )
