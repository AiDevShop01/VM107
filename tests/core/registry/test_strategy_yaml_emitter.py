"""Phase 48 Plan 48-08a — REQ-48-D11 strategy_yaml_emitter.

CONTEXT § Decision 11: on acceptance, an auto-generated
``VM107/registry/strategy/<accepted_strategy_id>.yaml`` is written.
The YAML must:
  - Carry a REGISTER_CAPABILITY header comment per Phase 47.6.
  - id == filename without .yaml == accepted_strategy_id.
  - type: strategy
  - status: accepted (default for V1; enum {accepted, deprecated, shadow, experimental})
  - shipped: 48
  - phase: 48
  - producer: VM107
  - allowed_execution_modes: [RESEARCH] default for V1.
  - validated_regimes, supported_instruments, risk_class derived where possible.
  - Pass the Phase 47.6 stage-2 schema validator
    (``core.registry.validation.validate_schemas``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml


def _accepted_doc() -> dict:
    return {
        "_id": "acc_phase48_test_001",
        "accepted_strategy_id": "acc_phase48_test_001",
        "root_hypothesis_id": "hyp_phase48_test_001",
        "strategy_family": "BREAKOUT",
        "refinement_loop_id": "loop_phase48_test_001",
        "final_strategy_spec_id": "spec_final",
        "final_code_module_id": "code_final",
        "final_backtest_result_id": "bt_final",
        "final_critic_verdict_id": "cv_final",
        "accepted_registry_snapshot_hash": "snapshot_test_deadbeef",
        "iteration_artifact_ids": [
            {"iter": 0, "strategy_spec_id": "spec0"},
            {"iter": 1, "strategy_spec_id": "spec1"},
            {"iter": 2, "strategy_spec_id": "spec_final"},
        ],
        "accepted_at": datetime.now(tz=timezone.utc).isoformat(),
        "accepted_by": "refinement_orchestrator@1.0.0",
        "acceptance_reason": "CRITIC_ACCEPT_AT_ITER_2",
        "schema_version": 1,
    }


def test_emit_strategy_yaml_creates_file_at_expected_path(tmp_path: Path):
    from core.registry.strategy_yaml_emitter import emit_strategy_yaml

    path = emit_strategy_yaml(_accepted_doc(), output_dir=tmp_path)
    assert isinstance(path, Path)
    assert path.exists()
    assert path.parent == tmp_path
    assert path.name == "acc_phase48_test_001.yaml"


def test_emit_strategy_yaml_carries_register_capability_header(tmp_path: Path):
    from core.registry.strategy_yaml_emitter import emit_strategy_yaml

    path = emit_strategy_yaml(_accepted_doc(), output_dir=tmp_path)
    text = path.read_text()
    first_line = text.splitlines()[0]
    assert first_line.startswith("# REGISTER_CAPABILITY:")
    assert "type=strategy" in first_line
    assert "id=acc_phase48_test_001" in first_line


def test_emit_strategy_yaml_required_fields_present(tmp_path: Path):
    from core.registry.strategy_yaml_emitter import emit_strategy_yaml

    path = emit_strategy_yaml(_accepted_doc(), output_dir=tmp_path)
    parsed = yaml.safe_load(path.read_text())
    assert parsed["id"] == "acc_phase48_test_001"
    assert parsed["type"] == "strategy"
    # Phase 47.6 CapabilityStatus — must be one of {stub, experimental, real, deprecated}.
    assert parsed["status"] == "real"
    # Decision 11 strategy lifecycle enum — separate field per the planner deviation
    # captured in 48-08a-SUMMARY (status enum collision with 47.6 CapabilityStatus).
    assert parsed["strategy_lifecycle_status"] == "accepted"
    assert parsed["shipped"] == 48
    assert parsed["phase"] == 48
    assert parsed["producer"] == "VM107"
    assert parsed["impact_on_decision"] in {"HIGH", "MEDIUM", "LOW"}
    assert parsed["deprecated"] is False
    assert parsed["allowed_execution_modes"] == ["RESEARCH"]
    assert parsed["strategy_family"] == "BREAKOUT"
    assert parsed["root_hypothesis_id"] == "hyp_phase48_test_001"
    assert parsed["accepted_strategy_id"] == "acc_phase48_test_001"
    # Mongo doc is canonical truth — YAML stores references only.
    assert "iteration_artifact_ids" not in parsed
    assert parsed["accepted_registry_snapshot_hash"] == "snapshot_test_deadbeef"


def test_emit_strategy_yaml_passes_phase_47_6_stage2_validation(tmp_path: Path):
    """YAML must pass core.registry.validation.validate_schemas Stage 2."""
    from core.registry.strategy_yaml_emitter import emit_strategy_yaml
    from core.registry.validation import validate_schemas

    path = emit_strategy_yaml(_accepted_doc(), output_dir=tmp_path)
    raw = yaml.safe_load(path.read_text())

    # Stage 2 validates each entry against the per-type Pydantic schema.
    # validate_schemas raises on failure.
    validate_schemas([(path, raw)])


def test_emit_strategy_yaml_refuses_overwrite_worm_enforcement(tmp_path: Path):
    """WORM at the registry level: a second write for the same accepted_strategy_id raises."""
    from core.registry.strategy_yaml_emitter import StrategyYAMLAlreadyExists, emit_strategy_yaml

    emit_strategy_yaml(_accepted_doc(), output_dir=tmp_path)
    with pytest.raises(StrategyYAMLAlreadyExists):
        emit_strategy_yaml(_accepted_doc(), output_dir=tmp_path)


def test_emit_strategy_yaml_no_full_doc_duplication(tmp_path: Path):
    """YAML must NOT duplicate the full Mongo doc (Decision 11)."""
    from core.registry.strategy_yaml_emitter import emit_strategy_yaml

    path = emit_strategy_yaml(_accepted_doc(), output_dir=tmp_path)
    text = path.read_text()
    # acceptance_reason is the sort of large/narrative field that the
    # decision says should NOT live in the registry YAML (canonical truth
    # is the Mongo doc). The id + reference fields are enough for discovery.
    assert "acceptance_reason" not in text
    assert "accepted_by" not in text
    assert "iteration_artifact_ids" not in text
