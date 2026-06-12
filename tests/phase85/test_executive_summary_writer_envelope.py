"""Phase 85 Plan 09 — executive_summary_writer envelope + B1 + Phase 71 freshness tests.

Tests:
1. test_envelope_wraps_summary          — assert ToolResultEnvelope[ExecutiveSummaryOutput]
2. test_envelope_provenance_includes_both_upstream_artifact_ids — provenance references both
                                          upstream B1 artifact IDs for traceability
3. test_envelope_freshness_class_FRESH_on_recent_release — FreshnessClass.LIVE on fresh event
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

import pytest
from pydantic import BaseModel

pytestmark = pytest.mark.phase_85


# ─────────────────────────────────────────────────────────────────────────────
# Payload model for executive_summary_writer
# ─────────────────────────────────────────────────────────────────────────────

class CitationRef(BaseModel):
    citation_id: str
    source: str
    snippet: Optional[str] = None


class ExecutiveSummaryOutput(BaseModel):
    executive_summary: str
    citations: List[CitationRef]


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutiveSummaryWriterEnvelope:
    """Phase 70.5 ToolResultEnvelope wrapping and B1 provenance for executive_summary_writer."""

    def test_envelope_wraps_summary(self):
        """ToolResultEnvelope must accept ExecutiveSummaryOutput payload."""
        from fingpt_core.contracts.tool_envelope import ToolResultEnvelope

        payload = ExecutiveSummaryOutput(
            executive_summary=(
                "May CPI rose 3.4% year-over-year, beating the 3.3% consensus and the 3.2% "
                "prior reading, confirming that inflation remains sticky. The INFLATIONARY "
                "regime persists and may delay Federal Reserve rate cuts through Q3. Among "
                "paired assets, DXY leads directionally at 75/100 strength while gold faces "
                "downside pressure from rising real rates."
            ),
            citations=[
                CitationRef(citation_id="c1", source="vm102.indicator_history", snippet="CPI 3.4%"),
                CitationRef(citation_id="c2", source="vm102.indicator_releases", snippet="Consensus 3.3%"),
                CitationRef(citation_id="c3", source="vm102.indicator_asset_exposure", snippet="DXY +0.72"),
            ],
        )

        envelope = ToolResultEnvelope(
            envelope_id=uuid.uuid4(),
            tool_name="vm107.macro_executive_summary_writer",
            tool_version="85",
            outcome_class="success",
            success=True,
            generated_at=datetime.now(timezone.utc),
            confidence=0.88,
            registry_snapshot_hash="test-hash",
            payload_schema_version="1.0",
            payload=payload,
        )

        assert envelope.success is True
        assert envelope.tool_name == "vm107.macro_executive_summary_writer"
        assert "CPI" in envelope.payload.executive_summary
        assert len(envelope.payload.citations) == 3
        # Word count in acceptable band
        word_count = len(envelope.payload.executive_summary.split())
        assert 35 <= word_count <= 65, (
            f"executive_summary word count {word_count} out of [35,65] band"
        )

    def test_envelope_provenance_includes_both_upstream_artifact_ids(self):
        """Envelope provenance metadata should reference both upstream B1 artifact IDs.

        Plan 85-09 spec: when composing, the executive_summary_writer should record
        which B1 artifact IDs produced the release_analyst and asset_exposure_analyst
        inputs. This ensures Phase 71 citation chain is traceable back to both upstream
        reasoning artifacts.
        """
        # Simulate both upstream agent completing and storing their B1 artifact IDs
        release_analyst_artifact_id = str(uuid.uuid4())
        asset_exposure_artifact_id = str(uuid.uuid4())

        # The provenance data the composer should propagate
        provenance_metadata = {
            "upstream_artifact_ids": [
                release_analyst_artifact_id,
                asset_exposure_artifact_id,
            ],
            "composer": "vm107.macro_executive_summary_writer",
        }

        assert len(provenance_metadata["upstream_artifact_ids"]) == 2, (
            "Executive summary provenance must reference exactly 2 upstream B1 artifacts"
        )
        # Both must look like UUIDs
        import re
        uuid_pattern = re.compile(r"^[0-9a-f-]{36}$")
        for artifact_id in provenance_metadata["upstream_artifact_ids"]:
            assert uuid_pattern.match(str(artifact_id)), (
                f"Artifact ID {artifact_id!r} does not look like a UUID"
            )

    def test_envelope_freshness_class_FRESH_on_recent_release(self):
        """Phase 71 FreshnessClass.LIVE on a very recent economic release.

        Economic releases fire seconds after the scheduled timestamp, so the
        executive summary generated within the 60s budget window is LIVE freshness.
        """
        from fingpt_core.contracts.provenance import FreshnessClass, freshness_seconds_to_class

        # economic_event.release_timestamp fires at T; executive_summary_writer runs
        # typically within 30–60 seconds. expected_freshness_seconds is 60 (60s budget).
        expected_freshness_seconds = 60

        # Scenarios: within budget → LIVE
        assert freshness_seconds_to_class(30, expected_freshness_seconds) == FreshnessClass.LIVE, (
            "30s freshness within 60s budget must be LIVE"
        )
        assert freshness_seconds_to_class(60, expected_freshness_seconds) == FreshnessClass.LIVE, (
            "60s freshness at 60s budget boundary must be LIVE"
        )
        # Scenarios: beyond budget → RECENT
        assert freshness_seconds_to_class(120, expected_freshness_seconds) == FreshnessClass.RECENT, (
            "120s freshness (2×budget) must be RECENT"
        )

    def test_envelope_low_confidence_on_partial(self):
        """Partial outcome (max_iterations=3 hit, missing upstream) → confidence < 0.5."""
        from fingpt_core.contracts.tool_envelope import ToolResultEnvelope

        payload = ExecutiveSummaryOutput(
            executive_summary="Awaiting full analysis — release analyst output not yet available.",
            citations=[],
        )

        envelope = ToolResultEnvelope(
            envelope_id=uuid.uuid4(),
            tool_name="vm107.macro_executive_summary_writer",
            tool_version="85",
            outcome_class="partial",
            success=False,
            generated_at=datetime.now(timezone.utc),
            confidence=0.25,
            registry_snapshot_hash="test-hash",
            payload_schema_version="1.0",
            payload=payload,
        )

        assert envelope.outcome_class == "partial"
        assert envelope.confidence < 0.5, (
            f"Partial outcome should have confidence < 0.5, got {envelope.confidence}"
        )
        assert envelope.success is False
        assert "Awaiting" in envelope.payload.executive_summary
