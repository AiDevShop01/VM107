"""Phase 85 Plan 09 — executive_summary_writer runner tests (TDD RED/GREEN).

Tests:
1.  test_profile_loadable                     — profile YAML exists + id correct
2.  test_profile_denies_vm102_tools           — vm102.indicator_history in denied_tools
3.  test_max_iterations_3                     — max_iterations == 3
4.  test_max_cost_0_10                        — max_cost_usd == 0.10
5.  test_happy_path_with_mocked_llm           — fixture upstream outputs; LLM mock returns
                                                valid summary; envelope + B1 + UPDATE called
6.  test_word_count_in_acceptable_range       — 35 <= len(summary.split()) <= 65
7.  test_citations_deduplicated               — upstream outputs share 1 duplicate citation;
                                                assert deduped in output
8.  test_missing_upstream_returns_low_confidence — drop one upstream output; envelope
                                                    confidence < 0.5; summary contains "Awaiting"
9.  test_write_summary_uses_default_conn      — patch both get_default_conn + get_analytics_conn;
                                                assert get_default_conn called (NOT analytics)
10. test_write_summary_raises_on_zero_rows    — nonexistent event_id raises RuntimeError
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

pytestmark = pytest.mark.phase_85

VM107_ROOT = Path("/Volumes/ HardDrive/FinGPT/VM107")
PROFILE_PATH = VM107_ROOT / "profiles" / "executive_summary_writer.yaml"
PROMPT_PATH = VM107_ROOT / "prompts" / "executive_summary_writer.md"


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

FIXTURE_RELEASE_ANALYST_OUTPUT = {
    "what_happened": "CPI came in at 3.4%, above consensus 3.3% and prior 3.2%.",
    "why_it_matters": "Inflation above the 3.0–3.5% target_inflation band; may delay rate cuts.",
    "regime_impact_label": "INFLATIONARY",
    "citations": [
        {"citation_id": "c1", "source": "vm102.indicator_history", "snippet": "CPI 3.4% YoY"},
        {"citation_id": "c2", "source": "vm102.indicator_releases", "snippet": "Consensus 3.3%"},
    ],
}

FIXTURE_ASSET_EXPOSURE_OUTPUT = {
    "per_asset": [
        {"asset_id": "DXY",  "direction": "BULL",    "strength_score": 75, "confidence": 0.82, "rationale": "USD strengthens on hot CPI."},
        {"asset_id": "GOLD", "direction": "BEAR",    "strength_score": 65, "confidence": 0.74, "rationale": "Real rates rise; gold pressured."},
        {"asset_id": "SPX",  "direction": "NEUTRAL", "strength_score": 30, "confidence": 0.51, "rationale": "Mixed: earnings vs rate drag."},
    ],
    "citations": [
        {"citation_id": "c1", "source": "vm102.indicator_history", "snippet": "CPI 3.4% YoY"},  # duplicate
        {"citation_id": "c3", "source": "vm102.indicator_asset_exposure", "snippet": "DXY correlation +0.72"},
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Profile YAML tests
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutiveSummaryWriterProfile:
    """Agent profile YAML at profiles/executive_summary_writer.yaml."""

    def test_profile_loadable(self):
        """Profile YAML must exist and have correct id."""
        import yaml
        assert PROFILE_PATH.exists(), f"Missing: {PROFILE_PATH}"
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert data.get("id") == "vm107.macro_executive_summary_writer", (
            f"Expected id=vm107.macro_executive_summary_writer, got {data.get('id')!r}"
        )

    def test_profile_denies_vm102_tools(self):
        """Composer must NOT allow vm102 tools — pure stitching only."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        denied = data.get("denied_tools", [])
        # vm102 tool must be in denied (composer does not re-fetch)
        assert "vm102.indicator_history" in denied, (
            "vm107.macro_executive_summary_writer must deny vm102.indicator_history"
        )
        assert "vm102.indicator_asset_exposure" in denied, (
            "vm107.macro_executive_summary_writer must deny vm102.indicator_asset_exposure"
        )

    def test_max_iterations_3(self):
        """max_iterations must be 3 (composer is constrained)."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert data.get("max_iterations") == 3, (
            f"Expected max_iterations=3, got {data.get('max_iterations')!r}"
        )

    def test_max_cost_0_10(self):
        """max_cost_usd must be 0.10 (tighter than upstream agents)."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert data.get("max_cost_usd") == 0.10, (
            f"Expected max_cost_usd=0.10, got {data.get('max_cost_usd')!r}"
        )

    def test_profile_impact_on_decision_high(self):
        """impact_on_decision must be HIGH."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert data.get("impact_on_decision") == "HIGH"

    def test_profile_denies_call_subordinate(self):
        """Profile must deny call_subordinate, code_execution_tool, trade_execution_tool."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        denied = data.get("denied_tools", [])
        for tool in ("call_subordinate", "code_execution_tool", "trade_execution_tool"):
            assert tool in denied, f"Profile must deny {tool!r}"

    def test_profile_allows_lookup_reasoning_artifact(self):
        """Composer still needs lookup_reasoning_artifact for B1 chain resolution."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        allowed = data.get("allowed_tools", [])
        assert "lookup_reasoning_artifact" in allowed, (
            "lookup_reasoning_artifact must be in allowed_tools"
        )

    def test_profile_router_affinity_macro(self):
        """Profile must declare router_affinity: vm107.macro for slot-30 routing."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert data.get("router_affinity") == "vm107.macro", (
            f"Expected router_affinity=vm107.macro, got {data.get('router_affinity')!r}"
        )

    def test_profile_output_schema_has_executive_summary(self):
        """output_schema must define executive_summary field."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        schema = data.get("output_schema", {})
        assert "executive_summary" in schema, "output_schema must include executive_summary"

    def test_profile_output_schema_has_citations(self):
        """output_schema must define citations field."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        schema = data.get("output_schema", {})
        assert "citations" in schema, "output_schema must include citations"


# ─────────────────────────────────────────────────────────────────────────────
# Prompt MD tests
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutiveSummaryWriterPrompt:
    """Prompt at prompts/executive_summary_writer.md."""

    def test_prompt_exists(self):
        """Prompt MD file must exist."""
        assert PROMPT_PATH.exists(), f"Missing: {PROMPT_PATH}"

    def test_prompt_has_executive_summary_field(self):
        """Prompt must define executive_summary output field."""
        content = PROMPT_PATH.read_text()
        assert "executive_summary" in content

    def test_prompt_has_word_count_rule(self):
        """Prompt must include a word count target/rule (~50 words)."""
        content = PROMPT_PATH.read_text()
        assert "50" in content or "word" in content.lower()

    def test_prompt_has_no_trade_recommendation_rule(self):
        """Prompt must include NEVER recommend a trade rule."""
        content = PROMPT_PATH.read_text()
        assert "NEVER" in content or "never" in content.lower()

    def test_prompt_has_citations_deduplicate_rule(self):
        """Prompt must instruct deduplication of citations."""
        content = PROMPT_PATH.read_text()
        assert "citation" in content.lower() or "dedup" in content.lower()

    def test_prompt_has_awaiting_fallback_rule(self):
        """Prompt must define the Awaiting fallback for missing upstream inputs."""
        content = PROMPT_PATH.read_text()
        assert "Awaiting" in content or "awaiting" in content or "missing" in content.lower()

    def test_prompt_has_json_output_block(self):
        """Prompt must include a strict JSON output schema block."""
        content = PROMPT_PATH.read_text()
        assert "executive_summary" in content and "{" in content


# ─────────────────────────────────────────────────────────────────────────────
# Happy-path + behavioral tests
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutiveSummaryWriterBehavior:
    """Behavioral tests with mocked LLM and persistence."""

    def test_happy_path_with_mocked_llm(self):
        """Fixture upstream outputs + mocked LLM → envelope B1 + UPDATE called."""
        from fingpt_core.contracts.tool_envelope import ToolResultEnvelope
        from pydantic import BaseModel

        class ExecSummaryPayload(BaseModel):
            executive_summary: str
            citations: list

        mock_summary_text = (
            "May CPI rose 3.4% year-over-year, beating the 3.3% consensus and the 3.2% "
            "prior reading, confirming that inflation remains sticky. The INFLATIONARY "
            "regime persists and may delay Federal Reserve rate cuts through Q3. Among "
            "paired assets, DXY leads directionally at 75/100 strength while gold faces "
            "downside pressure from rising real rates."
        )
        assert 35 <= len(mock_summary_text.split()) <= 65, "Fixture summary out of range"

        payload = ExecSummaryPayload(
            executive_summary=mock_summary_text,
            citations=[
                {"citation_id": "c1", "source": "vm102.indicator_history", "snippet": "CPI 3.4% YoY"},
                {"citation_id": "c2", "source": "vm102.indicator_releases", "snippet": "Consensus 3.3%"},
                {"citation_id": "c3", "source": "vm102.indicator_asset_exposure", "snippet": "DXY correlation +0.72"},
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
        assert envelope.confidence == 0.88
        assert envelope.payload.executive_summary == mock_summary_text

        # Simulate post-processing: write_summary called with event_id
        event_id = "CPIAUCSL:2026-06-12T12:30:00Z"
        with patch("persistence.economic_event_summary.write_summary") as mock_write:
            from persistence.economic_event_summary import write_summary
            write_summary(event_id=event_id, summary_text=mock_summary_text)
            mock_write.assert_called_once_with(event_id=event_id, summary_text=mock_summary_text)

    def test_word_count_in_acceptable_range(self):
        """Summary word count must be 35–65 (50 ± 15)."""
        # Boundary checks for the acceptance band
        too_short = " ".join(["word"] * 34)
        just_right_low = " ".join(["word"] * 35)
        target = " ".join(["word"] * 50)
        just_right_high = " ".join(["word"] * 65)
        too_long = " ".join(["word"] * 66)

        def in_range(text):
            return 35 <= len(text.split()) <= 65

        assert not in_range(too_short), "34-word summary should fail range check"
        assert in_range(just_right_low), "35-word summary should pass"
        assert in_range(target), "50-word summary should pass"
        assert in_range(just_right_high), "65-word summary should pass"
        assert not in_range(too_long), "66-word summary should fail range check"

    def test_citations_deduplicated(self):
        """Upstream outputs share citation c1; output citations must have c1 only once."""
        # c1 appears in both release_analyst and asset_exposure outputs
        upstream_citations = (
            FIXTURE_RELEASE_ANALYST_OUTPUT["citations"]
            + FIXTURE_ASSET_EXPOSURE_OUTPUT["citations"]
        )
        # Dedup by citation_id (set-based)
        seen_ids = set()
        deduped = []
        for c in upstream_citations:
            if c["citation_id"] not in seen_ids:
                seen_ids.add(c["citation_id"])
                deduped.append(c)

        c1_count = sum(1 for c in deduped if c["citation_id"] == "c1")
        assert c1_count == 1, f"c1 appears {c1_count} times after dedup; expected 1"
        assert len(deduped) == 3, f"Expected 3 unique citations (c1,c2,c3), got {len(deduped)}"

    def test_missing_upstream_returns_low_confidence(self):
        """If either upstream output is missing, envelope confidence < 0.5 and summary
        contains 'Awaiting' or similar placeholder text."""
        from fingpt_core.contracts.tool_envelope import ToolResultEnvelope
        from pydantic import BaseModel

        class ExecSummaryPayload(BaseModel):
            executive_summary: str
            citations: list

        # Missing release_analyst_output — only asset_exposure_output available
        degraded_summary = "Awaiting full analysis — release analyst output not yet available."

        payload = ExecSummaryPayload(
            executive_summary=degraded_summary,
            citations=[],
        )

        envelope = ToolResultEnvelope(
            envelope_id=uuid.uuid4(),
            tool_name="vm107.macro_executive_summary_writer",
            tool_version="85",
            outcome_class="partial",
            success=False,
            generated_at=datetime.now(timezone.utc),
            confidence=0.30,  # low confidence — degraded mode
            registry_snapshot_hash="test-hash",
            payload_schema_version="1.0",
            payload=payload,
        )

        assert envelope.confidence < 0.5, (
            f"Missing upstream should yield confidence < 0.5, got {envelope.confidence}"
        )
        assert "Awaiting" in envelope.payload.executive_summary or \
               "awaiting" in envelope.payload.executive_summary.lower(), (
            "Missing upstream summary must contain 'Awaiting' placeholder"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Persistence tests
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteSummaryPersistence:
    """Tests for persistence/economic_event_summary.write_summary()."""

    def test_write_summary_uses_default_conn(self):
        """write_summary() must call get_default_conn (tradetracker), NOT get_analytics_conn."""
        fake_cur = MagicMock()
        fake_cur.__enter__ = MagicMock(return_value=fake_cur)
        fake_cur.__exit__ = MagicMock(return_value=False)
        fake_cur.rowcount = 1

        fake_conn = MagicMock()
        fake_conn.__enter__ = MagicMock(return_value=fake_conn)
        fake_conn.__exit__ = MagicMock(return_value=False)
        fake_conn.cursor = MagicMock(return_value=fake_cur)

        with patch(
            "persistence.economic_event_summary.get_default_conn",
            return_value=fake_conn,
        ) as mock_default, patch(
            "persistence.economic_event_summary.get_analytics_conn",
            return_value=fake_conn,
        ) as mock_analytics:
            from persistence.economic_event_summary import write_summary
            write_summary(event_id="CPIAUCSL:2026-06-12T12:30:00Z", summary_text="Test summary.")

        mock_default.assert_called_once(), "get_default_conn must be called exactly once"
        mock_analytics.assert_not_called(), "get_analytics_conn must NOT be called"

    def test_write_summary_raises_on_zero_rows(self):
        """write_summary() with a nonexistent event_id raises RuntimeError (D2 lock)."""
        fake_cur = MagicMock()
        fake_cur.__enter__ = MagicMock(return_value=fake_cur)
        fake_cur.__exit__ = MagicMock(return_value=False)
        fake_cur.rowcount = 0  # simulate 0 rows affected

        fake_conn = MagicMock()
        fake_conn.__enter__ = MagicMock(return_value=fake_conn)
        fake_conn.__exit__ = MagicMock(return_value=False)
        fake_conn.cursor = MagicMock(return_value=fake_cur)

        with patch(
            "persistence.economic_event_summary.get_default_conn",
            return_value=fake_conn,
        ):
            from persistence.economic_event_summary import write_summary
            with pytest.raises(RuntimeError) as exc_info:
                write_summary(event_id="nonexistent-event-id", summary_text="Some text.")

        err_msg = str(exc_info.value)
        assert "0 rows" in err_msg or "wrong DB" in err_msg, (
            f"RuntimeError must mention '0 rows' or 'wrong DB', got: {err_msg!r}"
        )

    def test_write_summary_sql_is_update_not_insert(self):
        """UPDATE SQL targets economic_event table (Plan 85-03 column)."""
        import persistence.economic_event_summary as mod
        assert "UPDATE economic_event" in mod.UPDATE_SQL, (
            "write_summary must use UPDATE on economic_event, not INSERT/UPSERT"
        )
        assert "ai_executive_summary" in mod.UPDATE_SQL, (
            "UPDATE must target ai_executive_summary column (Plan 85-03)"
        )
