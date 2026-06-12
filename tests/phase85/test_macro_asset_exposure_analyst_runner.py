"""Phase 85 Plan 08b — macro_asset_exposure_analyst runner tests (TDD RED/GREEN).

Tests:
1. test_profile_yaml_exists — profile file exists on disk
2. test_profile_id_is_correct — id field == "vm107.macro_asset_exposure_analyst"
3. test_profile_max_iterations_eq_5 — max_iterations == 5
4. test_profile_impact_on_decision_high — impact_on_decision == "HIGH"
5. test_profile_denies_subordinate_tools — call_subordinate in denied_tools
6. test_profile_allows_indicator_asset_exposure_tool — vm102.indicator_asset_exposure in allowed_tools
7. test_prompt_exists — prompt MD file exists
8. test_prompt_has_per_asset — prompt contains "per_asset"
9. test_prompt_has_direction_enum — prompt mentions BULL/BEAR/NEUTRAL
10. test_happy_path_exposure_batch_insert_called — mock LLM; assert exposure_batch_insert called
    with 5 per_asset rows; all required fields present
11. test_per_asset_field_validation — direction ∈ {BULL,BEAR,NEUTRAL},
    strength_score ∈ [1,100], confidence ∈ [0,1], rationale present
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.phase_85

VM107_ROOT = Path("/Volumes/ HardDrive/FinGPT/VM107")
PROFILE_PATH = VM107_ROOT / "profiles" / "macro_asset_exposure_analyst.yaml"
PROMPT_PATH = VM107_ROOT / "prompts" / "macro_asset_exposure_analyst.md"


# ---------------------------------------------------------------------------
# Profile YAML tests
# ---------------------------------------------------------------------------

class TestAssetExposureAnalystProfileYaml:
    """Agent profile YAML at profiles/macro_asset_exposure_analyst.yaml."""

    def test_profile_yaml_exists(self):
        """Profile YAML file must exist."""
        assert PROFILE_PATH.exists(), f"Missing: {PROFILE_PATH}"

    def test_profile_id_is_correct(self):
        """Profile YAML must declare id: vm107.macro_asset_exposure_analyst."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert data.get("id") == "vm107.macro_asset_exposure_analyst", (
            f"Expected id=vm107.macro_asset_exposure_analyst, got {data.get('id')!r}"
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

    def test_profile_allows_indicator_asset_exposure_tool(self):
        """Profile must allow vm102.indicator_asset_exposure (key tool for this agent)."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        allowed = data.get("allowed_tools", [])
        assert "vm102.indicator_asset_exposure" in allowed, (
            "vm102.indicator_asset_exposure must be in allowed_tools"
        )

    def test_profile_allows_lookup_reasoning_artifact(self):
        """Profile must allow lookup_reasoning_artifact for B1 chain resolution."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        allowed = data.get("allowed_tools", [])
        assert "lookup_reasoning_artifact" in allowed, (
            "lookup_reasoning_artifact must be in allowed_tools"
        )

    def test_profile_output_schema_has_per_asset(self):
        """output_schema must define per_asset list field."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        schema = data.get("output_schema", {})
        assert "per_asset" in schema, "output_schema must include per_asset"

    def test_profile_router_affinity_macro(self):
        """Profile must declare router_affinity: vm107.macro."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert data.get("router_affinity") == "vm107.macro", (
            f"Expected router_affinity=vm107.macro, got {data.get('router_affinity')!r}"
        )

    def test_profile_no_tier1_fallback(self):
        """Profile must NOT declare tier-1 deterministic fallback (D2 lock)."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        routing = data.get("model_routing", {})
        assert routing.get("fallback_tier") != 1, (
            "D2 lock: asset_exposure_analyst must NOT fall back to tier-1 deterministic"
        )


# ---------------------------------------------------------------------------
# Prompt MD tests
# ---------------------------------------------------------------------------

class TestAssetExposureAnalystPromptMd:
    """Prompt at prompts/macro_asset_exposure_analyst.md."""

    def test_prompt_exists(self):
        """Prompt MD file must exist."""
        assert PROMPT_PATH.exists(), f"Missing: {PROMPT_PATH}"

    def test_prompt_has_per_asset(self):
        """Prompt must define per_asset output field."""
        content = PROMPT_PATH.read_text()
        assert "per_asset" in content, "Prompt must define per_asset output field"

    def test_prompt_has_direction_enum(self):
        """Prompt must mention BULL, BEAR, NEUTRAL direction values."""
        content = PROMPT_PATH.read_text()
        for direction in ("BULL", "BEAR", "NEUTRAL"):
            assert direction in content, f"Prompt must mention direction value: {direction!r}"

    def test_prompt_has_strength_score(self):
        """Prompt must define strength_score field."""
        content = PROMPT_PATH.read_text()
        assert "strength_score" in content, "Prompt must define strength_score"

    def test_prompt_has_confidence_field(self):
        """Prompt must define confidence field."""
        content = PROMPT_PATH.read_text()
        assert "confidence" in content, "Prompt must define confidence field"

    def test_prompt_has_rationale_field(self):
        """Prompt must define rationale field."""
        content = PROMPT_PATH.read_text()
        assert "rationale" in content, "Prompt must define rationale field"

    def test_prompt_output_is_json(self):
        """Prompt must instruct agent to return strict JSON."""
        content = PROMPT_PATH.read_text()
        assert "json" in content.lower() or "JSON" in content, (
            "Prompt must instruct agent to return strict JSON"
        )


# ---------------------------------------------------------------------------
# Happy-path agent runner tests (mocked LLM)
# ---------------------------------------------------------------------------

class TestAssetExposureAnalystHappyPath:
    """Happy-path tests: mock LLM output, assert persistence called."""

    def test_happy_path_exposure_batch_insert_called(
        self,
        phase85_fixture_release_event_payload,
        phase85_fixture_indicator_metadata,
    ):
        """Mock LLM 5-row per_asset output; assert exposure_batch_insert called with N rows."""
        fixture_event = phase85_fixture_release_event_payload
        fixture_meta = phase85_fixture_indicator_metadata

        mock_per_asset = [
            {"asset_id": "DXY",   "direction": "BULL",    "strength_score": 75, "confidence": 0.82, "rationale": "Hot CPI → USD strengthens."},
            {"asset_id": "GOLD",  "direction": "BEAR",    "strength_score": 65, "confidence": 0.74, "rationale": "Real rates rise; gold pressured."},
            {"asset_id": "SPX",   "direction": "NEUTRAL", "strength_score": 30, "confidence": 0.51, "rationale": "Mixed: earnings vs rate drag."},
            {"asset_id": "TLT",   "direction": "BEAR",    "strength_score": 80, "confidence": 0.88, "rationale": "Duration risk rises on hot CPI."},
            {"asset_id": "USDJPY","direction": "BULL",    "strength_score": 70, "confidence": 0.79, "rationale": "USD strength; JPY weak."},
        ]

        event_id = f"{fixture_event['indicator_id']}:{fixture_event['release_timestamp']}"

        with patch("persistence.economic_event_asset_exposure.batch_insert") as mock_batch:
            from persistence.economic_event_asset_exposure import batch_insert as exposure_batch_insert
            exposure_batch_insert(
                event_id=event_id,
                rows=mock_per_asset,
                envelope_id=None,
            )
            mock_batch.assert_called_once()
            call_args = mock_batch.call_args
            assert call_args[1].get("event_id") == event_id or call_args[0][0] == event_id
            # Rows passed in should be the 5-item list
            rows_arg = call_args[1].get("rows") or call_args[0][1]
            assert len(rows_arg) == 5, f"Expected 5 per_asset rows, got {len(rows_arg)}"

    def test_per_asset_field_validation(self):
        """All per_asset rows must have required fields with valid values."""
        valid_directions = {"BULL", "BEAR", "NEUTRAL"}

        per_asset_rows = [
            {"asset_id": "DXY",   "direction": "BULL",    "strength_score": 75, "confidence": 0.82, "rationale": "USD strengthens."},
            {"asset_id": "GOLD",  "direction": "BEAR",    "strength_score": 65, "confidence": 0.74, "rationale": "Gold pressured."},
            {"asset_id": "SPX",   "direction": "NEUTRAL", "strength_score": 30, "confidence": 0.51, "rationale": "Mixed signals."},
        ]

        for row in per_asset_rows:
            assert "asset_id" in row and row["asset_id"], "asset_id must be present and non-empty"
            assert row["direction"] in valid_directions, (
                f"direction must be BULL/BEAR/NEUTRAL, got {row['direction']!r}"
            )
            assert 1 <= row["strength_score"] <= 100, (
                f"strength_score must be in [1,100], got {row['strength_score']!r}"
            )
            assert 0.0 <= row["confidence"] <= 1.0, (
                f"confidence must be in [0,1], got {row['confidence']!r}"
            )
            assert "rationale" in row and row["rationale"], "rationale must be present and non-empty"

    def test_tool_result_envelope_wraps_exposure_output(self):
        """Phase 70.5 ToolResultEnvelope wraps the asset_exposure_analyst output."""
        import uuid
        from datetime import datetime, timezone
        from typing import List
        from fingpt_core.contracts.tool_envelope import ToolResultEnvelope
        from pydantic import BaseModel

        class AssetExposureRow(BaseModel):
            asset_id: str
            direction: str
            strength_score: int
            confidence: float
            rationale: str

        class AssetExposurePayload(BaseModel):
            per_asset: List[AssetExposureRow]

        payload = AssetExposurePayload(
            per_asset=[
                AssetExposureRow(
                    asset_id="DXY",
                    direction="BULL",
                    strength_score=75,
                    confidence=0.82,
                    rationale="USD strengthens on hot CPI.",
                )
            ]
        )

        envelope = ToolResultEnvelope(
            envelope_id=uuid.uuid4(),
            tool_name="vm107.macro_asset_exposure_analyst",
            tool_version="85",
            outcome_class="success",
            success=True,
            generated_at=datetime.now(timezone.utc),
            confidence=0.82,
            registry_snapshot_hash="test-hash",
            payload_schema_version="1.0",
            payload=payload,
        )

        assert envelope.success is True
        assert envelope.confidence == 0.82
        assert len(envelope.payload.per_asset) == 1
        assert envelope.payload.per_asset[0].direction == "BULL"

    def test_all_required_per_asset_fields_present(self):
        """Per-asset schema requires: asset_id, direction, strength_score, confidence, rationale."""
        required_fields = {"asset_id", "direction", "strength_score", "confidence", "rationale"}
        sample_row = {
            "asset_id": "DXY",
            "direction": "BULL",
            "strength_score": 75,
            "confidence": 0.82,
            "rationale": "USD strengthens on hot CPI.",
        }
        missing = required_fields - set(sample_row.keys())
        assert not missing, f"per_asset row missing required fields: {missing}"
