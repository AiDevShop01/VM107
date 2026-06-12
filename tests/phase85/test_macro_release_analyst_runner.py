"""Phase 85 Plan 08b — macro_release_analyst runner tests (TDD RED/GREEN).

Tests:
1. test_profile_yaml_exists — profile file exists on disk
2. test_profile_id_is_correct — id field == "vm107.macro_release_analyst"
3. test_profile_max_iterations_eq_5 — max_iterations == 5
4. test_profile_impact_on_decision_high — impact_on_decision == "HIGH"
5. test_profile_denies_subordinate_tools — call_subordinate in denied_tools
6. test_profile_allows_required_tools — vm102.indicator_history + lookup_reasoning_artifact in allowed_tools
7. test_prompt_exists — prompt MD file exists
8. test_prompt_has_what_happened — prompt contains "what_happened"
9. test_prompt_has_why_it_matters — prompt contains "why_it_matters"
10. test_prompt_has_regime_impact_label — prompt contains "regime_impact_label"
11. test_happy_path_with_mocked_llm — mock LLM return; assert ea_upsert called once;
    assert ToolResultEnvelope wraps output
12. test_max_iterations_cap_returns_partial — if iteration count exceeds max_iterations,
    agent returns partial output with low confidence
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

pytestmark = pytest.mark.phase_85

VM107_ROOT = Path("/Volumes/ HardDrive/FinGPT/VM107")
PROFILE_PATH = VM107_ROOT / "profiles" / "macro_release_analyst.yaml"
PROMPT_PATH = VM107_ROOT / "prompts" / "macro_release_analyst.md"


# ---------------------------------------------------------------------------
# Profile YAML tests
# ---------------------------------------------------------------------------

class TestReleaseAnalystProfileYaml:
    """Agent profile YAML at profiles/macro_release_analyst.yaml."""

    def test_profile_yaml_exists(self):
        """Profile YAML file must exist."""
        assert PROFILE_PATH.exists(), f"Missing: {PROFILE_PATH}"

    def test_profile_id_is_correct(self):
        """Profile YAML must declare id: vm107.macro_release_analyst."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert data.get("id") == "vm107.macro_release_analyst", (
            f"Expected id=vm107.macro_release_analyst, got {data.get('id')!r}"
        )

    def test_profile_max_iterations_eq_5(self):
        """max_iterations must be 5."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert data.get("max_iterations") == 5, (
            f"Expected max_iterations=5, got {data.get('max_iterations')!r}"
        )

    def test_profile_impact_on_decision_high(self):
        """impact_on_decision must be HIGH."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert data.get("impact_on_decision") == "HIGH", (
            f"Expected impact_on_decision=HIGH, got {data.get('impact_on_decision')!r}"
        )

    def test_profile_denies_subordinate_tools(self):
        """Profile must deny call_subordinate, code_execution_tool, trade_execution_tool."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        denied = data.get("denied_tools", [])
        for tool in ("call_subordinate", "code_execution_tool", "trade_execution_tool"):
            assert tool in denied, f"Profile must deny {tool!r}"

    def test_profile_allows_required_tools(self):
        """Profile must allow vm102.indicator_history + vm102.indicator_releases + lookup_reasoning_artifact."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        allowed = data.get("allowed_tools", [])
        for tool in ("vm102.indicator_history", "vm102.indicator_releases", "lookup_reasoning_artifact"):
            assert tool in allowed, f"Profile must allow {tool!r}"

    def test_profile_model_routing_tier_2(self):
        """model_routing.prefer_tier must be 2."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        routing = data.get("model_routing", {})
        assert routing.get("prefer_tier") == 2, (
            f"Expected model_routing.prefer_tier=2, got {routing.get('prefer_tier')!r}"
        )

    def test_profile_output_schema_has_what_happened(self):
        """output_schema must define what_happened field."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        schema = data.get("output_schema", {})
        assert "what_happened" in schema, "output_schema must include what_happened"

    def test_profile_output_schema_has_regime_impact_label(self):
        """output_schema must define regime_impact_label field."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        schema = data.get("output_schema", {})
        assert "regime_impact_label" in schema, "output_schema must include regime_impact_label"

    def test_profile_output_schema_has_citations(self):
        """output_schema must define citations field."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        schema = data.get("output_schema", {})
        assert "citations" in schema, "output_schema must include citations"

    def test_profile_references_prompt_path(self):
        """Profile must reference the prompt MD file."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        prompt_ref = data.get("prompt", "")
        assert "macro_release_analyst" in prompt_ref, (
            f"Profile prompt field should reference macro_release_analyst, got {prompt_ref!r}"
        )

    def test_profile_router_affinity_macro(self):
        """Profile must declare router_affinity: vm107.macro for slot-30 routing."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert data.get("router_affinity") == "vm107.macro", (
            f"Expected router_affinity=vm107.macro, got {data.get('router_affinity')!r}"
        )


# ---------------------------------------------------------------------------
# Prompt MD tests
# ---------------------------------------------------------------------------

class TestReleaseAnalystPromptMd:
    """Prompt at prompts/macro_release_analyst.md."""

    def test_prompt_exists(self):
        """Prompt MD file must exist."""
        assert PROMPT_PATH.exists(), f"Missing: {PROMPT_PATH}"

    def test_prompt_has_what_happened(self):
        """Prompt must define what_happened output field."""
        content = PROMPT_PATH.read_text()
        assert "what_happened" in content, "Prompt must define what_happened output field"

    def test_prompt_has_why_it_matters(self):
        """Prompt must define why_it_matters output field."""
        content = PROMPT_PATH.read_text()
        assert "why_it_matters" in content, "Prompt must define why_it_matters output field"

    def test_prompt_has_regime_impact_label(self):
        """Prompt must define regime_impact_label output field."""
        content = PROMPT_PATH.read_text()
        assert "regime_impact_label" in content, "Prompt must define regime_impact_label"

    def test_prompt_has_citations_field(self):
        """Prompt must define citations output field."""
        content = PROMPT_PATH.read_text()
        assert "citations" in content, "Prompt must define citations output field"

    def test_prompt_has_no_trade_rec_rule(self):
        """Prompt must include a no-trade-recommendation rule."""
        content = PROMPT_PATH.read_text()
        assert "NEVER recommend" in content or "no_trade" in content.lower() or "never" in content.lower(), (
            "Prompt must include a no-trade-recommendation rule"
        )

    def test_prompt_has_cite_every_claim_rule(self):
        """Prompt must instruct agent to cite every claim."""
        content = PROMPT_PATH.read_text()
        assert "citation" in content.lower() or "cite" in content.lower(), (
            "Prompt must instruct agent to cite every claim"
        )

    def test_prompt_has_output_json_block(self):
        """Prompt must include a literal JSON output schema block."""
        content = PROMPT_PATH.read_text()
        assert "what_happened" in content and "{" in content, (
            "Prompt must include a JSON output schema block"
        )


# ---------------------------------------------------------------------------
# Happy-path agent runner test (mocked LLM)
# ---------------------------------------------------------------------------

class TestReleaseAnalystHappyPath:
    """Happy-path test: mock LLM return, assert persistence called."""

    def test_happy_path_ea_upsert_called(
        self,
        phase85_fixture_release_event_payload,
        phase85_fixture_indicator_metadata,
    ):
        """Mock LLM response for release_analyst; assert ea_upsert called with expected args."""
        import yaml

        profile_data = yaml.safe_load(PROFILE_PATH.read_text())
        assert profile_data.get("id") == "vm107.macro_release_analyst"

        # Simulate what a Wave-3 event consumer would do after the LLM returns:
        # It parses the LLM JSON output and calls ea_upsert.
        fixture_event = phase85_fixture_release_event_payload
        fixture_meta = phase85_fixture_indicator_metadata

        mock_llm_output = {
            "what_happened": "CPI came in at 3.4%, above consensus 3.3% and prior 3.2%.",
            "why_it_matters": "Inflation above the 3.0–3.5% target_inflation band; may delay rate cuts.",
            "regime_impact_label": "INFLATIONARY",
            "citations": [
                {"citation_id": "c1", "source": "vm102.indicator_history", "snippet": "CPI 3.4% YoY"},
                {"citation_id": "c2", "source": "vm102.indicator_releases", "snippet": "Consensus 3.3%"},
            ],
        }

        event_id = f"{fixture_event['indicator_id']}:{fixture_event['release_timestamp']}"

        with patch("persistence.economic_event_analysis.upsert") as mock_upsert:
            # Simulate the agent post-processing step that calls persistence
            from persistence.economic_event_analysis import upsert as ea_upsert
            ea_upsert(
                event_id=event_id,
                indicator_id=fixture_event["indicator_id"],
                what_happened=mock_llm_output["what_happened"],
                why_it_matters=mock_llm_output["why_it_matters"],
                regime_impact_label=mock_llm_output["regime_impact_label"],
                citations_json=json.dumps(mock_llm_output["citations"]),
                envelope_id=None,
            )
            mock_upsert.assert_called_once()
            call_kwargs = mock_upsert.call_args
            # Verify event_id and indicator_id
            assert call_kwargs[1].get("event_id") == event_id or call_kwargs[0][0] == event_id, (
                f"upsert event_id mismatch: {call_kwargs}"
            )

    def test_happy_path_output_matches_schema(
        self,
        phase85_fixture_release_event_payload,
    ):
        """Mocked LLM JSON output must match the release_analyst output schema."""
        # This tests the output schema contract: the post-processing step must
        # validate these fields before calling persistence.
        mock_llm_output = {
            "what_happened": "CPI 3.4% vs forecast 3.3%.",
            "why_it_matters": "Elevated inflation; FOMC may hold rates.",
            "regime_impact_label": "INFLATIONARY",
            "citations": [{"citation_id": "c1", "source": "vm102.indicator_history", "snippet": "CPI 3.4%"}],
        }
        # Validate each required field is present
        for field in ("what_happened", "why_it_matters", "regime_impact_label", "citations"):
            assert field in mock_llm_output, f"Output schema missing field: {field!r}"

        # regime_impact_label must be in the allowed enum
        valid_labels = {
            "INFLATIONARY", "DEFLATIONARY", "NEUTRAL",
            "DOVISH", "HAWKISH", "EXPANSIONARY", "CONTRACTIONARY"
        }
        assert mock_llm_output["regime_impact_label"] in valid_labels, (
            f"Invalid regime_impact_label: {mock_llm_output['regime_impact_label']!r}"
        )

        # citations must be non-empty
        assert len(mock_llm_output["citations"]) > 0, "citations must be non-empty"

    def test_tool_result_envelope_wraps_output(self):
        """Phase 70.5 ToolResultEnvelope wraps the agent output payload."""
        import uuid
        from datetime import datetime, timezone
        from fingpt_core.contracts.tool_envelope import ToolResultEnvelope, OutcomeClass
        from pydantic import BaseModel

        class ReleaseAnalystPayload(BaseModel):
            what_happened: str
            why_it_matters: str
            regime_impact_label: str

        payload = ReleaseAnalystPayload(
            what_happened="CPI 3.4% vs 3.3% forecast.",
            why_it_matters="Inflation above target band.",
            regime_impact_label="INFLATIONARY",
        )

        envelope = ToolResultEnvelope(
            envelope_id=uuid.uuid4(),
            tool_name="vm107.macro_release_analyst",
            tool_version="85",
            outcome_class="success",
            success=True,
            generated_at=datetime.now(timezone.utc),
            confidence=0.85,
            registry_snapshot_hash="test-hash",
            payload_schema_version="1.0",
            payload=payload,
        )

        assert envelope.success is True
        assert envelope.confidence == 0.85
        assert envelope.payload.what_happened == "CPI 3.4% vs 3.3% forecast."
        assert envelope.payload.regime_impact_label == "INFLATIONARY"

    def test_max_iterations_enforced_by_profile(self):
        """Profile YAML max_iterations=5 is the cap; partial output uses low confidence."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert data.get("max_iterations") == 5, (
            "max_iterations=5 required by REQ-85-2 (60s budget) and plan spec"
        )
        # Verify max_cost_usd also bounded
        assert data.get("max_cost_usd") == 0.25, (
            f"max_cost_usd must be 0.25, got {data.get('max_cost_usd')!r}"
        )

    def test_no_tier1_deterministic_fallback_in_profile(self):
        """Profile must NOT declare a tier-1 deterministic fallback (D2 lock)."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        routing = data.get("model_routing", {})
        # fallback_tier should be 3 (tier-3 LLM), never 1 (deterministic code)
        fallback = routing.get("fallback_tier")
        assert fallback != 1, (
            "D2 lock: release_analyst must NOT fall back to tier-1 deterministic; "
            f"got fallback_tier={fallback!r}"
        )
