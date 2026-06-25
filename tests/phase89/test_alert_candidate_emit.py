"""Phase 89↔Phase 91 contract tests — emit_alert_candidate helper.

3 tests covering the Phase 89↔Phase 91 contract surface (shared by contradiction
detector + Wave 4 discovery agent):

  Test 6: Contradiction emit path — alert_type='contradiction', b13_internal_severity='warning'
           → envelope matches alert_candidate_event.schema.json, severity='Important'
  Test 7: Discovery emit path — alert_type='discovery', b13_internal_severity=None
           → envelope matches schema, severity defaults to 'Info', proposal_id present
  Test 8: DLQ when PHASE_91_UAE_URL unset — no exception raised, DLQ captures envelope

Per project locks:
  - emit_alert_candidate in core/alerts/phase91_emit.py is the SHARED contract surface.
  - Wave 4 discovery agent imports from the same module.
  - Validate against fixtures/alert_candidate_event.schema.json (Draft 7).
"""
from __future__ import annotations

import json
import os
import pathlib
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import jsonschema
import pytest

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"
SCHEMA_PATH = FIXTURES_DIR / "alert_candidate_event.schema.json"

pytestmark = pytest.mark.phase89


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


# ── Test 6: Contradiction emit path ──────────────────────────────────────────

def test_contradiction_emit_path_schema_valid():
    """alert_type='contradiction' path — envelope validates against JSON Schema Draft 7.

    Verifies:
      - severity='Important' (warning→Important per Decision 13 translation)
      - b13_internal_severity='warning' preserved in envelope
      - citation list present
      - schema_version='0.1-provisional'
    """
    from core.alerts.phase91_emit import emit_alert_candidate

    schema = _load_schema()
    validator = jsonschema.Draft7Validator(schema)
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
                explanation="DXY diverged at 3.0σ from Phase 87 prediction",
                citations=["release:CPI-2026-06-21", "belief:real-yields-drive-gold"],
                contradiction_id=uuid.uuid4(),
            )

    assert len(captured_envelopes) == 1, "Expected exactly 1 envelope posted"
    envelope = captured_envelopes[0]

    # Schema validation
    errors = list(validator.iter_errors(envelope))
    assert not errors, f"Schema validation failed: {[e.message for e in errors[:3]]}"

    # Severity translation
    assert envelope["severity"] == "Important", (
        f"warning → Important per Decision 13; got {envelope['severity']!r}"
    )
    assert envelope["b13_internal_severity"] == "warning"
    assert envelope["alert_type"] == "contradiction"
    assert len(envelope["citations"]) >= 1
    # Phase 91 Plan 1 — schema promoted from 0.1-provisional → 1.0
    assert envelope["schema_version"] == "1.0"
    assert envelope["event_type"] == "alert_candidate_created"
    # Phase 91 Plan 1 — event_id is now required (schema v1.0)
    assert "event_id" in envelope
    assert len(envelope["event_id"]) >= 16


# ── Test 7: Discovery emit path ───────────────────────────────────────────────

def test_discovery_emit_path_schema_valid():
    """alert_type='discovery', b13_internal_severity=None → severity='Info', proposal_id present.

    Wave 4 discovery agent also imports emit_alert_candidate from core.alerts.phase91_emit.
    This tests the discovery call path (b13_internal_severity=None → default severity 'Info').
    """
    from core.alerts.phase91_emit import emit_alert_candidate

    schema = _load_schema()
    validator = jsonschema.Draft7Validator(schema)
    captured_envelopes = []

    def _mock_post(url, *, json=None, **kwargs):
        captured_envelopes.append(json)
        return MagicMock(status_code=201)

    proposal_id = uuid.uuid4()

    with patch.dict("os.environ", {"PHASE_91_UAE_URL": "http://mock-phase91/alerts"}):
        with patch("core.alerts.phase91_emit.requests.post", side_effect=_mock_post):
            emit_alert_candidate(
                alert_type="discovery",
                producer_agent_id="vm107.macro_relationship_discovery",
                subject_id="CPIAUCSL",
                b13_internal_severity=None,  # discovery path — no B13 internal severity
                explanation="New Copper→PMI edge discovered with r=0.52, p<0.01, n=48",
                citations=["correlation:copper-pmi-2026"],
                proposal_id=proposal_id,
            )

    assert len(captured_envelopes) == 1
    envelope = captured_envelopes[0]

    # Schema validation
    errors = list(validator.iter_errors(envelope))
    assert not errors, f"Schema validation failed: {[e.message for e in errors[:3]]}"

    # Discovery path defaults to 'Info' severity when b13_internal_severity is None
    assert envelope["severity"] == "Info", (
        f"discovery path with no b13_internal_severity → 'Info'; got {envelope['severity']!r}"
    )
    # proposal_id must be present in the envelope
    assert "proposal_id" in envelope, "discovery envelope must include proposal_id"
    assert envelope["proposal_id"] == str(proposal_id)


# ── Test 8: DLQ when PHASE_91_UAE_URL unset ──────────────────────────────────

def test_dlq_when_phase91_url_unset():
    """When PHASE_91_UAE_URL is unset → no exception, DLQ captures envelope for replay."""
    from core.alerts.phase91_emit import emit_alert_candidate

    # Ensure PHASE_91_UAE_URL is NOT set
    env_without_url = {k: v for k, v in os.environ.items() if k != "PHASE_91_UAE_URL"}

    captured_dlq = []

    def _mock_dlq_write(envelope):
        captured_dlq.append(envelope)

    with patch.dict("os.environ", env_without_url, clear=True):
        # Unset the key explicitly in case it was set by a previous test
        os.environ.pop("PHASE_91_UAE_URL", None)

        # Patch the DLQ writer inside the module
        with patch("core.alerts.phase91_emit._write_to_dlq", side_effect=_mock_dlq_write):
            # Must NOT raise — DLQ is the fallback
            emit_alert_candidate(
                alert_type="contradiction",
                producer_agent_id="vm107.macro_contradiction_detector",
                subject_id="CPIAUCSL",
                b13_internal_severity="info",
                explanation="Minor divergence captured for replay",
                citations=[],
                contradiction_id=uuid.uuid4(),
            )

    # DLQ captured the envelope
    assert len(captured_dlq) == 1, "DLQ must capture 1 envelope when URL is unset"
    dlq_envelope = captured_dlq[0]
    assert dlq_envelope["event_type"] == "alert_candidate_created"
    assert dlq_envelope["alert_type"] == "contradiction"


# ── Phase 91 Plan 1 — event_id idempotency contract ──────────────────────────

def test_phase91_event_id_auto_synthesised_when_omitted():
    """When caller omits event_id, emit_alert_candidate must synthesise one.

    Phase 91 schema v1.0 requires event_id. Auto-synthesis from sha256 of
    producer_agent_id + subject_id + created_at ensures backward-compat for
    existing callers (contradiction_engine, edge_proposer) that pre-date the
    event_id parameter.
    """
    from core.alerts.phase91_emit import emit_alert_candidate

    captured = []

    def _mock_post(url, *, json=None, **kwargs):
        captured.append(json)
        return MagicMock(status_code=201)

    with patch.dict("os.environ", {"PHASE_91_UAE_URL": "http://mock-phase91/alerts"}):
        with patch("core.alerts.phase91_emit.requests.post", side_effect=_mock_post):
            emit_alert_candidate(
                alert_type="contradiction",
                producer_agent_id="vm107.macro_contradiction_detector",
                subject_id="CPIAUCSL",
                b13_internal_severity="warning",
                explanation="auto event_id test",
                citations=[],
                contradiction_id=uuid.uuid4(),
            )

    assert len(captured) == 1
    envelope = captured[0]
    assert "event_id" in envelope
    assert len(envelope["event_id"]) >= 16
    assert envelope["schema_version"] == "1.0"


def test_phase91_event_id_uses_caller_supplied_value():
    """When caller supplies event_id explicitly, it is preserved verbatim."""
    from core.alerts.phase91_emit import emit_alert_candidate

    captured = []

    def _mock_post(url, *, json=None, **kwargs):
        captured.append(json)
        return MagicMock(status_code=201)

    fixed_id = "abcdef0123456789"

    with patch.dict("os.environ", {"PHASE_91_UAE_URL": "http://mock-phase91/alerts"}):
        with patch("core.alerts.phase91_emit.requests.post", side_effect=_mock_post):
            emit_alert_candidate(
                alert_type="discovery",
                producer_agent_id="vm107.macro_relationship_discovery",
                subject_id="DXY",
                b13_internal_severity=None,
                explanation="caller-supplied id test",
                citations=[],
                event_id=fixed_id,
            )

    assert captured[0]["event_id"] == fixed_id
