"""
Affinity map tests — covers ROUTER-AFFINITY-01 + ROUTER-WEIGHTS-01.

test_yaml_loads_with_required_keys and test_mode_weights_sum pass immediately
(YAML skeleton ships with correct values). Other tests xfail until Plan 02
implements AffinityMap.lookup().

Per-task verification map commands (from VALIDATION.md):
    pytest tests/routing/test_affinity.py -x -q
    pytest tests/routing/test_affinity.py::test_mode_weights_sum -x -q
"""
import pytest
import yaml
from pathlib import Path

# Path to the model_routing.yaml skeleton (relative to VM107 root)
YAML_PATH = Path(__file__).parents[2] / "conf" / "model_routing.yaml"


def test_yaml_loads_with_required_keys():
    """
    YAML parses without error and contains all required top-level keys.

    Passes immediately (Wave 0 skeleton ships with correct structure).
    """
    cfg = yaml.safe_load(YAML_PATH.read_text())
    assert cfg["version"] == "1.0"
    assert {"timezone", "peak_hours"} <= set(cfg["routing"])
    assert {"exploration", "exploitation", "stabilization"} == set(cfg["mode_weights"])


def test_mode_weights_sum():
    """
    All three mode_weight sets sum to exactly 1.0.

    Passes immediately (Wave 0 default values are mathematically correct).
    Validates: exploration (0.6+0.25+0.15=1.0), exploitation (0.4+0.4+0.2=1.0),
               stabilization (0.2+0.3+0.5=1.0).
    """
    cfg = yaml.safe_load(YAML_PATH.read_text())
    for mode, w in cfg["mode_weights"].items():
        total = w["quality"] + w["cost"] + w["latency"]
        assert abs(total - 1.0) < 1e-9, (
            f"{mode} mode_weights sum to {total}, expected 1.0. "
            f"Values: quality={w['quality']}, cost={w['cost']}, latency={w['latency']}"
        )


def test_default_fallback_chain_lookup():
    """AffinityMap.lookup() returns correct chain for known (agent_id, task_type) pair."""
    pytest.xfail("Plan 02: AffinityMap.lookup() pending")


def test_unknown_agent_falls_back_to_default():
    """AffinityMap.lookup() uses affinity['default']['default'] for unknown agent_id."""
    pytest.xfail("Plan 02: AffinityMap default fallback pending")


def test_unknown_task_type_falls_back_to_agent_default():
    """AffinityMap.lookup() uses affinity[agent_id]['default'] for unknown task_type."""
    pytest.xfail("Plan 02: AffinityMap inner default pending")
