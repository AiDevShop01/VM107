"""Phase 85 Plan 15 — Task 2 (TDD RED): macro_indicator_describer runner tests.

Tests:
1. test_describer_profile_yaml_exists_and_valid — agent profile YAML loadable
2. test_describer_prompt_exists_and_has_required_fields — prompt MD has all 3 output fields
3. test_describer_registry_yaml_exists_and_valid — capability registry YAML loadable
4. test_upsert_respects_manual_override — persistence helper skips manual_override=true rows
5. test_upsert_writes_new_description — persistence helper UPDATEs when no manual_override
6. test_registry_yaml_has_phase_47_6_fields — registry YAML has typical_confidence, is_deterministic etc.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

pytestmark = pytest.mark.phase_85

VM107_ROOT = Path("/Volumes/ HardDrive/FinGPT/VM107")
PROFILE_PATH = VM107_ROOT / "profiles" / "macro_indicator_describer.yaml"
PROMPT_PATH = VM107_ROOT / "prompts" / "macro_indicator_describer.md"
REGISTRY_YAML_PATH = VM107_ROOT / "registry" / "agent_profile" / "vm107.macro_indicator_describer.yaml"
PERSISTENCE_PATH = VM107_ROOT / "persistence" / "economic_indicator_description.py"


class TestDescriberProfileYaml:
    """Agent profile YAML at profiles/macro_indicator_describer.yaml."""

    def test_profile_yaml_exists(self):
        """Profile YAML file must exist."""
        assert PROFILE_PATH.exists(), f"Missing: {PROFILE_PATH}"

    def test_profile_id_is_correct(self):
        """Profile YAML must declare id: vm107.macro_indicator_describer."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert data.get("id") == "vm107.macro_indicator_describer", (
            f"Expected id=vm107.macro_indicator_describer, got {data.get('id')!r}"
        )

    def test_profile_denied_tools_present(self):
        """Profile must deny call_subordinate, code_execution_tool, trade_execution_tool."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        denied = data.get("denied_tools", [])
        for tool in ("call_subordinate", "code_execution_tool", "trade_execution_tool"):
            assert tool in denied, f"Profile must deny {tool!r}"

    def test_profile_max_iterations_le_3(self):
        """Profile max_iterations must be 3 (leaf agent)."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert data.get("max_iterations") == 3, (
            f"Expected max_iterations=3, got {data.get('max_iterations')!r}"
        )

    def test_profile_impact_on_decision_low(self):
        """Profile impact_on_decision must be LOW (editorial, not quantitative)."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert data.get("impact_on_decision") == "LOW", (
            f"Expected impact_on_decision=LOW, got {data.get('impact_on_decision')!r}"
        )

    def test_profile_references_prompt(self):
        """Profile must reference a prompt file path."""
        import yaml
        data = yaml.safe_load(PROFILE_PATH.read_text())
        assert "prompt" in data or "prompts" in str(data), (
            "Profile must reference a prompt file"
        )


class TestDescriberPromptMd:
    """Prompt at prompts/macro_indicator_describer.md."""

    def test_prompt_exists(self):
        """Prompt MD file must exist."""
        assert PROMPT_PATH.exists(), f"Missing: {PROMPT_PATH}"

    def test_prompt_has_what_is_it(self):
        """Prompt must define what_is_it output field."""
        content = PROMPT_PATH.read_text()
        assert "what_is_it" in content, "Prompt must define what_is_it output field"

    def test_prompt_has_why_important(self):
        """Prompt must define why_important output field."""
        content = PROMPT_PATH.read_text()
        assert "why_important" in content, "Prompt must define why_important output field"

    def test_prompt_has_why_traders_care(self):
        """Prompt must define why_traders_care output field."""
        content = PROMPT_PATH.read_text()
        assert "why_traders_care" in content, "Prompt must define why_traders_care output field"

    def test_prompt_has_no_live_data_injection(self):
        """Prompt must not mention live prices, actual values — editorial only."""
        content = PROMPT_PATH.read_text()
        # Prompt should not instruct agent to fetch live data
        assert "actual_value" not in content, (
            "Prompt must not reference actual_value — descriptions are editorial"
        )


class TestRegistryYaml:
    """Capability registry YAML at registry/agent_profile/vm107.macro_indicator_describer.yaml."""

    def test_registry_yaml_exists(self):
        """Registry YAML file must exist."""
        assert REGISTRY_YAML_PATH.exists(), f"Missing: {REGISTRY_YAML_PATH}"

    def test_registry_yaml_id_matches(self):
        """Registry YAML id must match vm107.macro_indicator_describer."""
        import yaml
        data = yaml.safe_load(REGISTRY_YAML_PATH.read_text())
        assert data.get("id") == "vm107.macro_indicator_describer", (
            f"Registry id mismatch: {data.get('id')!r}"
        )

    def test_registry_yaml_type_is_agent_profile(self):
        """Registry YAML type must be agent_profile."""
        import yaml
        data = yaml.safe_load(REGISTRY_YAML_PATH.read_text())
        assert data.get("type") == "agent_profile", (
            f"Registry type must be agent_profile, got {data.get('type')!r}"
        )

    def test_registry_yaml_has_phase_47_6_fields(self):
        """Registry YAML must have Phase 47.6 gate fields: typical_confidence, expected_freshness_seconds, is_deterministic, version."""
        import yaml
        data = yaml.safe_load(REGISTRY_YAML_PATH.read_text())
        for field in ("typical_confidence", "expected_freshness_seconds", "is_deterministic", "version"):
            assert field in data, f"Registry YAML missing Phase 47.6 field: {field!r}"

    def test_registry_yaml_shipped_85(self):
        """Registry YAML shipped value must be 85."""
        import yaml
        data = yaml.safe_load(REGISTRY_YAML_PATH.read_text())
        assert data.get("shipped") == 85, (
            f"Expected shipped=85, got {data.get('shipped')!r}"
        )


class TestPersistenceHelper:
    """Persistence helper at persistence/economic_indicator_description.py."""

    def test_persistence_module_importable(self):
        """persistence.economic_indicator_description must be importable."""
        import importlib
        mod = importlib.import_module("persistence.economic_indicator_description")
        assert hasattr(mod, "upsert_description"), (
            "Module must export upsert_description function"
        )

    def test_upsert_respects_manual_override(self):
        """upsert_description returns False and does NOT UPDATE when existing row has manual_override=True."""
        from persistence.economic_indicator_description import upsert_description

        # Seed a row with manual_override=True in the mock DB
        fake_cur = MagicMock()
        fake_conn = MagicMock()
        fake_conn.__enter__ = MagicMock(return_value=fake_conn)
        fake_conn.__exit__ = MagicMock(return_value=False)
        fake_conn.cursor = MagicMock(return_value=fake_cur)
        fake_cur.__enter__ = MagicMock(return_value=fake_cur)
        fake_cur.__exit__ = MagicMock(return_value=False)

        # Simulate existing row with manual_override=True
        fake_cur.fetchone.return_value = (True,)

        with patch("persistence.economic_indicator_description.get_default_conn", return_value=fake_conn):
            result = upsert_description(
                "CPIAUCSL",
                {"what_is_it": "test", "why_important": "test", "why_traders_care": "test"},
                model_version="claude-3-5",
                prompt_version="1.0.0",
                manual_override=False,
            )

        assert result is False, "upsert_description must return False for manual_override=True rows"
        # UPDATE must NOT have been called
        update_calls = [c for c in fake_cur.execute.call_args_list if "UPDATE" in str(c)]
        assert len(update_calls) == 0, "No UPDATE should happen when existing row is manual_override=True"

    def test_upsert_writes_new_description(self):
        """upsert_description returns True and executes UPDATE when row has no manual_override."""
        from persistence.economic_indicator_description import upsert_description

        fake_cur = MagicMock()
        fake_conn = MagicMock()
        fake_conn.__enter__ = MagicMock(return_value=fake_conn)
        fake_conn.__exit__ = MagicMock(return_value=False)
        fake_conn.cursor = MagicMock(return_value=fake_cur)
        fake_cur.__enter__ = MagicMock(return_value=fake_cur)
        fake_cur.__exit__ = MagicMock(return_value=False)

        # Simulate existing row with manual_override=False
        fake_cur.fetchone.return_value = (False,)

        with patch("persistence.economic_indicator_description.get_default_conn", return_value=fake_conn):
            result = upsert_description(
                "CPIAUCSL",
                {"what_is_it": "CPI measures urban consumer prices", "why_important": "Central bank target", "why_traders_care": "Fed reaction function"},
                model_version="claude-3-5",
                prompt_version="1.0.0",
            )

        assert result is True, "upsert_description must return True when write succeeds"
        # UPDATE must have been called
        update_calls = [c for c in fake_cur.execute.call_args_list if "UPDATE" in str(c)]
        assert len(update_calls) == 1, "Exactly one UPDATE should be executed"

    def test_upsert_payload_contains_required_keys(self):
        """Persisted JSONB payload must include generated_at, model_version, prompt_version, manual_override."""
        from persistence.economic_indicator_description import upsert_description
        import json

        fake_cur = MagicMock()
        fake_conn = MagicMock()
        fake_conn.__enter__ = MagicMock(return_value=fake_conn)
        fake_conn.__exit__ = MagicMock(return_value=False)
        fake_conn.cursor = MagicMock(return_value=fake_cur)
        fake_cur.__enter__ = MagicMock(return_value=fake_cur)
        fake_cur.__exit__ = MagicMock(return_value=False)

        fake_cur.fetchone.return_value = (False,)

        with patch("persistence.economic_indicator_description.get_default_conn", return_value=fake_conn):
            upsert_description(
                "CPIAUCSL",
                {"what_is_it": "test", "why_important": "test", "why_traders_care": "test"},
                model_version="claude-3-5",
                prompt_version="1.0.0",
            )

        # Find the UPDATE call and inspect the JSON payload
        update_calls = [c for c in fake_cur.execute.call_args_list if "UPDATE" in str(c)]
        assert update_calls, "Expected an UPDATE call"
        params = update_calls[0][0][1]  # positional args to execute
        payload = json.loads(params[0])  # first param is the JSON string
        for key in ("generated_at", "model_version", "prompt_version", "manual_override"):
            assert key in payload, f"Payload missing key: {key!r}"
        assert payload["model_version"] == "claude-3-5"
        assert payload["prompt_version"] == "1.0.0"
