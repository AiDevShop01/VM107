"""Tests for VM107 replay template YAML registry entries — CONTEXT §6, §20.

12 V1 narration template YAMLs in VM107/registry/replay_template/ — one per
Phase 56-58 emitted event type. Graduates in 59-03.

Shape test asserts Phase 47.6 alias-extended frontmatter, declarative-only
templates (no if:/branch:/when:/Jinja), and no LLM-style phrasing.
"""
import pathlib
import re
import yaml
import pytest

REGISTRY = pathlib.Path(__file__).parent.parent.parent / "registry" / "replay_template"
EXPECTED_EVENT_TYPES = {
    "checklist_completed",
    "order_submitted",
    "fill_received",
    "position_closed",
    "review_recorded",
    "idea_state_transition",
    "campaign_state_transition",
    "execution_state_transition",
    "analytics_snapshot_recorded",
    "analytics_fanout_completed",
    "replay_artifact_generated",
    "replay_artifact_regenerated",
}
REQUIRED_KEYS = {
    "id",
    "type",
    "status",
    "shipped",
    "last_changed",
    "name",
    "event_type",
    "replay_template_version",
    "artifact_type",
    "template",
    "required_fields",
    "tone",
    "language",
    "phase",
    "capabilities",
    "hard_scoped",
}
FORBIDDEN_PATTERNS = [
    "if:",
    "branch:",
    "when:",
    "{% ",
    "${",
    "should have",
    "recommend",
    "advice",
]


def _all_yamls():
    if not REGISTRY.exists():
        return []
    return sorted(REGISTRY.glob("*.yaml"))


def test_template_dir_exists():
    """registry/replay_template/ directory must exist."""
    assert REGISTRY.exists(), f"Template directory missing: {REGISTRY}"


def test_v1_set_complete():
    found = {p.stem for p in _all_yamls()}
    assert found == EXPECTED_EVENT_TYPES, (
        f"missing={EXPECTED_EVENT_TYPES - found}, extra={found - EXPECTED_EVENT_TYPES}"
    )


def test_all_yamls_parse_and_have_required_keys():
    """All 12 YAMLs parse cleanly and have Phase 47.6 alias-extended frontmatter."""
    all_yamls = _all_yamls()
    assert len(all_yamls) > 0, "No YAML files found in registry/replay_template/"
    for path in all_yamls:
        data = yaml.safe_load(path.read_text())
        missing = REQUIRED_KEYS - set(data.keys())
        assert not missing, f"{path.name} missing keys: {missing}"
        assert data["type"] == "replay_template", f"{path.name}: type must be 'replay_template'"
        assert data["replay_template_version"] == "1.0.0", f"{path.name}: version must be '1.0.0'"
        assert data["artifact_type"] == "narration_v1", f"{path.name}: artifact_type must be 'narration_v1'"
        assert data["tone"] == "observational", f"{path.name}: tone must be 'observational'"
        assert data["language"] == "en", f"{path.name}: language must be 'en'"
        assert data["phase"] == 59, f"{path.name}: phase must be 59"


def test_all_templates_are_declarative():
    """No YAML may contain forbidden patterns (if:/branch:/when:/Jinja/LLM phrasing)."""
    all_yamls = _all_yamls()
    assert len(all_yamls) > 0, "No YAML files found in registry/replay_template/"
    for path in all_yamls:
        raw = path.read_text()
        for pat in FORBIDDEN_PATTERNS:
            assert pat not in raw, f"{path.name} contains forbidden pattern: {pat!r}"


def test_template_placeholders_match_required_fields():
    """Every template placeholder must map to a declared required_field."""
    all_yamls = _all_yamls()
    assert len(all_yamls) > 0, "No YAML files found"
    for path in all_yamls:
        data = yaml.safe_load(path.read_text())
        placeholders = set(re.findall(r"\{(\w+)\}", data["template"]))
        required = set(data["required_fields"])
        # occurred_at is always injected by narrator — not in required_fields per se
        missing = placeholders - required - {"occurred_at"}
        assert not missing, f"{path.name} has placeholders not in required_fields: {missing}"


def test_capabilities_include_replay_narration():
    """Every YAML must declare the 'replay_narration' capability."""
    all_yamls = _all_yamls()
    assert len(all_yamls) > 0, "No YAML files found"
    for path in all_yamls:
        data = yaml.safe_load(path.read_text())
        caps = data.get("capabilities", [])
        assert "replay_narration" in caps, (
            f"{path.name} missing 'replay_narration' in capabilities"
        )


def test_event_type_field_matches_filename():
    """Each YAML's event_type field must match its filename stem."""
    all_yamls = _all_yamls()
    assert len(all_yamls) > 0, "No YAML files found"
    for path in all_yamls:
        data = yaml.safe_load(path.read_text())
        assert data["event_type"] == path.stem, (
            f"{path.name}: event_type '{data['event_type']}' does not match filename stem '{path.stem}'"
        )
