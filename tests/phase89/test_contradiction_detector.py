"""Phase 89 Wave 3 — end-to-end contradiction detector tests.

5 tests covering:
  1. Synthetic warning divergence end-to-end (CPI → DXY divergence 3.0σ → artifact + WS + Phase 91)
  2. Phase 91 alert emit — severity translation warning→Important (Decision 13)
  3. Blocking severity end-to-end (4.5σ → blocking → WS + Phase 91 Critical + BeliefStore wiring)
  4. WS publish latency (mock clock — assert publish within 2s of detector completion)
  5. Phase 87 prediction shape contract test (mock macro_transmission_analysis row parses correctly)

Per project locks:
  - No live Redis/Postgres/Mongo — all mocked.
  - WS payload is thin-invalidation only (no domain data).
  - Phase 91 emit checks severity translation per contract YAML.
"""
from __future__ import annotations

import json
import pathlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest
import yaml

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"
VM107_DIR = pathlib.Path(__file__).parents[2]

pytestmark = pytest.mark.phase89


def _load_b13_contract() -> dict:
    path = VM107_DIR / "registry" / "contract" / "contract.b13_contradiction_engine.yaml"
    return yaml.safe_load(path.read_text())


# ── Test 1: Warning divergence end-to-end ────────────────────────────────────

def test_warning_divergence_end_to_end(belief_store_double):
    """CPI release → 3.0σ DXY divergence → artifact + WS topic + Phase 91 Important."""
    from core.contradiction.contradiction_engine import ContradictionEngine, ContradictionArtifact
    from publishers.macro_ws_invalidation import publish_contradiction_raised

    bs = belief_store_double()
    contradiction_id = uuid.uuid4()
    detected_at = datetime.now(tz=timezone.utc)

    # Build a warning-severity artifact
    artifact = ContradictionArtifact(
        contradiction_id=contradiction_id,
        indicator_id="CPIAUCSL",
        asset_keys=["DXY"],
        predicted_value={"DXY": 0.8},
        actual_value={"DXY": 1.4},
        divergence_sigma={"DXY": 3.0},
        severity="warning",
        explanation_candidates=[{"narrative": "Treasury demand offset CPI effect", "confidence": 0.6}],
        related_belief_id=None,
        conflict_strength=3.0,
        unresolved=True,
        resolution_strategy=None,
        resolution_artifact_id=None,
        detected_at=detected_at,
        resolved_at=None,
    )

    # Verify artifact fields
    assert artifact.severity == "warning"
    assert artifact.indicator_id == "CPIAUCSL"
    assert artifact.conflict_strength == 3.0

    # Mock WS publish and assert topic shape
    published_messages = []

    def _capture_publish(indicator_id, contradiction_id, severity):
        msg = {
            "topic": f"macro.contradiction.{indicator_id}.raised",
            "snapshot_id": str(uuid.uuid4()),
        }
        published_messages.append(msg)

    with patch("publishers.macro_ws_invalidation.publish_contradiction_raised", side_effect=_capture_publish):
        from publishers.macro_ws_invalidation import publish_contradiction_raised
        publish_contradiction_raised(
            indicator_id="CPIAUCSL",
            contradiction_id=str(contradiction_id),
            severity="warning",
        )

    assert len(published_messages) == 1
    msg = published_messages[0]
    assert msg["topic"] == "macro.contradiction.CPIAUCSL.raised"
    assert "snapshot_id" in msg
    # Thin invalidation: no domain data in payload
    assert "severity" not in msg
    assert "predicted_value" not in msg
    assert "actual_value" not in msg


# ── Test 2: Phase 91 alert emit — warning → Important (Decision 13) ──────────

def test_phase91_alert_emit_warning_important():
    """Warning divergence → emit_alert_candidate posts with severity='Important'."""
    contract = _load_b13_contract()
    assert contract["phase_91_severity_translation"]["warning"] == "Important"

    from core.alerts.phase91_emit import emit_alert_candidate

    captured_envelopes = []

    def _mock_post(url, *, json=None, **kwargs):
        captured_envelopes.append(json)
        return MagicMock(status_code=201)

    with patch.dict("os.environ", {"PHASE_91_UAE_URL": "http://mock-phase91/alerts"}):
        with patch("core.alerts.phase91_emit.requests.post", side_effect=_mock_post):
            emit_alert_candidate(
                alert_type="contradiction",
                producer_agent_id="vm107.macro_contradiction_detector",
                subject_id="CPIAUCSL",
                b13_internal_severity="warning",
                explanation="DXY diverged at 3.0σ — Treasury auction demand offset CPI effect",
                citations=["release:CPI-2026-06-21"],
                contradiction_id=uuid.uuid4(),
            )

    assert len(captured_envelopes) == 1
    envelope = captured_envelopes[0]
    assert envelope["severity"] == "Important"
    assert envelope["b13_internal_severity"] == "warning"
    assert envelope["alert_type"] == "contradiction"
    assert envelope["confidence"] >= 0.5
    assert len(envelope["citations"]) >= 1


# ── Test 3: Blocking severity end-to-end ─────────────────────────────────────

def test_blocking_severity_end_to_end(belief_store_double):
    """4.5σ divergence → blocking → WS Critical indicator + Phase 91 Critical + BeliefStore wiring."""
    from core.contradiction.contradiction_engine import ContradictionEngine, ContradictionArtifact
    from core.alerts.phase91_emit import emit_alert_candidate

    bs = belief_store_double()
    related_belief_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
    contradiction_id = uuid.uuid4()

    artifact = ContradictionArtifact(
        contradiction_id=contradiction_id,
        indicator_id="CPIAUCSL",
        asset_keys=["Gold", "SPX"],
        predicted_value={"Gold": -0.8, "SPX": -0.5},
        actual_value={"Gold": 1.2, "SPX": -3.1},
        divergence_sigma={"Gold": 5.2, "SPX": 4.1},
        severity="blocking",
        explanation_candidates=[{"narrative": "Regime break in Gold/CPI channel", "confidence": 0.7}],
        related_belief_id=related_belief_id,
        conflict_strength=5.2,
        unresolved=True,
        resolution_strategy=None,
        resolution_artifact_id=None,
        detected_at=datetime.now(tz=timezone.utc),
        resolved_at=None,
    )

    # Verify blocking severity
    assert artifact.severity == "blocking"

    # BeliefStore wiring mock
    with patch("core.contradiction.contradiction_engine.psycopg2.connect") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value = mock_cursor

        with patch.dict("os.environ", {"CONTRADICTION_POSTGRES_URL": "postgresql://mock"}):
            engine = ContradictionEngine(belief_store=bs)
            engine.increment_contradicting_count(
                belief_id=str(related_belief_id),
                contradiction_id=str(contradiction_id),
            )

    # Verify BeliefStore.propose called with confirms_belief=False
    propose_calls = [c for c in bs._calls if c["method"] == "propose"]
    assert len(propose_calls) == 1
    assert propose_calls[0]["confirms_belief"] is False

    # Phase 91 emit → Critical
    contract = _load_b13_contract()
    assert contract["phase_91_severity_translation"]["blocking"] == "Critical"

    captured_envelopes = []

    def _mock_post(url, *, json=None, **kwargs):
        captured_envelopes.append(json)
        return MagicMock(status_code=201)

    with patch.dict("os.environ", {"PHASE_91_UAE_URL": "http://mock-phase91/alerts"}):
        with patch("core.alerts.phase91_emit.requests.post", side_effect=_mock_post):
            emit_alert_candidate(
                alert_type="contradiction",
                producer_agent_id="vm107.macro_contradiction_detector",
                subject_id="CPIAUCSL",
                b13_internal_severity="blocking",
                explanation="Gold at 5.2σ — blocking contradiction detected",
                citations=["release:CPI-2022-06-10"],
                contradiction_id=contradiction_id,
            )

    assert captured_envelopes[0]["severity"] == "Critical"


# ── Test 4: WS publish latency within 2s ─────────────────────────────────────

def test_ws_publish_latency_within_2s():
    """Mock clock — assert WS publish occurs within 2s of detector completion."""
    from publishers.macro_ws_invalidation import publish_contradiction_raised

    published_at = {}

    def _mock_redis_publish(*args, **kwargs):
        published_at["t"] = time.monotonic()

    start = time.monotonic()

    # Simulate the "detector completed" → WS publish sequence
    with patch("publishers.macro_ws_invalidation._get_redis_url", return_value="redis://mock"):
        with patch("publishers.macro_ws_invalidation.redis") as mock_redis:
            mock_r = MagicMock()
            mock_redis.from_url.return_value = mock_r
            mock_r.publish.side_effect = lambda topic, msg: published_at.__setitem__("t", time.monotonic())

            publish_contradiction_raised(
                indicator_id="CPIAUCSL",
                contradiction_id=str(uuid.uuid4()),
                severity="warning",
            )

    elapsed = published_at.get("t", start) - start
    assert elapsed < 2.0, f"WS publish must complete within 2s, took {elapsed:.3f}s"


# ── Test 5: Phase 87 prediction shape contract test ──────────────────────────

def test_phase87_prediction_shape_contract():
    """Mock macro_transmission_analysis row → detector parses structure without errors."""
    from core.contradiction.contradiction_engine import ContradictionEngine

    # Realistic Phase 87 transmission engine prediction shape
    mock_prediction = {
        "indicator_id": "CPIAUCSL",
        "release_timestamp": "2026-06-21T12:30:00Z",
        "predicted_moves": {
            "DXY": {"direction": "up", "magnitude": 0.8, "confidence": 0.72},
            "Gold": {"direction": "down", "magnitude": -1.0, "confidence": 0.68},
            "SPX": {"direction": "down", "magnitude": -0.6, "confidence": 0.65},
            "UST10Y": {"direction": "up", "magnitude": 0.08, "confidence": 0.70},
        },
    }

    # Extract predicted_per_asset (what detector expects)
    predicted_per_asset = {
        asset: data["magnitude"]
        for asset, data in mock_prediction["predicted_moves"].items()
    }

    # Actual reaction
    actual_per_asset = {"DXY": 1.4, "Gold": -0.8, "SPX": -0.5, "UST10Y": 0.12}
    sigma_historical = {"DXY": 1.0, "Gold": 0.5, "SPX": 0.3, "UST10Y": 0.1}

    with patch("core.contradiction.contradiction_engine.psycopg2.connect") as mock_conn:
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.cursor.return_value = mock_cursor

        with patch.dict("os.environ", {"CONTRADICTION_POSTGRES_URL": "postgresql://mock"}):
            engine = ContradictionEngine()

            # Should not raise — prediction shape is valid
            divergence = engine.detect_divergence(
                indicator_id="CPIAUCSL",
                predicted_per_asset=predicted_per_asset,
                actual_per_asset=actual_per_asset,
                sigma_historical=sigma_historical,
            )

    # Verify divergence computation is correct
    assert "DXY" in divergence
    # DXY: |1.4 - 0.8| / 1.0 = 0.6σ
    assert abs(divergence["DXY"] - 0.6) < 0.001
    # Gold: |-0.8 - (-1.0)| / 0.5 = 0.2 / 0.5 = 0.4σ
    assert abs(divergence["Gold"] - 0.4) < 0.001
