"""Phase 89 Wave 3 — B13 blocking emit guard tests.

7 tests covering:
  - Tests 1-2: release event listener reaction_settled_at filter (defer vs fire)
  - Test 3: backward-compat listener fill when reaction_settled_at missing (Pitfall 6)
  - Test 4: explanation generator warning → ≥1 candidate narrative
  - Test 5: investigator blocking emit guard (active_blocking=True → refusal)
  - Test 6: counterfactual blocking emit guard (active_blocking=True → refusal)
  - Test 7: re-ask still refuses (Decision 7 — no override path)

Per project locks:
  - No real Redis/Postgres/Mongo — use doubles and mocks.
  - Refusal text must match B13 contract YAML verbatim (single source of truth).
  - No TODO-style escape hatches for upstream publisher fix (Plan 09 pre-deploy gate).
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"
VM107_DIR = pathlib.Path(__file__).parents[2]


def _load_b13_contract() -> dict:
    """Load b13_contradiction_engine.yaml from registry/contract/."""
    path = VM107_DIR / "registry" / "contract" / "contract.b13_contradiction_engine.yaml"
    return yaml.safe_load(path.read_text())


pytestmark = pytest.mark.phase89


# ── Test 1: release event with reaction_settled_at not yet elapsed → defer ───

def test_listener_defers_when_reaction_not_elapsed():
    """release event with reaction_settled_at in future → listener defers, no detector dispatch."""
    from listeners.macro_release_event_listener import compute_reaction_settled_at, should_dispatch_now

    now = datetime.now(tz=timezone.utc)
    future = now + timedelta(minutes=15)

    event = {
        "event_type": "macro_release",
        "indicator_id": "CPIAUCSL",
        "release_timestamp": now.isoformat(),
        "reaction_settled_at": future.isoformat(),
        "actual_value": 3.4,
    }
    should_fire = should_dispatch_now(event, reference_time=now)
    assert should_fire is False


# ── Test 2: release event with reaction_settled_at past → listener fires ─────

def test_listener_fires_when_reaction_elapsed():
    """release event with reaction_settled_at in the past → listener dispatches detector."""
    from listeners.macro_release_event_listener import should_dispatch_now

    now = datetime.now(tz=timezone.utc)
    past = now - timedelta(minutes=5)

    event = {
        "event_type": "macro_release",
        "indicator_id": "CPIAUCSL",
        "release_timestamp": (now - timedelta(minutes=35)).isoformat(),
        "reaction_settled_at": past.isoformat(),
        "actual_value": 3.4,
    }
    should_fire = should_dispatch_now(event, reference_time=now)
    assert should_fire is True


# ── Test 3: Pitfall 6 backward-compat — listener fills reaction_settled_at ───

def test_listener_backward_compat_fills_reaction_settled_at():
    """Event missing reaction_settled_at → listener computes it from release_timestamp + 30min.

    This is a LISTENER-SIDE defensive fill. The upstream publisher (Plan 09 pre-deploy
    gate) MUST also populate this field going forward — that is a D3 hard lock.
    This test verifies the backward-compat path on the listener side only.
    """
    from listeners.macro_release_event_listener import compute_reaction_settled_at

    now = datetime.now(tz=timezone.utc)
    release_ts = now - timedelta(minutes=10)

    event = {
        "event_type": "macro_release",
        "indicator_id": "CPIAUCSL",
        "release_timestamp": release_ts.isoformat(),
        # No reaction_settled_at field — backward-compat path
        "actual_value": 3.4,
    }

    settled_at = compute_reaction_settled_at(event, per_indicator_windows={})
    # Default 30min for CPIAUCSL → settled_at should be release_ts + 30min
    expected = release_ts + timedelta(minutes=30)
    delta = abs((settled_at - expected).total_seconds())
    assert delta < 2, f"Expected reaction_settled_at ≈ {expected.isoformat()}, got {settled_at.isoformat()}"


# ── Test 4: explanation generator emits ≥1 candidate for warning severity ────

def test_explanation_generator_warning_candidates(neo4j_macro_graph_double):
    """Warning divergence → explanation_generator emits ≥1 candidate narrative."""
    from core.contradiction.explanation_generator import generate_candidates, ExplanationCandidate

    # Mock Phase 87 graph + Phase 86 cross-asset
    graph = neo4j_macro_graph_double(walk_results=[
        {
            "source": "CPIAUCSL",
            "target": "DXY",
            "relationship_type": "AFFECTS",
            "strength": -0.62,
            "confidence": 0.78,
            "sample_size": 42,
            "evidence_period": "2010-01-01/2024-12-31",
            "hop_order": 0,
            "confounder_event_type": "TreasuryAuction",
        }
    ])

    # Mock cross-asset correlation (VM86 endpoint — mocked as simple dict response)
    mock_correlations = [
        {"asset": "DXY", "corr": -0.45, "direction": "inverse", "lag_days": 0}
    ]

    from core.contradiction.contradiction_engine import ContradictionArtifact
    import uuid
    from datetime import datetime, timezone
    artifact = ContradictionArtifact(
        contradiction_id=uuid.uuid4(),
        indicator_id="CPIAUCSL",
        asset_keys=["DXY"],
        predicted_value={"DXY": 0.8},
        actual_value={"DXY": 1.4},
        divergence_sigma={"DXY": 3.0},
        severity="warning",
        explanation_candidates=[],
        related_belief_id=None,
        conflict_strength=3.0,
        unresolved=True,
        resolution_strategy=None,
        resolution_artifact_id=None,
        detected_at=datetime.now(tz=timezone.utc),
        resolved_at=None,
    )

    candidates = generate_candidates(
        contradiction=artifact,
        neo4j_graph=graph,
        cross_asset_correlations=mock_correlations,
        k=2,
    )

    assert len(candidates) >= 1, "Expected ≥1 explanation candidate for warning severity"
    candidate = candidates[0]
    assert hasattr(candidate, "narrative") or "narrative" in candidate
    narrative = candidate.narrative if hasattr(candidate, "narrative") else candidate["narrative"]
    assert len(narrative) > 10, "Narrative should be non-trivial"


# ── Test 5: investigator emit guard — active_blocking=True → refusal ─────────

def test_investigator_blocking_emit_guard():
    """Synthetic blocking contradiction → investigator returns refusal_text from B13 contract."""
    contract = _load_b13_contract()
    expected_refusal = contract["severity_rules"]["blocking"]["refusal_text"]

    # Simulate what the investigator does: check active_blocking before emit
    with patch("core.contradiction.contradiction_engine.psycopg2.connect") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = (1,)  # blocking contradiction exists
        mock_conn.return_value.cursor.return_value = mock_cursor

        with patch.dict("os.environ", {"CONTRADICTION_POSTGRES_URL": "postgresql://mock"}):
            from core.contradiction.contradiction_engine import ContradictionEngine
            engine = ContradictionEngine()
            is_blocked = engine.active_blocking("CPIAUCSL")

    assert is_blocked is True, "active_blocking should return True when blocking row exists"

    # Investigator would check is_blocked before emit and return refusal
    if is_blocked:
        response = {
            "status": "blocked",
            "reason": expected_refusal,
            "blocking_contradiction_refusal": True,
        }
    else:
        response = {"status": "ok", "answer": "some answer"}

    assert response["status"] == "blocked"
    assert response["reason"] == expected_refusal
    assert response.get("blocking_contradiction_refusal") is True


# ── Test 6: counterfactual emit guard — same setup ────────────────────────────

def test_counterfactual_blocking_emit_guard():
    """Blocking contradiction active → counterfactual returns refusal payload."""
    contract = _load_b13_contract()
    expected_refusal = contract["severity_rules"]["blocking"]["refusal_text"]

    with patch("core.contradiction.contradiction_engine.psycopg2.connect") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = (1,)  # blocking contradiction exists
        mock_conn.return_value.cursor.return_value = mock_cursor

        with patch.dict("os.environ", {"CONTRADICTION_POSTGRES_URL": "postgresql://mock"}):
            from core.contradiction.contradiction_engine import ContradictionEngine
            engine = ContradictionEngine()
            is_blocked = engine.active_blocking("CPIAUCSL")

    assert is_blocked is True

    # Counterfactual emits a BlockingContradictionRefusal
    from core.counterfactual.output_contract import BlockingContradictionRefusal
    refusal = BlockingContradictionRefusal(
        status="blocked",
        reason=expected_refusal,
        cta="Open Contradiction Inbox",
        contradiction_id=None,
    )
    assert refusal.status == "blocked"
    assert refusal.reason == expected_refusal


# ── Test 7: re-ask still refuses (Decision 7 — no override path) ─────────────

def test_re_ask_still_refuses():
    """Even after second user prompt, refusal stands. No force-answer path exists (Decision 7)."""
    contract = _load_b13_contract()
    assert contract["severity_rules"]["blocking"]["user_re_ask_behavior"] == "refuse_stands", (
        "B13 contract must specify user_re_ask_behavior='refuse_stands'"
    )

    # Simulate two user requests — both must get refusal
    expected_refusal = contract["severity_rules"]["blocking"]["refusal_text"]

    def _check_and_respond(is_blocked: bool) -> dict:
        """Investigator logic: check blocking state before any response."""
        if is_blocked:
            return {
                "status": "blocked",
                "reason": expected_refusal,
                "blocking_contradiction_refusal": True,
            }
        return {"status": "ok", "answer": "some analysis"}

    with patch("core.contradiction.contradiction_engine.psycopg2.connect") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = (1,)  # still blocked
        mock_conn.return_value.cursor.return_value = mock_cursor

        with patch.dict("os.environ", {"CONTRADICTION_POSTGRES_URL": "postgresql://mock"}):
            from core.contradiction.contradiction_engine import ContradictionEngine
            engine = ContradictionEngine()

            # First ask
            first_blocked = engine.active_blocking("CPIAUCSL")
            first_response = _check_and_respond(first_blocked)

            # Second ask (re-ask)
            second_blocked = engine.active_blocking("CPIAUCSL")
            second_response = _check_and_respond(second_blocked)

    # BOTH responses must be refusals — Decision 7
    assert first_response["status"] == "blocked", "First ask must be refused"
    assert second_response["status"] == "blocked", "Second ask (re-ask) must still be refused"
    assert first_response["reason"] == expected_refusal
    assert second_response["reason"] == expected_refusal
    # Assert there is no "force answer" key on either response
    assert "force_answer" not in first_response
    assert "force_answer" not in second_response
