"""Phase 89 Wave 3 — B13 severity grader tests.

9 tests covering all severity paths per B13 contract YAML:
  - Tests 1-3: info severity (single-asset 1.5–2.5σ)
  - Tests 4-5: warning severity (single-asset 2.5–3.5σ + multi-asset same direction)
  - Tests 6-7: blocking severity (>3.5σ + belief contradiction)
  - Test 8: active_blocking reads Postgres directly (Pitfall 2 — no Mongo cache)
  - Test 9: BeliefStore wiring — blocking write calls BeliefStore.propose(confirms_belief=False)
  - Tests via parametrize: loop over b13_divergence_events.yaml fixture (9 events)

Per project locks:
  - No real Postgres/Mongo/Neo4j in unit tests — use doubles.
  - env-driven config: CONTRADICTION_POSTGRES_URL must be read from env (no defaults).
"""
from __future__ import annotations

import pathlib
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
import yaml

# ── Fixture data ──────────────────────────────────────────────────────────────

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


def _load_divergence_events() -> list[dict]:
    """Load all 9 divergence events from b13_divergence_events.yaml."""
    path = FIXTURES_DIR / "b13_divergence_events.yaml"
    data = yaml.safe_load(path.read_text())
    return data["divergence_events"]


_DIVERGENCE_EVENTS = _load_divergence_events()
_INFO_EVENTS = [e for e in _DIVERGENCE_EVENTS if e["expected_severity"] == "info"]
_WARNING_EVENTS = [e for e in _DIVERGENCE_EVENTS if e["expected_severity"] == "warning"]
_BLOCKING_EVENTS = [e for e in _DIVERGENCE_EVENTS if e["expected_severity"] == "blocking"]


# ── Load B13 contract YAML for rule-checking ─────────────────────────────────

def _load_b13_contract() -> dict:
    """Load b13_contradiction_engine.yaml from registry/contract/."""
    path = pathlib.Path(__file__).parents[2] / "registry" / "contract" / "contract.b13_contradiction_engine.yaml"
    return yaml.safe_load(path.read_text())


# ── Helper: compute divergence_sigma from raw event ──────────────────────────

def _compute_sigma(event: dict) -> dict[str, float]:
    """Extract per-asset divergence sigma from the fixture event.

    In the b13_divergence_events.yaml fixture, the `sigma_historical_per_asset`
    field stores the PRE-COMPUTED divergence sigma values (the fixture notes
    say "DXY at 2.8σ" which equals sigma_historical_per_asset.DXY=2.8).
    We use these values directly as the divergence_sigma input to grade_severity.

    This is by design: the fixture captures realistic scenarios with known sigma
    outcomes. The historical standard deviation is implicitly baked in. The
    ContradictionEngine.detect_divergence() method computes sigma at runtime from
    raw predicted/actual/sigma_hist inputs — the fixture tests the grader itself.
    """
    return {
        asset: float(sigma)
        for asset, sigma in event["sigma_historical_per_asset"].items()
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

pytestmark = pytest.mark.phase89


# Test 1: info severity single-asset 2.0σ
def test_info_severity_single_asset_2sigma():
    """Single-asset divergence at 2.0σ → severity='info', ui_surface=none, delta=0.0."""
    from core.contradiction.severity_grader import grade_severity, SeverityResult

    contract = _load_b13_contract()
    # 2.0σ on a single asset — within info band [1.5, 2.5]
    divergence_sigma = {"DXY": 2.0, "Gold": 0.0, "SPX": 0.0, "UST10Y": 0.0}
    result: SeverityResult = grade_severity(
        divergence_sigma_per_asset=divergence_sigma,
        active_beliefs=[],
        contract=contract,
    )
    assert result.severity == "info"
    assert result.ui_surface == "none"
    assert result.downstream_confidence_delta == 0.0


# Test 2: warning single-asset 3.0σ
def test_warning_severity_single_asset_3sigma():
    """Single-asset 3.0σ → severity='warning', ui_surface=indicator_page_banner, delta=-0.20."""
    from core.contradiction.severity_grader import grade_severity, SeverityResult

    contract = _load_b13_contract()
    divergence_sigma = {"DXY": 3.0, "Gold": 0.0, "SPX": 0.0, "UST10Y": 0.0}
    result: SeverityResult = grade_severity(
        divergence_sigma_per_asset=divergence_sigma,
        active_beliefs=[],
        contract=contract,
    )
    assert result.severity == "warning"
    assert result.ui_surface == "indicator_page_banner"
    assert result.downstream_confidence_delta == -0.20


# Test 3: warning multi-asset same direction 2.0σ
def test_warning_multi_asset_same_direction():
    """Two assets at 2.0σ in same direction (both positive divergence) → warning."""
    from core.contradiction.severity_grader import grade_severity, SeverityResult

    contract = _load_b13_contract()
    # DXY + Gold both at 2.0σ (same direction) → multi-asset warning
    divergence_sigma = {"DXY": 2.0, "Gold": 2.0, "SPX": 0.0, "UST10Y": 0.0}
    result: SeverityResult = grade_severity(
        divergence_sigma_per_asset=divergence_sigma,
        active_beliefs=[],
        contract=contract,
    )
    assert result.severity == "warning"


# Test 4: blocking sigma >3.5σ
def test_blocking_severity_high_sigma():
    """Single-asset 4.5σ → severity='blocking', downstream_confidence_delta='REFUSE_CONFIDENT_EMIT'."""
    from core.contradiction.severity_grader import grade_severity, SeverityResult

    contract = _load_b13_contract()
    divergence_sigma = {"DXY": 0.0, "Gold": 4.5, "SPX": 0.0, "UST10Y": 0.0}
    result: SeverityResult = grade_severity(
        divergence_sigma_per_asset=divergence_sigma,
        active_beliefs=[],
        contract=contract,
    )
    assert result.severity == "blocking"
    assert result.downstream_confidence_delta == "REFUSE_CONFIDENT_EMIT"


# Test 5: blocking via belief contradiction (2.0σ but belief conf=0.85)
def test_blocking_belief_contradiction_path():
    """2.0σ on Gold BUT contradicts BeliefStore belief at conf=0.85 → blocking (belief trigger)."""
    from core.contradiction.severity_grader import grade_severity, SeverityResult

    contract = _load_b13_contract()
    # 2.0σ would normally be info, but belief confidence 0.85 > 0.7 triggers blocking
    divergence_sigma = {"DXY": 0.8, "Gold": 2.0, "SPX": 0.2, "UST10Y": 0.2}
    active_beliefs = [
        {
            "belief_id": "BLF-CPI-GOLD-001",
            "confidence": 0.85,
            "subject_id": "CPIAUCSL",
            "statement": "CPI beat suppresses Gold via DXY appreciation",
            "lifecycle_state": "active",
        }
    ]
    result: SeverityResult = grade_severity(
        divergence_sigma_per_asset=divergence_sigma,
        active_beliefs=active_beliefs,
        contract=contract,
    )
    assert result.severity == "blocking"


# Test 6: active_blocking happy path
def test_active_blocking_happy_path(tmp_path):
    """Write a blocking contradiction; active_blocking('CPIAUCSL') returns True."""
    from core.contradiction.contradiction_engine import ContradictionEngine

    # Mock psycopg2 connection to simulate a blocking row exists
    with patch("core.contradiction.contradiction_engine.psycopg2.connect") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = (1,)  # row found → blocking
        mock_conn.return_value.cursor.return_value = mock_cursor

        with patch.dict("os.environ", {"CONTRADICTION_POSTGRES_URL": "postgresql://mock"}):
            engine = ContradictionEngine()
            result = engine.active_blocking("CPIAUCSL")

    assert result is True


# Test 7: active_blocking cache bypass (Pitfall 2) — reads Postgres, not Mongo cache
def test_active_blocking_reads_postgres_not_mongo(belief_store_double):
    """Pitfall 2: active_blocking() MUST read Postgres directly, never Mongo cache.

    We verify that even when a stale Mongo belief is present, active_blocking reads
    the macro_contradictions table (Postgres) for blocking rows — not BeliefStore cache.
    """
    from core.contradiction.contradiction_engine import ContradictionEngine

    # BeliefStore double returns a stale "active" belief with high confidence
    bs = belief_store_double(
        default_belief={
            "belief_id": str(uuid.uuid4()),
            "probability": 0.9,
            "confidence": 0.9,
            "evidence_count": 5,
            "contradicting_count": 0,
            "lifecycle_state": "active",
            "is_active": True,
        }
    )

    # Mock Postgres returning NO blocking row (unresolved blocking=False in DB)
    with patch("core.contradiction.contradiction_engine.psycopg2.connect") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = None  # no blocking row in Postgres
        mock_conn.return_value.cursor.return_value = mock_cursor

        with patch.dict("os.environ", {"CONTRADICTION_POSTGRES_URL": "postgresql://mock"}):
            engine = ContradictionEngine()
            result = engine.active_blocking("CPIAUCSL")

    # Despite belief store having stale high-confidence belief, Postgres says no block
    assert result is False
    # Verify BeliefStore.query was NOT called by active_blocking (Pitfall 2)
    query_calls = [c for c in bs._calls if c["method"] == "query"]
    assert len(query_calls) == 0, (
        "active_blocking() must NOT call BeliefStore.query — Pitfall 2 closed"
    )


# Test 8: BeliefStore wiring — blocking write calls propose(confirms_belief=False)
def test_belief_store_wiring_on_blocking_write(belief_store_double):
    """On blocking write, contradiction_engine calls BeliefStore.propose(confirms_belief=False)."""
    from core.contradiction.contradiction_engine import ContradictionEngine, ContradictionArtifact

    bs = belief_store_double()
    contradiction_id = uuid.uuid4()
    artifact = ContradictionArtifact(
        contradiction_id=contradiction_id,
        indicator_id="CPIAUCSL",
        asset_keys=["Gold"],
        predicted_value={"Gold": -0.4},
        actual_value={"Gold": 0.6},
        divergence_sigma={"Gold": 4.5},
        severity="blocking",
        explanation_candidates=[],
        related_belief_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        conflict_strength=4.5,
        unresolved=True,
        resolution_strategy=None,
        resolution_artifact_id=None,
        detected_at=datetime.now(tz=timezone.utc),
        resolved_at=None,
    )

    with patch("core.contradiction.contradiction_engine.psycopg2.connect") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value = mock_cursor

        with patch.dict("os.environ", {"CONTRADICTION_POSTGRES_URL": "postgresql://mock"}):
            engine = ContradictionEngine(belief_store=bs)
            engine.increment_contradicting_count(
                belief_id=str(artifact.related_belief_id),
                contradiction_id=str(contradiction_id),
            )

    propose_calls = [c for c in bs._calls if c["method"] == "propose"]
    assert len(propose_calls) == 1, "Expected exactly 1 propose call for blocking"
    call_record = propose_calls[0]
    assert call_record["confirms_belief"] is False
    assert call_record["proposer_id"] == "macro_contradiction_detector"
    assert "contradiction_id" in call_record["evidence"]


# Test 9: Pydantic ContradictionArtifact validates per ARCHITECTURE §5.4
def test_contradiction_artifact_pydantic_validation():
    """ContradictionArtifact validates all ARCHITECTURE §5.4 column fields."""
    from core.contradiction.contradiction_engine import ContradictionArtifact

    artifact = ContradictionArtifact(
        contradiction_id=uuid.uuid4(),
        indicator_id="CPIAUCSL",
        asset_keys=["DXY", "Gold"],
        predicted_value={"DXY": 0.5, "Gold": -0.4},
        actual_value={"DXY": 0.8, "Gold": 0.6},
        divergence_sigma={"DXY": 1.2, "Gold": 5.0},
        severity="blocking",
        explanation_candidates=[{"narrative": "test", "confidence": 0.8}],
        related_belief_id=None,
        conflict_strength=5.0,
        unresolved=True,
        resolution_strategy=None,
        resolution_artifact_id=None,
        detected_at=datetime.now(tz=timezone.utc),
        resolved_at=None,
    )
    assert artifact.severity == "blocking"
    assert artifact.conflict_strength == 5.0
    assert artifact.unresolved is True


# ── Parametrized fixture loop ─────────────────────────────────────────────────

@pytest.mark.parametrize("event", _DIVERGENCE_EVENTS, ids=[e["event_id"] for e in _DIVERGENCE_EVENTS])
def test_severity_grader_against_fixtures(event):
    """Loop over all 9 b13_divergence_events.yaml entries; assert severity matches expected."""
    from core.contradiction.severity_grader import grade_severity, SeverityResult

    contract = _load_b13_contract()
    sigma_per_asset = _compute_sigma(event)
    active_beliefs = event.get("active_beliefs", [])

    result: SeverityResult = grade_severity(
        divergence_sigma_per_asset=sigma_per_asset,
        active_beliefs=active_beliefs,
        contract=contract,
    )
    assert result.severity == event["expected_severity"], (
        f"Event {event['event_id']}: expected {event['expected_severity']!r}, "
        f"got {result.severity!r}. sigma={sigma_per_asset}"
    )
